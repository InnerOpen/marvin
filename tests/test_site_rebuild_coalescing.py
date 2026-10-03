"""Rebuild requests are coalesced per workspace: a burst becomes one `webhook_triggered`.

A bulk edit fires a workflow per entry, each asking for a rebuild; with a deploy hook on
`webhook_triggered` that was one static-site build per entry. Requests now queue a row, and the
scheduler tick sends one rebuild per workspace once requests have gone quiet.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pytest import fixture, raises
from sqlalchemy import delete, select

from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel
from marvin.services import site_rebuild
from marvin.services.site_rebuild import MAX_LISTED_CHANGES, rebuild_change, request_rebuild

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
QUIET_SECONDS = 60
MAX_WAIT_SECONDS = 600


def dispatch_due_rebuilds(session, send, *, now):
    """The tick under test, with the windows pinned so the tests don't depend on the environment."""
    return site_rebuild.dispatch_due_rebuilds(session, send, now=now, quiet_seconds=QUIET_SECONDS, max_wait_seconds=MAX_WAIT_SECONDS)


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
    """Records each dispatched rebuild as (group_id, reason); what each covered goes in `.covered`."""

    def __init__(self):
        super().__init__()
        self.covered: dict = {}

    def send(self, group_id, reason, changes, count):
        self.append((group_id, reason))
        self.covered[group_id] = (changes, count)


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

    def send(group_id, reason, changes, count):
        if group_id == workspace:
            raise RuntimeError("bus down")
        sent.send(group_id, reason, changes, count)

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
    assert row.changes == [rebuild_change("square listing")]  # the same reason twice is one line
    assert "queued" in summary and "2 requests pending" in summary


def test_the_windows_come_from_app_settings(db_session, workspace, sent, monkeypatch):
    settings = SimpleNamespace(SITE_REBUILD_QUIET_SECONDS=5, SITE_REBUILD_MAX_WAIT_SECONDS=30)
    monkeypatch.setattr(site_rebuild, "get_app_settings", lambda: settings)
    request_rebuild(db_session, workspace, "quick", now=_at(0))

    assert site_rebuild.dispatch_due_rebuilds(db_session, sent.send, now=_at(5)) == 1


def test_max_wait_shorter_than_quiet_is_rejected():
    from pydantic import ValidationError

    from marvin.core.settings.settings import AppSettings

    with raises(ValidationError, match="SITE_REBUILD_MAX_WAIT_SECONDS"):
        AppSettings(SECRET="x", SITE_REBUILD_QUIET_SECONDS=120, SITE_REBUILD_MAX_WAIT_SECONDS=60)


# --- What changed: each request can say what it was for, and the rebuild lists them ---


def _entry_change(n: int, verb: str = "published") -> dict:
    return rebuild_change(f"Entry 'e{n}' {verb}", f"entry_{verb}", "entry", uuid.UUID(int=n))


def _listed(db_session, workspace) -> list[dict]:
    db_session.expire_all()
    return db_session.execute(select(SiteRebuildRequestModel.changes).where(SiteRebuildRequestModel.group_id == workspace)).scalar_one()


def test_each_request_records_what_changed_newest_last(db_session, workspace):
    request_rebuild(db_session, workspace, "a", change=_entry_change(1), now=_at(0))
    request_rebuild(db_session, workspace, "b", change=_entry_change(2), now=_at(1))

    assert _listed(db_session, workspace) == [_entry_change(1), _entry_change(2)]


def test_a_repeat_change_to_one_entry_is_listed_once_as_the_newest(db_session, workspace):
    request_rebuild(db_session, workspace, "a", change=_entry_change(1, "updated"), now=_at(0))
    request_rebuild(db_session, workspace, "b", change=_entry_change(2), now=_at(1))
    request_rebuild(db_session, workspace, "c", change=_entry_change(1, "published"), now=_at(2))

    assert _listed(db_session, workspace) == [_entry_change(2), _entry_change(1, "published")]


def test_the_list_keeps_the_newest_changes_but_the_count_stays_exact(db_session, workspace):
    total = MAX_LISTED_CHANGES + 7
    for n in range(total):
        count = request_rebuild(db_session, workspace, "edit", change=_entry_change(n), now=_at(n))

    listed = _listed(db_session, workspace)
    assert count == total
    assert listed == [_entry_change(n) for n in range(total - MAX_LISTED_CHANGES, total)]


def test_a_request_without_a_change_still_counts(db_session, workspace):
    request_rebuild(db_session, workspace, "a", change=_entry_change(1), now=_at(0))
    count = request_rebuild(db_session, workspace, "manual", now=_at(1))

    assert count == 2 and _listed(db_session, workspace) == [_entry_change(1)]


def test_the_dispatch_hands_over_what_the_rebuild_covers(db_session, workspace, sent):
    request_rebuild(db_session, workspace, "a", change=_entry_change(1), now=_at(0))
    request_rebuild(db_session, workspace, "b", change=_entry_change(1), now=_at(1))
    request_rebuild(db_session, workspace, "c", change=_entry_change(2), now=_at(2))

    dispatch_due_rebuilds(db_session, sent.send, now=_at(2 + QUIET_SECONDS))

    assert sent.covered[workspace] == ([_entry_change(1), _entry_change(2)], 3)


def test_the_rebuild_event_carries_the_changes():
    from fastapi.encoders import jsonable_encoder

    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventSiteRebuildData, EventTypes
    from marvin.services.scheduled_tasks.handlers.publishing import dispatch_site_rebuild

    dispatched: list[dict] = []
    gid = uuid.uuid4()

    dispatch_site_rebuild(gid, "3 requests, latest: x", SimpleNamespace(dispatch=lambda **kw: dispatched.append(kw)), [_entry_change(1)], 3)

    (kw,) = dispatched
    assert kw["event_type"] == EventTypes.webhook_triggered and kw["message"] == "Site rebuild requested: 3 requests, latest: x"
    data = kw["document_data"]
    assert isinstance(data, EventSiteRebuildData) and data.request_count == 3 and data.workspace_id == gid
    # What a deploy hook (or any event-driven webhook) is POSTed: the event, camelCase, changes included.
    message = EventBusMessage.from_type(EventTypes.webhook_triggered, kw["message"])
    event = Event(message=message, event_type=kw["event_type"], integration_id="x", document_data=data)
    body = jsonable_encoder(event, exclude_none=True)["documentData"]
    assert body["requestCount"] == 3
    assert body["changes"] == [
        {"label": "Entry 'e1' published", "event": "entry_published", "entityType": "entry", "entityId": str(uuid.UUID(int=1))}
    ]
