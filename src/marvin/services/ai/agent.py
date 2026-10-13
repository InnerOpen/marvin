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
    # Per call: a preview dict when *this* call must be approved whatever the policy (a big bulk
    # write, see tools/bulk_writes.py), else None. Set only on runs that can park.
    approval_check: Callable[[dict], dict | None] | None = None


@dataclass
class AgentStep:
    """One tool invocation in the trace, for the response and audit."""

    tool: str
    arguments: dict
    result: str


PENDING_CALL = "call"
PENDING_HANDOFF = "handoff"


@dataclass
class PendingCall:
    """A tool call the run is waiting on.

    `kind="call"`: an "ask first" call waiting for the user's decision. `kind="handoff"`: a tool that
    deferred (`ToolDeferred`) — a hand-off whose specialist parked on its own ask; nobody decides it
    directly, its output arrives through `ResumeState.outputs` once the specialist finishes. `child`
    is the deferring tool's record (for a hand-off: the specialist and its own pending calls).
    """

    id: str
    tool: str
    arguments: dict
    # What the approval card shows beyond the arguments (a bulk write's targets × items), if any.
    preview: dict | None = None
    kind: str = PENDING_CALL
    child: dict | None = None


class ToolDeferred(Exception):  # noqa: N818 — a control-flow signal, not an error
    """Raised by a tool whose result is not ready yet: a hand-off whose specialist parked for the
    user's approval. The loop pends the call (`kind="handoff"`, with `child`) instead of failing it;
    the result is fed in on resume via `ResumeState.outputs`."""

    def __init__(self, child: dict):
        super().__init__("tool deferred")
        self.child = child


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
    # Deferred (hand-off) calls whose result is now known: call id → the tool output. A hand-off call
    # missing here is still waiting (its specialist parked again) and stays pending.
    outputs: dict[str, str] = field(default_factory=dict)


DECISION_APPROVE = "approve"
DECISION_DENY = "deny"
STOPPED_AWAITING_APPROVAL = "awaiting_approval"
DECLINED_RESULT = json.dumps({"error": "the user declined this action; do not retry it, continue without it"})
# An approved call whose tool is no longer bound when the run resumes (the caller's role or the agent's
# matrix changed while it waited): never run with wider rights than the decision-time binding.
NOT_PERMITTED_RESULT = json.dumps({"error": "this action is no longer permitted for you; do not retry it, continue without it"})


# ── Parking a paused run: the pending calls and the steps so far as JSON ────────────────────────


def serialize_pending(calls: list[PendingCall]) -> list[dict]:
    out = []
    for c in calls:
        d = {"id": c.id, "tool": c.tool, "arguments": dict(c.arguments or {})}
        if c.preview:
            d["preview"] = dict(c.preview)
        if c.kind != PENDING_CALL:
            d["kind"] = c.kind
        if c.child is not None:
            d["child"] = dict(c.child)
        out.append(d)
    return out


def deserialize_pending(data) -> list[PendingCall]:
    out: list[PendingCall] = []
    for d in data or []:
        if not isinstance(d, dict) or not d.get("id") or not d.get("tool"):
            continue
        preview = d.get("preview") if isinstance(d.get("preview"), dict) else None
        child = d.get("child") if isinstance(d.get("child"), dict) else None
        out.append(
            PendingCall(
                id=str(d["id"]),
                tool=str(d["tool"]),
                arguments=dict(d.get("arguments") or {}),
                preview=preview,
                kind=str(d.get("kind") or PENDING_CALL),
                child=child,
            )
        )
    return out


# Decidable ids of a nested park are paths: the parent's hand-off call id, "/", the child's call id
# (and so on down, when hand-offs nest).
PATH_SEP = "/"


def flatten_pending(calls, prefix: str = "", chain: tuple = ()) -> list[dict]:
    """One flat list of what the user decides, from a (possibly nested) serialized pending record.

    A plain call keeps its shape (and gains `via` when it belongs to a specialist); a hand-off call is
    replaced by its specialist's own pending calls, ids prefixed with the hand-off's id — `c1/c7` —
    each tagged `via` (the specialist's slug), `viaName`, `viaChain` (outermost first),
    `childThreadId` and `childExecutionId`. The parent's own asks come first, in call order.
    """
    out: list[dict] = []
    for c in calls or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        cid = f"{prefix}{c['id']}"
        child = c.get("child") if isinstance(c.get("child"), dict) else None
        if c.get("kind") == PENDING_HANDOFF and child is not None:
            agent = str(child.get("agent") or "")
            link = {
                "agent": agent,
                "name": child.get("name") or agent,
                "thread_id": child.get("thread_id"),
                "execution_id": child.get("execution_id"),
            }
            sub = (*chain, link)
            out.extend(flatten_pending(child.get("calls"), prefix=f"{cid}{PATH_SEP}", chain=sub))
            continue
        item = {k: v for k, v in c.items() if k not in ("kind", "child")}
        item["id"] = cid
        if chain:
            item["via"] = chain[-1]["agent"]
            item["viaName"] = chain[-1]["name"]
            item["viaChain"] = [link["agent"] for link in chain]
            if chain[-1].get("thread_id"):
                item["childThreadId"] = str(chain[-1]["thread_id"])
            if chain[-1].get("execution_id"):
                item["childExecutionId"] = str(chain[-1]["execution_id"])
        out.append(item)
    return out


def split_decisions(decisions: dict[str, str], call_id: str) -> dict[str, str]:
    """The part of a path-keyed decision map that belongs under hand-off call `call_id`, ids relative to it."""
    head = f"{call_id}{PATH_SEP}"
    return {k[len(head) :]: v for k, v in (decisions or {}).items() if k.startswith(head)}


def serialize_steps(steps: list[AgentStep]) -> list[dict]:
    """Untruncated — these are replayed into the resumed run's own trace, not shown to the user yet."""
    return [{"tool": s.tool, "arguments": dict(s.arguments or {}), "result": s.result} for s in steps]


def deserialize_steps(data) -> list[AgentStep]:
    out: list[AgentStep] = []
    for d in data or []:
        if not isinstance(d, dict) or not d.get("tool"):
            continue
        out.append(AgentStep(tool=str(d["tool"]), arguments=dict(d.get("arguments") or {}), result=str(d.get("result") or "")))
    return out


EventListener = Callable[[dict], None]


def _notify(on_event: EventListener | None, event: dict) -> None:
    """Tell the listener; a listener that raises must never kill the run."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:  # noqa: BLE001 — progress reporting is best-effort
        pass


def _approval_needed(tool: AgentTool | None, arguments: dict) -> tuple[bool, dict | None]:
    """(pend?, preview) for one call: an "ask first" tool always pends; any tool pends a call its
    `approval_check` flags. A check that raises never pends — the tool reports the bad input itself."""
    if tool is None:
        return False, None
    preview = None
    if tool.approval_check is not None:
        try:
            preview = tool.approval_check(arguments)
        except Exception:  # noqa: BLE001
            preview = None
    return (tool.requires_approval or preview is not None), preview


def _event_calls(pending: list[PendingCall]) -> list[dict]:
    """The `awaiting_approval` event's calls: what the user decides, hand-offs flattened to their specialist's asks."""
    return [
        {"id": c["id"], "tool": c["tool"], **({"via": c["via"]} if c.get("via") else {})}
        for c in flatten_pending(serialize_pending(pending))
        if c.get("tool")
    ]


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

    Tools flagged `requires_approval`, and calls a tool's `approval_check` flags, are not run: within one completion the other calls run as
    usual and the flagged ones pend; the loop returns with `stopped_reason="awaiting_approval"`,
    `pending_calls` and the transcript (`convo`). Call again with `resume` (the transcript, the
    pending calls and the user's decisions) and a fresh step budget: approved calls run, denied
    ones answer the model with a decline, and the loop continues. Every provider needs one tool
    message per call id, so the transcript is only ever handed back complete.

    A tool may also defer (`ToolDeferred` — a hand-off whose specialist parked on its own ask): the
    call pends as `kind="handoff"` beside the batch's other calls, which still run. On resume its
    output comes from `resume.outputs`; while it is missing (the specialist parked again) the loop
    settles what it can — approved calls run, denied ones are declined — and parks again without
    asking the model.
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

    def record(call_id: str, name: str, arguments: dict, out: str) -> None:
        result.steps.append(AgentStep(tool=name, arguments=arguments, result=out))
        convo.append(Message(role="tool", content=out, tool_call_id=call_id))

    def dispatch(call_id: str, name: str, arguments: dict, deferred: list[PendingCall]) -> None:
        tool = by_name.get(name)
        _notify(on_event, {"type": "tool_call", "tool": name, "arguments": arguments})
        ok = True
        if tool is None:
            ok = False
            out = json.dumps({"error": f"unknown tool: {name}"})
        else:
            try:
                out = tool.run(arguments)
            except ToolDeferred as d:
                # No tool message yet: the call stays open until its result is fed in on resume.
                _notify(on_event, {"type": "tool_result", "tool": name, "ok": True, "deferred": True})
                deferred.append(PendingCall(id=call_id, tool=name, arguments=arguments, kind=PENDING_HANDOFF, child=d.child))
                return
            except Exception as e:  # tool failures are surfaced to the model, not fatal
                ok = False
                out = json.dumps({"error": str(e)})
        _notify(on_event, {"type": "tool_result", "tool": name, "ok": ok})
        record(call_id, name, arguments, out)

    def stop_awaiting(pending: list[PendingCall]) -> AgentResult:
        _notify(on_event, {"type": "awaiting_approval", "calls": _event_calls(pending)})
        result.pending_calls = pending
        result.convo = convo
        result.stopped_reason = STOPPED_AWAITING_APPROVAL
        return result

    if resume is not None:
        still: list[PendingCall] = []
        for call in resume.pending:
            arguments = dict(call.arguments or {})
            if call.kind == PENDING_HANDOFF:
                if call.id in resume.outputs:
                    _notify(on_event, {"type": "tool_result", "tool": call.tool, "ok": True})
                    record(call.id, call.tool, arguments, resume.outputs[call.id])
                else:
                    still.append(call)  # the specialist is still waiting on the user
            elif resume.decisions.get(call.id) != DECISION_APPROVE:
                _notify(on_event, {"type": "declined", "tool": call.tool})
                convo.append(Message(role="tool", content=DECLINED_RESULT, tool_call_id=call.id))
            elif call.tool not in by_name:
                _notify(on_event, {"type": "declined", "tool": call.tool, "reason": "not_permitted"})
                record(call.id, call.tool, arguments, NOT_PERMITTED_RESULT)
            else:
                dispatch(call.id, call.tool, arguments, still)
        if still:
            # Something is still out (a specialist re-parked, or an approved hand-off parked): wait again
            # without asking the model — the transcript only goes back to it complete.
            return stop_awaiting(still)

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
        deferred: list[PendingCall] = []
        for call in completion.tool_calls:
            arguments = dict(call.arguments or {})
            pend, preview = _approval_needed(by_name.get(call.name), arguments)
            if pend:
                pending.append(PendingCall(id=call.id, tool=call.name, arguments=arguments, preview=preview))
                continue
            dispatch(call.id, call.name, arguments, deferred)
        if pending or deferred:
            return stop_awaiting(pending + deferred)

    # Step budget exhausted: force a final answer with tools disabled (keeps the tool history valid).
    convo.append(Message(role="user", content="You have used your tool budget. Give your best final answer now, using what you've gathered."))
    _notify(on_event, {"type": "thinking"})
    final = provider.complete_with_tools(convo, model, tool_defs, options, tool_choice="none")
    account(final)
    result.answer = final.content
    result.stopped_reason = "max_steps"
    return result
