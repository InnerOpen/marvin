"""Agents author workflows: the guide (generated from code), get_workflow, draft_workflow, update_workflow_draft.

The incident: asked in Ask to create a workflow, an agent said it couldn't author workflow JSON, then wrote
invented JSON — `steps`, `type: find_entries`, `for_each`, `{{steps[...]}}` — that isn't Marvin's format. Now
the agent reads the real format from `workflow_authoring_guide` and saves through `draft_workflow`: the REST
create path's own gate plus unknown-key and reference checks, created switched off, with a link to the editor.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction
from marvin_integration_sdk.ai import ToolCall
from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport
from pytest import fixture

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tools import get_tool
from marvin.services.automation.authoring import SECTIONS, authoring_guide, draft_issues, guide_size
from tests import test_content_role_gates as gates

workspace = gates.workspace  # fixture: a workspace with a signed-in user (gates._sign_in)
P = gates.P
E, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN

GOOD = {
    "trigger": {"type": "manual"},
    "target": {"entity": "entry", "query": {"has_images": True}},
    "actions": [{"kind": "entry", "op": "unpublish"}],
}

# What the agent wrote in the incident, near enough: a whole workflow with its own step language.
INVENTED = {
    "name": "Move entries with images to Drafts",
    "trigger": {"type": "manual"},
    "steps": [
        {"id": "find", "type": "find_entries", "query": {"has_images": True}},
        {"for_each": "{{steps[0].output.entries}}", "type": "update_entry", "status": "draft"},
    ],
}


class _Shop(IntegrationProvider):
    slug = "wf_author_shop"
    name = "Shop"
    actions = (
        ProviderAction(
            key="create_listing", label="Create listing", input_schema={"properties": {"title": {"type": "string"}}, "required": ["title"]}
        ),
        ProviderAction(key="refund", label="Refund", requires_approval=True),
    )


@fixture
def ws(db_session, workspace, monkeypatch):
    """The signed-in workspace with what a guide lists: an entry type, a collection, an integration, AI on."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    monkeypatch.setitem(INTEGRATION_REGISTRY, _Shop.slug, _Shop())
    gid = workspace.gid
    # A real membership too: a workflow's steps run with its author's role, read from the database.
    db_session.add(WorkspaceMembers(session=db_session, user_id=workspace.uid, group_id=gid, workspace_role=AD))
    admin = gates._sign_in(workspace, AD)
    et = admin.post(f"{P}/entry-types", json={"name": "Recipe"}).json()
    db_session.add(Collections(session=db_session, group_id=gid, name="Featured", slug="featured"))
    db_session.add(IntegrationModel(session=db_session, group_id=gid, provider=_Shop.slug, name="Shop", slug="shop", enabled=True))
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, enabled=True, model="fake-model"))
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=workspace.uid, et=et, workspace=workspace, session=db_session)
    _cleanup(db_session, gid)


def _cleanup(session, gid):
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.groups.ai_threads import AIThreadModel
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    session.rollback()
    session.query(EntryAssets).filter(EntryAssets.entry_id.in_(session.query(Entries.id).filter(Entries.group_id == gid))).delete(
        synchronize_session=False
    )
    for model in (AIExecutionModel, AIThreadModel, ScheduledTaskModel, WorkspaceAutomationModel, Entries, WorkspaceMembers):
        session.query(model).filter(model.group_id == gid).delete(synchronize_session=False)
    session.commit()


def _ctx(ws, role=AD):
    member = SimpleNamespace(group_id=ws.gid, workspace_role=role)
    user = SimpleNamespace(id=ws.uid, admin=False, workspace_memberships=[member])
    return SimpleNamespace(session=ws.session, group_id=ws.gid, user=user, provider=None, logger=None)


def _tool(ws, name, args, role=AD) -> dict:
    return json.loads(get_tool(name).handler(_ctx(ws, role), args))


def _rows(ws):
    ws.session.expire_all()
    return ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid).order_by(WorkspaceAutomationModel.name).all()


# ── The guide is generated from code ─────────────────────────────────────────


def test_guide_lists_marvins_real_vocabulary(ws):
    from marvin.schemas.group.automation_definition import ACTION_MODELS, TRIGGER_MODELS
    from marvin.services.automation.actions.entry import OP_SENDS
    from marvin.services.entries.query import SPEC_KEYS
    from marvin.services.events.event_catalog import TRIGGERABLE_EVENT_TYPES

    guide = authoring_guide(ws.session, ws.gid)
    assert set(guide) == {*SECTIONS, "more"}
    events = {e for names in guide["events"]["triggerable"].values() for e in names}
    assert events == TRIGGERABLE_EVENT_TYPES and "entry_published" in events
    assert set(guide["triggers"]) == set(TRIGGER_MODELS)
    assert set(guide["actions"]["kinds"]) == set(ACTION_MODELS)
    assert guide["actions"]["kinds"]["integration"]["required"] == ["integration", "action"]
    assert set(guide["actions"]["entry_ops"]) == set(OP_SENDS)
    assert guide["actions"]["entry_ops"]["unpublish"] == "status → draft"
    assert set(guide["target"]["query"]) == set(SPEC_KEYS) and "has_images" in guide["target"]["query"]
    assert "${steps.<id>.output.<key>}" in guide["actions"]["step_id"] and "steps" in guide["templates"]["namespaces"]


def test_guide_names_this_workspaces_references(ws):
    work = authoring_guide(ws.session, ws.gid)["workspace"]
    assert "featured" in work["collections"]
    assert ws.et["slug"] in work["entry_types"]
    shop = next(i for i in work["integrations"] if i["slug"] == "shop")
    assert shop["actions"] == ["create_listing"]  # refund needs approval: a workflow can't run it
    assert "generate-summary" in work["operations"]
    assert "request_site_rebuild" in work["handlers"]

    detail = authoring_guide(ws.session, ws.gid, "workspace")["workspace"]
    listing = next(i for i in detail["integrations"] if i["slug"] == "shop")["actions"][0]
    assert listing["args"] == {"title": "string"} and listing["required"] == ["title"]


def test_guide_says_when_ai_operations_are_unavailable(ws):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    ws.session.query(WorkspaceAISettingsModel).filter_by(group_id=ws.gid).update({"enabled": False})
    ws.session.commit()
    assert "can't run" in authoring_guide(ws.session, ws.gid)["workspace"]["operations"]
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [{"kind": "operation", "op": "generate-summary"}]})
    assert [i["path"] for i in issues] == ["actions[0]"]


def test_guide_stays_bounded_in_a_big_workspace(ws):
    from marvin.db.models.platform.collections import Collections

    for i in range(120):
        ws.session.add(Collections(session=ws.session, group_id=ws.gid, name=f"Collection {i:03}", slug=f"collection-{i:03}"))
    ws.session.commit()
    overview = authoring_guide(ws.session, ws.gid)
    assert len(overview["workspace"]["collections"]) == 50
    assert guide_size(overview) < 16_000
    for section in SECTIONS:
        part = authoring_guide(ws.session, ws.gid, section)
        assert list(part) == [section] and guide_size(part) < 16_000, section


def test_guide_tool_needs_admin_and_rejects_an_unknown_section(ws):
    assert "error" in _tool(ws, "workflow_authoring_guide", {"section": "everything"})
    assert "events" in _tool(ws, "workflow_authoring_guide", {"section": "events"})


def test_template_namespaces_are_what_a_run_can_read(ws):
    from marvin.services.automation.engine import TEMPLATE_NAMESPACES, _entry_context, match_context

    entry = gates._sign_in(ws.workspace, AD).post(f"{P}/entries", json={"entry_type_id": ws.et["id"], "title": "Soup", "status": "draft"}).json()
    context = match_context(ws.session, ws.gid, {"event_type": "entry_updated", "entry_id": entry["id"]})
    # A run adds step outputs (`steps`) and, in on_failure steps, the failure (`error`); `depth` is plumbing.
    assert set(context) - {"depth"} | {"steps", "error"} == set(TEMPLATE_NAMESPACES)
    for key in _entry_context(ws.session, ws.gid, entry["id"]):
        assert key in TEMPLATE_NAMESPACES["entry"], key


# Every worked example is a Library recipe now; tests/test_workflow_library.py drafts each one.


# ── draft_workflow ───────────────────────────────────────────────────────────


def test_draft_creates_what_rest_creates_but_switched_off(ws):
    rest = gates._sign_in(ws.workspace, AD).post("/api/automations", json={"name": "Via REST", "definition": GOOD})
    assert rest.status_code == 201, rest.text
    out = _tool(ws, "draft_workflow", {"name": "Via agent", "definition": GOOD})
    assert out["created"] is True and out["workflow"]["slug"] == "via-agent" and out["workflow"]["enabled"] is False

    by_slug = {r.slug: r for r in _rows(ws)}
    made, ref = by_slug["via-agent"], by_slug["via-rest"]
    assert made.definition == ref.definition == GOOD
    assert (made.enabled, made.created_by, made.trigger_type) == (ref.enabled, ref.created_by, ref.trigger_type) == (False, ws.uid, "manual")
    assert out["editLink"] == f"[Open “Via agent” in the workflow editor](/automation/workflows?workflow={made.id}&edit=1)"


def test_draft_with_a_schedule_trigger_gets_its_backing_task_like_rest(ws):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    out = _tool(ws, "draft_workflow", {"name": "Hourly rebuild", "recipe": "hourly-site-rebuild", "vars": {"interval_seconds": 3600}})
    task = ws.session.query(ScheduledTaskModel).filter_by(group_id=ws.gid, slug=f"wf-{out['workflow']['id']}").one()
    assert task.enabled is False and task.task_type == "run_automation"


@pytest.mark.parametrize(
    "definition",
    [{**GOOD, "enabled": True}, {"name": "Doc", "enabled": True, "definition": {**GOOD, "enabled": True}}],
    ids=["bare", "document"],
)
def test_draft_never_enables(ws, definition):
    out = _tool(ws, "draft_workflow", {"name": "Never on", "definition": definition})
    assert out["workflow"]["enabled"] is False and "enabled" in " ".join(out["ignored"])
    assert _rows(ws)[0].enabled is False and "enabled" not in _rows(ws)[0].definition


def test_a_whole_document_is_accepted_and_a_json_string_too(ws):
    doc = {"name": "From a document", "definition": GOOD}
    assert _tool(ws, "draft_workflow", {"name": "", "definition": doc})["workflow"]["name"] == "From a document"
    assert _tool(ws, "draft_workflow", {"name": "As text", "definition": json.dumps(GOOD)})["workflow"]["slug"] == "as-text"


def test_a_malformed_definition_gets_path_issues_and_creates_nothing(ws):
    bad = {"trigger": {"type": "event"}, "actions": [{"kind": "entry", "op": "draftify"}, {"kind": "webhook", "body": "x"}]}
    out = _tool(ws, "draft_workflow", {"name": "Broken", "definition": bad})
    paths = [i["path"] for i in out["issues"]]
    assert paths == ["trigger.event", "actions[0].op", "actions[1].body"]
    assert "publish" in out["issues"][1]["message"] and "Nothing was saved" in out["fix"]
    assert _rows(ws) == []


def test_the_incidents_invented_json_is_refused_with_useful_issues(ws):
    out = _tool(ws, "draft_workflow", {"name": "Move entries with images to Drafts", "definition": INVENTED})
    assert [i["path"] for i in out["issues"]] == ["steps"]
    assert "not a field" in out["issues"][0]["message"] and "actions" in out["issues"][0]["message"]
    # The same steps put under `actions`: each step's missing `kind` is named.
    out = _tool(ws, "draft_workflow", {"name": "x", "definition": {"trigger": {"type": "manual"}, "actions": INVENTED["steps"]}})
    assert [i["path"] for i in out["issues"]] == ["actions[0]", "actions[1]"] and "kind" in out["issues"][0]["message"]
    # Nothing a workflow reads: no trigger, no actions.
    out = _tool(ws, "draft_workflow", {"name": "x", "definition": {"steps": INVENTED["steps"]}})
    assert 'no "trigger" or "actions"' in out["error"]
    assert _rows(ws) == []


@pytest.mark.parametrize(
    "definition, path, hint",
    [
        ({"trigger": {"type": "event", "event": "entry_saved"}, "actions": [{"kind": "entry", "op": "publish"}]}, "trigger.event", "entry_"),
        ({**GOOD, "target": {"query": {"has_image": True}}}, "target.query.has_image", "has_images"),
        ({**GOOD, "target": {"query": {"entry_type": "recipes"}}}, "target.query.entry_type", "recipe"),
        ({**GOOD, "target": {"query": {"status": "drafts"}}}, "target.query.status", "draft"),
        ({**GOOD, "actions": [{"kind": "entry", "op": "add_to_collection", "collection_slug": "featurd"}]}, "actions[0].collection_slug", "featured"),
        ({**GOOD, "actions": [{"kind": "entry", "op": "publish", "entity_type": "asset"}]}, "actions[0].entity_type", "trash"),
        ({**GOOD, "actions": [{"kind": "integration", "integration": "shop", "action": "refund"}]}, "actions[0].action", "create_listing"),
        ({**GOOD, "actions": [{"kind": "integration", "integration": "square", "action": "x"}]}, "actions[0].integration", "shop"),
        ({**GOOD, "actions": [{"kind": "handler", "task": "prune_event_logs"}]}, "actions[0].task", "request_site_rebuild"),
        ({**GOOD, "actions": [{"kind": "operation", "op": "summarise"}]}, "actions[0].op", "generate-summary"),
        ({**GOOD, "actions": [{"kind": "emit_event", "event": "made_up"}]}, "actions[0].event", "entry_"),
        ({**GOOD, "actions": [{"kind": "webhook", "webhook_id": str(uuid.uuid4())}]}, "actions[0].webhook_id", "none in this workspace"),
        ({**GOOD, "conditions": [{"field": "entry.status", "op": "equals", "value": "x"}]}, "conditions[0].op", "eq"),
        ({**GOOD, "on_failure": [{"kind": "entry", "op": "set_metadata"}]}, "on_failure[0].metadata", "metadata"),
        (
            {"trigger": {"type": "chained", "automation": "nope"}, "actions": [{"kind": "handler", "task": "request_site_rebuild"}]},
            "trigger.automation",
            "Workflows",
        ),
    ],
)
def test_names_this_workspace_doesnt_have_are_refused(ws, definition, path, hint):
    out = _tool(ws, "draft_workflow", {"name": "Refs", "definition": definition})
    assert [i["path"] for i in out["issues"]] == [path] and hint in out["issues"][0]["message"], out
    assert _rows(ws) == []


def test_templates_are_left_to_run_time(ws):
    definition = {
        "trigger": {"type": "incoming_webhook"},
        "target": {"query": {"entry_type": "${event.payload.type}"}},
        "actions": [{"kind": "entry", "op": "add_to_collection", "collection_slug": "$event.payload.collection"}],
    }
    assert draft_issues(ws.session, ws.gid, definition) == []


def test_a_name_that_is_taken_is_refused_like_rest(ws):
    _tool(ws, "draft_workflow", {"name": "Twice", "definition": GOOD})
    out = _tool(ws, "draft_workflow", {"name": "Twice", "definition": GOOD})
    assert "already exists" in out["error"] and "update_workflow_draft" in out["error"] and out["existing"]["slug"] == "twice"
    assert len(_rows(ws)) == 1
    rest = gates._sign_in(ws.workspace, AD).post("/api/automations", json={"name": "Twice", "definition": GOOD})
    assert rest.status_code == 409


def test_draft_reports_advisory_warnings_without_blocking(ws):
    definition = {"trigger": {"type": "incoming_webhook"}, "conditions": [{"field": "entry.status", "op": "eq", "value": "draft"}], "actions": []}
    out = _tool(ws, "draft_workflow", {"name": "Warned", "definition": definition})
    assert out["created"] and any("never match" in w for w in out["warnings"]) and any("no steps" in w for w in out["warnings"])


# ── get_workflow / update_workflow_draft ─────────────────────────────────────


def test_get_workflow_returns_the_definition_and_the_last_run(ws):
    made = _tool(ws, "draft_workflow", {"name": "Readable", "definition": GOOD})["workflow"]
    out = _tool(ws, "get_workflow", {"workflow": "readable"})
    assert (out["id"], out["definition"], out["enabled"], out["lastRun"]) == (made["id"], GOOD, False, None)
    gates._sign_in(ws.workspace, AD).patch(f"/api/automations/{made['id']}", json={"enabled": True})
    gates._sign_in(ws.workspace, AD).post(f"/api/automations/{made['id']}/run")
    run = _tool(ws, "get_workflow", {"workflow": made["id"]})["lastRun"]
    assert run["status"] in ("success", "completed", "partial", "failed") and run["trigger"] == "manual"
    assert "available" in _tool(ws, "get_workflow", {"workflow": "nope"})


def test_update_revises_a_disabled_draft(ws):
    made = _tool(ws, "draft_workflow", {"name": "Revise me", "definition": GOOD})["workflow"]
    new = {**GOOD, "actions": [{"kind": "entry", "op": "archive"}]}
    out = _tool(ws, "update_workflow_draft", {"workflow": "revise-me", "name": "Revised", "definition": new})
    assert out["updated"] and out["workflow"] == {**made, "name": "Revised"}
    row = _rows(ws)[0]
    assert (row.name, row.slug, row.definition, row.enabled) == ("Revised", "revise-me", new, False)


def test_update_checks_the_definition_like_draft(ws):
    _tool(ws, "draft_workflow", {"name": "Keep", "definition": GOOD})
    out = _tool(ws, "update_workflow_draft", {"workflow": "keep", "definition": INVENTED})
    assert [i["path"] for i in out["issues"]] == ["steps"]
    assert _rows(ws)[0].definition == GOOD


def test_update_refuses_an_enabled_workflow(ws):
    made = _tool(ws, "draft_workflow", {"name": "Live one", "definition": GOOD})["workflow"]
    gates._sign_in(ws.workspace, AD).patch(f"/api/automations/{made['id']}", json={"enabled": True})
    out = _tool(ws, "update_workflow_draft", {"workflow": "live-one", "name": "Hijacked", "definition": {**GOOD, "actions": []}})
    assert "is enabled" in out["error"] and "switch it off" in out["error"] and "editLink" in out
    row = _rows(ws)[0]
    assert (row.name, row.definition, row.enabled) == ("Live one", GOOD, True)


# ── Permissions, matrix, MCP ─────────────────────────────────────────────────


def test_workflow_tools_need_admin_like_the_automation_routes():
    from marvin.services.ai.operations.base import ROLE_ADMIN
    from marvin.services.ai.tools.categories import CATEGORY_BY_TOOL, category_writes

    for name in ("workflow_authoring_guide", "get_workflow", "draft_workflow", "update_workflow_draft"):
        assert get_tool(name).min_role == ROLE_ADMIN, name
    assert CATEGORY_BY_TOOL["workflow_authoring_guide"] == CATEGORY_BY_TOOL["get_workflow"] == "automation_read"
    assert CATEGORY_BY_TOOL["draft_workflow"] == CATEGORY_BY_TOOL["update_workflow_draft"] == "automation_author"
    assert category_writes("automation_author") and not get_tool("draft_workflow").read_only


def test_matrix_defaults_allow_marvin_and_ask_on_workspace_agents():
    from dataclasses import replace

    from marvin.services.ai.agents import SYSTEM_AGENTS, AgentSpec, permission_matrix, resolve_policy
    from marvin.services.ai.operations.base import ROLE_ADMIN, ROLE_AUTHOR

    marvin = SYSTEM_AGENTS["marvin"]
    custom = AgentSpec(slug="helper", name="Helper", kind="persona", allow_writes=True)
    assert resolve_policy(marvin, "draft_workflow", "automation_author", ROLE_ADMIN)[0] == "allow"
    assert resolve_policy(custom, "draft_workflow", "automation_author", ROLE_ADMIN)[0] == "ask"
    assert resolve_policy(replace(custom, allow_writes=False), "draft_workflow", "automation_author", ROLE_ADMIN)[0] == "block"
    assert resolve_policy(marvin, "draft_workflow", "automation_author", ROLE_AUTHOR)[0] == "block"
    row = next(
        r
        for r in permission_matrix(marvin, ROLE_ADMIN, [{"name": "draft_workflow", "category": "automation_author"}])
        if r["id"] == "automation_author"
    )
    assert (row["label"], row["writes"], row["inherited"]) == ("Automation: author", True, "allow")


def test_mcp_lists_and_runs_the_tools_for_an_admin_only(ws):
    names = {t["name"] for t in gates._sign_in(ws.workspace, AD).get("/api/ai/tools").json()}
    assert {"workflow_authoring_guide", "get_workflow", "draft_workflow", "update_workflow_draft"} <= names
    assert not {"draft_workflow", "workflow_authoring_guide"} & {t["name"] for t in gates._sign_in(ws.workspace, E).get("/api/ai/tools").json()}

    res = gates._sign_in(ws.workspace, AD).post(
        "/api/ai/tools/draft_workflow/invoke", json={"args": {"name": "Over MCP", "definition": GOOD}, "source": "mcp"}
    )
    assert res.status_code == 200 and res.json()["workflow"]["enabled"] is False, res.text
    # An EDITOR can't create a workflow over REST, so not through the tool either.
    assert gates._sign_in(ws.workspace, E).post("/api/automations", json={"name": "No", "definition": GOOD}).status_code == 403
    res = gates._sign_in(ws.workspace, E).post(
        "/api/ai/tools/draft_workflow/invoke", json={"args": {"name": "No", "definition": GOOD}, "source": "mcp"}
    )
    assert res.status_code == 403
    assert [r.slug for r in _rows(ws)] == ["over-mcp"]
    assert _rows(ws)[0].created_by == ws.uid  # recorded as the person, like a REST create


def test_preamble_tells_the_agent_to_draft_when_the_tool_is_bound():
    from marvin.services.ai.agents import WORKFLOW_GUIDE_ONLY_RULE, WORKFLOW_RULE, workspace_preamble

    bound = workspace_preamble("Shop", ["workflow_authoring_guide", "draft_workflow", "update_workflow_draft"])
    assert WORKFLOW_RULE in bound and "Never say you can't create workflows" in bound and "editLink verbatim" in bound
    assert WORKFLOW_GUIDE_ONLY_RULE in workspace_preamble("Shop", ["workflow_authoring_guide"])
    unbound = workspace_preamble("Shop", ["search_content"])
    assert WORKFLOW_RULE not in unbound and WORKFLOW_GUIDE_ONLY_RULE not in unbound


# ── End to end: the incident's request, scripted ─────────────────────────────


def test_asking_marvin_for_the_incidents_workflow_creates_it_switched_off(ws, monkeypatch):
    """The owner's ask, through the real /api/ai/agent loop with a scripted model: read the guide, draft a
    real definition, answer with the link. The workflow exists, switched off, and a dry run shows it would
    move the published entry with an image to draft — and nothing else."""
    from marvin.db.models.platform import Assets, EntryAssets
    from marvin.services.ai import factory

    admin = gates._sign_in(ws.workspace, AD)
    new = lambda title: admin.post(f"{P}/entries", json={"entry_type_id": ws.et["id"], "title": title, "status": "published"}).json()["id"]  # noqa: E731
    pictured, plain = new("With a photo"), new("Words only")
    photo = Assets(
        session=ws.session, group_id=ws.gid, slug=f"p-{ws.gid.hex[:6]}", name="P", original_filename="p.png", filename="p.png",
        extension="png", file_size=1, mime_type="image/png", asset_type="image", checksum=uuid.uuid4().hex,
        storage_provider="local", storage_key="p.png", uploaded_by=ws.uid,
    )  # fmt: skip
    ws.session.add(photo)
    ws.session.flush()
    ws.session.add(EntryAssets(entry_id=uuid.UUID(pictured), asset_id=photo.id, position=0))
    ws.session.commit()

    transport = ScriptedTransport()
    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: FakeAIProvider(transport))
    definition = {
        "trigger": {"type": "manual"},
        "target": {"entity": "entry", "query": {"has_images": True, "status": "published"}},
        "actions": [{"kind": "entry", "op": "unpublish"}],
    }
    transport.reply_tool_calls([ToolCall(id="c1", name="workflow_authoring_guide", arguments={})])
    transport.reply_tool_calls(
        [ToolCall(id="c2", name="draft_workflow", arguments={"name": "Move entries with images to Drafts", "definition": definition})]
    )

    def answer(request) -> str:
        """The model's last turn: quote the draft's link back, as the preamble tells it to."""
        result = json.loads(request["messages"][-1]["content"])
        return f"Done — I created the workflow, switched off. {result['editLink']} Check which entries it targets with a dry run before enabling it."

    sent = transport.send

    def send(request):  # the third request answers from what draft_workflow returned
        if len(transport.requests) == 2:
            transport.reply_text(answer(request))
        return sent(request)

    transport.send = send
    res = admin.post("/api/ai/agent", json={"message": "create a workflow that moves entries with images to Drafts", "modelOverride": "fake-model"})
    assert res.status_code == 200, res.text
    body = res.json()

    # The model saw the rule and the tools; it read the guide before drafting.
    first = transport.requests[0]
    assert "workflow_authoring_guide" in {t["name"] for t in first["tools"]} and "draft_workflow" in {t["name"] for t in first["tools"]}
    assert any("Never say you can't create workflows" in (m.get("content") or "") for m in first["messages"] if m["role"] == "system")
    assert [s["tool"] for s in body["steps"]] == ["workflow_authoring_guide", "draft_workflow"]

    (row,) = _rows(ws)
    assert (row.name, row.enabled, row.definition, row.created_by) == ("Move entries with images to Drafts", False, definition, ws.uid)
    assert f"/automation/workflows?workflow={row.id}&edit=1" in body["answer"]

    plan = admin.post(f"/api/automations/{row.id}/run", params={"dry_run": "true"}).json()
    assert plan["status"] == "dry_run" and plan["ok"], plan
    assert [(p["target"]["id"], p["resolved"]["would_set_status"]) for p in plan["plan"]] == [(pictured, "draft")]
    assert plain not in json.dumps(plan)
