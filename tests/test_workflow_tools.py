"""Workflows as the agent sees them: `workspace_overview.structure` names what exists, `list_workflows`
lists them, and `run_workflow` matches loosely and says what IS there when a name misses — the live
failure was Marvin running "Summerize Published Notes" against "Summarize published bench notes" and
then having no way to look the real name up.
"""

import json
import uuid
from types import SimpleNamespace

from pytest import fixture

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.groups import Groups
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


def test_overview_structure_names_workflows_and_the_other_configured_elements(workspace):
    out = json.loads(workspace_overview(workspace, {}))
    structure = out["structure"]
    assert [w["slug"] for w in structure["workflows"]] == ["add-tags-to-entry", "summarize-bench-notes"]
    assert structure["workflows"][1] == {
        "name": "Summarize published bench notes",
        "slug": "summarize-bench-notes",
        "enabled": True,
        "trigger": "manual",
    }
    for key in ("scheduledTasks", "incomingWebhooks", "outgoingWebhooks", "notifiers", "mcpServers", "integrations", "agents"):
        assert structure[key] == [], key


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
    monkeypatch.setattr(
        engine, "run_automation_now", lambda s, g, auto, user_id=None, logger=None: ran.append(auto.slug) or {"ok": True, "result": "done"}
    )
    assert json.loads(run_workflow(workspace, {"workflow": "SUMMARIZE PUBLISHED BENCH NOTES"}))["ok"] is True
    assert json.loads(run_workflow(workspace, {"workflow": "Summarize-Bench-Notes"}))["workflow"] == "summarize-bench-notes"
    assert ran == ["summarize-bench-notes"] * 2
    disabled = json.loads(run_workflow(workspace, {"workflow": "add tags to entry"}))
    assert "disabled" in disabled["error"] and ran == ["summarize-bench-notes"] * 2


def test_run_workflow_miss_lists_what_exists_instead_of_a_bare_error(workspace):
    out = json.loads(run_workflow(workspace, {"workflow": "Summerize Published Notes"}))
    assert out["error"].startswith("no workflow 'Summerize Published Notes'")
    assert [w["slug"] for w in out["available"]] == ["add-tags-to-entry", "summarize-bench-notes"]
