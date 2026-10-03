"""Scheduled publishing publishes due entries once, and only the ones it should.

Regression: publishing never cleared publish_at, so an entry that went live (on schedule or by
hand) and was then unpublished went live again on the next run, and an archived entry with an old
schedule was brought back.

Regression: the scheduled publish/expiry wrote the status directly and dispatched an event with no
entry in it, so nothing keyed on the entry reacted: a smart collection didn't pick up a scheduled
publish until it was re-saved. They now change status as a manual edit does (EntryService).
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pytest import fixture

from marvin.services.event_bus_service.event_types import EventTypes
from marvin.services.scheduled_tasks.handlers.publishing import PublishScheduledEntriesHandler, UnpublishExpiredEntriesHandler

PAST = datetime.now(UTC) - timedelta(hours=1)
FUTURE = datetime.now(UTC) + timedelta(days=1)


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"sched-{gid.hex[:8]}", slug=f"sched-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Newsletter", slug="newsletter", schema_json={})
    db_session.add(et)
    db_session.commit()
    yield SimpleNamespace(id=gid, entry_type_id=et.id)
    collection_ids = [c.id for c in db_session.query(Collections).filter_by(group_id=gid)]
    if collection_ids:
        db_session.query(EntryCollections).filter(EntryCollections.collection_id.in_(collection_ids)).delete()
    db_session.query(Collections).filter_by(group_id=gid).delete()
    db_session.query(Entries).filter_by(group_id=gid).delete()
    db_session.query(EntryTypes).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@fixture
def make_entry(db_session, workspace):
    from marvin.db.models.platform import Entries

    def make(status="draft", **fields):
        entry = Entries(
            session=db_session,
            group_id=workspace.id,
            entry_type_id=workspace.entry_type_id,
            title=f"E-{uuid.uuid4().hex[:6]}",
            slug=f"e-{uuid.uuid4().hex[:8]}",
            status=status,
        )
        for key, value in fields.items():
            setattr(entry, key, value)
        db_session.add(entry)
        db_session.commit()
        return entry.id

    return make


def run_task(workspace_id, handler=PublishScheduledEntriesHandler, **config):
    events: list[dict] = []
    task = SimpleNamespace(group_id=workspace_id, task_config=config)
    summary = handler().execute(task, SimpleNamespace(dispatch=lambda **kw: events.append(kw)))
    return summary, events


def of_type(events, event_type):
    return [e for e in events if e["event_type"] == event_type]


def reload(db_session, entry_id):
    from marvin.db.models.platform import Entries

    db_session.expire_all()
    return db_session.get(Entries, entry_id)


def test_publish_due_entry_publishes_and_clears_schedule(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at, entry.published_at is not None) == ("published", None, True)
    assert len(of_type(events, EventTypes.entry_published)) == 1 and summary.startswith("1 entry published")


def test_publish_entry_unpublished_after_schedule_stays_unpublished(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)
    run_task(workspace.id)
    entry = reload(db_session, entry_id)
    entry.status = "draft"
    entry.published_at = None
    db_session.commit()

    run_task(workspace.id)

    assert reload(db_session, entry_id).status == "draft"


def test_publish_archived_entry_with_old_schedule_is_not_resurrected(db_session, workspace, make_entry):
    entry_id = make_entry(status="archived", publish_at=PAST)

    summary, _ = run_task(workspace.id)

    assert reload(db_session, entry_id).status == "archived"
    assert summary is None


def test_publish_future_schedule_is_left_alone(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=FUTURE)

    run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at is not None) == ("draft", True)


def test_publish_keeps_a_backdated_published_at(db_session, workspace, make_entry):
    backdated = datetime(2024, 1, 15, 9, 0, tzinfo=UTC)
    entry_id = make_entry(publish_at=PAST, published_at=backdated)

    run_task(workspace.id)

    assert reload(db_session, entry_id).published_at == backdated


def test_publish_dry_run_changes_nothing(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id, dry_run=True)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at is not None, events) == ("draft", True, [])
    assert summary.endswith("(dry run)")


def repos_for(db_session, workspace):
    from marvin.repos.all_repositories import get_repositories

    return get_repositories(db_session, group_id=workspace.id)


def test_manual_publish_clears_schedule(db_session, workspace, make_entry):
    from marvin.schemas.platform import EntryUpdate

    entry_id = make_entry(publish_at=FUTURE)

    repos_for(db_session, workspace).entries.update(entry_id, EntryUpdate(status="published"))

    assert reload(db_session, entry_id).publish_at is None


def test_create_as_published_drops_schedule(db_session, workspace):
    from marvin.schemas.platform import EntryCreate

    created = repos_for(db_session, workspace).entries.create(
        EntryCreate(entry_type_id=workspace.entry_type_id, title="Live now", status="published", publish_at=FUTURE)
    )

    assert reload(db_session, created.id).publish_at is None


def test_manual_publish_then_unpublish_is_not_republished_by_task(db_session, workspace, make_entry):
    from marvin.schemas.platform import EntryUpdate

    entry_id = make_entry(publish_at=PAST)
    repos = repos_for(db_session, workspace)
    repos.entries.update(entry_id, EntryUpdate(status="published"))
    repos.entries.update(entry_id, EntryUpdate(status="draft"))

    run_task(workspace.id)

    assert reload(db_session, entry_id).status == "draft"


def test_system_and_workspace_publish_tasks_publish_once(db_session, workspace, make_entry):
    """The built-in platform-wide task and a workspace's own task can both run in one tick."""
    entry_id = make_entry(publish_at=PAST)

    _, system_events = run_task(None)
    workspace_summary, workspace_events = run_task(workspace.id)

    published = of_type(system_events + workspace_events, EventTypes.entry_published)
    published_here = [e for e in published if e["group_id"] == workspace.id]
    assert (reload(db_session, entry_id).status, len(published_here), workspace_summary) == ("published", 1, None)


def test_unpublish_with_nothing_expired_records_nothing(workspace):
    task = SimpleNamespace(group_id=workspace.id, task_config={})

    assert UnpublishExpiredEntriesHandler().execute(task, SimpleNamespace(dispatch=lambda **_: None)) is None


# ── Same events as a manual status change ──────────────────────────────────────


def test_publish_emits_updated_then_published_about_the_entry(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    _, events = run_task(workspace.id)

    assert [e["event_type"] for e in events] == [EventTypes.entry_updated, EventTypes.entry_published]
    published = events[1]
    data = published["document_data"]
    assert (published["entity_id"], published["group_id"], data.entry_id, data.entry_type, data.after) == (
        entry_id,
        workspace.id,
        entry_id,
        "newsletter",
        {"status": "published"},
    )


def test_expiry_emits_updated_unpublished_archived_about_the_entry(db_session, workspace, make_entry):
    entry_id = make_entry(status="published", expire_at=PAST)

    _, events = run_task(workspace.id, handler=UnpublishExpiredEntriesHandler)

    expected = [EventTypes.entry_updated, EventTypes.entry_unpublished, EventTypes.entry_archived]
    assert [(e["event_type"], e["entity_id"], e["document_data"].entry_id) for e in events] == [(t, entry_id, entry_id) for t in expected]


def smart_collection_bus():
    """The real event bus, fanning out only to the smart-collection listener."""
    from marvin.services.event_bus_service.event_bus_listener import SmartCollectionReactionListener
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    class SmartCollectionBus(EventBusService):
        def _get_listeners(self, group_id):
            return [SmartCollectionReactionListener(group_id)]

    return SmartCollectionBus(bg_tasks=None)


def run_with_bus(workspace_id, handler):
    task = SimpleNamespace(group_id=workspace_id, task_config={})
    return handler().execute(task, smart_collection_bus())


@fixture
def published_collection(db_session, workspace):
    from marvin.db.models.platform import Collections

    collection = Collections(
        session=db_session,
        group_id=workspace.id,
        name="Published newsletters",
        slug=f"published-{uuid.uuid4().hex[:6]}",
        is_smart=True,
        smart_rules={"entry_types": ["newsletter"], "statuses": ["published"]},
    )
    db_session.add(collection)
    db_session.commit()
    return collection.id


def members(db_session, collection_id):
    from marvin.db.models.platform import EntryCollections

    db_session.expire_all()
    return {row.entry_id for row in db_session.query(EntryCollections).filter_by(collection_id=collection_id)}


def test_scheduled_publish_joins_matching_smart_collection(db_session, workspace, make_entry, published_collection):
    entry_id = make_entry(publish_at=PAST)

    run_with_bus(workspace.id, PublishScheduledEntriesHandler)

    assert entry_id in members(db_session, published_collection)


def test_expiry_leaves_published_only_smart_collection(db_session, workspace, make_entry, published_collection):
    from marvin.services.collections.smart_collections import sync_entry

    entry_id = make_entry(status="published", expire_at=PAST)
    sync_entry(db_session, workspace.id, reload(db_session, entry_id))
    db_session.commit()
    assert entry_id in members(db_session, published_collection)

    summary = run_with_bus(workspace.id, UnpublishExpiredEntriesHandler)

    assert (reload(db_session, entry_id).status, entry_id in members(db_session, published_collection)) == ("archived", False)
    assert summary.startswith("1 entry archived")


@fixture
def strict_type_id(db_session, workspace):
    from marvin.db.models.platform import EntryTypes

    et = EntryTypes(
        session=db_session,
        group_id=workspace.id,
        name="Issue",
        slug="issue",
        schema_json={"fields": [{"key": "subject", "label": "Subject", "type": "text", "required": True}]},
    )
    db_session.add(et)
    db_session.commit()
    return et.id


def test_incomplete_entry_is_skipped_and_others_publish(db_session, workspace, make_entry, strict_type_id):
    incomplete_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    complete_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id)

    incomplete, complete = reload(db_session, incomplete_id), reload(db_session, complete_id)
    assert (incomplete.status, incomplete.publish_at is not None, complete.status) == ("draft", True, "published")
    assert [e["entity_id"] for e in of_type(events, EventTypes.entry_published)] == [complete_id]
    assert summary == f"1 entry published: '{complete.title}'; 1 skipped (incomplete: '{incomplete.title}' — Required field 'Subject' is empty.)"
