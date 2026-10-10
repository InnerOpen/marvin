"""The cleanup jobs that used to be Admin → Maintenance buttons are system scheduled tasks now
(services/scheduled_tasks/handlers/maintenance.py), so a run has config, history and Run Now."""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from marvin.repos.platform.api_clients import APIClientsRepository
from marvin.repos.users.long_live_tokens import LongLiveTokensRepository
from marvin.services.scheduled_tasks.handlers import maintenance
from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

PLATFORM = None  # a system task's group_id


def _task(**config):
    return SimpleNamespace(group_id=PLATFORM, task_config=config)


@pytest.fixture
def owner(db_session, monkeypatch):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.api_clients import APIClients
    from marvin.db.models.users.users import LongLiveToken, Users

    @contextmanager
    def this_session():
        yield db_session

    monkeypatch.setattr(maintenance, "session_context", this_session)

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"mt-{marker}", slug=f"mt-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"mt-{marker}",
            email=f"mt-{marker}@t.test",
            full_name="MT",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid)
    db_session.rollback()
    db_session.query(LongLiveToken).filter_by(user_id=uid).delete()
    db_session.query(APIClients).filter_by(group_id=gid).delete()
    db_session.query(Users).filter_by(id=uid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _revoke(db_session, model, row_id, days_ago):
    db_session.query(model).filter_by(id=row_id).update({"revoked_at": datetime.now(UTC) - timedelta(days=days_ago)})
    db_session.commit()


def _ids(db_session, model, ids):
    return {row.id for row in db_session.query(model).filter(model.id.in_(ids))}


def test_revoked_tokens_go_after_the_grace_period_and_live_ones_stay(db_session, owner):
    from marvin.db.models.platform.api_clients import APIClients
    from marvin.db.models.users.users import LongLiveToken
    from marvin.schemas.user.user import LongLiveTokenRead

    tokens = LongLiveTokensRepository(db_session, "id", LongLiveToken, LongLiveTokenRead)
    old, recent, live = (tokens.create({"name": n, "user_id": owner.uid}).id for n in ("old", "recent", "live"))
    _revoke(db_session, LongLiveToken, old, days_ago=40)
    _revoke(db_session, LongLiveToken, recent, days_ago=2)
    clients = APIClientsRepository(db_session, owner.gid)
    old_site, live_site = (clients.create({"name": n, "created_by": owner.uid}).id for n in ("old site", "live site"))
    _revoke(db_session, APIClients, old_site, days_ago=40)

    summary = maintenance.PruneRevokedTokensHandler().execute(_task(age_days=30), None)

    assert summary.startswith("Deleted ") and "revoked over 30 days ago" in summary
    assert _ids(db_session, LongLiveToken, [old, recent, live]) == {recent, live}
    assert _ids(db_session, APIClients, [old_site, live_site]) == {live_site}


def test_age_zero_deletes_every_revoked_token(db_session, owner):
    from marvin.db.models.users.users import LongLiveToken
    from marvin.schemas.user.user import LongLiveTokenRead

    tokens = LongLiveTokensRepository(db_session, "id", LongLiveToken, LongLiveTokenRead)
    just_revoked = tokens.create({"name": "now", "user_id": owner.uid}).id
    _revoke(db_session, LongLiveToken, just_revoked, days_ago=0)

    maintenance.PruneRevokedTokensHandler().execute(_task(age_days=0), None)

    assert _ids(db_session, LongLiveToken, [just_revoked]) == set()


def test_admin_only_cleanup_refuses_a_workspace_context():
    workspace_task = SimpleNamespace(group_id=uuid.uuid4(), task_config={})
    for handler in (maintenance.PruneRevokedTokensHandler(), maintenance.OptimizeDatabaseHandler()):
        assert handler.admin_only
        assert handler.execute(workspace_task, None).startswith("Skipped:")


def test_optimize_database_runs_outside_a_transaction():
    # VACUUM inside a transaction is an error on both Postgres and SQLite: this would raise.
    summary = maintenance.OptimizeDatabaseHandler().execute(_task(), None)
    assert summary.startswith("VACUUM + ANALYZE completed")


def test_the_old_maintenance_buttons_ship_as_system_tasks():
    shipped = {d.task_type: d for d in SYSTEM_SCHEDULED_TASKS}
    assert shipped["cleanup_temp_files"].enabled and shipped["cleanup_temp_files"].task_config == {"age_hours": 24}
    assert shipped["prune_revoked_tokens"].enabled and shipped["prune_revoked_tokens"].task_config == {"age_days": 30}
    # Autovacuum already does this; the task is there for Run Now, not a schedule.
    assert not shipped["optimize_database"].enabled


def test_the_seeder_creates_a_disabled_task_disabled(db_session):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.services.scheduled_tasks.system_tasks import seed_system_scheduled_tasks

    db_session.query(ScheduledTaskModel).filter_by(slug="optimize_database", group_id=None).delete()
    db_session.commit()
    seed_system_scheduled_tasks(db_session)
    db_session.commit()

    row = db_session.query(ScheduledTaskModel).filter_by(slug="optimize_database", group_id=None).one()
    assert row.enabled is False
