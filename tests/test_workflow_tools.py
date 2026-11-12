"""Workflows as the agent sees them: `workspace_overview.structure` names what exists, `list_workflows`
lists them, and `run_workflow` matches loosely and says what IS there when a name misses — the live
failure was Marvin running "Summerize Published Notes" against "Summarize published bench notes" and
then having no way to look the real name up.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.builtins import list_workflows, run_workflow
from marvin.services.ai.tools.builtins_overview import workspace_overview


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"wf-{marker}", slug=f"wf-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    for name, slug, enabled in (
        ("Summarize published bench notes", "summarize-bench-notes", True),
        ("Add Tags To Entry", "add-tags-to-entry", False),
    ):
        db_session.add(
            WorkspaceAutomationModel(
                session=db_session, group_id=gid, name=name, slug=slug, enabled=enabled, definition={"trigger": {"type": "manual"}}
            )
        )
    db_session.flush()
    yield SimpleNamespace(session=db_session, group_id=gid, user=None, provider=None, logger=None)
    db_session.rollback()


def _as(workspace, role):
    """The workspace ctx with a caller holding `role` in it."""
    member = SimpleNamespace(group_id=workspace.group_id, workspace_role=role)
    user = SimpleNamespace(id=uuid.uuid4(), admin=False, workspace_memberships=[member])
    return SimpleNamespace(**{**vars(workspace), "user": user})


def test_overview_structure_names_workflows_and_the_other_configured_elements(workspace):
    out = json.loads(workspace_overview(_as(workspace, WorkspaceRole.ADMIN), {}))
    structure = out["structure"]
    assert [w["slug"] for w in structure["workflows"]] == ["add-tags-to-entry", "summarize-bench-notes"]
    assert structure["workflows"][1] == {
        "name": "Summarize published bench notes",
        "slug": "summarize-bench-notes",
        "enabled": True,
        "trigger": "manual",
    }
    for key in ("scheduledTasks", "incomingWebhooks", "outgoingWebhooks", "mcpServers", "integrations", "agents"):
        assert structure[key] == [], key


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER])
def test_overview_structure_lists_only_agents_below_admin(workspace, role):
    """Workflows, tasks, webhooks, MCP servers and integrations are settings: their routes are
    admin-only, so the overview names them to admins only."""
    structure = json.loads(workspace_overview(_as(workspace, role), {}))["structure"]
    assert set(structure) == {"agents", "note"}


def test_workflow_tools_need_admin_like_the_automation_routes():
    from marvin.services.ai.operations.base import ROLE_ADMIN
    from marvin.services.ai.tools import get_tool

    assert get_tool("list_workflows").min_role == ROLE_ADMIN
    assert get_tool("run_workflow").min_role == ROLE_ADMIN


def test_list_workflows_is_read_only_and_lists_name_slug_enabled_trigger(workspace):
    from marvin.services.ai.tools import list_tools
    from marvin.services.ai.tools.categories import category_of

    spec = next(t for t in list_tools() if t.name == "list_workflows")
    assert spec.read_only and category_of("list_workflows", read_only=True) == "automation_read"
    out = json.loads(list_workflows(workspace, {}))
    assert out["count"] == 2 and out["workflows"][0] == {
        "name": "Add Tags To Entry",
        "slug": "add-tags-to-entry",
        "enabled": False,
        "trigger": "manual",
    }


def test_run_workflow_matches_case_insensitively_by_name_or_slug(workspace, monkeypatch):
    import marvin.services.automation.engine as engine

    ran = []

    def fake_run(session, group_id, auto, **kwargs):
        ran.append(auto.slug)
        return {"ok": True, "result": "done"}

    monkeypatch.setattr(engine, "run_automation_now", fake_run)
    assert json.loads(run_workflow(workspace, {"workflow": "SUMMARIZE PUBLISHED BENCH NOTES"}))["ok"] is True
    assert json.loads(run_workflow(workspace, {"workflow": "Summarize-Bench-Notes"}))["workflow"] == "summarize-bench-notes"
    assert ran == ["summarize-bench-notes"] * 2
    disabled = json.loads(run_workflow(workspace, {"workflow": "add tags to entry"}))
    assert "disabled" in disabled["error"] and ran == ["summarize-bench-notes"] * 2


def test_run_workflow_miss_lists_what_exists_instead_of_a_bare_error(workspace):
    out = json.loads(run_workflow(workspace, {"workflow": "Summerize Published Notes"}))
    assert out["error"].startswith("no workflow 'Summerize Published Notes'")
    assert [w["slug"] for w in out["available"]] == ["add-tags-to-entry", "summarize-bench-notes"]


def test_a_job_is_followed_until_it_finishes_and_its_result_comes_back():
    from marvin.services.automation import watch

    states = iter(
        [
            ("check-1", {"kind": "check-fountain", "status": "queued"}),
            ("check-1", {"kind": "check-fountain", "status": "running", "log": "reading"}),
            ("check-1", {"kind": "check-fountain", "status": "done", "result": {"errors": 7}, "log": "Checked."}),
        ]
    )
    slept = []
    out = watch.wait_for_job(lambda: next(states), 30, sleep=slept.append)
    assert out == {"slug": "check-1", "kind": "check-fountain", "status": "done", "finished": True, "result": {"errors": 7}, "log": "Checked."}
    assert len(slept) == 2  # it looked three times, waiting between


def test_a_job_that_is_not_done_in_time_says_where_it_got_to_and_what_is_not_a_job_is_ignored():
    from marvin.services.automation import watch

    clock = iter([0, 0, 1, 2, 3, 4, 5])
    out = watch.wait_for_job(lambda: ("render-1", {"kind": "render", "status": "running"}), 3, sleep=lambda s: None, clock=lambda: next(clock))
    assert out["status"] == "running" and out["finished"] is False
    assert watch.wait_for_job(lambda: ("a-post", {"title": "x"}), 5, sleep=lambda s: None) is None  # no kind, no status: not a worker job
    assert watch.wait_for_job(lambda: ("a-job", {"kind": "k", "status": "published"}), 5) is None  # a status that is not the worker's
    assert watch.wait_for_job(lambda: None, 5) is None
    assert watch.entry_of({"result": {"entry_id": "abc"}}) == "abc" and watch.entry_of({"result": "done"}) is None and watch.entry_of(None) is None
    assert len(watch.outcome("j", {"kind": "k", "status": "done", "log": "x" * 20000})["log"]) == watch.LOG_LIMIT


def test_run_workflow_names_the_job_it_started_and_waits_for_it_when_asked(workspace, monkeypatch):
    import marvin.services.automation.engine as engine
    from marvin.services.automation import watch

    monkeypatch.setattr(
        engine,
        "run_automation_now",
        lambda session, group_id, auto, **kw: {"ok": True, "result": {"op": "create", "entry_id": "11111111-1111-1111-1111-111111111111"}},
    )
    seen = []
    monkeypatch.setattr(
        watch,
        "follow",
        lambda session, gid, eid, seconds: seen.append((eid, seconds))
        or {"slug": "check-a-fountain", "kind": "check-fountain", "status": "done", "finished": True, "result": {"errors": 7}},
    )
    out = json.loads(run_workflow(workspace, {"workflow": "summarize-bench-notes", "inputs": {"text": "x"}, "wait": 20}))
    assert out["job"] == {"slug": "check-a-fountain", "kind": "check-fountain", "status": "done", "finished": True, "result": {"errors": 7}}
    assert seen == [("11111111-1111-1111-1111-111111111111", 20)]
    monkeypatch.setattr(watch, "follow", lambda *a: {"slug": "r", "kind": "render", "status": "queued", "finished": False})
    assert (
        "get_entry 'r'" in json.loads(run_workflow(workspace, {"workflow": "summarize-bench-notes"}))["job"]["next"]
    )  # no wait: it says where to look
    monkeypatch.setattr(watch, "follow", lambda *a: None)
    assert "job" not in json.loads(run_workflow(workspace, {"workflow": "summarize-bench-notes"}))  # the run made no worker job
    assert get_tool("run_workflow").input_schema["properties"]["wait"]["maximum"] == watch.MAX_WAIT
