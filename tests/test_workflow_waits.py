"""Wait steps: a run parks at the step and goes on later — after a while (`for`), or at a moment worked out from a date
(`until` + `offset` + `at`) in the workspace's time zone. The minutely sweep resumes it with the entry as it is then;
an entry gone to the Trash, or a workflow switched off or changed, cancels it. A moment already past doesn't wait."""

# ruff: noqa: F811 — `ws` / `workspace` are fixtures, not redefinitions
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.workflow_waits import WorkflowWaitModel
from marvin.services.automation import waits
from marvin.services.automation.engine import run_automation_now
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures


def _entry(ws, title="Open studio", data=None):
    from marvin.db.models.platform.entries import Entries

    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}", status="published", data_json=data or {}, metadata_json={},
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _workflow(ws, actions, inputs=None):
    trigger = {"type": "manual", "inputs": inputs} if inputs else {"type": "manual"}
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Later", slug=f"later-{uuid.uuid4().hex[:6]}", enabled=True,
        definition={"trigger": trigger, "actions": actions},
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    return row


def _run(ws, row, **kwargs):
    return run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), **kwargs)


def _metadata(ws, entry) -> dict:
    ws.session.expire_all()
    return ws.session.get(type(entry), entry.id).metadata_json or {}


def _wait_row(ws, row) -> WorkflowWaitModel:
    return ws.session.query(WorkflowWaitModel).filter_by(automation_id=row.id).one()


# ── When ─────────────────────────────────────────────────────────────────────
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def test_a_span_and_a_date_with_an_offset_and_a_time(ws):
    assert waits.resume_time(ws.session, ws.gid, wait_for="3d", now_=NOW) == NOW + timedelta(days=3)
    assert waits.resume_time(ws.session, ws.gid, wait_for="90m", now_=NOW) == NOW + timedelta(minutes=90)
    # A week before 8 November at 09:00 New York is 1 November at 09:00 — after the clock went back that morning,
    # so 14:00 UTC, not 13:00: the offset is counted on the calendar, not in hours.
    when = waits.resume_time(ws.session, ws.gid, until="2026-11-08", offset="-7d", at="09:00", now_=NOW)
    assert when == datetime(2026, 11, 1, 14, 0, tzinfo=UTC)
    assert waits.resume_time(ws.session, ws.gid, until="2026-12-01T18:30:00+00:00", now_=NOW) == datetime(2026, 12, 1, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"wait_for": "soon"}, "give a span like"),
        ({"until": "next tuesday"}, "isn't a date"),
        ({"until": ""}, "resolved to empty"),
        ({"until": "2026-11-08", "offset": "a week"}, "give a span like -7d"),
        ({"until": "2026-11-08", "at": "9am"}, "time of day like 09:00"),
    ],
)
def test_what_cant_be_read_says_so(ws, kwargs, message):
    from marvin.services.automation.actions.base import AutomationActionError

    with pytest.raises(AutomationActionError, match=message):
        waits.resume_time(ws.session, ws.gid, now_=NOW, **kwargs)


# ── Park and resume ──────────────────────────────────────────────────────────
def test_a_run_parks_and_goes_on_when_its_time_comes(ws):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    studio = _entry(ws)
    row = _workflow(
        ws,
        [
            {"kind": "wait", "id": "later", "for": "2d"},
            {"kind": "entry", "op": "set_metadata", "metadata": {"reminded": "${steps.later.output.waited_until}"}},
        ],
        inputs=[{"name": "piece", "type": "entry"}],
    )

    result = _run(ws, row, inputs={"piece": studio.slug})

    assert result["ok"] and _metadata(ws, studio) == {}  # parked: nothing after the wait ran yet
    wait = _wait_row(ws, row)
    parked = ws.session.get(AutomationExecutionModel, wait.execution_id)
    assert (wait.status, parked.status) == ("waiting", "waiting")
    assert waits.resume_due(ws.session, now_=waits.now()) == 0  # not yet

    assert waits.resume_due(ws.session, now_=waits.now() + timedelta(days=2, minutes=1)) == 1

    ws.session.expire_all()
    assert _metadata(ws, studio)["reminded"] == wait.resume_at.isoformat()
    assert (_wait_row(ws, row).status, ws.session.get(AutomationExecutionModel, wait.execution_id).status) == ("resumed", "resumed")
    assert waits.resume_due(ws.session, now_=waits.now() + timedelta(days=3)) == 0  # once


def test_run_inputs_survive_a_wait(ws):
    studio = _entry(ws)
    row = _workflow(
        ws,
        [{"kind": "wait", "for": "1h"}, {"kind": "entry", "op": "set_metadata", "metadata": {"style": "${input.style}"}}],
        inputs=[{"name": "piece", "type": "entry"}, {"name": "style", "type": "choice", "options": ["haiku", "limerick"]}],
    )
    _run(ws, row, inputs={"piece": studio.slug, "style": "limerick"})

    waits.resume_due(ws.session, now_=waits.now() + timedelta(hours=2))

    assert _metadata(ws, studio)["style"] == "limerick"


def test_a_moment_already_past_doesnt_wait(ws):
    studio = _entry(ws, data={"date": "2020-01-01"})
    row = _workflow(
        ws,
        [
            {"kind": "wait", "id": "w", "until": "${entry.data.date}", "offset": "-7d"},
            {"kind": "entry", "op": "set_metadata", "metadata": {"late": "${steps.w.output.late}"}},
        ],
        inputs=[{"name": "piece", "type": "entry"}],
    )

    _run(ws, row, inputs={"piece": studio.slug})

    assert _metadata(ws, studio)["late"] is True and ws.session.query(WorkflowWaitModel).filter_by(automation_id=row.id).count() == 0


@pytest.mark.parametrize("change", ["trash the entry", "switch the workflow off"])
def test_a_wait_is_cancelled_when_its_entry_or_workflow_goes(ws, change):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    studio = _entry(ws)
    row = _workflow(
        ws,
        [{"kind": "wait", "for": "1d"}, {"kind": "entry", "op": "set_metadata", "metadata": {"done": True}}],
        inputs=[{"name": "piece", "type": "entry"}],
    )
    _run(ws, row, inputs={"piece": studio.slug})
    if change == "trash the entry":
        studio.status = "trashed"
    else:
        row.enabled = False
    ws.session.commit()

    waits.resume_due(ws.session, now_=waits.now() + timedelta(days=2))

    wait = _wait_row(ws, row)
    assert wait.status == "cancelled" and wait.note and ws.session.get(AutomationExecutionModel, wait.execution_id).status == "cancelled"
    assert "done" not in _metadata(ws, studio)


def test_a_dry_run_says_when_and_doesnt_wait(ws):
    row = _workflow(ws, [{"kind": "wait", "for": "3d"}])
    result = run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, dry_run=True)
    assert result["ok"] and "would_wait_until" in result["plan"][0]["resolved"]
    assert ws.session.query(WorkflowWaitModel).filter_by(automation_id=row.id).count() == 0


def test_a_wait_of_more_than_a_year_fails(ws):
    row = _workflow(ws, [{"kind": "wait", "until": (datetime.now(UTC) + timedelta(days=400)).date().isoformat()}])
    result = _run(ws, row)
    assert not result["ok"]


@pytest.mark.parametrize(
    "step",
    [
        {"kind": "wait"},
        {"kind": "wait", "for": "3d", "until": "2026-11-08"},
        {"kind": "wait", "for": "3d", "offset": "-1d"},
        {"kind": "wait", "for": "soon"},
    ],
)
def test_the_validator_names_a_wait_step_it_cant_read(ws, step):
    from marvin.services.automation.authoring import draft_issues

    assert draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [step]})


def test_an_admin_cancels_a_waiting_run_from_the_api(ws):
    from fastapi.testclient import TestClient

    from marvin.app import app
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.db.models.users.roles import WorkspaceRole
    from tests.test_workflow_library_api import _sign_in

    studio = _entry(ws)
    row = _workflow(
        ws,
        [{"kind": "wait", "for": "2d"}, {"kind": "entry", "op": "set_metadata", "metadata": {"reminded": True}}],
        inputs=[{"name": "piece", "type": "entry"}],
    )
    _run(ws, row, inputs={"piece": studio.slug})
    wait = _wait_row(ws, row)
    _sign_in(ws.gid, WorkspaceRole.ADMIN)
    client = TestClient(app)
    base = f"/api/automations/{row.id}/executions/{wait.execution_id}/cancel"

    cancelled = client.post(base)

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(base).status_code == 409  # not waiting any more
    assert waits.resume_due(ws.session, now_=waits.now() + timedelta(days=3)) == 0
    assert _metadata(ws, studio) == {}  # the steps after the wait never ran
    ws.session.expire_all()
    assert (_wait_row(ws, row).status, ws.session.get(AutomationExecutionModel, wait.execution_id).status) == ("cancelled", "cancelled")
    assert "cancelled by" in _wait_row(ws, row).note
    app.dependency_overrides.clear()
