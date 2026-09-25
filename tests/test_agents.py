"""Workspace agents: schema contract, system agents, allowlist filtering, and run gates.

Pure-level tests (no DB, no network) for services/ai/agents.py and schemas/group/agent.py.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from marvin.schemas.group.agent import SYSTEM_AGENT_SLUGS, AgentCreate, AgentRead, AgentUpdate
from marvin.services.ai.agents import (
    SYSTEM_AGENTS,
    AgentSpec,
    filter_tools,
    list_agents,
    may_talk,
    resolve_agent,
    spec_from_row,
)
from marvin.services.ai.operations.base import ROLE_AUTHOR, ROLE_EDITOR, ROLE_VIEWER

# ── Schema ───────────────────────────────────────────────────────────────────


def test_agent_create_accepts_a_persona_with_an_allowlist_from_the_wire():
    body = AgentCreate.model_validate({"slug": "workshop", "name": "Workshop", "toolAllowlist": ["search_content", "get_entry"], "minRole": 1})
    assert body.slug == "workshop"
    assert body.kind == "persona"
    assert body.tool_allowlist == ["search_content", "get_entry"]
    assert body.model_dump(by_alias=True)["toolAllowlist"] == ["search_content", "get_entry"]


def test_agent_create_normalises_and_rejects_bad_slugs():
    assert AgentCreate(slug=" Workshop ", name="w").slug == "workshop"
    for bad in ("", "a", "-lead", "has space", "x" * 65):
        with pytest.raises(ValidationError):
            AgentCreate(slug=bad, name="w")


@pytest.mark.parametrize("slug", SYSTEM_AGENT_SLUGS)
def test_agent_create_refuses_to_shadow_a_system_agent(slug):
    with pytest.raises(ValidationError):
        AgentCreate(slug=slug, name="nope")


def test_agent_create_validates_kind_register_and_sources():
    with pytest.raises(ValidationError):
        AgentCreate(slug="a1", name="a", kind="workflow")  # v3, not yet
    with pytest.raises(ValidationError):
        AgentCreate(slug="a1", name="a", default_register="shouty")
    with pytest.raises(ValidationError):
        AgentCreate(slug="a1", name="a", sources=["editor", "carrier-pigeon"])
    ok = AgentCreate(slug="a1", name="a", sources=["editor", "editor", "mcp"], tool_allowlist=[" x ", "", "x"])
    assert ok.sources == ["editor", "mcp"]
    assert ok.tool_allowlist == ["x"]


def test_agent_update_is_fully_optional_but_still_validated():
    assert AgentUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        AgentUpdate(default_register="loud")


def test_agent_read_marks_system_agents_without_an_id():
    r = AgentRead(slug="ask", name="Ask", is_system=True)
    assert r.id is None and r.model_dump(by_alias=True)["isSystem"] is True


# ── System agents + resolution ───────────────────────────────────────────────


def test_system_agents_match_the_reserved_slugs_and_shapes():
    assert tuple(SYSTEM_AGENTS) == SYSTEM_AGENT_SLUGS
    assert SYSTEM_AGENTS["marvin"].tool_allowlist is None  # everything the role allows
    assert SYSTEM_AGENTS["ask"].tool_allowlist == ("search_content", "workspace_overview")
    assert SYSTEM_AGENTS["chat"].kind == "model"
    assert all(s.is_system for s in SYSTEM_AGENTS.values())


def _row(**over):
    base = {
        "id": "11111111-2222-3333-4444-555555555555",
        "slug": "workshop",
        "name": "Workshop",
        "description": "brand voice",
        "kind": "persona",
        "system_prompt": "Speak plainly.",
        "model_override": None,
        "tool_allowlist": ["search_content"],
        "default_register": "professional",
        "min_role": ROLE_VIEWER,
        "sources": None,
        "enabled": True,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_spec_from_row_carries_every_field_and_defaults_sources():
    s = spec_from_row(_row())
    assert s.slug == "workshop" and s.tool_allowlist == ("search_content",) and s.default_register == "professional"
    assert s.is_system is False and s.id == "11111111-2222-3333-4444-555555555555"
    assert "editor" in s.sources and "mcp" in s.sources  # None → all invocation sources


def _session_with(rows):
    session = MagicMock()
    q = session.query.return_value.filter_by.return_value
    q.order_by.return_value.all.return_value = rows
    q.first.return_value = rows[0] if rows else None
    return session


def test_resolve_agent_prefers_system_then_rows_then_none():
    session = _session_with([_row()])
    assert resolve_agent(session, "g1", "ASK ").is_system is True
    assert resolve_agent(session, "g1", "workshop").slug == "workshop"
    assert resolve_agent(_session_with([]), "g1", "ghost") is None


def test_list_agents_puts_system_agents_first():
    specs = list_agents(_session_with([_row()]), "g1")
    assert [s.slug for s in specs] == ["marvin", "ask", "chat", "workshop"]


# ── Tool filtering + gates ───────────────────────────────────────────────────


def _tool(name):
    return SimpleNamespace(name=name)


def test_filter_tools_none_means_everything_and_a_list_restricts():
    tools = [_tool("search_content"), _tool("compose_entry"), _tool("get_entry")]
    assert [t.name for t in filter_tools(tools, None)] == ["search_content", "compose_entry", "get_entry"]
    assert [t.name for t in filter_tools(tools, ("get_entry", "search_content"))] == ["search_content", "get_entry"]
    assert filter_tools(tools, ()) == []


def test_may_talk_gates_on_enabled_role_and_source():
    spec = AgentSpec(slug="w", name="W", min_role=ROLE_EDITOR, sources=("editor", "mcp"))
    assert may_talk(spec, ROLE_EDITOR, "editor") == (True, "")
    ok, why = may_talk(spec, ROLE_AUTHOR, "editor")
    assert not ok and "role" in why
    ok, why = may_talk(spec, ROLE_EDITOR, "api")
    assert not ok and "source" in why
    ok, why = may_talk(AgentSpec(slug="w", name="W", enabled=False), ROLE_EDITOR, "editor")
    assert not ok and "disabled" in why


def test_write_policy_defaults_off_for_user_agents_and_on_for_marvin():
    assert AgentCreate(slug="w1", name="w").allow_writes is False
    assert SYSTEM_AGENTS["marvin"].allow_writes is True
    assert SYSTEM_AGENTS["ask"].allow_writes is False
    assert spec_from_row(_row(allow_writes=True)).allow_writes is True
    assert spec_from_row(_row()).allow_writes is False  # row without the attr → off


# ── Permission matrix ────────────────────────────────────────────────────────

from marvin.services.ai.agents import (  # noqa: E402 — appended section
    POLICY_ALLOW,
    POLICY_BLOCK,
    catalog_tools,
    permission_matrix,
    resolve_policy,
)
from marvin.services.ai.tools import list_tools  # noqa: E402
from marvin.services.ai.tools.categories import CATEGORY_BY_ID, CATEGORY_BY_TOOL, category_of  # noqa: E402


def test_every_agent_facing_registry_tool_has_a_category():
    uncategorised = [
        t.name for t in list_tools() if ("agent" in t.sources or t.name in ("list_agents", "run_agent")) and t.name not in CATEGORY_BY_TOOL
    ]
    assert uncategorised == [], f"add these to CATEGORY_BY_TOOL: {uncategorised}"
    # and the mapping only names known categories, with read/write agreeing with the registry flag
    for t in list_tools():
        cat = CATEGORY_BY_TOOL.get(t.name)
        if cat:
            assert cat in CATEGORY_BY_ID
            assert CATEGORY_BY_ID[cat].writes == (not t.read_only), (
                f"{t.name}: category writes={CATEGORY_BY_ID[cat].writes} vs read_only={t.read_only}"
            )


def test_category_of_places_mcp_tools_by_their_hints():
    assert category_of("mcp__n8n__send_telegram") == "mcp"  # no hints → assume it writes
    assert category_of("mcp__brain__read_note", read_only=True) == "mcp_read"
    assert category_of("mcp__brain__delete_note", read_only=False, destructive=True) == "mcp_destructive"
    assert category_of("mcp__brain__odd", read_only=True, destructive=True) == "mcp_destructive"  # destructive wins


def test_mcp_tool_info_keeps_the_servers_annotations():
    from types import SimpleNamespace

    from marvin.services.ai.mcp_client import tool_info_from_listed

    hints = SimpleNamespace(readOnlyHint=True, destructiveHint=False)
    listed = SimpleNamespace(name="read-note", description="Read a note", inputSchema={"type": "object"}, annotations=hints)
    info = tool_info_from_listed(listed)
    assert (info.read_only, info.destructive) == (True, False)
    bare = tool_info_from_listed(SimpleNamespace(name="x", description=None, inputSchema=None, annotations=None))
    assert (bare.read_only, bare.destructive, bare.input_schema) == (None, None, {})


def test_read_only_agent_reaches_read_only_mcp_tools_but_not_writes():
    ro = AgentSpec(slug="w", name="W")
    assert resolve_policy(ro, "mcp__brain__read_note", "mcp_read", ROLE_VIEWER)[0] == POLICY_ALLOW
    assert resolve_policy(ro, "mcp__brain__create_note", "mcp", ROLE_EDITOR)[0] == POLICY_BLOCK
    assert resolve_policy(ro, "mcp__brain__delete_note", "mcp_destructive", ROLE_EDITOR)[0] == POLICY_BLOCK
    rw = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"mcp_destructive": "block"})
    assert resolve_policy(rw, "mcp__brain__create_note", "mcp", ROLE_EDITOR)[0] == POLICY_ALLOW
    assert resolve_policy(rw, "mcp__brain__delete_note", "mcp_destructive", ROLE_EDITOR) == (POLICY_BLOCK, "category policy")


def test_category_of_falls_back_sensibly():
    assert category_of("future_tool", read_only=True) == "other_read"
    assert category_of("future_tool", read_only=False) == "other_write"


def test_resolve_policy_reads_allow_and_writes_follow_allow_writes():
    ro = AgentSpec(slug="w", name="W")  # allow_writes False
    assert resolve_policy(ro, "search_content", "entries_read", ROLE_VIEWER)[0] == POLICY_ALLOW
    decision, why = resolve_policy(ro, "compose_entry", "entries_author", ROLE_EDITOR)
    assert decision == POLICY_BLOCK and "read-only" in why
    rw = AgentSpec(slug="w", name="W", allow_writes=True)
    assert resolve_policy(rw, "compose_entry", "entries_author", ROLE_AUTHOR)[0] == POLICY_ALLOW


def test_resolve_policy_never_lets_a_write_through_below_author():
    rw = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"entries_author": "allow", "compose_entry": "allow"})
    decision, why = resolve_policy(rw, "compose_entry", "entries_author", ROLE_VIEWER)
    assert decision == POLICY_BLOCK and "AUTHOR" in why


def test_resolve_policy_precedence_allowlist_then_tool_then_category():
    spec = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"links": "block", "attach_tag": "allow"})
    assert resolve_policy(spec, "attach_tag", "links", ROLE_EDITOR) == (POLICY_ALLOW, "tool policy")
    assert resolve_policy(spec, "attach_asset", "links", ROLE_EDITOR) == (POLICY_BLOCK, "category policy")
    listed = AgentSpec(slug="w", name="W", tool_allowlist=("get_entry",))
    assert resolve_policy(listed, "search_content", "entries_read", ROLE_EDITOR)[1] == "not in the agent's allowlist"


def test_permission_matrix_rows_cover_the_catalog_and_keep_mcp():
    rows = permission_matrix(AgentSpec(slug="w", name="W"), ROLE_VIEWER, catalog_tools())
    ids = [r["id"] for r in rows]
    assert "entries_read" in ids and "entries_author" in ids and "ai_ops" in ids
    assert [i for i in ids if i.startswith("mcp")] == ["mcp_read", "mcp", "mcp_destructive"]
    entries = next(r for r in rows if r["id"] == "entries_read")
    assert entries["default"] == POLICY_ALLOW and all(t["decision"] == POLICY_ALLOW for t in entries["tools"])
    author = next(r for r in rows if r["id"] == "entries_author")
    assert author["default"] == POLICY_BLOCK and {t["name"] for t in author["tools"]} == {"compose_entry", "revise_entry"}
    assert next(r for r in rows if r["id"] == "mcp")["tools"] == []
    # discovered MCP tools handed in by the controller land in their hinted rows
    with_mcp = catalog_tools() + [
        {"name": "mcp__brain__read_note", "category": "mcp_read", "description": "", "kind": "mcp", "readOnly": True, "minRole": ROLE_VIEWER}
    ]
    rows = permission_matrix(AgentSpec(slug="w", name="W"), ROLE_VIEWER, with_mcp)
    read_row = next(r for r in rows if r["id"] == "mcp_read")
    assert read_row["default"] == POLICY_ALLOW and read_row["tools"][0]["decision"] == POLICY_ALLOW


def test_schema_validates_policy_values_and_suggestions():
    ok = AgentCreate(slug="w2", name="w", tool_policy={"links": "block"}, icon="🧵", suggestions=["What's on the bench?"])
    assert ok.tool_policy == {"links": "block"} and ok.suggestions == ["What's on the bench?"]
    # "ask" (ask-first) is a valid policy value since agents v2 slice C landed POLICY_ASK
    assert AgentCreate(slug="w2", name="w", tool_policy={"links": "ask"}).tool_policy == {"links": "ask"}
    with pytest.raises(ValidationError):
        AgentCreate(slug="w2", name="w", tool_policy={"links": "maybe"})
    with pytest.raises(ValidationError):
        AgentCreate(slug="w2", name="w", suggestions=[str(i) for i in range(9)])


# ── view_image (read-only vision) ────────────────────────────────────────────


def test_view_image_is_registered_read_only_and_categorised_as_a_read():
    spec = next(t for t in list_tools() if t.name == "view_image")
    assert spec.read_only is True and spec.min_role == ROLE_VIEWER
    assert category_of("view_image", read_only=True) == "library_read"
    # so a read-only agent may use it
    assert resolve_policy(AgentSpec(slug="w", name="W"), "view_image", "library_read", ROLE_VIEWER)[0] == POLICY_ALLOW


def test_view_image_describes_from_pixels_without_writing_back(monkeypatch):
    from marvin.services.ai.tools import builtins_vision as bv

    class FakeBuilder:
        def __init__(self, *_): ...

        def with_asset(self, _id):
            return self

        def with_asset_images(self, limit=1):
            return self

        def build(self):
            asset = {"name": "unnamed.jpg", "slug": "ask-unnamed", "mime_type": "image/jpeg", "image_data": "AAAA"}
            return SimpleNamespace(assets=[asset])

    class FakeProvider:
        provider_type = "openai"

        def complete(self, messages, model, opts):
            # the user message must be multimodal: text + an image part
            content = messages[-1].content
            assert isinstance(content, list) and any(getattr(part, "data", None) == "AAAA" for part in content)
            description = "A close-up of raw selvedge denim with a copper rivet."
            return SimpleNamespace(content=description, prompt_tokens=10, completion_tokens=12, total_tokens=22)

    monkeypatch.setattr("marvin.services.ai.context.ContextBuilder", FakeBuilder)
    monkeypatch.setattr("marvin.services.ai.entity_resolve.resolve_entity_id", lambda s, g, t, i: "5161836e-77a0-4ee7-8f3e-25f6d94117e3")
    monkeypatch.setattr(bv, "_default_model", lambda ctx: "gpt-4o-mini", raising=False)
    monkeypatch.setattr("marvin.services.ai.tools.builtins_agents._default_model", lambda ctx: "gpt-4o-mini")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None  # no ai_models row → can't assert incompatibility
    ctx = SimpleNamespace(session=session, group_id="g1", user=SimpleNamespace(id="u1"), provider=FakeProvider(), logger=MagicMock())

    out = json.loads(bv.view_image(ctx, {"asset": "5161836e-77a0-4ee7-8f3e-25f6d94117e3", "question": "what fabric?"}))
    assert out["description"].startswith("A close-up")
    assert out["asset"]["name"] == "unnamed.jpg"
    # nothing written to the asset: only the execution row is added
    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 1 and added[0].operation_slug == "tool:view_image" and added[0].status == "completed"


# ── workspace preamble + overview ─────────────────────────────────────────────


def test_workspace_overview_is_registered_read_only_and_categorised_as_a_read():
    spec = next(t for t in list_tools() if t.name == "workspace_overview")
    assert spec.read_only is True and spec.min_role == ROLE_VIEWER
    assert category_of("workspace_overview", read_only=True) == "library_read"
    assert resolve_policy(AgentSpec(slug="w", name="W"), "workspace_overview", "library_read", ROLE_VIEWER)[0] == POLICY_ALLOW


def test_workspace_preamble_names_the_rag_and_mentions_only_bound_tools():
    from marvin.services.ai.agents import workspace_preamble

    text = workspace_preamble("Mash & Burn Co.", ["search_content", "get_entry"])
    assert '"Mash & Burn Co." workspace' in text
    assert "the RAG" in text and "knowledge base" in text
    assert "search_content" in text
    assert "workspace_overview" not in text and "find_entries" not in text

    full = workspace_preamble(None, ["workspace_overview", "search_content", "find_entries"])
    assert "this workspace of Marvin" in full
    assert full.index("workspace_overview") < full.index("search_content") < full.index("find_entries")


def test_ask_agent_may_use_the_overview_tool():
    ask = SYSTEM_AGENTS["ask"]
    assert set(ask.tool_allowlist) == {"search_content", "workspace_overview"}


def test_model_agent_prompt_says_what_it_cannot_see_and_where_to_go():
    from marvin.services.ai.agents import model_agent_system_prompt

    text = model_agent_system_prompt("Chat")
    assert "NO tools" in text and "the RAG" in text
    assert "Ask agent" in text and "Marvin agent" in text
    assert "gloomy" not in text and "gloomy" in model_agent_system_prompt("Marvin", gloomy=True)


def test_workspace_preamble_lists_connected_mcp_servers_and_tells_the_agent_to_act():
    from marvin.services.ai.agents import external_servers, workspace_preamble

    names = ["search_content", "mcp__brain__read_note", "mcp__brain__search_vault", "mcp__cloudflare_mcp__docs"]
    assert external_servers(names) == {"brain": 2, "cloudflare_mcp": 1}
    text = workspace_preamble("W", names)
    assert "brain (2 tools, named mcp__brain__*)" in text and "cloudflare_mcp (1 tools" in text
    assert "Act, don't announce" in text
    assert "Connected external sources" not in workspace_preamble("W", ["search_content"])
    assert "Act, don't announce" not in workspace_preamble("W", [])
