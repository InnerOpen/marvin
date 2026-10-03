"""Runs a restart killed: mark them failed instead of leaving them `running` forever.

An agent run is one synchronous request. When the process dies mid-run (a deploy past its grace
period, an OOM kill, a crash) nothing records the end: its `ai_executions` row stays `running` and
its thread never gets the answer, so the Ask page and the bubble have nothing honest to show. The
next process sweeps those rows: `failed` with INTERRUPTED_ERROR, and — when the run had a thread —
a short assistant turn saying so, stored with the execution id, which is exactly what the bubble's
recovery (frontend/src/lib/marvin/pending.ts `findReply`) looks for.

Only `running` rows are swept. `awaiting_approval` runs are parked on purpose: their state lives in
the thread and a resume continues them on any process.

Which rows are safe to sweep: those started before this process started (minus a margin for clock
skew), and only once no older process can still be serving them. Under a rolling update the old pod
keeps draining its runs for up to terminationGracePeriodSeconds after the new pod is ready, so the
sweep is delayed by AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS (the chart sets grace + a margin). With
more than one *steady-state* replica this would still fail another live replica's older runs — the
deployment runs one replica (SQLite is single-writer); a per-run heartbeat is the fix if that changes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from marvin.db.models._model_utils.datetime import get_utc_now
from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.ai_threads import AIThreadModel

INTERRUPTED_ERROR = "Interrupted: the server restarted while this run was in progress."
INTERRUPTED_REPLY = (
    "I was interrupted: the server restarted while I was working on this. Anything I changed before the restart is kept — ask again to finish."
)
# Rows started this close to the process start are left alone: replicas' clocks are not identical.
CLOCK_SKEW_MARGIN = timedelta(seconds=10)
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"


def _naive_utc(value: datetime | None) -> datetime | None:
    """Timestamps are stored naive UTC; an aware value (e.g. the process start) is converted."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _thread_of(session: Session, execution: AIExecutionModel) -> AIThreadModel | None:
    raw = (execution.metadata_json or {}).get("thread_id")
    try:
        tid = uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None
    return session.get(AIThreadModel, tid) if tid else None


def _close_thread(session: Session, execution: AIExecutionModel) -> bool:
    """Tell the run's thread it ended. Skipped when the conversation has moved on since the run
    started (a later turn exists): an "interrupted" turn below newer ones would only confuse."""
    from marvin.services.ai.threads import append_turn, touch

    thread = _thread_of(session, execution)
    if thread is None:
        return False
    started = _naive_utc(execution.started_at) or execution.created_at
    if thread.last_message_at is not None and started is not None and thread.last_message_at > started:
        return False
    # The user's turn is stored when a run ends, so a killed run never stored it. Restore it when the
    # execution logged it, keeping the thread's turns alternating.
    question = (execution.input_json or {}).get("message")
    last = max(thread.messages, key=lambda m: m.seq, default=None)
    if question and not (last is not None and last.role == "user" and last.content == question):
        append_turn(session, thread, "user", question)
    append_turn(session, thread, "assistant", INTERRUPTED_REPLY, meta={"interrupted": True}, execution_id=execution.id)
    touch(thread)
    return True


def mark_interrupted_runs(session: Session, process_started_at: datetime) -> int:
    """Fail every `running` execution started before this process (less the skew margin); returns how many."""
    cutoff = _naive_utc(process_started_at) - CLOCK_SKEW_MARGIN
    rows = (
        session.query(AIExecutionModel)
        .filter(AIExecutionModel.status == STATUS_RUNNING, func.coalesce(AIExecutionModel.started_at, AIExecutionModel.created_at) < cutoff)
        .all()
    )
    now = get_utc_now()
    for execution in rows:
        execution.status = STATUS_FAILED
        execution.error_message = INTERRUPTED_ERROR
        execution.completed_at = now
        _close_thread(session, execution)
    session.commit()
    return len(rows)
