"""Rebuild requests are coalesced per workspace: a burst becomes one `webhook_triggered`.

A bulk edit fires a workflow per entry, each asking for a rebuild; with a deploy hook on
`webhook_triggered` that was one static-site build per entry. Requests now queue a row, and the
scheduler tick sends one rebuild per workspace once requests have gone quiet.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pytest import fixture
from sqlalchemy import delete, select

from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel
from marvin.services.site_rebuild import MAX_WAIT_SECONDS, QUIET_SECONDS, dispatch_due_rebuilds, request_rebuild

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _workspace(db_session):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"rebuild-{gid.hex[:8]}", slug=f"rebuild-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    return gid


@fixture
def workspace(db_session):
    gid = _workspace(db_session)
    yield gid
    db_session.execute(delete(SiteRebuildRequestModel))
    db_session.commit()


class _Sent(list):
    """Records each dispatched rebuild as (group_id, reason)."""

    def send(self, group_id, reason):
        self.append((group_id, reason))


@fixture
def sent():
    return _Sent()


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_a_burst_of_requests_becomes_one_rebuild(db_session, workspace, sent):
    for i in range(126):
        request_rebuild(db_session, workspace, "square listing", now=_at(i * 0.5))

    assert dispatch_due_rebuilds(db_session, sent.send, now=_at(63 + QUIET_SECONDS)) == 1
    assert sent == [(workspace, "126 requests, latest: square listing")]


def test_nothing_is_sent_while_requests_keep_arriving(db_session, workspace, sent):
    request_rebuild(db_session, workspace, "a", now=_at(0))
    request_rebuild(db_session, workspace, "b", now=_at(50))

    assert dispatch_due_rebuilds(db_session, sent.send, now=_at(50 + QUIET_SECONDS - 1)) == 0
    assert sent == []


def test_a_single_request_is_sent_once_quiet(db_session, workspace, sent):
    request_rebuild(db_session, workspace, "square sold", now=_at(0))

    dispatch_due_rebuilds(db_session, sent.send, now=_at(QUIET_SECONDS))
    dispatch_due_rebuilds(db_session, sent.send, now=_at(QUIET_SECONDS + 120))  # already sent — not again

    assert sent == [(workspace, "square sold")]


def test_a_steady_stream_is_sent_after_the_max_wait(db_session, workspace, sent):
    for t in range(0, MAX_WAIT_SECONDS + 1, 30):  # never quiet for QUIET_SECONDS
        request_rebuild(db_session, workspace, "edit", now=_at(t))

    assert dispatch_due_rebuilds(db_session, sent.send, now=_at(MAX_WAIT_SECONDS)) == 1


def test_workspaces_are_coalesced_separately(db_session, workspace, sent):
    other = _workspace(db_session)
    request_rebuild(db_session, workspace, "a", now=_at(0))
    request_rebuild(db_session, other, "b", now=_at(0))

    dispatch_due_rebuilds(db_session, sent.send, now=_at(QUIET_SECONDS))

    assert sorted(sent) == sorted([(workspace, "a"), (other, "b")])


def test_a_request_landing_mid_dispatch_is_kept_for_the_next_tick(db_session, workspace, sent):
    """The claim deletes the row only if it is unchanged, so a bump between read and claim survives."""
    request_rebuild(db_session, workspace, "first", now=_at(0))

    # Simulate a request racing the tick: bump the row after it was read but before the claim.
    real_execute = db_session.execute
    bumped = {"done": False}

    def execute(stmt, *a, **kw):
        if not bumped["done"] and getattr(stmt, "is_delete", False):
            bumped["done"] = True
            request_rebuild(db_session, workspace, "second", now=_at(QUIET_SECONDS + 1))
        return real_execute(stmt, *a, **kw)

    db_session.execute = execute  # type: ignore[method-assign]
    try:
        assert dispatch_due_rebuilds(db_session, sent.send, now=_at(QUIET_SECONDS + 1)) == 0
    finally:
        db_session.execute = real_execute  # type: ignore[method-assign]

    assert db_session.execute(select(SiteRebuildRequestModel.reason)).scalar_one() == "second"
    assert dispatch_due_rebuilds(db_session, sent.send, now=_at(2 * QUIET_SECONDS + 1)) == 1


def test_one_failing_dispatch_does_not_block_the_others(db_session, workspace, sent):
    other = _workspace(db_session)
    request_rebuild(db_session, workspace, "a", now=_at(0))
    request_rebuild(db_session, other, "b", now=_at(0))

    def send(group_id, reason):
        if group_id == workspace:
            raise RuntimeError("bus down")
        sent.send(group_id, reason)

    dispatch_due_rebuilds(db_session, send, now=_at(QUIET_SECONDS))

    assert sent == [(other, "b")]


def test_the_handler_queues_instead_of_dispatching(db_session, workspace):
    from marvin.services.scheduled_tasks.handlers.publishing import RequestSiteRebuildHandler

    bus = SimpleNamespace(dispatch=lambda **kw: (_ for _ in ()).throw(AssertionError("dispatched immediately")))
    task = SimpleNamespace(group_id=workspace, task_config={"reason": "square listing"})

    RequestSiteRebuildHandler().execute(task, bus)  # type: ignore[arg-type]
    summary = RequestSiteRebuildHandler().execute(task, bus)  # type: ignore[arg-type]

    db_session.expire_all()
    row = db_session.execute(select(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == workspace)).scalar_one()
    assert row.request_count == 2 and row.reason == "square listing"
    assert "queued" in summary and "2 requests pending" in summary
