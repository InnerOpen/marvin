"""DB-backed tests for the registry bulk tag tool (services/ai/tools/builtins_actions).

Covers what shipped beyond the single-item path: selecting targets by `entities` or `filter`
(type / tag / query, dimensions mirroring smart-collection rules), idempotency, the unknown-tag
→ empty case, and the asset/resource smart-collection resync — the latent-gap fix where tagging
via link_tag alone never re-materialized collection membership.
"""

import json
import uuid

from pytest import fixture

from marvin.db.models.platform import (
    Assets,
    AssetTags,
    CollectionAssets,
    Collections,
)
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext
from marvin.services.ai.tools.builtins_actions import _resolve_targets


@fixture(autouse=True)
def _quiet_events(monkeypatch):
    """Isolate the tool's selection/counting/resync from the event subsystem (whose audit-log
    persistence needs seed rows a throwaway workspace lacks) — the service tests do the same with a
    spy bus. link_tag still find-or-creates the tag, links the junction, and commits."""
    monkeypatch.setattr("marvin.services.tagging._emit", lambda *a, **k: None)


def _asset(db_session, gid, uid, slug, name, asset_type, ext="jpg", mime="image/jpeg"):
    aid = uuid.uuid4()
    db_session.execute(
        Assets.__table__.insert().values(
            id=aid,
            group_id=gid,
            slug=slug,
            name=name,
            original_filename=f"{slug}.{ext}",
            filename=slug,
            extension=ext,
            file_size=10,
            mime_type=mime,
            asset_type=asset_type,
            checksum=uuid.uuid4().hex,
            storage_provider="local",
            storage_key=f"k/{aid.hex}",
            uploaded_by=uid,
        )
    )
    return aid


@fixture
def ws(db_session):
    """A workspace with 2 image + 1 svg + 1 document asset."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"blk-{marker}", slug=f"blk-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )

    ids = {
        "img1": _asset(db_session, gid, uid, "img-1", "Photo One", "image"),
        "img2": _asset(db_session, gid, uid, "img-2", "Photo Two", "image"),
        "svg1": _asset(db_session, gid, uid, "logo", "Logo", "svg", ext="svg", mime="image/svg+xml"),
        "doc1": _asset(db_session, gid, uid, "spec", "Spec", "document", ext="pdf", mime="application/pdf"),
    }
    db_session.commit()

    yield gid, ids

    db_session.query(CollectionAssets).delete()
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(AssetTags).delete()
    from marvin.db.models.platform import Tags

    db_session.query(Tags).filter(Tags.group_id == gid).delete()
    db_session.execute(Assets.__table__.delete().where(Assets.group_id == gid))
    db_session.execute(Users.__table__.delete().where(Users.group_id == gid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _ctx(db_session, gid):
    return ToolContext(session=db_session, group_id=gid, user=None, provider=None)


def _attach(db_session, gid, args):
    return json.loads(get_tool("attach_tag").handler(_ctx(db_session, gid), args))


# ── target resolution ─────────────────────────────────────────────────────────
def test_filter_by_asset_type_selects_matching(db_session, ws):
    gid, _ = ws
    ids, err = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"asset_types": ["image", "svg"]}})
    assert err is None
    assert len(ids) == 3  # 2 image + 1 svg, not the document


def test_filter_by_mime_type_is_finer_than_asset_type(db_session, ws):
    gid, _ = ws
    # asset_type "image" covers jpeg; mime_types targets the exact type — svg only, no jpegs.
    svg, _ = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"mime_types": ["image/svg+xml"]}})
    assert len(svg) == 1  # only the logo.svg
    jpg, _ = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"mime_types": ["image/jpeg"]}})
    assert len(jpg) == 2  # the two photos


def test_filter_by_query_matches_name(db_session, ws):
    gid, _ = ws
    ids, _ = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"query": "Photo"}})
    assert len(ids) == 2


def test_entities_list_resolves_by_slug(db_session, ws):
    gid, _ = ws
    ids, _ = _resolve_targets(_ctx(db_session, gid), "asset", {"entities": ["img-1", "logo", "nope-xyz"]})
    assert len(ids) == 2  # the unknown slug is dropped


# ── attach: bulk, idempotent, single-shape ─────────────────────────────────────
def test_bulk_attach_then_idempotent(db_session, ws):
    gid, _ = ws
    r1 = _attach(db_session, gid, {"entity_type": "asset", "filter": {"asset_types": ["image", "svg"]}, "tag": "site asset"})
    assert r1["targets"] == 3 and r1["attached"] == 3 and r1["unchanged"] == 0
    r2 = _attach(db_session, gid, {"entity_type": "asset", "filter": {"asset_types": ["image", "svg"]}, "tag": "site asset"})
    assert r2["attached"] == 0 and r2["unchanged"] == 3  # nothing re-added


def test_single_target_keeps_simple_shape(db_session, ws):
    gid, _ = ws
    r = _attach(db_session, gid, {"entity_type": "asset", "entity": "img-1", "tag": "hero"})
    assert r["result"] == "attached" and r["entity"] == "img-1" and r["tag"] == "hero"


def test_multiple_tags_applied_to_each(db_session, ws):
    gid, _ = ws
    r = _attach(db_session, gid, {"entity_type": "asset", "entities": ["img-1", "img-2"], "tags": ["a", "b"]})
    assert r["targets"] == 2 and r["attached"] == 4  # 2 entities × 2 tags


# ── filter by tag (the "query from tags" dimension) ────────────────────────────
def test_filter_by_tag_and_unknown_tag(db_session, ws):
    gid, _ = ws
    _attach(db_session, gid, {"entity_type": "asset", "filter": {"asset_types": ["image", "svg"]}, "tag": "site"})
    # select by the tag we just applied…
    ids, _ = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"tags": ["site"]}})
    assert len(ids) == 3
    # …AND narrows with another dimension
    ids2, _ = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"asset_types": ["svg"], "tags": ["site"]}})
    assert len(ids2) == 1
    # unknown tag → no rows, no error
    ids3, err = _resolve_targets(_ctx(db_session, gid), "asset", {"filter": {"tags": ["does-not-exist"]}})
    assert ids3 == [] and err is None


# ── the latent-gap fix: bulk tag resyncs smart-collection membership ───────────
def test_bulk_tag_materializes_smart_collection(db_session, ws):
    gid, _ = ws
    col = Collections(
        session=db_session,
        group_id=gid,
        name="Site Assets",
        slug="site-assets",
        target_type="asset",
        is_smart=True,
        smart_rules={"tags": ["site"]},
    )
    db_session.add(col)
    db_session.commit()

    assert db_session.query(CollectionAssets).filter_by(collection_id=col.id).count() == 0
    r = _attach(db_session, gid, {"entity_type": "asset", "filter": {"asset_types": ["image", "svg"]}, "tag": "site"})
    assert r["collections_resynced"] == 3
    # every image/svg asset is now a materialized member
    assert db_session.query(CollectionAssets).filter_by(collection_id=col.id).count() == 3


# ── big bulk writes ask first (tools/bulk_writes.py) ──────────────────────────
# 4 assets × 6 tags = 24 links: over both thresholds. 2 assets × 3 tags stays direct.
_SIX_TAGS = ["red", "blue", "green", "portrait", "landscape", "large-format"]
_ALL_ASSETS = {"entity_type": "asset", "filter": {"asset_types": ["image", "svg", "document"]}}


def _links(db_session, ids):
    return db_session.query(AssetTags).filter(AssetTags.asset_id.in_(list(ids.values()))).count()


def _loop(db_session, gid, args, *, can_park, resume=None):
    from marvin.services.ai.agent import AgentTool, run_agent_loop
    from marvin.services.ai.base import CompletionResult, ToolCall
    from marvin.services.ai.tools import bulk_writes

    spec = get_tool("attach_tag")
    run, check = bulk_writes.bind(spec, _ctx(db_session, gid), can_park=can_park)
    tool = AgentTool(name="attach_tag", description="", input_schema={}, run=run, category="links", approval_check=check)

    def result(content="", calls=None):
        return CompletionResult(content=content, prompt_tokens=1, completion_tokens=1, total_tokens=2, model="m", tool_calls=calls or [])

    class Provider:
        def __init__(self):
            self.results = (
                [result(content="done")] if resume else [result(calls=[ToolCall(id="c1", name="attach_tag", arguments=args)]), result("done")]
            )

        def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
            return self.results.pop(0)

    return run_agent_loop(Provider(), "m", [], [tool], resume=resume)


def test_big_bulk_attach_parks_for_approval_with_the_targets_listed(db_session, ws):
    gid, ids = ws
    res = _loop(db_session, gid, {**_ALL_ASSETS, "tags": _SIX_TAGS}, can_park=True)
    assert res.stopped_reason == "awaiting_approval"
    preview = res.pending_calls[0].preview
    assert preview["summary"] == "Attach 6 tags to 4 assets (24 links)"
    assert {"Photo One", "Photo Two", "Logo", "Spec"} == set(preview["targets"])
    assert _links(db_session, ids) == 0


def test_big_bulk_attach_runs_once_the_user_approves(db_session, ws):
    from marvin.services.ai.agent import ResumeState

    gid, ids = ws
    parked = _loop(db_session, gid, {**_ALL_ASSETS, "tags": _SIX_TAGS}, can_park=True)
    resume = ResumeState(convo=parked.convo, pending=parked.pending_calls, decisions={"c1": "approve"})
    _loop(db_session, gid, None, can_park=True, resume=resume)
    assert _links(db_session, ids) == 24


def test_big_bulk_attach_is_refused_where_the_run_cannot_park(db_session, ws):
    gid, ids = ws
    res = _loop(db_session, gid, {**_ALL_ASSETS, "tags": _SIX_TAGS}, can_park=False)
    assert res.stopped_reason == "complete"
    assert "smaller steps" in json.loads(res.steps[0].result)["error"]
    assert _links(db_session, ids) == 0


def test_small_bulk_attach_runs_directly(db_session, ws):
    gid, ids = ws
    res = _loop(db_session, gid, {"entity_type": "asset", "entities": ["img-1", "img-2"], "tags": ["red", "blue", "denim"]}, can_park=True)
    assert res.stopped_reason == "complete"
    assert _links(db_session, ids) == 6


def test_big_bulk_detach_asks_too(db_session, ws):
    from marvin.services.ai.tools import bulk_writes

    gid, _ = ws
    _, check = bulk_writes.bind(get_tool("detach_tag"), _ctx(db_session, gid), can_park=True)
    assert check({**_ALL_ASSETS, "tags": _SIX_TAGS})["summary"] == "Detach 6 tags from 4 assets (24 links)"


# ── nobody to ask: MarvinMCP's direct invoke and the stateless run_agent ──────


def _invoke(db_session, gid, args):
    """POST /api/ai/tools/attach_tag/invoke as MarvinMCP does, signed in as an EDITOR of the workspace."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from marvin.app import app
    from marvin.core.dependencies import get_current_user
    from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
    from marvin.db.models.users.users import Users

    uid = db_session.query(Users.id).filter(Users.group_id == gid).scalar()
    role = WorkspaceRole.EDITOR
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid,
        group_id=gid,
        active_group_id=gid,
        admin=False,
        is_superuser=False,
        full_name="U",
        email="u@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=gid, workspace_role=role)],
        get_workspace_role=lambda group_id: role if str(group_id) == str(gid) else None,
    )
    try:
        res = TestClient(app).post("/api/ai/tools/attach_tag/invoke", json={"args": args, "source": "mcp"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert res.status_code == 200, res.text
    return res.json()


def test_mcp_invoke_refuses_a_big_filtered_attach_and_writes_nothing(db_session, ws):
    gid, ids = ws
    out = _invoke(db_session, gid, {**_ALL_ASSETS, "tags": _SIX_TAGS})
    assert "Attach 6 tags to 4 assets (24 links)" in out["error"]
    assert "Ask page" in out["error"] and out["links"] == 24 and out["targets"] == 4
    assert _links(db_session, ids) == 0


def test_mcp_invoke_runs_a_small_attach(db_session, ws):
    gid, ids = ws
    out = _invoke(db_session, gid, {"entity_type": "asset", "entities": ["img-1", "img-2"], "tags": ["red", "blue", "denim"]})
    assert "error" not in out
    assert _links(db_session, ids) == 6


def _standalone_attach(db_session, gid):
    from marvin.services.ai.agents import SYSTEM_AGENTS
    from marvin.services.ai.operations.base import ROLE_EDITOR
    from marvin.services.ai.tools.builtins_agents import standalone_tools

    tools = standalone_tools(SYSTEM_AGENTS["marvin"], _ctx(db_session, gid), ROLE_EDITOR)
    return next(t for t in tools if t.name == "attach_tag")


def test_stateless_run_agent_refuses_a_big_attach_and_writes_nothing(db_session, ws):
    # MCP run_agent(agent="marvin") has no thread: Marvin's Allow on attach_tag must not lift the bulk gate
    gid, ids = ws
    out = json.loads(_standalone_attach(db_session, gid).run({**_ALL_ASSETS, "tags": _SIX_TAGS}))
    assert "Attach 6 tags to 4 assets (24 links)" in out["error"]
    assert _links(db_session, ids) == 0


def test_stateless_run_agent_runs_a_small_attach(db_session, ws):
    gid, ids = ws
    _standalone_attach(db_session, gid).run({"entity_type": "asset", "entities": ["img-1", "img-2"], "tags": ["red", "blue", "denim"]})
    assert _links(db_session, ids) == 6


def test_attach_tag_description_steers_per_target_tagging():
    desc = get_tool("attach_tag").description
    assert "PER TARGET" in desc and "generate_tags" in desc and "wholesale" in desc
