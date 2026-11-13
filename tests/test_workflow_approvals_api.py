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


def _resume_inline(ws, monkeypatch):  # noqa: F811
    """A decision's run goes on in a thread of its own, on a session of its own; here that thread runs when it starts (on a
    fresh session, as a real one would have), so the test can look at what the run did."""
    import contextlib

    from marvin.db import db_setup
    from marvin.services.automation import approvals

    @contextlib.contextmanager
    def fresh_session():
        session = db_setup.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    class _Inline:
        def __init__(self, target, args=(), **_):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(approvals.threading, "Thread", _Inline)
    monkeypatch.setattr("marvin.db.db_setup.session_context", fresh_session)


def test_an_editor_sees_and_decides_a_waiting_run(ws, monkeypatch):  # noqa: F811
    from marvin.db.models.platform.entries import Entries

    _resume_inline(ws, monkeypatch)
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


def test_the_decided_list_keeps_each_note_with_who_and_when(ws, monkeypatch):  # noqa: F811
    _resume_inline(ws, monkeypatch)
    _waiting_run(ws)
    uid = _sign_in_as_real_editor(ws)
    client = TestClient(app)

    assert client.get(f"{APPROVALS}?state=decided").json() == []  # nothing is settled yet
    (waiting,) = client.get(APPROVALS).json()
    client.post(f"{APPROVALS}/{waiting['id']}/decide", json={"decision": "deny", "note": "Not this week"})

    assert client.get(APPROVALS).json() == []  # no longer waiting
    (row,) = client.get(f"{APPROVALS}?state=decided").json()
    assert (row["id"], row["status"], row["note"], row["decidedBy"]) == (waiting["id"], "denied", "Not this week", str(uid))
    assert row["decidedByName"] and row["decidedAt"] and row["message"] == "Feature “Spring sale”?"
    assert client.get(f"{APPROVALS}?state=nonsense").status_code == 422


def test_an_author_may_not_read_the_decided_list(ws):  # noqa: F811
    _waiting_run(ws)
    _sign_in(ws.gid, WorkspaceRole.AUTHOR)
    assert TestClient(app).get(f"{APPROVALS}?state=decided").status_code == 403


# ── filters: a page asks for its own cards, not the workspace's oldest hundred ──


def _asked(ws, entry_id=None, *, automation_id=None, execution_id=None, n: int = 1, minutes_ago: int = 0):  # noqa: F811
    """`n` approvals waiting (rows as `park` writes them), for a page to find among the rest."""
    from datetime import UTC, datetime, timedelta

    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel
    from marvin.services.automation.authz import ROLE_EDITOR

    automation_id = automation_id or ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid, slug="sign-off").one().id
    rows = [
        WorkflowApprovalModel(
            session=ws.session,
            group_id=ws.gid,
            automation_id=automation_id,
            execution_id=execution_id,
            step_index=0,
            message=f"Keep take {i}?",
            min_role=ROLE_EDITOR,
            entry_id=entry_id,
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )
        for i in range(n)
    ]
    ws.session.add_all(rows)
    ws.session.flush()
    for row in rows:
        row.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    ws.session.commit()
    return rows


def _other_workflow(ws):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    row = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Covers", slug="covers", enabled=True, definition={"actions": []})
    ws.session.add(row)
    ws.session.commit()
    return row


def test_the_list_filters_by_workflow_slug(ws):  # noqa: F811
    _waiting_run(ws)
    _asked(ws, automation_id=_other_workflow(ws).id)
    client = TestClient(app)

    assert [a["automationSlug"] for a in client.get(f"{APPROVALS}?automation=covers").json()] == ["covers"]
    assert [a["automationSlug"] for a in client.get(f"{APPROVALS}?automation=sign-off").json()] == ["sign-off"]
    assert client.get(f"{APPROVALS}?automation=no-such").json() == []


def test_the_list_filters_by_entries(ws):  # noqa: F811
    entry = _waiting_run(ws)
    first, second = uuid.uuid4(), uuid.uuid4()
    _asked(ws, first)
    _asked(ws, second)
    client = TestClient(app)

    assert [a["entryId"] for a in client.get(f"{APPROVALS}?entry_id={entry.id}").json()] == [str(entry.id)]
    assert {a["entryId"] for a in client.get(f"{APPROVALS}?entry_id={first}&entry_id={second}").json()} == {str(first), str(second)}
    too_many = "&".join(f"entry_id={uuid.uuid4()}" for _ in range(51))
    assert client.get(f"{APPROVALS}?{too_many}").status_code == 422


def test_the_list_filters_by_the_run_that_asked_and_each_card_names_it(ws):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    _waiting_run(ws)
    _asked(ws)
    run = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_slug="sign-off").one()

    (card,) = TestClient(app).get(f"{APPROVALS}?execution_id={run.id}").json()

    assert (card["executionId"], card["message"]) == (str(run.id), "Feature “Spring sale”?")


def test_the_filters_narrow_together_and_apply_to_the_decided_list(ws, monkeypatch):  # noqa: F811
    _resume_inline(ws, monkeypatch)
    entry = _waiting_run(ws)
    _asked(ws, entry.id, automation_id=_other_workflow(ws).id)
    _sign_in_as_real_editor(ws)
    client = TestClient(app)

    (card,) = client.get(f"{APPROVALS}?automation=sign-off&entry_id={entry.id}").json()
    assert card["automationSlug"] == "sign-off"
    assert client.get(f"{APPROVALS}?automation=sign-off&entry_id={uuid.uuid4()}").json() == []

    client.post(f"{APPROVALS}/{card['id']}/decide", json={"decision": "deny"})
    assert [a["id"] for a in client.get(f"{APPROVALS}?state=decided&automation=sign-off").json()] == [card["id"]]
    assert client.get(f"{APPROVALS}?state=decided&automation=covers").json() == []


def test_a_card_past_the_first_hundred_is_found_with_a_filter(ws):  # noqa: F811
    entry = _waiting_run(ws)
    _asked(ws, n=100, minutes_ago=60)  # a hundred older ones: the list is oldest first and stops at a hundred
    client = TestClient(app)

    unfiltered = client.get(APPROVALS).json()
    assert len(unfiltered) == 100 and str(entry.id) not in {a["entryId"] for a in unfiltered}

    assert [a["entryId"] for a in client.get(f"{APPROVALS}?entry_id={entry.id}").json()] == [str(entry.id)]


# ── a long question: a short message to read, the whole of it folded away ──


def test_a_card_carries_the_detail_beside_its_message(ws):  # noqa: F811
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel

    _waiting_run(ws)
    ws.session.query(WorkflowApprovalModel).filter_by(group_id=ws.gid).update({"detail": "The whole prompt, every line of it."})
    ws.session.commit()

    (card,) = TestClient(app).get(APPROVALS).json()

    assert (card["message"], card["detail"]) == ("Feature “Spring sale”?", "The whole prompt, every line of it.")


# ── one workflow's state, for a page that offers to run it ──

STATE = "/api/automations/state"


def test_an_editor_reads_a_workflows_state_but_may_not_run_it(ws):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    _waiting_run(ws)
    _sign_in(ws.gid, WorkspaceRole.EDITOR)

    state = TestClient(app).get(f"{STATE}?slug=sign-off").json()

    workflow = ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid, slug="sign-off").one()
    assert state == {"found": True, "id": str(workflow.id), "enabled": True, "name": "Sign-off", "canRun": False}


def test_an_admin_may_run_an_enabled_workflow_and_not_a_disabled_one(ws):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    _waiting_run(ws)
    client = TestClient(app)
    assert client.get(f"{STATE}?slug=sign-off").json()["canRun"] is True

    ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid, slug="sign-off").update({"enabled": False})
    ws.session.commit()

    off = client.get(f"{STATE}?slug=sign-off").json()
    assert (off["found"], off["enabled"], off["name"], off["canRun"]) == (True, False, "Sign-off", False)


def test_a_slug_no_workflow_has_is_not_found_and_an_author_may_not_ask(ws):  # noqa: F811
    client = TestClient(app)
    assert client.get(f"{STATE}?slug=no-such").json() == {"found": False, "id": None, "enabled": False, "name": None, "canRun": False}
    assert client.get(STATE).status_code == 422

    _sign_in(ws.gid, WorkspaceRole.AUTHOR)
    assert client.get(f"{STATE}?slug=no-such").status_code == 403
