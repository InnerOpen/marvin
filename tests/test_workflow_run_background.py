"""The Run button doesn't wait (`POST /api/automations/{id}/run?background=true`): it answers "started" and the run goes
on after the response, in its own session — a run over many entries (re-listing a whole shop) outlasted the request.
Without `background` the API still waits and returns the result, as before."""

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

    assert started.status_code == 200 and started.json() == {"status": "started", "ok": True}
    ws.session.expire_all()  # the test client runs background tasks once the response is sent
    assert {ws.session.get(Entries, e.id).metadata_json.get("relisted") for e in entries} == {"yes"}
    (run,) = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_id=workflow.id).all()
    assert (run.status, run.targets_run) == ("success", 3)


def test_without_background_the_api_still_waits_for_the_result(ws, campaigns):  # noqa: F811
    workflow, _ = campaigns
    ran = TestClient(app).post(f"/api/automations/{workflow.id}/run")
    assert ran.status_code == 200 and ran.json()["status"] == "ran" and ran.json()["ran"] == 3
