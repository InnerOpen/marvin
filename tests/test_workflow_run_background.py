"""The Run button doesn't wait (`POST /api/automations/{id}/run?background=true`): it answers "started" and the run goes
on after the response, in its own session — a run over many entries (re-listing a whole shop) outlasted the request.
Without `background` the API still waits and returns the result, as before. Either way the answer names the run
(`execution_id`), so whoever pressed Run can follow it (`GET /api/automations/runs/{execution_id}`)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from tests.test_workflow_library_api import ws  # noqa: F401 — the fixture

DEFINITION = {
    "trigger": {"type": "manual"},
    "target": {"entity": "entry", "query": {"entry_type": "campaign"}},
    "actions": [{"kind": "entry", "op": "set_metadata", "metadata": {"relisted": "yes"}}],
}


@pytest.fixture
def campaigns(ws):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.platform import EntryTypes
    from marvin.db.models.platform.entries import Entries

    entry_type = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="campaign").one()
    entries = [
        Entries(
            session=ws.session,
            group_id=ws.gid,
            entry_type_id=entry_type.id,
            title=f"Sale {i}",
            slug=f"sale-{i}-{uuid.uuid4().hex[:4]}",
            status="published",
        )
        for i in range(3)
    ]
    ws.session.add_all(entries)
    workflow = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Relist", slug="relist", enabled=True, definition=DEFINITION)
    ws.session.add(workflow)
    ws.session.commit()
    uid = _sign_in_real_admin(ws)
    yield workflow, entries
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users.users import Users

    ws.session.rollback()
    for model in (AutomationActionExecutionModel, AutomationExecutionModel):
        ws.session.query(model).filter(model.group_id == ws.gid).delete(synchronize_session=False)
    ws.session.query(EventLogModel).filter(EventLogModel.user_id == uid).delete(synchronize_session=False)
    ws.session.query(Users).filter(Users.id == uid).delete(synchronize_session=False)
    ws.session.commit()


def _sign_in_real_admin(ws):  # noqa: F811
    """A real user (the run records who ran it), signed in as the workspace's ADMIN."""
    from types import SimpleNamespace

    from marvin.core.dependencies import get_current_user
    from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
    from marvin.db.models.users.users import Users

    uid = uuid.uuid4()
    ws.session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=ws.gid, username=f"run-{uid.hex[:8]}", email=f"run-{uid.hex[:8]}@t.test", full_name="Runner",
            password="x", is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip
    ws.session.commit()
    role = WorkspaceRole.ADMIN
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid, group_id=ws.gid, active_group_id=ws.gid, admin=False, is_superuser=False, platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=ws.gid, workspace_role=role)],
        get_workspace_role=lambda group_id: role if str(group_id) == str(ws.gid) else None,
    )  # fmt: skip
    return uid


def test_a_background_run_answers_at_once_and_still_does_the_work(ws, campaigns):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.db.models.platform.entries import Entries

    workflow, entries = campaigns

    started = TestClient(app).post(f"/api/automations/{workflow.id}/run?background=true")

    assert started.status_code == 200 and started.json() == {"status": "started", "ok": True, "execution_id": started.json()["execution_id"]}
    ws.session.expire_all()  # the test client runs background tasks once the response is sent
    assert {ws.session.get(Entries, e.id).metadata_json.get("relisted") for e in entries} == {"yes"}
    (run,) = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_id=workflow.id).all()
    assert (run.status, run.targets_run) == ("success", 3)


def test_a_background_run_is_recorded_under_the_id_its_answer_gave(ws, campaigns):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    workflow, _ = campaigns

    started = TestClient(app).post(f"/api/automations/{workflow.id}/run?background=true")

    ws.session.expire_all()
    (run,) = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_id=workflow.id).all()
    assert started.json()["execution_id"] == str(run.id)
    assert (run.targets_matched, run.steps_ok, run.correlation_id is not None) == (3, 3, True)  # the run filled in the row made for it


def test_a_background_run_that_never_starts_is_closed_as_failed(ws, campaigns, monkeypatch):  # noqa: F811
    """The id was given out, so the row must not sit at "running" for good when the run stops before its first step."""
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.services.automation import engine

    workflow, _ = campaigns

    def no_run(*args, **kwargs):
        raise RuntimeError("the target query broke")

    monkeypatch.setattr(engine, "_run_targets", no_run)

    started = TestClient(app).post(f"/api/automations/{workflow.id}/run?background=true")

    ws.session.expire_all()
    run = ws.session.get(AutomationExecutionModel, uuid.UUID(started.json()["execution_id"]))
    assert (run.status, run.finished_at is not None) == ("failed", True) and "did not start" in run.error


def test_without_background_the_api_still_waits_for_the_result(ws, campaigns):  # noqa: F811
    workflow, _ = campaigns
    ran = TestClient(app).post(f"/api/automations/{workflow.id}/run")
    assert ran.status_code == 200 and ran.json()["status"] == "ran" and ran.json()["ran"] == 3


def test_a_waited_run_names_its_recorded_run_too(ws, campaigns):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    workflow, _ = campaigns

    ran = TestClient(app).post(f"/api/automations/{workflow.id}/run")

    (run,) = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_id=workflow.id).all()
    assert ran.json()["execution_id"] == str(run.id)


def test_a_dry_run_names_no_run(ws, campaigns):  # noqa: F811
    workflow, _ = campaigns
    assert "execution_id" not in TestClient(app).post(f"/api/automations/{workflow.id}/run?dry_run=true").json()
