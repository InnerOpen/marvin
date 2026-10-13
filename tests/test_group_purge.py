"""Deleting a workspace must not trip over the rows that don't cascade.

Most workspace-scoped tables declare ondelete="CASCADE", but preferences, invite tokens, webhooks,
event-log rows and reports do not. A force delete used to leave them in place and then
fail on a foreign key, so `force=true` could never actually delete anything.
"""

import uuid
from datetime import UTC, datetime

from pytest import fixture
from sqlalchemy import delete, func, select

from marvin.db.models.groups import Groups
from marvin.db.models.groups.invite_tokens import GroupInviteToken
from marvin.db.models.groups.preferences import GroupPreferencesModel
from marvin.db.models.groups.reports import ReportEntryModel, ReportModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.platform.event_log import EventLogModel
from marvin.services.group.group_purge import purge_group_dependents


@fixture
def loaded_group(db_session):
    """A workspace carrying one row in each table that does *not* cascade."""
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    db_session.add(Groups(session=db_session, id=gid, name=f"purge-{marker}", slug=f"purge-{marker}"))
    db_session.flush()

    report_id = uuid.uuid4()
    db_session.add_all(
        [
            GroupPreferencesModel(session=db_session, id=uuid.uuid4(), group_id=gid),
            GroupInviteToken(session=db_session, id=uuid.uuid4(), group_id=gid, token=f"tok-{marker}", uses_left=1),
            GroupWebhooksModel(session=db_session, id=uuid.uuid4(), group_id=gid, name="wh", url="http://example.test"),
            # EventLogModel doesn't use the auto_init/session constructor the group models do.
            EventLogModel(
                id=uuid.uuid4(),
                event_id=uuid.uuid4(),
                workspace_id=gid,
                event_type="test_message",
                occurred_at=datetime.now(UTC),
                integration_id="test",
                event_data={},
                message_title="test",
            ),
            ReportModel(session=db_session, id=report_id, group_id=gid, name="report", category="test", status="success"),
        ]
    )
    db_session.flush()
    # Children of the per-group parents — they reference the parent rows, not the group.
    db_session.add_all(
        [
            ReportEntryModel(session=db_session, id=uuid.uuid4(), report_id=report_id, success=True),
        ]
    )
    db_session.flush()

    yield gid

    # Purge before dropping the group — without it the teardown hits the very foreign key this
    # module is about, and every test errors instead of reporting its own result.
    purge_group_dependents(db_session, gid)
    db_session.execute(delete(Groups).where(Groups.id == gid))
    db_session.flush()


def _counts(session, gid):
    """Rows still pointing at the workspace, per non-cascading table."""
    return {
        "preferences": session.execute(select(func.count()).select_from(GroupPreferencesModel).where(GroupPreferencesModel.group_id == gid)).scalar(),
        "invites": session.execute(select(func.count()).select_from(GroupInviteToken).where(GroupInviteToken.group_id == gid)).scalar(),
        "webhooks": session.execute(select(func.count()).select_from(GroupWebhooksModel).where(GroupWebhooksModel.group_id == gid)).scalar(),
        "event_log": session.execute(select(func.count()).select_from(EventLogModel).where(EventLogModel.workspace_id == gid)).scalar(),
        "reports": session.execute(select(func.count()).select_from(ReportModel).where(ReportModel.group_id == gid)).scalar(),
    }


def test_fixture_actually_populates_the_non_cascading_tables(db_session, loaded_group):
    # Guards the test itself: if a model stops being written here, the purge assertions below
    # would pass vacuously.
    assert all(n == 1 for n in _counts(db_session, loaded_group).values())


def test_purge_clears_every_non_cascading_table(db_session, loaded_group):
    purge_group_dependents(db_session, loaded_group)
    assert all(n == 0 for n in _counts(db_session, loaded_group).values())


def test_purge_also_clears_the_child_rows(db_session, loaded_group):
    # Report entries hang off the per-group parent; leaving them would strand rows whose parent
    # is gone.
    purge_group_dependents(db_session, loaded_group)
    assert db_session.execute(select(func.count()).select_from(ReportEntryModel)).scalar() == 0


def test_group_can_be_deleted_after_purge(db_session, loaded_group):
    # The actual regression: this DELETE previously failed on a foreign key constraint.
    purge_group_dependents(db_session, loaded_group)
    db_session.execute(delete(Groups).where(Groups.id == loaded_group))
    db_session.flush()
    assert db_session.get(Groups, loaded_group) is None


def test_purge_leaves_other_workspaces_alone(db_session, loaded_group):
    other = uuid.uuid4()
    marker = other.hex[:8]
    db_session.add(Groups(session=db_session, id=other, name=f"keep-{marker}", slug=f"keep-{marker}"))
    db_session.flush()
    db_session.add(GroupPreferencesModel(session=db_session, id=uuid.uuid4(), group_id=other))
    db_session.flush()

    purge_group_dependents(db_session, loaded_group)

    assert _counts(db_session, other)["preferences"] == 1

    purge_group_dependents(db_session, other)
    db_session.execute(delete(Groups).where(Groups.id == other))
    db_session.flush()
