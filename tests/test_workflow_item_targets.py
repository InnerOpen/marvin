"""Assets and resources as workflow targets and subjects.

A `target` of entity asset | resource runs the steps once per match of the shared item query
(services/item_query.py), each row bound as `${asset.*}` / `${resource.*}` and as the run's subject, so a bare
`trash` / `restore` acts on it; an asset_* / resource_* event binds its item the same way. The validator refuses
what can't run — the owner's "trash published resources" draft (an `entity_query` on a resource, a `where`
shape, a publish status resources don't have) gets each problem named at its path.
"""

# ruff: noqa: E501, F811 — parametrised definitions read best on one line; `ws` is a fixture, not a redefinition
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from marvin_integration_sdk.ai import ToolCall
from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.services.automation.authoring import EXAMPLES, ITEM_EXAMPLES, authoring_guide, draft_issues
from marvin.services.automation.engine import match_context, run_automation_now, run_automations_for_event
from marvin.services.automation.selector import resolve_target_entities
from tests import test_content_role_gates as gates
from tests.test_workflow_authoring import AD, P, _rows, _tool, workspace, ws  # noqa: F401 — fixtures
from tests.workflow_fakes import fake_workflow

# The owner's draft, as the agent saved it — a workflow that could never run.
OWNERS_JSON = {
    "trigger": {"type": "manual"},
    "actions": [
        {
            "kind": "entry",
            "op": "trash",
            "entity_type": "resource",
            "entity_query": {"where": [{"field": "publish_status", "op": "eq", "value": "published"}]},
        }
    ],
}
MANUAL = {"type": "manual"}


def _asset(ws, name, *, asset_type="image", mime="image/png", trashed=False, created=None, **extra):
    from marvin.db.models.platform import Assets

    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    row = Assets(
        session=ws.session, group_id=ws.gid, slug=slug, name=name, original_filename=f"{name}.bin", filename=f"{name}.bin", extension="bin",
        file_size=3, mime_type=mime, asset_type=asset_type, checksum=uuid.uuid4().hex, storage_provider="local", storage_key=f"it/{slug}",
        uploaded_by=ws.uid, trashed_at=datetime.now(UTC) if trashed else None, **extra,
    )  # fmt: skip
    ws.session.add(row)
    ws.session.flush()
    if created:
        row.created_at = created
    return row


def _resource(ws, name, *, resource_type="supplier", trashed=False, **extra):
    from marvin.db.models.platform import Resources

    row = Resources(
        session=ws.session, group_id=ws.gid, slug=f"{name}-{uuid.uuid4().hex[:6]}", name=name, resource_type=resource_type,
        created_by=ws.uid, trashed_at=datetime.now(UTC) if trashed else None, **extra,
    )  # fmt: skip
    ws.session.add(row)
    ws.session.flush()
    return row


@pytest.fixture
def items(ws):
    """Assets: an unattached image, an attached image, an svg, a trashed image. Resources: a tagged supplier in a
    collection, a tool, a trashed one."""
    from marvin.db.models.platform import AssetTags, CollectionResources, Collections, EntryAssets, ResourceTags, Tags

    s = ws.session
    admin = gates._sign_in(ws.workspace, AD)
    entry_id = admin.post(f"{P}/entries", json={"entry_type_id": ws.et["id"], "title": "Page", "status": "draft"}).json()["id"]
    old = datetime.now(UTC) - timedelta(days=30)
    loose = _asset(ws, "loose", created=old)
    attached = _asset(ws, "attached")
    logo = _asset(ws, "logo", asset_type="svg", mime="image/svg+xml", description="The logo", metadata_json={"source": "brand"})
    binned = _asset(ws, "binned", trashed=True)
    s.add(EntryAssets(entry_id=uuid.UUID(entry_id), asset_id=attached.id, position=0))
    tag = Tags(session=s, group_id=ws.gid, name="Wool", slug="wool")
    gallery = Collections(session=s, group_id=ws.gid, name="Gallery", slug="gallery")
    s.add_all([tag, gallery])
    s.flush()
    s.add(AssetTags(asset_id=loose.id, tag_id=tag.id))
    mill = _resource(ws, "mill", url="https://mill.example")
    hammer = _resource(ws, "hammer", resource_type="tool")
    gone = _resource(ws, "gone", trashed=True)
    s.add_all([ResourceTags(resource_id=mill.id, tag_id=tag.id), CollectionResources(collection_id=gallery.id, resource_id=mill.id)])
    s.commit()
    yield SimpleNamespace(loose=loose, attached=attached, logo=logo, binned=binned, mill=mill, hammer=hammer, gone=gone, entry_id=entry_id)
    s.rollback()
    for row in (loose, attached, logo, binned, mill, hammer, gone, tag, gallery):
        s.delete(row)
    s.commit()


def _ids(rows):
    return sorted(str(r.id) for r in rows)


def _resolve(ws, entity, query):
    rows, total = resolve_target_entities(ws.session, ws.gid, {"entity": entity, "query": query}, {"event": {}})
    assert total == len(rows)
    return _ids(rows)


# ── The selector ─────────────────────────────────────────────────────────────


def test_asset_target_resolves_with_each_filter_and_leaves_the_trash_out(ws, items):
    assert _resolve(ws, "asset", {}) == _ids([items.loose, items.attached, items.logo])
    assert _resolve(ws, "asset", {"asset_type": "image"}) == _ids([items.loose, items.attached])
    assert _resolve(ws, "asset", {"asset_types": ["svg"]}) == _ids([items.logo])
    assert _resolve(ws, "asset", {"mime_type": "image/svg+xml"}) == _ids([items.logo])
    assert _resolve(ws, "asset", {"text": "logo"}) == _ids([items.logo])
    assert _resolve(ws, "asset", {"tags": ["wool"]}) == _ids([items.loose])
    assert _resolve(ws, "asset", {"unattached": True}) == _ids([items.loose, items.logo])
    assert _resolve(ws, "asset", {"unattached": False}) == _ids([items.attached])
    assert _resolve(ws, "asset", {"created_before": (datetime.now(UTC) - timedelta(days=1)).isoformat()}) == _ids([items.loose])
    assert _resolve(ws, "asset", {"trashed": True}) == _ids([items.binned])  # the Trash's side, for a restore


def test_resource_target_resolves_with_each_filter(ws, items):
    assert _resolve(ws, "resource", {}) == _ids([items.mill, items.hammer])
    assert _resolve(ws, "resource", {"resource_type": "supplier"}) == _ids([items.mill])
    assert _resolve(ws, "resource", {"collection": "Gallery"}) == _ids([items.mill])
    assert _resolve(ws, "resource", {"tags": "wool"}) == _ids([items.mill])
    assert _resolve(ws, "resource", {"query": "ham"}) == _ids([items.hammer])
    assert _resolve(ws, "resource", {"trashed": "true"}) == _ids([items.gone])
    # A template in the query resolves against the run's context, as for entries.
    rows, _ = resolve_target_entities(
        ws.session, ws.gid, {"entity": "resource", "query": {"resource_type": "$event.payload.kind"}}, {"event": {"payload": {"kind": "tool"}}}
    )
    assert _ids(rows) == _ids([items.hammer])


# ── Fan-out: each row is the run's subject ───────────────────────────────────


def _run(ws, definition, **kw):
    seen = []

    def record(session, group_id, action, context, **_):
        seen.append((action, context))
        return {"ok": True}

    res = run_automation_now(ws.session, ws.gid, fake_workflow(slug="t", created_by=None, definition=definition), run_action=record, **kw)
    return res, seen


def test_each_asset_row_is_bound_as_asset_and_as_the_events_subject(ws, items):
    _, seen = _run(
        ws, {"trigger": MANUAL, "target": {"entity": "asset", "query": {"asset_type": "svg"}}, "actions": [{"kind": "webhook", "url": "x"}]}
    )
    ((_action, ctx),) = seen
    assert ctx["asset"]["name"] == "logo" and ctx["asset"]["mime_type"] == "image/svg+xml" and ctx["asset"]["asset_type"] == "svg"
    assert ctx["asset"]["description"] == "The logo" and ctx["asset"]["metadata"] == {"source": "brand"} and ctx["asset"]["trashed"] is False
    assert ctx["event"]["entity_type"] == "asset" and ctx["event"]["asset_id"] == ctx["event"]["entity_id"] == str(items.logo.id)
    assert "entry" not in ctx and "resource" not in ctx


def test_resource_rows_are_filtered_by_conditions_on_resource_fields(ws, items):
    definition = {
        "trigger": MANUAL,
        "target": {"entity": "resource", "query": {}},
        "conditions": [{"field": "resource.tags", "op": "contains", "value": "wool"}],
        "actions": [{"kind": "webhook", "url": "x", "body": {"link": "${resource.url}"}}],
    }
    res, seen = _run(ws, definition)
    assert res["ran"] == 1
    ((_action, ctx),) = seen
    assert ctx["resource"]["name"] == "mill" and ctx["resource"]["url"] == "https://mill.example" and ctx["resource"]["resource_type"] == "supplier"


def _dispatched(monkeypatch):
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: seen.append((kw["event_type"].name, str(kw["entity_id"]))))
    return seen


def test_trash_every_resource_runs_end_to_end_and_sends_each_rows_event(ws, items, monkeypatch):
    """The owner's ask, in the real vocabulary: a manual workflow whose target is every resource, with a bare `trash` step
    (its entity_type follows the target). The Trash's own rows are left alone, and running it again does nothing."""
    from marvin.services.automation.actions.entry import ITEM_OP_SENDS
    from marvin.services.automation.authz import ROLE_ADMIN
    from marvin.services.automation.engine import resolve_authorizer_role

    monkeypatch.setattr("marvin.services.automation.engine.resolve_authorizer_role", lambda *a, **k: ROLE_ADMIN, raising=False)
    sent = _dispatched(monkeypatch)
    definition = {"trigger": MANUAL, "target": {"entity": "resource", "query": {}}, "actions": [{"kind": "entry", "op": "trash"}]}
    wf = fake_workflow(slug="trash-resources", created_by=None, definition=definition)

    res = run_automation_now(ws.session, ws.gid, wf)

    assert res["ok"] is True and res["ran"] == 2
    ws.session.expire_all()
    assert items.mill.trashed_at is not None and items.hammer.trashed_at is not None and items.gone.trashed_at is not None
    assert sorted(e for e, _ in sent if e.startswith("resource_")) == sorted(ITEM_OP_SENDS[("resource", "trash")] * 2)
    assert {i for e, i in sent if e == "resource_trashed"} == {str(items.mill.id), str(items.hammer.id)}
    assert run_automation_now(ws.session, ws.gid, wf)["ran"] == 0  # nothing left outside the Trash
    del resolve_authorizer_role


def test_restore_all_resources_in_the_trash(ws, items, monkeypatch):
    sent = _dispatched(monkeypatch)
    definition = {"trigger": MANUAL, "target": {"entity": "resource", "query": {"trashed": True}}, "actions": [{"kind": "entry", "op": "restore"}]}
    res = run_automation_now(ws.session, ws.gid, fake_workflow(slug="r", created_by=None, definition=definition))
    assert res["ran"] == 1 and res["ok"] is True
    ws.session.expire_all()
    assert items.gone.trashed_at is None and items.mill.trashed_at is None
    assert [(e, i) for e, i in sent if e.startswith("resource_")] == [("resource_restored", str(items.gone.id))]


def test_dry_run_plans_the_asset_rows_without_touching_them(ws, items):
    definition = {"trigger": MANUAL, "target": {"entity": "asset", "query": {"unattached": True}}, "actions": [{"kind": "entry", "op": "trash"}]}
    res = run_automation_now(ws.session, ws.gid, fake_workflow(slug="d", created_by=None, definition=definition), dry_run=True)
    assert res["dry_run"] is True and res["ran"] == 2
    planned = {s["resolved"]["entity_id"]: s["resolved"] for s in res["plan"]}
    assert set(planned) == set(_ids([items.loose, items.logo]))
    assert all(p["entity_type"] == "asset" and p["op"] == "trash" and p["dry_run"] for p in planned.values())
    assert [s["target"]["entity"] for s in res["plan"]] == ["asset", "asset"] and {s["target"]["name"] for s in res["plan"]} == {"loose", "logo"}
    ws.session.expire_all()
    assert items.loose.trashed_at is None and items.logo.trashed_at is None


# ── Asset / resource events bind their item ──────────────────────────────────


def test_an_asset_event_binds_the_asset_like_an_entry_event_binds_the_entry(ws, items):
    ctx = match_context(ws.session, ws.gid, {"event_type": "asset_uploaded", "asset_id": str(items.loose.id), "entity_type": "asset"})
    assert ctx["asset"]["slug"] == items.loose.slug and ctx["asset"]["tags"] == ["wool"] and ctx["asset"]["filename"] == "loose.bin"
    ctx = match_context(ws.session, ws.gid, {"event_type": "resource_created", "resource_id": str(items.mill.id), "entity_type": "resource"})
    assert ctx["resource"]["name"] == "mill" and "asset" not in ctx


def test_on_asset_uploaded_a_bare_trash_step_trashes_that_asset(ws, items, monkeypatch):
    sent = _dispatched(monkeypatch)
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Bin uploads", slug="bin-uploads", enabled=True, created_by=ws.uid,
        definition={"trigger": {"type": "event", "event": "asset_uploaded"}, "actions": [{"kind": "entry", "op": "trash"}]},
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    event = {"event_type": "asset_uploaded", "asset_id": str(items.attached.id), "entity_type": "asset", "entity_id": str(items.attached.id)}
    assert run_automations_for_event(ws.session, ws.gid, event) == 1
    ws.session.expire_all()
    assert items.attached.trashed_at is not None
    assert ("asset_trashed", str(items.attached.id)) in sent


# ── The validator ────────────────────────────────────────────────────────────


def test_the_owners_draft_is_refused_with_each_problem_at_its_path(ws):
    issues = draft_issues(ws.session, ws.gid, OWNERS_JSON)
    assert [i["path"] for i in issues] == ["actions[0].entity_query", "actions[0].entity_query.where"]
    query, where = (i["message"] for i in issues)
    assert "entity_query finds entries only" in query and "target" in query and "entity_slug" in query  # (a) and the fix
    assert "flat object" in where and "where" in where and "Keys:" in where  # (b) the real shape and the allowed keys
    assert "no publish status" in where and "trashed: true" in where  # (c) resources aren't published
    # The REST write path refuses the certain failure too (422), with the same text.
    rest = gates._sign_in(ws.workspace, AD).post("/api/automations", json={"name": "Owner", "definition": OWNERS_JSON})
    assert rest.status_code == 422 and "entity_query finds entries only" in rest.json()["detail"]["issues"][0]["message"]


ASSET_TRASH = [{"kind": "entry", "op": "trash"}]


@pytest.mark.parametrize(
    ("definition", "path", "hint"),
    [
        ({"trigger": MANUAL, "target": {"entity": "asset", "query": {"kind": "image"}}, "actions": ASSET_TRASH}, "target.query.kind", "asset_type"),
        (
            {"trigger": MANUAL, "target": {"entity": "resource", "query": {"where": []}}, "actions": ASSET_TRASH},
            "target.query.where",
            "trashed: true",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "asset", "query": {"status": "published"}}, "actions": ASSET_TRASH},
            "target.query.status",
            "no publish status",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "asset", "query": {"asset_type": "photo"}}, "actions": ASSET_TRASH},
            "target.query.asset_type",
            "image",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "resource", "query": {"collection": "nope"}}, "actions": ASSET_TRASH},
            "target.query.collection",
            "featured",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "entry", "query": {"status": {"op": "eq", "value": "x"}}}, "actions": ASSET_TRASH},
            "target.query.status",
            "not an object",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "entry", "query": {"where": {"field": "x"}}}, "actions": ASSET_TRASH},
            "target.query.where",
            "list of comparisons",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "entry", "query": {"where": [{"field": "x", "op": "like"}]}}, "actions": ASSET_TRASH},
            "target.query.where",
            "eq",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "asset", "query": {}}, "actions": [{"kind": "entry", "op": "publish"}]},
            "actions[0].op",
            "runs on assets",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "asset", "query": {}}, "actions": [{"kind": "entry", "op": "trash", "entity_type": "resource"}]},
            "actions[0].entity_type",
            "drop entity_type",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "resource", "query": {}}, "actions": [{"kind": "emit_event", "event": "entry_published"}]},
            "actions[0].event",
            "about an entry",
        ),
        (
            {"trigger": MANUAL, "target": {"entity": "asset", "query": {}}, "actions": [{"kind": "operation", "op": "improve-writing"}]},
            "actions[0].op",
            "runs on entry",
        ),
        (
            {"trigger": MANUAL, "actions": [{"kind": "operation", "op": "generate-alt-text", "entity_type": "resource"}]},
            "actions[0].entity_type",
            "runs on asset",
        ),
        ({"trigger": MANUAL, "target": {"entity": "collection", "query": {}}, "actions": ASSET_TRASH}, "target.entity", "asset"),
    ],
)
def test_unknown_keys_shapes_and_entry_only_steps_on_item_targets_are_refused(ws, definition, path, hint):
    out = _tool(ws, "draft_workflow", {"name": "Refused", "definition": definition})
    assert [i["path"] for i in out["issues"]] == [path] and hint in out["issues"][0]["message"], out
    assert _rows(ws) == []


def test_rest_stays_lenient_on_shapes_but_warns_and_refuses_certain_failures(ws):
    admin = gates._sign_in(ws.workspace, AD)
    lenient = {"trigger": MANUAL, "target": {"entity": "resource", "query": {"where": []}}, "actions": [{"kind": "entry", "op": "publish"}]}
    out = admin.post("/api/automations/validate", json={"definition": lenient}).json()["issues"]
    assert {(i["level"], i.get("path")) for i in out} >= {("warning", "target.query.where"), ("warning", "actions[0].op")}
    assert admin.post("/api/automations", json={"name": "Lenient", "definition": lenient}).status_code == 201
    # publish with an entity_type, and an entity_query on an asset step, fail at run time for certain → 422.
    for step in (
        {"kind": "entry", "op": "publish", "entity_type": "asset"},
        {"kind": "entry", "op": "trash", "entity_type": "asset", "entity_query": {}},
    ):
        res = admin.post("/api/automations", json={"name": "Certain", "definition": {"trigger": MANUAL, "actions": [step]}})
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["issues"][0]["path"] in ("actions[0].entity_type", "actions[0].entity_query")


def test_item_conditions_and_steps_are_coherent_for_the_validator(ws):
    from marvin.services.automation.validation import validate_definition

    good = {
        "trigger": {"type": "event", "event": "asset_uploaded"},
        "conditions": [{"field": "asset.asset_type", "op": "eq", "value": "image"}],
        "actions": [{"kind": "entry", "op": "trash"}, {"kind": "operation", "op": "generate-alt-text"}],
    }
    assert validate_definition(good) == [] and draft_issues(ws.session, ws.gid, good) == []
    on_target = {
        "trigger": MANUAL,
        "target": {"entity": "resource", "query": {}},
        "conditions": [{"field": "resource.url", "op": "exists"}],
        "actions": ASSET_TRASH,
    }
    assert validate_definition(on_target) == []


# ── The guide ────────────────────────────────────────────────────────────────


def test_guide_documents_all_three_target_entities_and_item_templates(ws):
    from marvin.services.item_query import KEY_NOTES, KEYS

    assert {k for notes in KEY_NOTES.values() for k in notes} == {k for keys in KEYS.values() for k in keys}
    assert all(set(KEY_NOTES[kind]) == set(KEYS[kind]) for kind in KEYS)
    guide = authoring_guide(ws.session, ws.gid, section="target")["target"]
    assert "asset" in guide["entity"] and "resource" in guide["entity"]
    assert set(guide["asset"]["query"]) == set(KEYS["asset"]) and guide["asset"]["example"]["entity"] == "asset"
    assert set(guide["resource"]["query"]) == set(KEYS["resource"]) and guide["resource"]["example"]["entity"] == "resource"
    actions = authoring_guide(ws.session, ws.gid, section="actions")["actions"]["asset_resource_ops"]
    assert actions["ops"] == ["restore", "trash"] and "entity_query finds entries only" in actions["note"] and "current item" in actions["acts_on"]
    namespaces = authoring_guide(ws.session, ws.gid, section="templates")["templates"]["namespaces"]
    assert "mime_type" in namespaces["asset"] and "resource_type" in namespaces["resource"]
    assert {e["title"] for e in ITEM_EXAMPLES} <= set(EXAMPLES) and all({"id", "title", "definition", "vars"} <= set(e) for e in ITEM_EXAMPLES)


# ── End to end: the owner's ask, scripted ────────────────────────────────────


def test_asking_marvin_to_trash_published_resources_drafts_a_resource_target(ws, items, monkeypatch):
    """ "Create a workflow that trashes all published resources when run": the model reads the guide and drafts a
    resource target (resources have no publish status — every resource outside the Trash is the published set).
    The draft passes, and a REST dry run plans each resource."""
    from marvin.services.ai import factory

    admin = gates._sign_in(ws.workspace, AD)
    transport = ScriptedTransport()
    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: FakeAIProvider(transport))
    definition = {"trigger": MANUAL, "target": {"entity": "resource", "query": {}}, "actions": [{"kind": "entry", "op": "trash"}]}
    transport.reply_tool_calls([ToolCall(id="c1", name="workflow_authoring_guide", arguments={"section": "target"})])
    transport.reply_tool_calls([ToolCall(id="c2", name="draft_workflow", arguments={"name": "Trash published resources", "definition": definition})])
    sent = transport.send

    def send(request):
        if len(transport.requests) == 2:
            result = json.loads(request["messages"][-1]["content"])
            transport.reply_text(f"Created, switched off: {result['editLink']}")
        return sent(request)

    transport.send = send
    res = admin.post(
        "/api/ai/agent", json={"message": "create a workflow that trashes all published resources when run", "modelOverride": "fake-model"}
    )
    assert res.status_code == 200, res.text
    assert [s["tool"] for s in res.json()["steps"]] == ["workflow_authoring_guide", "draft_workflow"]
    guide = json.loads(transport.requests[1]["messages"][-1]["content"])["target"]
    assert "resource" in guide and "no publish status" in guide["note"]

    (row,) = _rows(ws)
    assert (row.enabled, row.definition) == (False, definition)
    plan = admin.post(f"/api/automations/{row.id}/run", params={"dry_run": "true"}).json()
    assert plan["status"] == "dry_run" and plan["ran"] == 2
    assert {s["target"]["name"] for s in plan["plan"]} == {"mill", "hammer"} and all(s["resolved"]["entity_type"] == "resource" for s in plan["plan"])
    ws.session.expire_all()
    assert items.mill.trashed_at is None
