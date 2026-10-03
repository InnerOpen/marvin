"""The admin's activity toaster polls /events/feed: events since a cursor, oldest first, with the
failure reason when there is one."""

import uuid
from datetime import UTC, datetime, timedelta

from pytest import fixture

from marvin.db.models.platform.event_log import EventLogModel
from marvin.repos.platform.event_log import EventLogRepository
from marvin.routes.platform.events_controller import FEED_FIRST_LOOK, FEED_LIMIT, FEED_MAX_CHANGES, FEED_OVERLAP, build_feed

NOW = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"feed-{gid.hex[:8]}", slug=f"feed-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    yield gid
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id == gid).delete()
    db_session.commit()


def _event(db_session, workspace, seconds_ago: float, event_type="automation_ran", body="Automation 'x' ran", document=None):
    db_session.add(
        EventLogModel(
            event_id=uuid.uuid4(),
            event_type=event_type,
            occurred_at=NOW - timedelta(seconds=seconds_ago),
            workspace_id=workspace,
            integration_id="automation",
            event_data={"documentData": document or {}},
            message_title=event_type.replace("_", " ").title(),
            message_body=body,
        )
    )
    db_session.commit()


def _feed(db_session, workspace, since=None):
    return build_feed(EventLogRepository(db_session, workspace), workspace, since, now=NOW)


def test_events_since_the_cursor_come_oldest_first(db_session, workspace):
    _event(db_session, workspace, 3, body="first")
    _event(db_session, workspace, 1, body="second")

    feed = _feed(db_session, workspace, since=NOW - timedelta(seconds=4))

    assert [e.message_body for e in feed.events] == ["first", "second"]
    assert feed.now == NOW


def test_the_cursor_overlaps_so_a_late_written_event_is_not_missed(db_session, workspace):
    _event(db_session, workspace, 20 + FEED_OVERLAP.total_seconds() - 1, body="stamped just before the last poll")

    feed = _feed(db_session, workspace, since=NOW - timedelta(seconds=20))

    assert [e.message_body for e in feed.events] == ["stamped just before the last poll"]


def test_a_first_look_shows_only_the_last_few_seconds(db_session, workspace):
    _event(db_session, workspace, FEED_FIRST_LOOK.total_seconds() + 60, body="backlog")
    _event(db_session, workspace, 1, body="just now")

    assert [e.message_body for e in _feed(db_session, workspace).events] == ["just now"]


def test_a_failed_workflow_carries_its_reason(db_session, workspace):
    _event(db_session, workspace, 1, event_type="automation_failed", document={"error": "square.create_listing failed: HTTP 401"})

    (event,) = _feed(db_session, workspace, since=NOW - timedelta(seconds=5)).events

    assert event.detail == "square.create_listing failed: HTTP 401"


def test_other_workspaces_events_are_not_included(db_session, workspace):
    from marvin.db.models.groups import Groups

    other = uuid.uuid4()
    g = Groups(session=db_session, name=f"feed-{other.hex[:8]}", slug=f"feed-{other.hex[:8]}")
    g.id = other
    db_session.add(g)
    db_session.commit()
    _event(db_session, other, 1, body="not yours")

    try:
        assert _feed(db_session, workspace, since=NOW - timedelta(seconds=5)).events == []
    finally:
        db_session.query(EventLogModel).filter(EventLogModel.workspace_id == other).delete()
        db_session.commit()


def test_a_burst_returns_the_newest_events_up_to_the_limit(db_session, workspace):
    for i in range(FEED_LIMIT + 5):
        _event(db_session, workspace, 30 - i * 0.1, body=f"e{i}")

    events = _feed(db_session, workspace, since=NOW - timedelta(seconds=60)).events

    assert len(events) == FEED_LIMIT and events[-1].message_body == f"e{FEED_LIMIT + 4}"


def _change(n: int) -> dict:
    """A listed change as the event log stores it (the event's camelCase JSON)."""
    return {"label": f"Entry 'e{n}' published", "event": "entry_published", "entityType": "entry", "entityId": str(uuid.UUID(int=n))}


def test_a_site_rebuild_lists_what_changed(db_session, workspace):
    _event(db_session, workspace, 1, event_type="webhook_triggered", document={"requestCount": 3, "changes": [_change(1), _change(2)]})

    (event,) = _feed(db_session, workspace, since=NOW - timedelta(seconds=5)).events

    assert event.request_count == 3
    assert [(c.label, c.entity_type, c.entity_id) for c in event.changes] == [
        ("Entry 'e1' published", "entry", str(uuid.UUID(int=1))),
        ("Entry 'e2' published", "entry", str(uuid.UUID(int=2))),
    ]
    assert event.model_dump(by_alias=True)["changes"][0]["entityId"] == str(uuid.UUID(int=1))


def test_the_feed_keeps_only_the_newest_changes(db_session, workspace):
    total = FEED_MAX_CHANGES + 5
    _event(db_session, workspace, 1, event_type="webhook_triggered", document={"requestCount": total, "changes": [_change(n) for n in range(total)]})

    (event,) = _feed(db_session, workspace, since=NOW - timedelta(seconds=5)).events

    assert len(event.changes) == FEED_MAX_CHANGES and event.changes[-1].label == f"Entry 'e{total - 1}' published"
    assert event.request_count == total


def test_other_events_carry_no_change_list(db_session, workspace):
    _event(db_session, workspace, 1)

    (event,) = _feed(db_session, workspace, since=NOW - timedelta(seconds=5)).events

    assert event.changes is None and event.request_count is None
