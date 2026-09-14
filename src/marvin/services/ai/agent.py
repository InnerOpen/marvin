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


@dataclass
class AgentStep:
    """One tool invocation in the trace, for the response and audit."""

    tool: str
    arguments: dict
    result: str


@dataclass
class AgentResult:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    stopped_reason: str = "complete"  # "complete" | "max_steps"


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
) -> AgentResult:
    """Drive the tool-calling loop and return the final answer plus the tool-call trace.

    `on_event` (optional) hears the run as it happens: `{"type": "thinking"}` before each model
    call, `{"type": "tool_call", "tool", "arguments"}` / `{"type": "tool_result", "tool", "ok"}`
    around each tool — the feed behind a live step timeline.
    """
    tool_defs = [ToolDefinition(name=t.name, description=t.description, input_schema=t.input_schema) for t in tools]
    by_name = {t.name: t for t in tools}
    result = AgentResult(answer="")
    convo: list[Message] = list(messages)
    nudged = False

    def account(completion) -> None:
        result.prompt_tokens += completion.prompt_tokens or 0
        result.completion_tokens += completion.completion_tokens or 0
        result.total_tokens += completion.total_tokens or 0

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
        for call in completion.tool_calls:
            tool = by_name.get(call.name)
            _notify(on_event, {"type": "tool_call", "tool": call.name, "arguments": call.arguments or {}})
            ok = True
            if tool is None:
                ok = False
                out = json.dumps({"error": f"unknown tool: {call.name}"})
            else:
                try:
                    out = tool.run(call.arguments or {})
                except Exception as e:  # tool failures are surfaced to the model, not fatal
                    ok = False
                    out = json.dumps({"error": str(e)})
            _notify(on_event, {"type": "tool_result", "tool": call.name, "ok": ok})
            result.steps.append(AgentStep(tool=call.name, arguments=call.arguments or {}, result=out))
            convo.append(Message(role="tool", content=out, tool_call_id=call.id))

    # Step budget exhausted: force a final answer with tools disabled (keeps the tool history valid).
    convo.append(Message(role="user", content="You have used your tool budget. Give your best final answer now, using what you've gathered."))
    _notify(on_event, {"type": "thinking"})
    final = provider.complete_with_tools(convo, model, tool_defs, options, tool_choice="none")
    account(final)
    result.answer = final.content
    result.stopped_reason = "max_steps"
    return result
