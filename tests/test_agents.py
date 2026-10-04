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
        AgentCreate(slug="a1", name="a", default_register="not a tone slug!")  # an unknown-but-valid slug is a 422 on save
    with pytest.raises(ValidationError):
        AgentCreate(slug="a1", name="a", sources=["editor", "carrier-pigeon"])
    ok = AgentCreate(slug="a1", name="a", sources=["editor", "editor", "mcp"], tool_allowlist=[" x ", "", "x"])
    assert ok.sources == ["editor", "mcp"]
    assert ok.tool_allowlist == ["x"]


def test_agent_update_is_fully_optional_but_still_validated():
    assert AgentUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        AgentUpdate(default_register="loud noises!")


def test_agent_read_marks_system_agents_without_an_id():
    r = AgentRead(slug="ask", name="Ask", is_system=True)
    assert r.id is None and r.model_dump(by_alias=True)["isSystem"] is True


# ── System agents + resolution ───────────────────────────────────────────────


def test_system_agents_match_the_reserved_slugs_and_shapes():
    assert tuple(SYSTEM_AGENTS) == SYSTEM_AGENT_SLUGS
    assert SYSTEM_AGENTS["marvin"].tool_allowlist is None  # everything the role allows
    assert SYSTEM_AGENTS["ask"].tool_allowlist == ("search_content", "workspace_overview", "search_docs", "read_doc", "suggest_agent")
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
    POLICY_ASK,
    POLICY_BLOCK,
    ROUTER_ASK_CATEGORIES,
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
    # and the mapping only names known categories, with read/write agreeing with the registry flag.
    # run_agent is the one documented exception: for the matrix a hand-off is not a write (the child's
    # tools are already capped by the caller's role), while the MCP projection still flags it as
    # non-read-only because the child run may author.
    for t in list_tools():
        cat = CATEGORY_BY_TOOL.get(t.name)
        if cat and t.name != "run_agent":
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
    rw = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"mcp_destructive": "block", "mcp": "allow"})
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
    # writes on → every write category asks first by default; the matrix turns it to allow per row/tool
    rw = AgentSpec(slug="w", name="W", allow_writes=True)
    assert resolve_policy(rw, "compose_entry", "entries_author", ROLE_AUTHOR) == (POLICY_ASK, "ask first (default)")
    opened = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"entries_author": "allow"})
    assert resolve_policy(opened, "compose_entry", "entries_author", ROLE_AUTHOR) == (POLICY_ALLOW, "category policy")


def test_custom_agent_write_categories_default_to_ask_when_writes_are_on_and_block_otherwise():
    on = AgentSpec(slug="w", name="W", allow_writes=True)
    off = AgentSpec(slug="w", name="W")
    for cat in ("entries_author", "links", "assets_import", "automation_run", "ai_ops", "mcp", "mcp_destructive", "other_write"):
        assert default_policy(on, cat) == POLICY_ASK, cat
        assert default_policy(off, cat) == POLICY_BLOCK, cat
    for cat in ("entries_read", "library_read", "mcp_read", "other_read"):
        assert default_policy(on, cat) == POLICY_ALLOW and default_policy(off, cat) == POLICY_ALLOW, cat


def test_marvin_asks_only_for_outward_writes_and_allows_the_rest():
    marvin = SYSTEM_AGENTS["marvin"]
    for cat in ROUTER_ASK_CATEGORIES:
        assert default_policy(marvin, cat) == POLICY_ASK, cat
    assert ROUTER_ASK_CATEGORIES == ("automation_run", "mcp", "mcp_destructive")
    for cat in ("entries_author", "links", "assets_import", "ai_ops", "other_write"):
        assert default_policy(marvin, cat) == POLICY_ALLOW, cat
    assert resolve_policy(marvin, "compose_entry", "entries_author", ROLE_AUTHOR) == (POLICY_ALLOW, "router default")
    assert resolve_policy(marvin, "run_workflow", "automation_run", ROLE_AUTHOR) == (POLICY_ASK, "ask first (default)")
    # a workspace agent that happens to be called marvin is not the router
    lookalike = AgentSpec(slug="marvin", name="Marvin", allow_writes=True)
    assert default_policy(lookalike, "entries_author") == POLICY_ASK


def test_role_cap_turns_ask_into_block_below_author():
    rw = AgentSpec(slug="w", name="W", allow_writes=True)
    assert resolve_policy(rw, "compose_entry", "entries_author", ROLE_VIEWER) == (POLICY_BLOCK, "caller role is below AUTHOR")
    assert resolve_policy(SYSTEM_AGENTS["marvin"], "run_workflow", "automation_run", ROLE_VIEWER)[0] == POLICY_BLOCK


def test_permission_matrix_reports_ask_as_the_default_and_decision():
    rows = permission_matrix(AgentSpec(slug="w", name="W", allow_writes=True), ROLE_AUTHOR, catalog_tools())
    author = next(r for r in rows if r["id"] == "entries_author")
    assert author["default"] == POLICY_ASK and author["override"] is None
    assert {t["decision"] for t in author["tools"]} == {POLICY_ASK}
    assert all(t["reason"] == "ask first (default)" for t in author["tools"])


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


def test_preamble_tells_agents_to_keep_workspace_paths_relative():
    from marvin.services.ai.agents import LINKS_RULE, workspace_preamble

    assert LINKS_RULE in workspace_preamble("W", ["compose_entry"])
    assert "/workspace/entries/<id>" in LINKS_RULE and "Never prepend a hostname" in LINKS_RULE
    assert LINKS_RULE not in workspace_preamble("W", [])  # nothing bound → no tool results to link


def test_ask_agent_may_use_the_overview_tool():
    ask = SYSTEM_AGENTS["ask"]
    assert set(ask.tool_allowlist) == {"search_content", "workspace_overview", "search_docs", "read_doc", "suggest_agent"}
    # it may refer (a no-op) but never hand off
    assert resolve_policy(ask, "suggest_agent", "agents_read", ROLE_VIEWER)[0] == POLICY_ALLOW
    assert resolve_policy(ask, "run_agent", "agents_run", ROLE_VIEWER)[0] == POLICY_BLOCK


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


# ── Slice D: hand-offs + referrals ───────────────────────────────────────────

from marvin.services.ai.agents import HANDOFF_RULES, REFERRAL_RULES, default_policy, roster_block  # noqa: E402
from marvin.services.ai.tools import ToolContext  # noqa: E402
from marvin.services.ai.tools.builtins_agents import list_agents as list_agents_tool  # noqa: E402
from marvin.services.ai.tools.builtins_agents import run_agent as run_agent_tool  # noqa: E402
from marvin.services.ai.tools.builtins_agents import suggest_agent  # noqa: E402


def test_agents_run_defaults_allow_for_marvin_and_block_for_everyone_else():
    assert default_policy(SYSTEM_AGENTS["marvin"], "agents_run") == POLICY_ALLOW
    assert default_policy(SYSTEM_AGENTS["ask"], "agents_run") == POLICY_BLOCK
    custom = spec_from_row(_row(tool_allowlist=None, allow_writes=True))
    assert default_policy(custom, "agents_run") == POLICY_BLOCK  # allow_writes does not open hand-offs
    assert resolve_policy(SYSTEM_AGENTS["marvin"], "run_agent", "agents_run", ROLE_VIEWER) == (POLICY_ALLOW, "router default")
    decision, reason = resolve_policy(custom, "run_agent", "agents_run", ROLE_AUTHOR)
    assert decision == POLICY_BLOCK and reason == "hand-offs are off unless allowed"
    # a VIEWER talking to marvin can still be routed: a hand-off is not a write
    assert resolve_policy(SYSTEM_AGENTS["marvin"], "run_agent", "agents_run", ROLE_VIEWER)[0] == POLICY_ALLOW


def test_agents_run_can_be_opened_explicitly_by_category_or_tool():
    by_cat = spec_from_row(_row(tool_allowlist=None, tool_policy={"agents_run": "allow"}))
    assert resolve_policy(by_cat, "run_agent", "agents_run", ROLE_VIEWER) == (POLICY_ALLOW, "category policy")
    by_tool = spec_from_row(_row(tool_allowlist=None, tool_policy={"run_agent": "allow"}))
    assert resolve_policy(by_tool, "run_agent", "agents_run", ROLE_VIEWER) == (POLICY_ALLOW, "tool policy")


def test_handoff_hint_rides_on_rows_schemas_and_the_system_ask_agent():
    assert spec_from_row(_row(handoff_hint="materials and stock")).handoff_hint == "materials and stock"
    assert spec_from_row(_row()).handoff_hint is None
    assert SYSTEM_AGENTS["ask"].handoff_hint and "citations" in SYSTEM_AGENTS["ask"].handoff_hint
    assert AgentCreate(slug="m1", name="M", handoff_hint="x" * 300).handoff_hint == "x" * 300
    with pytest.raises(ValidationError):
        AgentCreate(slug="m1", name="M", handoff_hint="x" * 301)
    with pytest.raises(ValidationError):
        AgentUpdate(handoff_hint="x" * 301)


def _specs():
    materials = spec_from_row(_row(slug="materials", name="Materials", description="Stock and suppliers.", handoff_hint="it is about stock"))
    private = spec_from_row(_row(slug="private", name="Private", min_role=ROLE_EDITOR))
    mcp_only = spec_from_row(_row(slug="mcp-only", name="MCP only", sources=["mcp"]))
    return [*SYSTEM_AGENTS.values(), materials, private, mcp_only]


def test_roster_block_lists_only_who_the_caller_may_talk_to_and_skips_router_chat_and_self():
    block = roster_block(_specs(), "marvin", ROLE_VIEWER)
    assert "- materials — Materials: Stock and suppliers. Hand off when: it is about stock." in block
    assert "- ask — Ask:" in block
    for absent in ("- marvin", "- chat", "- private", "- mcp-only"):
        assert absent not in block
    assert HANDOFF_RULES in block and REFERRAL_RULES not in block
    # the running specialist is excluded and gets the referral rules instead
    block = roster_block(_specs(), "materials", ROLE_EDITOR, can_handoff=False)
    assert "- materials" not in block and "- private — Private" in block
    assert REFERRAL_RULES in block and HANDOFF_RULES not in block


def test_roster_block_is_empty_when_there_is_nobody_to_list():
    assert roster_block([SYSTEM_AGENTS["marvin"], SYSTEM_AGENTS["chat"]], "marvin", ROLE_VIEWER) == ""
    assert roster_block([SYSTEM_AGENTS["marvin"], SYSTEM_AGENTS["chat"]], "ask", ROLE_VIEWER, can_handoff=False) == ""


def _ctx(rows, **over):
    base = {"session": _session_with(rows), "group_id": "g1", "user": None, "source": "agent"}
    base.update(over)
    return ToolContext(**base)


def test_suggest_agent_records_a_referral_and_tells_the_model_to_finish():
    ctx = _ctx([_row(slug="materials", name="Materials")])
    out = json.loads(suggest_agent(ctx, {"agent": "materials", "question": "q" * 600, "reason": "r" * 400}))
    assert out["recorded"] is True and out["agent"] == "materials" and "Do NOT call" in out["next"]
    assert ctx.referrals == [{"agent": "materials", "name": "Materials", "question": "q" * 500, "reason": "r" * 300}]


def test_suggest_agent_rejects_unknown_and_disabled_agents():
    ctx = _ctx([])
    assert "unknown agent" in json.loads(suggest_agent(ctx, {"agent": "ghost", "question": "q"}))["error"]
    ctx = _ctx([_row(slug="off", name="Off", enabled=False)])
    assert "disabled" in json.loads(suggest_agent(ctx, {"agent": "off", "question": "q"}))["error"]
    assert ctx.referrals == []


def test_run_agent_prefers_the_controllers_delegate_when_set():
    seen = []

    def delegate(slug, message, max_steps):
        seen.append((slug, message, max_steps))
        return {"agent": slug, "answer": "42"}

    ctx = _ctx([], delegate=delegate)
    out = json.loads(run_agent_tool(ctx, {"agent": "materials", "message": "  stock?  ", "max_steps": 3}))
    assert out == {"agent": "materials", "answer": "42"}
    assert seen == [("materials", "stock?", 3)]


def test_list_agents_tool_gates_can_run_on_the_context_source():
    rows = [_row(slug="mcp-only", name="MCP only", sources=["mcp"])]
    from_agent = json.loads(list_agents_tool(_ctx(rows, source="agent"), {}))
    from_mcp = json.loads(list_agents_tool(_ctx(rows, source=None), {}))  # None → the pre-slice-D "mcp" fallback
    by_slug = lambda res: {a["slug"]: a["canRun"] for a in res["agents"]}  # noqa: E731
    assert by_slug(from_agent)["mcp-only"] is False and by_slug(from_mcp)["mcp-only"] is True


def test_run_agent_and_suggest_agent_are_bound_for_the_agent_source_but_not_chained():
    from marvin.services.ai.tools import get_tool

    assert "agent" in get_tool("run_agent").sources and "agent" in get_tool("suggest_agent").sources
    assert get_tool("suggest_agent").read_only is True
    assert category_of("suggest_agent") == "agents_read" and category_of("run_agent") == "agents_run"
    assert CATEGORY_BY_ID["agents_run"].writes is False


def test_preamble_has_the_tagging_rule_only_when_tags_can_be_attached():
    from marvin.services.ai.agents import TAGGING_RULE, workspace_preamble

    assert TAGGING_RULE in workspace_preamble("W", ["attach_tag", "list_tags"])
    assert TAGGING_RULE not in workspace_preamble("W", ["search_content"])
    assert "never apply the tag vocabulary" in TAGGING_RULE
