"""Automation needs a look: the workflow rules, the one summary the later pages plug into, and where it shows (the list's `attention`,
`GET /api/automations/attention`, the dashboard's `automation`)."""

# ruff: noqa: F811 — `workspace` is a fixture
import uuid
from datetime import UTC, datetime, timedelta

from marvin.db.models.groups.automation_executions import AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.automation import attention
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import workspace  # noqa: F401 — fixture

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
DEFINITION = {"trigger": {"type": "manual"}, "actions": []}


def _integration(session, gid, enabled=True):
    row = IntegrationModel(session=session, group_id=gid, provider="acme", name="Acme", slug=f"acme-{uuid.uuid4().hex[:4]}", enabled=enabled)
    session.add(row)
    session.commit()
    return row


def _workflow(session, gid, name, *, enabled=True, integration=None, blueprint=None):
    row = WorkspaceAutomationModel(
        session=session,
        group_id=gid,
        name=name,
        slug=name.lower().replace(" ", "-"),
        enabled=enabled,
        definition=DEFINITION,
        source_integration_id=integration.id if integration else None,
        source_blueprint=blueprint,
    )
    session.add(row)
    session.commit()
    return row


def _run(session, gid, workflow, status, hours_ago=1, handled=False):
    session.add(
        AutomationExecutionModel(
            session=session,
            group_id=gid,
            automation_id=workflow.id,
            automation_slug=workflow.slug,
            trigger_type="manual",
            status=status,
            handled=handled,
            started_at=NOW - timedelta(hours=hours_ago),
        )
    )
    session.commit()


def _client(workspace, role=WorkspaceRole.ADMIN):
    return gates._sign_in(workspace, role)


def _reasons(workspace) -> dict:
    res = _client(workspace).get("/api/automations")
    assert res.status_code == 200
    return {r["name"]: r["attention"] for r in res.json()}


def test_a_failed_or_partly_failed_last_run_is_flagged(db_session, workspace):
    for name, status in (("Failed", "failed"), ("Partial", "partial"), ("Fine", "success"), ("Busy", "running")):
        _run(db_session, workspace.gid, _workflow(db_session, workspace.gid, name), status)
    _workflow(db_session, workspace.gid, "Never ran")

    assert _reasons(workspace) == {
        "Failed": "last_run_failed",
        "Partial": "last_run_failed",
        "Fine": None,
        "Busy": None,
        "Never ran": None,
    }


def test_only_the_last_run_counts(db_session, workspace):
    wf = _workflow(db_session, workspace.gid, "Recovered")
    _run(db_session, workspace.gid, wf, "failed", hours_ago=5)
    _run(db_session, workspace.gid, wf, "success", hours_ago=1)

    assert _reasons(workspace)["Recovered"] is None


def test_a_failure_an_integration_policy_handled_is_not_flagged(db_session, workspace):
    _run(db_session, workspace.gid, _workflow(db_session, workspace.gid, "Handled"), "failed", handled=True)
    _run(db_session, workspace.gid, _workflow(db_session, workspace.gid, "Unhandled"), "failed", handled=False)

    assert _reasons(workspace) == {"Handled": None, "Unhandled": "last_run_failed"}


def test_a_plugin_workflow_that_is_off_while_its_integration_is_on_is_flagged(db_session, workspace):
    on, off = _integration(db_session, workspace.gid, True), _integration(db_session, workspace.gid, False)
    _workflow(db_session, workspace.gid, "Plugin off", enabled=False, integration=on)
    _workflow(db_session, workspace.gid, "Plugin on", enabled=True, integration=on)
    _workflow(db_session, workspace.gid, "Integration off", enabled=False, integration=off)

    assert _reasons(workspace) == {"Plugin off": "off_while_integration_on", "Plugin on": None, "Integration off": None}


def test_your_own_off_workflow_and_a_removed_integrations_are_not_flagged(db_session, workspace):
    _workflow(db_session, workspace.gid, "Mine", enabled=False)
    _workflow(db_session, workspace.gid, "Orphan", enabled=False, blueprint="acme-sync")  # its integration was removed: no id

    assert _reasons(workspace) == {"Mine": None, "Orphan": None}


def test_the_summary_counts_each_kind_and_names_the_first_page(db_session, workspace):
    integration = _integration(db_session, workspace.gid)
    _run(db_session, workspace.gid, _workflow(db_session, workspace.gid, "Broken"), "failed")
    _workflow(db_session, workspace.gid, "Plugin off", enabled=False, integration=integration)
    _workflow(db_session, workspace.gid, "Fine")

    found = _client(workspace).get("/api/automations/attention").json()

    assert found == {
        "total": 2,
        "kinds": {"workflows": 2, "incoming_webhooks": 0, "outgoing_webhooks": 0},
        "firstPage": "/automation/workflows?status=attention",
    }


def test_the_summary_is_empty_when_nothing_is_flagged(db_session, workspace):
    _workflow(db_session, workspace.gid, "Fine")

    found = _client(workspace).get("/api/automations/attention").json()

    assert found == {"total": 0, "kinds": {"workflows": 0, "incoming_webhooks": 0, "outgoing_webhooks": 0}, "firstPage": None}


def test_a_new_kind_plugs_into_the_summary_and_a_broken_one_counts_zero(db_session, workspace, monkeypatch):
    monkeypatch.setattr(attention, "_KINDS", list(attention._KINDS))
    attention.register("hooks", "/automation/incoming-webhooks?status=attention", lambda session, gid: 3)
    attention.register("broken", "/nowhere", lambda session, gid: 1 / 0)

    found = attention.summary(db_session, workspace.gid)

    assert found == {
        "total": 3,
        "kinds": {"workflows": 0, "incoming_webhooks": 0, "outgoing_webhooks": 0, "hooks": 3, "broken": 0},
        "first_page": "/automation/incoming-webhooks?status=attention",
    }


def test_the_first_page_is_the_first_kind_with_something_flagged(db_session, workspace, monkeypatch):
    monkeypatch.setattr(attention, "_KINDS", list(attention._KINDS))
    attention.register("hooks", "/hooks", lambda session, gid: 2)
    _run(db_session, workspace.gid, _workflow(db_session, workspace.gid, "Broken"), "failed")

    assert attention.summary(db_session, workspace.gid)["first_page"] == "/automation/workflows?status=attention"


def test_another_workspaces_workflows_never_count(db_session, workspace):
    from marvin.db.models.groups import Groups
    from marvin.services.group.group_purge import purge_group_dependents

    other_gid = uuid.uuid4()
    db_session.add(Groups(session=db_session, name=f"at-{other_gid.hex[:8]}", slug=f"at-{other_gid.hex[:8]}"))
    db_session.flush()
    other = db_session.query(Groups).filter(Groups.slug == f"at-{other_gid.hex[:8]}").one()
    try:
        _run(db_session, other.id, _workflow(db_session, other.id, "Theirs"), "failed")
        _workflow(db_session, workspace.gid, "Mine")

        assert attention.summary(db_session, workspace.gid)["total"] == 0
        assert attention.summary(db_session, other.id)["total"] == 1
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, other.id)
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()


def test_a_failure_in_another_workspace_that_names_my_workflow_does_not_flag_it(db_session, workspace):
    from marvin.db.models.groups import Groups
    from marvin.services.group.group_purge import purge_group_dependents

    mine = _workflow(db_session, workspace.gid, "Mine")
    other = Groups(session=db_session, name="at-x", slug=f"at-x-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    db_session.commit()
    try:
        _run(db_session, other.id, mine, "failed")
        assert _reasons(workspace)["Mine"] is None
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, other.id)
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()


def test_the_summary_is_for_admins(db_session, workspace):
    assert _client(workspace, WorkspaceRole.EDITOR).get("/api/automations/attention").status_code == 403


def test_the_dashboard_carries_the_count_and_the_page_for_admins_only(db_session, workspace):
    _run(db_session, workspace.gid, _workflow(db_session, workspace.gid, "Broken"), "failed")

    admin = _client(workspace).get("/api/platform/stats/dashboard").json()["attention"]
    editor = _client(workspace, WorkspaceRole.EDITOR).get("/api/platform/stats/dashboard").json()["attention"]

    assert (admin["automation"], admin["automationPage"]) == (1, "/automation/workflows?status=attention")
    assert (editor["automation"], editor["automationPage"]) == (0, None)
