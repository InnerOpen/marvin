"""Where a run stands (`GET /api/automations/runs/{execution_id}`, services/automation/run_state.py): one compact answer an
editor may read, followed past an approval to the run that went on, and on to the worker job its last step started."""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.users.roles import WorkspaceRole
from tests.test_workflow_approvals_api import APPROVALS, _resume_inline, _sign_in_as_real_editor, _waiting_run, runs_cleared  # noqa: F401
from tests.test_workflow_library import _entry_doc, _fire
from tests.test_workflow_library_api import _sign_in, ws  # noqa: F401 — the fixture

RUNS = "/api/automations/runs"
TOUCH = {"kind": "entry", "op": "set_metadata", "metadata": {"seen": "yes"}}
NO_QUESTION = {"kind": "approval", "message": "${entry.nothing_here}"}  # resolves empty: the step fails


def _campaign(ws, data: dict | None = None):  # noqa: F811
    from marvin.db.models.platform import EntryTypes
    from marvin.db.models.platform.entries import Entries

    entry_type = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="campaign").one()
    entry = Entries(
        session=ws.session,
        group_id=ws.gid,
        entry_type_id=entry_type.id,
        title="Spring sale",
        slug=f"spring-{uuid.uuid4().hex[:6]}",
        status="published",
        data_json=data or {},
    )
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _ran(ws, actions: list, data: dict | None = None):  # noqa: F811
    """A workflow of `actions` run once on a published campaign: (its recorded run, the campaign)."""
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = {"trigger": {"type": "event", "event": "entry_published"}, "actions": actions}
    workflow = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Note it", slug="note-it", enabled=True, definition=definition)
    ws.session.add(workflow)
    ws.session.commit()
    entry = _campaign(ws, data)
    _fire(ws, "entry_published", _entry_doc(entry), entity=entry.id, entity_type="entry")
    return ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_id=workflow.id).one(), entry


def _parked(ws):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    _waiting_run(ws)
    return ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_slug="sign-off").one()


def _unfinished(ws, *, steps: int = 0):  # noqa: F811
    """A run still going, as the recorder leaves it between its start and its finish, with `steps` recorded so far."""
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel

    run = AutomationExecutionModel(
        session=ws.session,
        group_id=ws.gid,
        automation_slug="slow",
        trigger_type="manual",
        status="running",
        started_at=datetime.now(UTC),
        definition_snapshot={"actions": [TOUCH] * 7},
    )
    ws.session.add(run)
    ws.session.flush()
    for index in range(steps):
        ws.session.add(
            AutomationActionExecutionModel(
                session=ws.session, execution_id=run.id, group_id=ws.gid, action_index=index, kind="entry", status="success"
            )
        )
    ws.session.commit()
    return run


def _state(run_id) -> dict:
    res = TestClient(app).get(f"{RUNS}/{run_id}")
    assert res.status_code == 200, res.text
    return res.json()


# ── who may read ─────────────────────────────────────────────────────────────


def test_an_editor_reads_a_finished_run(ws):  # noqa: F811
    run, _ = _ran(ws, [TOUCH])
    _sign_in(ws.gid, WorkspaceRole.EDITOR)

    state = _state(run.id)

    assert (state["executionId"], state["automationSlug"], state["automationName"], state["state"]) == (str(run.id), "note-it", "Note it", "done")
    assert state["startedAt"] and state["finishedAt"] and state["error"] is None
    assert (state["stepsTotal"], state["stepsOk"], state["stepsFailed"]) == (1, 1, 0)
    assert (state["waitingOn"], state["continuedBy"], state["job"]) == ([], None, None)


def test_an_author_may_not_read_a_run(ws):  # noqa: F811
    run, _ = _ran(ws, [TOUCH])
    _sign_in(ws.gid, WorkspaceRole.AUTHOR)
    assert TestClient(app).get(f"{RUNS}/{run.id}").status_code == 403


def test_a_run_of_another_workspace_is_not_found(ws):  # noqa: F811
    run, _ = _ran(ws, [TOUCH])
    _sign_in(uuid.uuid4(), WorkspaceRole.EDITOR)
    assert TestClient(app).get(f"{RUNS}/{run.id}").status_code == 404


def test_an_unknown_run_is_not_found(ws):  # noqa: F811
    assert TestClient(app).get(f"{RUNS}/{uuid.uuid4()}").status_code == 404


def test_the_answer_carries_no_step_output(ws):  # noqa: F811
    run, _ = _ran(ws, [TOUCH])
    assert set(_state(run.id)) == {
        "executionId", "automationSlug", "automationName", "state", "startedAt", "finishedAt", "error",
        "stepsTotal", "stepsOk", "stepsFailed", "waitingOn", "continuedBy", "job",
    }  # fmt: skip


# ── the states of one run ────────────────────────────────────────────────────


def test_a_run_with_no_step_recorded_yet_is_starting(ws):  # noqa: F811
    state = _state(_unfinished(ws).id)
    assert (state["state"], state["stepsOk"], state["finishedAt"]) == ("starting", 0, None)


def test_a_run_in_the_middle_says_how_far_it_has_got(ws):  # noqa: F811
    state = _state(_unfinished(ws, steps=3).id)
    assert (state["state"], state["stepsOk"], state["stepsTotal"], state["finishedAt"]) == ("running", 3, 7, None)


def test_a_run_whose_step_failed_says_why(ws):  # noqa: F811
    run, _ = _ran(ws, [TOUCH, NO_QUESTION])

    state = _state(run.id)

    assert (state["state"], state["stepsOk"], state["stepsFailed"]) == ("failed", 1, 1)
    assert "needs a message" in state["error"]


# ── past an approval ─────────────────────────────────────────────────────────


def test_a_run_at_an_approval_is_waiting_and_names_the_approval(ws):  # noqa: F811
    run = _parked(ws)
    _sign_in_as_real_editor(ws)
    (waiting,) = TestClient(app).get(APPROVALS).json()

    state = _state(run.id)

    assert state["state"] == "waiting" and state["finishedAt"] is None
    assert state["waitingOn"] == [{"approvalId": waiting["id"], "message": "Feature “Spring sale”?", "approvers": "editor"}]


def test_an_approval_above_the_readers_role_keeps_its_question_to_itself(ws):  # noqa: F811
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel
    from marvin.services.automation.authz import ROLE_ADMIN

    run = _parked(ws)
    ws.session.query(WorkflowApprovalModel).filter_by(group_id=ws.gid).update({"min_role": ROLE_ADMIN})
    ws.session.commit()
    _sign_in(ws.gid, WorkspaceRole.EDITOR)

    (asked,) = _state(run.id)["waitingOn"]

    assert (asked["message"], asked["approvers"]) == (None, "admin")


def test_after_the_decision_the_answer_follows_the_run_that_went_on(ws, monkeypatch):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    _resume_inline(ws, monkeypatch)
    run = _parked(ws)
    _sign_in_as_real_editor(ws)
    client = TestClient(app)
    (waiting,) = client.get(APPROVALS).json()

    client.post(f"{APPROVALS}/{waiting['id']}/decide", json={"decision": "approve"})

    state = _state(run.id)
    ws.session.expire_all()
    resumed = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, retry_of_id=run.id).one()
    assert (state["state"], state["executionId"], state["continuedBy"], state["waitingOn"]) == ("done", str(run.id), str(resumed.id), [])
    assert (state["stepsOk"], state["stepsTotal"], state["finishedAt"] is not None) == (2, 2, True)


def test_a_decided_approval_whose_run_has_not_gone_on_yet_is_running(ws):  # noqa: F811
    """Deciding answers at once and the run goes on behind it: between the two the run is neither waiting nor over."""
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel

    run = _parked(ws)
    ws.session.query(WorkflowApprovalModel).filter_by(group_id=ws.gid).update({"status": "approved"})
    ws.session.commit()

    assert _state(run.id)["state"] == "running"


# ── on to the worker job ─────────────────────────────────────────────────────


def test_a_run_that_queued_a_job_is_working_until_the_job_is_done(ws):  # noqa: F811
    run, job = _ran(ws, [TOUCH], data={"kind": "render", "status": "queued", "log": "a long log", "result": {"frames": 9}})

    working = _state(run.id)

    assert working["state"] == "working" and working["finishedAt"] is None
    assert working["job"] == {"entryId": str(job.id), "slug": job.slug, "kind": "render", "status": "queued", "finished": False}

    job.data_json = {**job.data_json, "status": "done"}
    ws.session.commit()
    done = _state(run.id)
    assert (done["state"], done["job"]["status"], done["job"]["finished"], done["finishedAt"] is not None) == ("done", "done", True, True)


def test_a_run_whose_job_failed_is_failed(ws):  # noqa: F811
    run, _ = _ran(ws, [TOUCH], data={"kind": "render", "status": "failed"})

    state = _state(run.id)

    assert state["state"] == "failed" and "render" in state["error"]


def test_a_step_output_too_large_to_keep_still_names_its_entry():
    from marvin.services.automation.recorder import _truncate

    kept = _truncate({"entry_id": "e-1", "merged": {"body": "x" * 9000}})

    assert kept["_truncated"] is True and kept["entry_id"] == "e-1"
