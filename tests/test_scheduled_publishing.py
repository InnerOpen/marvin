"""The Publish Scheduled Entries task publishes due entries once, and only the ones it should.

Regression: publishing never cleared publish_at, so an entry that went live on schedule and was
then unpublished went live again on the next run, and an archived entry with an old schedule was
brought back.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pytest import fixture

from marvin.services.scheduled_tasks.handlers.publishing import PublishScheduledEntriesHandler

PAST = datetime.now(UTC) - timedelta(hours=1)
FUTURE = datetime.now(UTC) + timedelta(days=1)


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"sched-{gid.hex[:8]}", slug=f"sched-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Newsletter", slug="newsletter", schema_json={})
    db_session.add(et)
    db_session.commit()
    yield SimpleNamespace(id=gid, entry_type_id=et.id)
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


def run_task(workspace_id, **config):
    events: list[dict] = []
    task = SimpleNamespace(group_id=workspace_id, task_config=config)
    summary = PublishScheduledEntriesHandler().execute(task, SimpleNamespace(dispatch=lambda **kw: events.append(kw)))
    return summary, events


def reload(db_session, entry_id):
    from marvin.db.models.platform import Entries

    db_session.expire_all()
    return db_session.get(Entries, entry_id)


def test_publish_due_entry_publishes_and_clears_schedule(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at, entry.published_at is not None) == ("published", None, True)
    assert len(events) == 1 and summary.startswith("1 entry published")


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
    assert summary == "No entries due for publishing"


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
