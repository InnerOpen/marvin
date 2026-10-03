"""Startup sweep of runs a restart killed (services/ai/interrupted_runs.py).

DB-backed through `db_session` with a hand-inserted workspace row; commits become flushes and the
test rolls back, so rows other tests left behind are never touched for real.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pytest import fixture

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.services.ai import threads as thread_svc
from marvin.services.ai.interrupted_runs import INTERRUPTED_ERROR, INTERRUPTED_REPLY, mark_interrupted_runs

PROCESS_START = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
# Stored naive UTC, as the columns hold them.
BEFORE = datetime(2026, 10, 3, 11, 56, 30, tzinfo=UTC).replace(tzinfo=None)
AFTER = datetime(2026, 10, 3, 12, 0, 30, tzinfo=UTC).replace(tzinfo=None)


@fixture
def ws(db_session, monkeypatch):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"int-{gid.hex[:8]}", slug=f"int-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    yield SimpleNamespace(group_id=gid, user=uuid.uuid4())
    db_session.rollback()


def _execution(db_session, ws, status, started_at, *, thread=None, message=None):
    row = AIExecutionModel(
        session=db_session,
        group_id=ws.group_id,
        operation_slug="agent:marvin",
        provider_type="fake",
        model_id="m",
        status=status,
        input_json={"message": message} if message else None,
        metadata_json={"thread_id": str(thread.id)} if thread is not None else None,
    )
    row.started_at = started_at
    db_session.add(row)
    db_session.flush()
    return row


def test_mark_interrupted_runs_fails_runs_started_before_the_process(db_session, ws):
    old = _execution(db_session, ws, "running", BEFORE)
    mark_interrupted_runs(db_session, PROCESS_START)
    assert old.status == "failed"
    assert old.error_message == INTERRUPTED_ERROR
    assert old.completed_at is not None


def test_mark_interrupted_runs_leaves_parked_runs_alone(db_session, ws):
    parked = _execution(db_session, ws, "awaiting_approval", BEFORE)
    mark_interrupted_runs(db_session, PROCESS_START)
    assert parked.status == "awaiting_approval" and parked.error_message is None


def test_mark_interrupted_runs_leaves_runs_of_this_process_alone(db_session, ws):
    mine = _execution(db_session, ws, "running", AFTER)
    mark_interrupted_runs(db_session, PROCESS_START)
    assert mine.status == "running"


def test_mark_interrupted_runs_spares_runs_inside_the_clock_skew_margin(db_session, ws):
    borderline = _execution(db_session, ws, "running", PROCESS_START.replace(tzinfo=None) - timedelta(seconds=3))
    mark_interrupted_runs(db_session, PROCESS_START)
    assert borderline.status == "running"


def test_mark_interrupted_runs_closes_the_thread_with_an_honest_turn(db_session, ws):
    thread = thread_svc.create_thread(db_session, ws.group_id, ws.user, "marvin", "tag the untagged images")
    run = _execution(db_session, ws, "running", BEFORE, thread=thread, message="tag the untagged images")
    mark_interrupted_runs(db_session, PROCESS_START)
    turns = sorted(thread.messages, key=lambda m: m.seq)
    # The killed run never stored the question; it is restored so the turns alternate, and the reply
    # carries the execution id — what the bubble's recovery (pending.ts findReply) matches on.
    assert [(m.role, m.content) for m in turns] == [("user", "tag the untagged images"), ("assistant", INTERRUPTED_REPLY)]
    assert turns[1].execution_id == run.id and turns[1].meta_json == {"interrupted": True}


def test_mark_interrupted_runs_without_a_logged_question_adds_only_the_reply(db_session, ws):
    thread = thread_svc.create_thread(db_session, ws.group_id, ws.user, "marvin", "hi")
    _execution(db_session, ws, "running", BEFORE, thread=thread)
    mark_interrupted_runs(db_session, PROCESS_START)
    assert [m.role for m in thread.messages] == ["assistant"]


def test_mark_interrupted_runs_skips_a_thread_that_moved_on(db_session, ws):
    thread = thread_svc.create_thread(db_session, ws.group_id, ws.user, "marvin", "hi")
    run = _execution(db_session, ws, "running", BEFORE, thread=thread, message="hi")
    thread_svc.append_turn(db_session, thread, "user", "newer question")
    thread.last_message_at = BEFORE + timedelta(minutes=2)
    mark_interrupted_runs(db_session, PROCESS_START)
    assert run.status == "failed"
    assert [m.content for m in thread.messages] == ["newer question"]


# ── Wiring: startup schedules the sweep ──────────────────────────────────────


def test_startup_sweep_runs_at_once_without_a_delay(monkeypatch):
    import marvin.app as app_mod

    seen = []
    monkeypatch.setattr(app_mod, "_sweep_interrupted_runs", seen.append)
    monkeypatch.setattr(app_mod.settings, "AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS", 0)
    assert app_mod._start_interrupted_run_sweep("t0") is None
    assert seen == ["t0"]


def test_startup_sweep_waits_out_a_draining_predecessor(monkeypatch):
    import asyncio

    import marvin.app as app_mod

    seen = []
    monkeypatch.setattr(app_mod, "_sweep_interrupted_runs", seen.append)
    monkeypatch.setattr(app_mod.settings, "AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS", 360)

    async def start_and_stop():
        task = app_mod._start_interrupted_run_sweep("t0")
        await asyncio.sleep(0)
        task.cancel()
        return task

    task = asyncio.run(start_and_stop())
    assert task.cancelled() and seen == []
