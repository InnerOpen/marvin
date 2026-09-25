"""Server-side agent loop — iterative tool dispatch over the provider tool-calling API.

The loop is provider-agnostic: it drives `AIProvider.complete_with_tools` (Phase 2a) in a
read-eval cycle. Each turn the model either answers (loop ends) or requests tool calls; the loop
runs each tool, feeds the results back as role="tool" messages, and repeats until the model
answers or the step budget is exhausted.

Tools are supplied by the caller as `AgentTool`s — thin closures over Marvin's own capabilities
(search, browse, compose, run an operation). This keeps the loop generic and the tool wiring in
the controller, where it can reuse gating/repos.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from marvin.services.ai.base import AIProvider, CompletionOptions, Message, ToolDefinition

DEFAULT_MAX_STEPS = 6

# A reply that only *announces* a tool call ("give me a moment to check") ends the turn with nothing
# done — there is no later turn in a request/response loop. Ask the model once to do it now.
_DEFERRAL = re.compile(
    r"\b(give me a (moment|second|minute)|one (moment|second)|hold on|bear with me|"
    r"let me (check|look|search|find|fetch|pull|see|dig|have a look|take a look|get)|"
    r"i(?:'ll| will| am going to| shall)( just)? (check|look|search|find|fetch|pull|see|dig|get|scrape|gather))\b",
    re.IGNORECASE,
)
NUDGE = (
    "Do it now: call the tool in this turn instead of describing what you will do. There is no later "
    "turn — a reply that only promises to check is a failed reply."
)


def looks_like_deferral(text: str | None) -> bool:
    return bool(text) and _DEFERRAL.search(text) is not None


@dataclass
class AgentTool:
    """A capability the agent may call. `run` takes the decoded arguments and returns a string
    result (typically JSON) that is fed back to the model verbatim."""

    name: str
    description: str
    input_schema: dict
    run: Callable[[dict], str]
    category: str = ""  # permission-matrix row, see tools/categories.py
    # "Ask first": the loop does not run this tool — it pends the call for the user's decision and
    # the run resumes (approved → run; denied → the model is told) via ResumeState.
    requires_approval: bool = False


@dataclass
class AgentStep:
    """One tool invocation in the trace, for the response and audit."""

    tool: str
    arguments: dict
    result: str


@dataclass
class PendingCall:
    """A tool call waiting for the user's decision (an "ask first" tool)."""

    id: str
    tool: str
    arguments: dict


@dataclass
class AgentResult:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    stopped_reason: str = "complete"  # "complete" | "max_steps" | "awaiting_approval"
    # Set when stopped_reason == "awaiting_approval": what is waiting, and the transcript to resume from.
    pending_calls: list[PendingCall] = field(default_factory=list)
    convo: list[Message] = field(default_factory=list)


@dataclass
class ResumeState:
    """Continue a paused run: its transcript, the calls that were pending, and the user's decisions."""

    convo: list[Message]
    pending: list[PendingCall]
    decisions: dict[str, str]  # call id → "approve" | "deny" (missing = deny)


DECISION_APPROVE = "approve"
DECISION_DENY = "deny"
STOPPED_AWAITING_APPROVAL = "awaiting_approval"
DECLINED_RESULT = json.dumps({"error": "the user declined this action"})


EventListener = Callable[[dict], None]


def _notify(on_event: EventListener | None, event: dict) -> None:
    """Tell the listener; a listener that raises must never kill the run."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:  # noqa: BLE001 — progress reporting is best-effort
        pass


def run_agent_loop(
    provider: AIProvider,
    model: str,
    messages: list[Message],
    tools: list[AgentTool],
    options: CompletionOptions | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    on_event: EventListener | None = None,
    resume: ResumeState | None = None,
) -> AgentResult:
    """Drive the tool-calling loop and return the final answer plus the tool-call trace.

    `on_event` (optional) hears the run as it happens: `{"type": "thinking"}` before each model
    call, `{"type": "tool_call", "tool", "arguments"}` / `{"type": "tool_result", "tool", "ok"}`
    around each tool — the feed behind a live step timeline.

    Tools flagged `requires_approval` are not run: within one completion the other calls run as
    usual and the flagged ones pend; the loop returns with `stopped_reason="awaiting_approval"`,
    `pending_calls` and the transcript (`convo`). Call again with `resume` (the transcript, the
    pending calls and the user's decisions) and a fresh step budget: approved calls run, denied
    ones answer the model with a decline, and the loop continues. Every provider needs one tool
    message per call id, so the transcript is only ever handed back complete.
    """
    tool_defs = [ToolDefinition(name=t.name, description=t.description, input_schema=t.input_schema) for t in tools]
    by_name = {t.name: t for t in tools}
    result = AgentResult(answer="")
    convo: list[Message] = list(resume.convo) if resume is not None else list(messages)
    nudged = False

    def account(completion) -> None:
        result.prompt_tokens += completion.prompt_tokens or 0
        result.completion_tokens += completion.completion_tokens or 0
        result.total_tokens += completion.total_tokens or 0

    def dispatch(call_id: str, name: str, arguments: dict) -> None:
        tool = by_name.get(name)
        _notify(on_event, {"type": "tool_call", "tool": name, "arguments": arguments})
        ok = True
        if tool is None:
            ok = False
            out = json.dumps({"error": f"unknown tool: {name}"})
        else:
            try:
                out = tool.run(arguments)
            except Exception as e:  # tool failures are surfaced to the model, not fatal
                ok = False
                out = json.dumps({"error": str(e)})
        _notify(on_event, {"type": "tool_result", "tool": name, "ok": ok})
        result.steps.append(AgentStep(tool=name, arguments=arguments, result=out))
        convo.append(Message(role="tool", content=out, tool_call_id=call_id))

    if resume is not None:
        for call in resume.pending:
            if resume.decisions.get(call.id) == DECISION_APPROVE:
                dispatch(call.id, call.tool, dict(call.arguments or {}))
            else:
                _notify(on_event, {"type": "declined", "tool": call.tool})
                convo.append(Message(role="tool", content=DECLINED_RESULT, tool_call_id=call.id))

    for _step in range(max_steps):
        _notify(on_event, {"type": "thinking"})
        completion = provider.complete_with_tools(convo, model, tool_defs, options)
        account(completion)

        if not completion.tool_calls:
            if tools and not nudged and looks_like_deferral(completion.content):
                nudged = True
                convo.append(Message(role="assistant", content=completion.content or ""))
                convo.append(Message(role="user", content=NUDGE))
                continue
            result.answer = completion.content
            return result

        convo.append(Message(role="assistant", content=completion.content or "", tool_calls=completion.tool_calls))
        pending: list[PendingCall] = []
        for call in completion.tool_calls:
            tool = by_name.get(call.name)
            if tool is not None and tool.requires_approval:
                pending.append(PendingCall(id=call.id, tool=call.name, arguments=dict(call.arguments or {})))
                continue
            dispatch(call.id, call.name, dict(call.arguments or {}))
        if pending:
            _notify(on_event, {"type": "awaiting_approval", "calls": [{"id": c.id, "tool": c.tool} for c in pending]})
            result.pending_calls = pending
            result.convo = convo
            result.stopped_reason = STOPPED_AWAITING_APPROVAL
            return result

    # Step budget exhausted: force a final answer with tools disabled (keeps the tool history valid).
    convo.append(Message(role="user", content="You have used your tool budget. Give your best final answer now, using what you've gathered."))
    _notify(on_event, {"type": "thinking"})
    final = provider.complete_with_tools(convo, model, tool_defs, options, tool_choice="none")
    account(final)
    result.answer = final.content
    result.stopped_reason = "max_steps"
    return result
