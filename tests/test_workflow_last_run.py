"""The workflow list says how each workflow's last run went (`last_run_at` / `last_run_status`), from its newest
execution, read in one query for the whole list — the Workflows page shows it on every card."""

# ruff: noqa: F811 — `workspace` is a fixture
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from marvin.db.models.groups.automation_executions import AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.users.roles import WorkspaceRole
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import workspace  # noqa: F401 — fixture

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
DEFINITION = {"trigger": {"type": "manual"}, "actions": []}


def _workflow(session, gid, name):
    row = WorkspaceAutomationModel(session=session, group_id=gid, name=name, slug=name.lower(), enabled=True, definition=DEFINITION)
    session.add(row)
    session.commit()
    return row


def _run(session, gid, workflow, status, hours_ago):
    session.add(
        AutomationExecutionModel(
            session=session,
            group_id=gid,
            automation_id=workflow.id,
            automation_slug=workflow.slug,
            trigger_type="manual",
            status=status,
            started_at=NOW - timedelta(hours=hours_ago),
        )
    )
    session.commit()


def _listed(workspace) -> dict:
    res = gates._sign_in(workspace, WorkspaceRole.ADMIN).get("/api/automations")
    assert res.status_code == 200
    return {row["name"]: row for row in res.json()}


def test_the_newest_run_decides_the_last_run(db_session, workspace):
    wf = _workflow(db_session, workspace.gid, "Digest")
    _run(db_session, workspace.gid, wf, "success", hours_ago=30)
    _run(db_session, workspace.gid, wf, "failed", hours_ago=2)  # the newest
    _run(db_session, workspace.gid, wf, "success", hours_ago=50)

    row = _listed(workspace)["Digest"]

    assert row["lastRunStatus"] == "failed"
    assert datetime.fromisoformat(row["lastRunAt"].replace("Z", "+00:00")) == NOW - timedelta(hours=2)


def test_a_workflow_that_never_ran_has_no_last_run(db_session, workspace):
    _workflow(db_session, workspace.gid, "Fresh")

    row = _listed(workspace)["Fresh"]

    assert row["lastRunAt"] is None and row["lastRunStatus"] is None


def test_each_workflow_gets_its_own_last_run(db_session, workspace):
    a, b = _workflow(db_session, workspace.gid, "A"), _workflow(db_session, workspace.gid, "B")
    _run(db_session, workspace.gid, a, "success", hours_ago=5)
    _run(db_session, workspace.gid, b, "partial", hours_ago=1)
    _workflow(db_session, workspace.gid, "C")

    rows = _listed(workspace)

    assert (rows["A"]["lastRunStatus"], rows["B"]["lastRunStatus"], rows["C"]["lastRunStatus"]) == ("success", "partial", None)


def test_another_workspaces_runs_never_count(db_session, workspace):
    from marvin.db.models.groups import Groups
    from marvin.services.group.group_purge import purge_group_dependents

    wf = _workflow(db_session, workspace.gid, "Mine")
    other_gid = uuid.uuid4()
    other = Groups(session=db_session, name=f"lr-{other_gid.hex[:8]}", slug=f"lr-{other_gid.hex[:8]}")
    other.id = other_gid
    db_session.add(other)
    db_session.commit()
    try:
        # A run recorded in the other workspace, even one that names this workflow, is not this workflow's run.
        _run(db_session, other_gid, wf, "failed", hours_ago=1)
        assert _listed(workspace)["Mine"]["lastRunStatus"] is None

        _run(db_session, workspace.gid, wf, "success", hours_ago=9)
        assert _listed(workspace)["Mine"]["lastRunStatus"] == "success"
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, other_gid)
        db_session.query(Groups).filter(Groups.id == other_gid).delete()
        db_session.commit()


def test_a_run_whose_workflow_was_deleted_changes_nothing(db_session, workspace):
    wf = _workflow(db_session, workspace.gid, "Kept")
    gone = _workflow(db_session, workspace.gid, "Gone")
    _run(db_session, workspace.gid, gone, "failed", hours_ago=1)
    db_session.delete(gone)
    db_session.commit()

    assert list(_listed(workspace)) == ["Kept"] and wf.id


def test_the_list_takes_one_query_for_the_runs_however_many_workflows(db_session, workspace):
    from marvin.db.db_setup import engine

    def executions_queries(count: int) -> int:
        for i in range(count):
            wf = _workflow(db_session, workspace.gid, f"W{count}-{i}")
            _run(db_session, workspace.gid, wf, "success", hours_ago=i + 1)
        db_session.expire_all()
        seen: list[str] = []
        listener = lambda conn, cursor, statement, *a: seen.append(statement)  # noqa: E731
        sa.event.listen(engine, "before_cursor_execute", listener)
        try:
            _listed(workspace)
        finally:
            sa.event.remove(engine, "before_cursor_execute", listener)
        return sum("automation_executions" in s for s in seen)

    assert executions_queries(2) == 1
    assert executions_queries(6) == 1


def test_each_workflow_counts_its_failed_runs_this_week_as_the_dashboard_does(db_session, workspace):
    """A workflow whose last run went fine can still have failed this week: the card says how many (the dashboard's count).
    Its runs are dated from the real clock, as the list counts the week from now."""
    now = datetime.now(UTC)

    def run(workflow, status, hours_ago):
        db_session.add(
            AutomationExecutionModel(
                session=db_session, group_id=workspace.gid, automation_id=workflow.id, automation_slug=workflow.slug,
                trigger_type="manual", status=status, started_at=now - timedelta(hours=hours_ago),
            )
        )  # fmt: skip
        db_session.commit()

    digest = _workflow(db_session, workspace.gid, "Digest")
    run(digest, "failed", hours_ago=30)
    run(digest, "partial", hours_ago=20)
    run(digest, "failed", hours_ago=24 * 9)  # older than the week: not counted
    run(digest, "success", hours_ago=1)  # the newest went fine
    quiet = _workflow(db_session, workspace.gid, "Quiet")
    run(quiet, "success", hours_ago=3)

    rows = _listed(workspace)

    assert (rows["Digest"]["lastRunStatus"], rows["Digest"]["failedRuns7d"]) == ("success", 2)
    assert rows["Quiet"]["failedRuns7d"] == 0
