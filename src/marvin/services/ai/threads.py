"""Ask threads — the server-side memory behind an agent conversation.

Plain session-taking functions (no controller state) so the routes, tests and — later — the
resume path all share one implementation. A thread belongs to the user who opened it; admins may
see every thread in the workspace. History replayed to the model is bounded downstream by the
controller's `_bounded_history`, which reads `role`/`content` off whatever rows it is handed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from marvin.db.models.groups.ai_threads import THREAD_STATUS_AWAITING, THREAD_STATUS_OPEN, AIThreadMessageModel, AIThreadModel

# Keep a stored tool result useful for reopening a thread without letting one search hit balloon
# the row; the model already saw the full result during the run.
STEP_RESULT_MAX_CHARS = 2000
TITLE_MAX_CHARS = 80
HISTORY_LIMIT = 10


class ThreadNotFound(LookupError):
    """No such thread for this workspace, or not the caller's to see."""


class ThreadAgentMismatch(ValueError):
    """The thread was opened with a different agent."""


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _visible(query, user_id, see_all: bool):
    return query if see_all else query.filter(AIThreadModel.created_by == user_id)


def resolve_thread(session: Session, group_id, thread_id, user_id, *, see_all: bool = False, agent_slug: str | None = None) -> AIThreadModel:
    """Load a thread the caller may use; `agent_slug` (when given) must match the thread's agent."""
    tid = _uuid(thread_id)
    if tid is None:
        raise ThreadNotFound(str(thread_id))
    row = _visible(session.query(AIThreadModel).filter_by(id=tid, group_id=group_id), user_id, see_all).first()
    if row is None:
        raise ThreadNotFound(str(thread_id))
    if agent_slug and row.agent_slug != agent_slug:
        raise ThreadAgentMismatch(f"thread belongs to agent '{row.agent_slug}', not '{agent_slug}'")
    return row


def create_thread(
    session: Session, group_id, user_id, agent_slug: str, first_message: str, entity_type=None, entity_id=None, parent_thread_id=None
) -> AIThreadModel:
    thread = AIThreadModel(
        session=session,
        group_id=group_id,
        agent_slug=agent_slug,
        title=title_from(first_message),
        entity_type=entity_type,
        entity_id=_uuid(entity_id),
        created_by=user_id,
        status=THREAD_STATUS_OPEN,
        parent_thread_id=_uuid(parent_thread_id),
    )
    session.add(thread)
    session.flush()
    return thread


def child_thread_for(session: Session, parent: AIThreadModel, agent_slug: str, user_id) -> AIThreadModel | None:
    """The specialist's thread hanging off `parent` for this user, or None before the first hand-off.

    One child per (parent, specialist, user): a second hand-off continues the conversation the
    specialist already had, and so does `/use <slug>` from the parent.
    """
    return (
        session.query(AIThreadModel)
        .filter_by(parent_thread_id=parent.id, agent_slug=agent_slug, created_by=user_id, group_id=parent.group_id)
        .order_by(AIThreadModel.created_at.desc())
        .first()
    )


def title_from(message: str) -> str | None:
    text = " ".join((message or "").split())
    if not text:
        return None
    return text if len(text) <= TITLE_MAX_CHARS else text[: TITLE_MAX_CHARS - 1].rstrip() + "…"


def list_threads(
    session: Session,
    group_id,
    user_id,
    *,
    see_all: bool = False,
    agent_slug: str | None = None,
    limit: int = 50,
    include_children: bool = False,
) -> list[AIThreadModel]:
    """Top-level threads by default; hand-off children (rows with a parent) only when asked for."""
    q = _visible(session.query(AIThreadModel).filter_by(group_id=group_id), user_id, see_all)
    if agent_slug:
        q = q.filter(AIThreadModel.agent_slug == agent_slug)
    if not include_children:
        q = q.filter(AIThreadModel.parent_thread_id.is_(None))
    q = q.order_by(AIThreadModel.last_message_at.desc().nullslast(), AIThreadModel.created_at.desc())
    return q.limit(max(1, min(limit, 200))).all()


def history_rows(thread: AIThreadModel, limit: int = HISTORY_LIMIT) -> list[AIThreadMessageModel]:
    """The last `limit` turns, oldest first — the shape `_bounded_history` expects."""
    rows = sorted(thread.messages, key=lambda m: m.seq)
    return rows[-limit:] if limit else rows


def append_turn(
    session: Session,
    thread: AIThreadModel,
    role: str,
    content: str,
    *,
    steps=None,
    meta: dict | None = None,
    execution_id=None,
    log_outputs: bool = True,
) -> AIThreadMessageModel:
    """Persist one turn. Tool results are truncated; without output logging only tool names are kept."""
    seq = max((m.seq for m in thread.messages), default=0) + 1
    steps_json = None
    if steps:
        steps_json = [_step_json(s, log_outputs) for s in steps]
    row = AIThreadMessageModel(
        session=session,
        thread_id=thread.id,
        group_id=thread.group_id,
        seq=seq,
        role=role,
        content=content or "",
        steps_json=steps_json,
        meta_json=meta or None,
        execution_id=_uuid(execution_id),
    )
    thread.messages.append(row)
    session.flush()
    return row


def _step_json(step, log_outputs: bool) -> dict:
    tool = getattr(step, "tool", None) or (step.get("tool") if isinstance(step, dict) else None)
    if not log_outputs:
        return {"tool": tool}
    arguments = getattr(step, "arguments", None) if not isinstance(step, dict) else step.get("arguments")
    result = getattr(step, "result", None) if not isinstance(step, dict) else step.get("result")
    result = "" if result is None else str(result)
    if len(result) > STEP_RESULT_MAX_CHARS:
        result = result[: STEP_RESULT_MAX_CHARS - 1] + "…"
    return {"tool": tool, "arguments": arguments or {}, "result": result}


def touch(thread: AIThreadModel, tokens: int | None = None) -> None:
    thread.last_message_at = _now()
    thread.total_tokens = int(thread.total_tokens or 0) + int(tokens or 0)


# ── Ask first: parking a run that is waiting for the user's decision ─────────


def park_thread(session: Session, thread: AIThreadModel, *, calls, convo, execution_id, run: dict, steps, referrals) -> None:
    """Freeze a paused run on its thread: what is waiting, the transcript to resume from, and the run's
    own parameters so `POST /threads/{id}/resume` can rebuild the loop without the original request.

    `calls`/`steps` are PendingCall/AgentStep lists, `convo` the loop's Message transcript (tool
    calls and ids included — every provider needs one tool message per call id), `run` is
    `{agent_slug, max_steps, register, entity_type, entity_id, model}`. Never exposed whole through
    the API: `AIThreadDetail.pending` shows the calls only.
    """
    from marvin.services.ai.agent import serialize_pending, serialize_steps
    from marvin.services.ai.base import serialize_messages

    thread.status = THREAD_STATUS_AWAITING
    thread.pending_json = {
        "calls": serialize_pending(calls),
        "convo": serialize_messages(convo),
        "execution_id": str(execution_id) if execution_id else None,
        "run": dict(run),
        "steps": serialize_steps(steps),
        "referrals": list(referrals or []),
    }
    touch(thread)
    session.flush()


def pending_state(thread: AIThreadModel) -> dict | None:
    """The parked record when the thread is waiting on calls, else None (open threads, stale rows)."""
    if thread.status != THREAD_STATUS_AWAITING:
        return None
    data = thread.pending_json or {}
    return data if data.get("calls") else None


def clear_pending(thread: AIThreadModel) -> None:
    thread.status = THREAD_STATUS_OPEN
    thread.pending_json = None


def _step_result(step):
    raw = getattr(step, "result", None) if not isinstance(step, dict) else step.get("result")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def extract_handoffs(steps) -> tuple[list[dict], list[dict]]:
    """(hand-offs, referrals) from a run's successful `run_agent` results.

    A hand-off is `{agent, threadId, executionId}` (the child thread is what "Continue with X" opens);
    the child's referrals are passed through so the parent can surface them. Error results are skipped.
    """
    handoffs: list[dict] = []
    referrals: list[dict] = []
    for step in steps or []:
        tool = getattr(step, "tool", None) or (step.get("tool") if isinstance(step, dict) else None)
        if tool != "run_agent":
            continue
        raw = _step_result(step)
        if raw is None or raw.get("error") or not raw.get("agent"):
            continue
        handoffs.append({"agent": raw["agent"], "threadId": raw.get("threadId"), "executionId": raw.get("executionId")})
        referrals.extend(r for r in (raw.get("referrals") or []) if isinstance(r, dict) and r.get("agent"))
    return handoffs, referrals


def extract_sources(steps) -> list[dict]:
    """Citations from the run's `search_content` results: one {entityType, entityId, title} per entity."""
    seen: set[str] = set()
    out: list[dict] = []
    for step in steps or []:
        tool = getattr(step, "tool", None) or (step.get("tool") if isinstance(step, dict) else None)
        if tool != "search_content":
            continue
        raw = _step_result(step)
        if raw is None:
            continue
        for hit in raw.get("results") or []:
            if not isinstance(hit, dict):
                continue
            etype, eid = hit.get("entityType"), hit.get("entityId")
            if not etype or not eid:
                continue
            key = f"{etype}:{eid}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"entityType": etype, "entityId": str(eid), "title": hit.get("title")})
    return out
