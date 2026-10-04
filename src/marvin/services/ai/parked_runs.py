"""Parked agent runs as a tree: a router's park can hold its specialists' parks (agents v2 slice C2).

When Marvin hands off and the specialist hits an "ask first" call, the specialist parks quietly on its
own child thread (`pending_json.parent` points up) and Marvin parks with a `kind="handoff"` call whose
`child` record snapshots the specialist's pending calls. The user decides once, on the root
conversation. This module holds what the controller and the scheduler share about such trees:

- walking up to the root (`root_of`) and down to the children (`child_threads`),
- ending a whole tree without running it (`end_tree`) — a new message on any thread in it (abandon),
  the TTL (expire), or a specialist the caller may no longer talk to,
- the append-only audit on each execution (`record_approvals` → `metadata_json.approvals`),
- the approval event payload (`approval_event_data`), fired once, on the root.

Plain session-taking functions, like services/ai/threads.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.ai_threads import THREAD_STATUS_AWAITING, AIThreadModel

EXECUTION_STATUS_AWAITING = "awaiting_approval"
REASON_ABANDONED = "abandoned"
REASON_EXPIRED = "expired"
REASON_NOT_PERMITTED = "no_longer_permitted"

ABANDONED_MESSAGE = "I stopped here — the pending actions were not approved."
ABANDONED_ERROR = "abandoned: a new message arrived while awaiting approval"
EXPIRED_MESSAGE = "This request expired before it was approved, so I didn't do it. Ask again if you still need it."
EXPIRED_ERROR = "expired: not approved in time"
NOT_PERMITTED_MESSAGE = "I stopped here — you may no longer use this agent."
NOT_PERMITTED_ERROR = "no longer permitted: the caller may no longer talk to this agent"

_END = {
    REASON_ABANDONED: (ABANDONED_MESSAGE, ABANDONED_ERROR),
    REASON_EXPIRED: (EXPIRED_MESSAGE, EXPIRED_ERROR),
    REASON_NOT_PERMITTED: (NOT_PERMITTED_MESSAGE, NOT_PERMITTED_ERROR),
}
# Guards a corrupt parent chain from looping forever; far above any configurable hand-off depth.
MAX_TREE_DEPTH = 16


def _uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _record(thread: AIThreadModel) -> dict | None:
    from marvin.services.ai.threads import pending_state

    return pending_state(thread)


def parent_thread_of(session: Session, thread: AIThreadModel) -> AIThreadModel | None:
    """The thread a parked specialist's decision belongs to, or None (a root, or not parked)."""
    record = _record(thread) or {}
    tid = _uuid((record.get("parent") or {}).get("thread_id"))
    return session.get(AIThreadModel, tid) if tid else None


def root_of(session: Session, thread: AIThreadModel) -> tuple[AIThreadModel, str]:
    """(root, path prefix) for a parked thread: the conversation the decision is taken on, and the
    prefix that turns this thread's own call ids into the root's path ids (`c1/` for a direct child).

    A thread that is not a parked specialist is its own root with an empty prefix. A parent that is no
    longer parked, or no longer lists this child, ends the walk there (the child is then decided alone).
    """
    from marvin.services.ai.agent import PATH_SEP, PENDING_HANDOFF

    node, prefix = thread, ""
    for _ in range(MAX_TREE_DEPTH):
        parent = parent_thread_of(session, node)
        parent_record = _record(parent) if parent is not None else None
        if parent_record is None:
            break
        call = next(
            (
                c
                for c in parent_record.get("calls") or []
                if isinstance(c, dict) and c.get("kind") == PENDING_HANDOFF and str((c.get("child") or {}).get("thread_id")) == str(node.id)
            ),
            None,
        )
        if call is None:
            break
        node, prefix = parent, f"{call['id']}{PATH_SEP}{prefix}"
    return node, prefix


def child_threads(session: Session, record: dict | None) -> list[tuple[dict, AIThreadModel | None]]:
    """(hand-off call, its specialist's thread or None) for every hand-off a parked record waits on."""
    from marvin.services.ai.agent import PENDING_HANDOFF

    out = []
    for c in (record or {}).get("calls") or []:
        if isinstance(c, dict) and c.get("kind") == PENDING_HANDOFF:
            tid = _uuid((c.get("child") or {}).get("thread_id"))
            out.append((c, session.get(AIThreadModel, tid) if tid else None))
    return out


def tree_threads(session: Session, root: AIThreadModel) -> list[AIThreadModel]:
    """The root and every parked specialist thread under it, root first."""
    out, frontier = [], [(root, 0)]
    while frontier:
        thread, depth = frontier.pop(0)
        out.append(thread)
        if depth >= MAX_TREE_DEPTH:
            continue
        frontier.extend((child, depth + 1) for _, child in child_threads(session, _record(thread)) if child is not None)
    return out


def execution_of(session: Session, record: dict | None) -> AIExecutionModel | None:
    eid = _uuid((record or {}).get("execution_id"))
    return session.get(AIExecutionModel, eid) if eid else None


def record_approvals(
    execution: AIExecutionModel | None,
    calls: list[dict],
    decisions: dict[str, str],
    *,
    decided_by=None,
    surface: str | None = None,
    reason: str | None = None,
) -> None:
    """Append one decision to the execution's `metadata_json.approvals` (never rewritten): when, who,
    from which surface, why (None for a user's decision), and each own call's tool and decision."""
    if execution is None or not calls:
        return
    entry = {
        "at": _now().isoformat(),
        "decided_by": str(decided_by) if decided_by else None,
        "surface": surface,
        "reason": reason,
        "calls": [{"id": str(c.get("id")), "tool": c.get("tool"), "decision": decisions.get(str(c.get("id")), "deny")} for c in calls],
    }
    meta = dict(execution.metadata_json or {})
    meta["approvals"] = [*(meta.get("approvals") or []), entry]
    execution.metadata_json = meta


def own_calls(record: dict | None) -> list[dict]:
    """A parked record's own decidable calls (hand-off calls are decided in their child's record)."""
    from marvin.services.ai.agent import PENDING_CALL

    return [c for c in (record or {}).get("calls") or [] if isinstance(c, dict) and (c.get("kind") or PENDING_CALL) == PENDING_CALL]


def end_tree(session: Session, root: AIThreadModel, reason: str, *, decided_by=None, surface: str | None = None) -> list[dict]:
    """End a parked tree without running anything: every pending call denied, each execution failed,
    each thread closed with a short assistant turn (turns keep alternating; meta `{reason: True}`), the
    parks cleared, each execution's audit appended. Returns the root's flattened calls (for the event).
    Flushes; the caller commits.
    """
    from marvin.services.ai.agent import DECISION_DENY, flatten_pending
    from marvin.services.ai.threads import append_turn, clear_pending

    message, error = _END[reason]
    flat = flatten_pending((_record(root) or {}).get("calls"))
    for thread in tree_threads(session, root):
        record = _record(thread)
        if record is None:
            continue
        execution = execution_of(session, record)
        mine = own_calls(record)
        record_approvals(execution, mine, {str(c.get("id")): DECISION_DENY for c in mine}, decided_by=decided_by, surface=surface, reason=reason)
        if execution is not None and execution.status == EXECUTION_STATUS_AWAITING:
            execution.status = "failed"
            execution.error_message = error
            execution.completed_at = _now()
        append_turn(session, thread, "assistant", message, meta={reason: True}, execution_id=execution.id if execution else None)
        clear_pending(thread)
    session.flush()
    return flat


def parked_at(thread: AIThreadModel) -> datetime | None:
    """When the user was last asked (naive UTC), falling back to the thread's last activity."""
    raw = ((thread.pending_json or {}) if isinstance(thread.pending_json, dict) else {}).get("parked_at")
    if raw:
        try:
            value = datetime.fromisoformat(str(raw))
            return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
        except ValueError:
            pass
    return thread.last_message_at


def is_expired(thread: AIThreadModel, ttl_hours: int, now: datetime | None = None) -> bool:
    """Whether a parked root has waited longer than the TTL (0 or less = parks never expire)."""
    if ttl_hours <= 0:
        return False
    asked = parked_at(thread)
    now = now or _now()
    if now.tzinfo is not None:
        now = now.astimezone(UTC).replace(tzinfo=None)
    return asked is not None and asked < now - timedelta(hours=ttl_hours)


def expire_parked_runs(session: Session, ttl_hours: int, emit: Callable[..., None] | None = None, now=None) -> int:
    """End every parked root older than the TTL (reason "expired"); `emit(root, calls, execution)` after each
    (the caller fires approval_rejected). Specialists' parks go with their root. Returns how many roots."""
    if ttl_hours <= 0:
        return 0
    parked = session.query(AIThreadModel).filter(AIThreadModel.status == THREAD_STATUS_AWAITING).all()
    expired = 0
    for thread in parked:
        if _record(thread) is None or root_of(session, thread)[0] is not thread:
            continue  # stale row, or a specialist: it goes with its root
        if not is_expired(thread, ttl_hours, now):
            continue
        execution = execution_of(session, _record(thread))
        calls = end_tree(session, thread, REASON_EXPIRED)
        session.commit()
        expired += 1
        if emit is not None:
            emit(thread, calls, execution)
    return expired


def approval_event_data(
    root: AIThreadModel,
    execution,
    calls: list[dict],
    decisions: dict | None,
    *,
    workspace_name: str | None = None,
    decided_by=None,
    surface: str | None = None,
    reason: str | None = None,
):
    """EventAIApprovalData for the root. `calls` are flattened (each carries its `via`); the event-level
    `via_agent` / `child_thread_id` / `child_execution_id` are set when every call comes from one specialist."""
    from marvin.services.event_bus_service.event_types import EventAIApprovalData

    origins = {(c.get("via"), c.get("childThreadId"), c.get("childExecutionId")) for c in calls if isinstance(c, dict)}
    via_agent, child_thread_id, child_execution_id = next(iter(origins)) if len(origins) == 1 else (None, None, None)
    return EventAIApprovalData(
        agent_slug=root.agent_slug,
        thread_id=root.id,
        execution_id=execution.id if execution is not None else None,
        calls=calls,
        decisions=decisions,
        via_agent=via_agent,
        child_thread_id=_uuid(child_thread_id),
        child_execution_id=_uuid(child_execution_id),
        decided_by=_uuid(decided_by),
        surface=surface,
        reason=reason,
        workspace_id=root.group_id,
        workspace_name=workspace_name,
    )


def approval_message(event_type, agent_name: str, calls: list[dict], reason: str | None = None) -> str:
    """The event log line: who is waiting, on what, and through whom."""
    tools = ", ".join(dict.fromkeys(str(c.get("tool")) for c in calls if isinstance(c, dict) and c.get("tool"))) or "an action"
    vias = list(dict.fromkeys(str(c.get("viaName") or c.get("via")) for c in calls if isinstance(c, dict) and c.get("via")))
    via = f" (via {', '.join(vias)})" if vias else ""
    name = getattr(event_type, "name", str(event_type))
    if name == "approval_requested":
        return f"{agent_name} is waiting for your approval: {tools}{via}"
    if name == "approval_granted":
        return f"{agent_name}: approved {tools}{via}"
    why = {REASON_EXPIRED: " — expired", REASON_ABANDONED: " — a new message arrived", REASON_NOT_PERMITTED: " — no longer permitted"}.get(
        reason or "", ""
    )
    return f"{agent_name}: declined {tools}{via}{why}"
