"""The workspace Scheduled tasks page's reads: the workspace's tasks and Marvin's own in one list (EDITOR+), a task's run history,
and the Needs-attention count it adds to the automation summary."""

# ruff: noqa: F811 — `workspace` is a fixture
import uuid
from datetime import UTC, datetime

import pytest

from marvin.db.models.groups import Groups
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel, ScheduledTaskModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.automation import attention
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import workspace  # noqa: F401 — fixture

URL = "/api/platform/scheduled-tasks"
ED, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _task(session, gid, name, *, status=None, enabled=True, integration=None, blueprint=None):
    row = ScheduledTaskModel(
        session=session,
        group_id=gid,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        enabled=enabled,
        schedule_type="cron",
        schedule_config={"cron_expression": "0 * * * *"},
        task_type="prune_expired_invitations",
        task_config={"secret": "do-not-show"},
        last_status=status,
        last_run_at=NOW if status else None,
        source_integration_id=integration,
        source_blueprint=blueprint,
    )
    session.add(row)
    session.commit()
    return row


def _integration(session, gid):
    row = IntegrationModel(session=session, group_id=gid, provider="acme", name="Acme", slug=f"acme-{uuid.uuid4().hex[:4]}", enabled=True)
    session.add(row)
    session.commit()
    return row


def _client(workspace, role=AD):
    return gates._sign_in(workspace, role)


@pytest.fixture
def system_task(db_session):
    row = _task(db_session, None, "Marvin Housekeeping", status="failed")
    yield row
    db_session.rollback()
    db_session.query(ScheduledTaskExecutionLogModel).filter(ScheduledTaskExecutionLogModel.task_id == row.id).delete()
    db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.id == row.id).delete()
    db_session.commit()


def _by_name(res):
    assert res.status_code == 200, res.text
    return {r["name"]: r for r in res.json()}


def test_the_overview_has_the_workspaces_tasks_and_marvins_own(db_session, workspace, system_task):
    _task(db_session, workspace.gid, "Mine")
    other = uuid.uuid4()
    db_session.add(Groups(session=db_session, name="x", slug=f"x-{other.hex[:6]}", id=other))
    db_session.commit()
    _task(db_session, other, "Someone else's")
    try:
        rows = _by_name(_client(workspace, ED).get(f"{URL}/overview"))
        # The platform's own seeded tasks are in there too (whatever the database holds), so look at the workspace's rows exactly.
        assert {n for n, r in rows.items() if not r["system"]} == {"Mine"}
        assert "Marvin Housekeeping" in rows and "Someone else's" not in rows
        assert all(r["attention"] is None for r in rows.values() if r["system"])
        assert rows["Mine"]["system"] is False and rows["Marvin Housekeeping"]["system"] is True
        assert rows["Mine"]["scheduleConfig"] == {"cron_expression": "0 * * * *"}
    finally:
        db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id == other).delete()
        db_session.query(Groups).filter(Groups.id == other).delete()
        db_session.commit()


def test_the_overview_leaves_out_what_a_task_is_configured_with(db_session, workspace):
    _task(db_session, workspace.gid, "Mine")
    row = _client(workspace, ED).get(f"{URL}/overview").json()[0]
    assert "taskConfig" not in row and "do-not-show" not in str(row)


@pytest.mark.parametrize("role", [WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER])
def test_below_an_editor_may_not_read_the_overview_or_a_history(db_session, workspace, role):
    task = _task(db_session, workspace.gid, "Mine")
    client = _client(workspace, role)
    assert client.get(f"{URL}/overview").status_code == 403
    assert client.get(f"{URL}/overview/{task.id}/history").status_code == 403


def test_an_editor_reads_but_only_an_admin_acts(db_session, workspace):
    task = _task(db_session, workspace.gid, "Mine")
    editor = _client(workspace, ED)
    assert editor.get(f"{URL}/overview").status_code == 200
    assert editor.patch(f"{URL}/{task.id}", json={"enabled": False}).status_code == 403
    assert editor.post(f"{URL}/{task.id}/execute").status_code == 403
    admin = _client(workspace, AD)
    assert admin.patch(f"{URL}/{task.id}", json={"enabled": False}).json()["enabled"] is False
    assert admin.post(f"{URL}/{task.id}/execute").status_code == 202


def test_a_task_is_flagged_when_it_is_on_and_its_last_run_failed(db_session, workspace):
    for name, status, enabled in (
        ("Failed", "failed", True),
        ("Timed out", "timeout", True),
        ("Fine", "success", True),
        ("New", None, True),
        ("Off", "failed", False),
    ):
        _task(db_session, workspace.gid, name, status=status, enabled=enabled)
    flags = {n: r["attention"] for n, r in _by_name(_client(workspace).get(f"{URL}/overview")).items() if not r["system"]}
    assert flags == {"Failed": "last_run_failed", "Timed out": "last_run_failed", "Fine": None, "New": None, "Off": None}
    assert attention.scheduled_tasks_needing_a_look(db_session, workspace.gid) == 2


def test_marvins_own_and_a_removed_integrations_tasks_are_never_flagged(db_session, workspace, system_task):
    _task(db_session, workspace.gid, "Left behind", status="failed", blueprint="acme/sync")
    live = _integration(db_session, workspace.gid)
    _task(db_session, workspace.gid, "Installed", status="failed", integration=live.id, blueprint="acme/sync")
    rows = _by_name(_client(workspace).get(f"{URL}/overview"))
    assert rows["Marvin Housekeeping"]["attention"] is None
    assert rows["Left behind"]["attention"] is None
    assert rows["Installed"]["attention"] == "last_run_failed"
    assert attention.scheduled_tasks_needing_a_look(db_session, workspace.gid) == 1


def test_the_summary_counts_scheduled_tasks_and_names_their_page(db_session, workspace):
    _task(db_session, workspace.gid, "Failed", status="failed")
    found = attention.summary(db_session, workspace.gid)
    assert found["kinds"]["scheduled_tasks"] == 1
    assert found["first_page"] == "/workspace/scheduled-tasks?status=attention"
    over_http = _client(workspace).get("/api/automations/attention").json()
    assert over_http["kinds"]["scheduled_tasks"] == 1 and over_http["firstPage"] == "/workspace/scheduled-tasks?status=attention"


def _run(session, task, status, error=None, traceback=None):
    session.add(
        ScheduledTaskExecutionLogModel(
            session=session, task_id=task.id, group_id=task.group_id, executed_at=NOW, status=status,
            error_message=error, error_traceback=traceback, output="did things",
        )
    )  # fmt: skip
    session.commit()


def test_a_tasks_history_is_there_for_the_workspaces_task_and_marvins_own(db_session, workspace, system_task):
    mine = _task(db_session, workspace.gid, "Mine")
    _run(db_session, mine, "failed", "boom", "Traceback: secret frames")
    _run(db_session, system_task, "success")
    client = _client(workspace, ED)
    history = client.get(f"{URL}/overview/{mine.id}/history").json()
    assert [(h["status"], h["errorMessage"], h["output"]) for h in history] == [("failed", "boom", "did things")]
    assert "errorTraceback" not in history[0] and "secret frames" not in str(history)
    assert [h["status"] for h in client.get(f"{URL}/overview/{system_task.id}/history").json()] == ["success"]


def test_another_workspaces_task_history_is_not_found(db_session, workspace):
    other = uuid.uuid4()
    db_session.add(Groups(session=db_session, name="x", slug=f"x-{other.hex[:6]}", id=other))
    db_session.commit()
    try:
        theirs = _task(db_session, other, "Theirs")
        assert _client(workspace, ED).get(f"{URL}/overview/{theirs.id}/history").status_code == 404
    finally:
        db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id == other).delete()
        db_session.query(Groups).filter(Groups.id == other).delete()
        db_session.commit()
