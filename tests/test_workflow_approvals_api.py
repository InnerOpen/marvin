"""Approvals over HTTP: `GET /api/automations/approvals` lists the runs waiting for the caller, and
`POST /api/automations/approvals/{id}/decide` lets the run go on (services/automation/approvals.py)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.users.roles import WorkspaceRole
from tests.test_workflow_library import _entry_doc, _fire
from tests.test_workflow_library_api import _sign_in, ws  # noqa: F401 — the fixture

APPROVALS = "/api/automations/approvals"


@pytest.fixture(autouse=True)
def runs_cleared(ws):  # noqa: F811
    """This workspace fixture doesn't expect runs: clear them (and the approvals) before it deletes the workspace."""
    yield
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel

    ws.session.rollback()
    from marvin.db.models.users.users import Users

    for model in (WorkflowApprovalModel, AutomationActionExecutionModel, AutomationExecutionModel):
        ws.session.query(model).filter(model.group_id == ws.gid).delete(synchronize_session=False)
    from marvin.db.models.platform.event_log import EventLogModel

    editors = [u.id for u in ws.session.query(Users).filter(Users.group_id == ws.gid, Users.username.like("ed-%"))]
    if editors:  # the events their decision sent hold them
        ws.session.query(EventLogModel).filter(EventLogModel.user_id.in_(editors)).delete(synchronize_session=False)
        ws.session.query(Users).filter(Users.id.in_(editors)).delete(synchronize_session=False)
    ws.session.commit()


def _waiting_run(ws):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.platform import EntryTypes
    from marvin.db.models.platform.entries import Entries

    definition = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [
            {"kind": "approval", "id": "ok", "message": "Feature “${entry.title}”?"},
            {"kind": "entry", "op": "set_metadata", "metadata": {"decision": "${steps.ok.output.decision}"}},
        ],
    }
    ws.session.add(
        WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Sign-off", slug="sign-off", enabled=True, definition=definition)
    )
    entry_type = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="campaign").one()
    entry = Entries(
        session=ws.session,
        group_id=ws.gid,
        entry_type_id=entry_type.id,
        title="Spring sale",
        slug=f"spring-{uuid.uuid4().hex[:6]}",
        status="published",
    )
    ws.session.add(entry)
    ws.session.commit()
    _fire(ws, "entry_published", _entry_doc(entry), entity=entry.id, entity_type="entry")
    return entry


def _sign_in_as_real_editor(ws):  # noqa: F811
    """A real user (a decision records who decided), signed in as an EDITOR of the workspace."""
    from types import SimpleNamespace

    from marvin.core.dependencies import get_current_user
    from marvin.db.models.users.roles import PlatformRole
    from marvin.db.models.users.users import Users

    uid = uuid.uuid4()
    marker = uid.hex[:8]
    ws.session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=ws.gid, username=f"ed-{marker}", email=f"ed-{marker}@t.test", full_name="Ed", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip
    ws.session.commit()
    role = WorkspaceRole.EDITOR
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid, group_id=ws.gid, active_group_id=ws.gid, admin=False, is_superuser=False, platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=ws.gid, workspace_role=role)],
        get_workspace_role=lambda group_id: role if str(group_id) == str(ws.gid) else None,
    )  # fmt: skip
    return uid


def test_an_editor_sees_and_decides_a_waiting_run(ws):  # noqa: F811
    from marvin.db.models.platform.entries import Entries

    entry = _waiting_run(ws)
    uid = _sign_in_as_real_editor(ws)
    client = TestClient(app)

    (waiting,) = client.get(APPROVALS).json()
    assert (waiting["message"], waiting["entryTitle"], waiting["approvers"], waiting["status"]) == (
        "Feature “Spring sale”?",
        "Spring sale",
        "editor",
        "pending",
    )

    decided = client.post(f"{APPROVALS}/{waiting['id']}/decide", json={"decision": "deny", "note": "Not this week"})
    assert decided.status_code == 200 and decided.json()["status"] == "denied" and decided.json()["note"] == "Not this week"
    ws.session.expire_all()
    assert ws.session.get(Entries, entry.id).metadata_json["decision"] == "denied"
    assert client.get(APPROVALS).json() == []
    assert client.post(f"{APPROVALS}/{waiting['id']}/decide", json={"decision": "approve"}).status_code == 409
    assert decided.json()["decidedBy"] == str(uid)


def test_an_author_may_not(ws):  # noqa: F811
    _waiting_run(ws)
    _sign_in(ws.gid, WorkspaceRole.AUTHOR)
    assert TestClient(app).get(APPROVALS).status_code == 403


def test_a_choice_travels_through_the_api(ws):  # noqa: F811
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel

    _waiting_run(ws)
    row = ws.session.query(WorkflowApprovalModel).filter_by(group_id=ws.gid).one()
    row.choices = ["Dawn", "Dusk"]
    ws.session.commit()
    _sign_in_as_real_editor(ws)
    client = TestClient(app)

    (waiting,) = client.get(APPROVALS).json()
    assert waiting["choices"] == ["Dawn", "Dusk"] and waiting["choice"] is None
    assert client.post(f"{APPROVALS}/{waiting['id']}/decide", json={"decision": "approve"}).status_code == 422
    decided = client.post(f"{APPROVALS}/{waiting['id']}/decide", json={"decision": "approve", "choice": "Dusk"})
    assert decided.status_code == 200 and (decided.json()["status"], decided.json()["choice"]) == ("approved", "Dusk")
