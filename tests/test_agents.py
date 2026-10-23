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
    assert SYSTEM_AGENTS["ask"].tool_allowlist == (
        "search_content",
        "get_entry",
        "get_asset",
        "get_resource",
        "workspace_overview",
        "search_docs",
        "read_doc",
        "suggest_agent",
    )
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
    assert [s.slug for s in specs] == ["marvin", "ask", "builder", "chat", "workshop"]


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
    assert resolve_policy(rw, "compose_entry", "entries_author", ROLE_EDITOR) == (POLICY_ASK, "ask first (default)")
    opened = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"entries_author": "allow"})
    assert resolve_policy(opened, "compose_entry", "entries_author", ROLE_EDITOR) == (POLICY_ALLOW, "category policy")


def test_custom_agent_write_categories_default_to_ask_when_writes_are_on_and_block_otherwise():
    on = AgentSpec(slug="w", name="W", allow_writes=True)
    off = AgentSpec(slug="w", name="W")
    for cat in ("entries_author", "entries_archive", "links", "assets_import", "automation_run", "ai_ops", "mcp", "mcp_destructive", "other_write"):
        assert default_policy(on, cat) == POLICY_ASK, cat
        assert default_policy(off, cat) == POLICY_BLOCK, cat
    for cat in ("entries_read", "library_read", "mcp_read", "other_read"):
        assert default_policy(on, cat) == POLICY_ALLOW and default_policy(off, cat) == POLICY_ALLOW, cat


def test_marvin_asks_only_for_outward_writes_and_allows_the_rest():
    marvin = SYSTEM_AGENTS["marvin"]
    for cat in ROUTER_ASK_CATEGORIES:
        assert default_policy(marvin, cat) == POLICY_ASK, cat
    # Switching an automation on or off reaches outside the workspace too (a Slack post, an email, a webhook).
    assert ROUTER_ASK_CATEGORIES == ("automation_run", "automation_manage", "mcp", "mcp_destructive")
    for cat in ("entries_author", "entries_archive", "links", "assets_import", "ai_ops", "other_write"):
        assert default_policy(marvin, cat) == POLICY_ALLOW, cat
    assert resolve_policy(marvin, "compose_entry", "entries_author", ROLE_EDITOR) == (POLICY_ALLOW, "router default")
    assert resolve_policy(marvin, "run_workflow", "automation_run", ROLE_EDITOR) == (POLICY_ASK, "ask first (default)")
    # a workspace agent that happens to be called marvin is not the router
    lookalike = AgentSpec(slug="marvin", name="Marvin", allow_writes=True)
    assert default_policy(lookalike, "entries_author") == POLICY_ASK


def test_role_cap_turns_ask_into_block_below_editor():
    """Agent writes reach any entry, so the floor is EDITOR: an AUTHOR changes only their own drafts."""
    rw = AgentSpec(slug="w", name="W", allow_writes=True)
    for role in (ROLE_VIEWER, ROLE_AUTHOR):
        assert resolve_policy(rw, "compose_entry", "entries_author", role) == (POLICY_BLOCK, "caller role is below EDITOR")
        assert resolve_policy(SYSTEM_AGENTS["marvin"], "run_workflow", "automation_run", role)[0] == POLICY_BLOCK


def test_permission_matrix_reports_ask_as_the_default_and_decision():
    rows = permission_matrix(AgentSpec(slug="w", name="W", allow_writes=True), ROLE_EDITOR, catalog_tools())
    author = next(r for r in rows if r["id"] == "entries_author")
    assert author["default"] == POLICY_ASK and author["override"] is None
    assert {t["decision"] for t in author["tools"]} == {POLICY_ASK}
    assert all(t["reason"] == "ask first (default)" for t in author["tools"])


def test_resolve_policy_never_lets_a_write_through_below_editor():
    rw = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"entries_author": "allow", "compose_entry": "allow"})
    for role in (ROLE_VIEWER, ROLE_AUTHOR):
        decision, why = resolve_policy(rw, "compose_entry", "entries_author", role)
        assert decision == POLICY_BLOCK and "EDITOR" in why


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
    assert author["default"] == POLICY_BLOCK
    assert {t["name"] for t in author["tools"]} == {
        "compose_entry",
        "revise_entry",
        "create_draft",
        "update_draft",
        "propose_playbook_change",
        "add_embed",
    }
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
    assert set(ask.tool_allowlist) == {
        "search_content",
        "get_entry",
        "get_asset",
        "get_resource",
        "workspace_overview",
        "search_docs",
        "read_doc",
        "suggest_agent",
    }
    from marvin.services.ai.tools import get_tool

    assert all(get_tool(name).read_only for name in ask.tool_allowlist)  # Ask never writes
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


def test_list_agents_says_which_agents_can_write_for_this_user():
    """A read-only agent asked for a change refers it to one that canWrite (suggest_agent says so)."""
    from types import SimpleNamespace

    from marvin.db.models.users.roles import WorkspaceRole

    rows = [_row(slug="workshop", name="Workshop", allow_writes=False), _row(slug="editor-bot", name="Editor bot", allow_writes=True)]
    editor = SimpleNamespace(admin=False, workspace_memberships=[SimpleNamespace(group_id="g1", workspace_role=WorkspaceRole.EDITOR)])
    can_write = lambda user: {a["slug"]: a["canWrite"] for a in json.loads(list_agents_tool(_ctx(rows, user=user), {}))["agents"]}  # noqa: E731
    as_editor, as_viewer = can_write(editor), can_write(None)
    assert as_editor["marvin"] is True and as_editor["editor-bot"] is True and as_editor["workshop"] is False
    assert not any(as_viewer.values())  # a viewer can't write through anyone
    from marvin.services.ai.tools import get_tool

    assert "tool" in get_tool("suggest_agent").input_schema["properties"]  # the per-tool match supersedes the bare canWrite hint


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


def test_builder_drafts_only_with_approval_and_never_switches_on_or_runs():
    """Builder (2026-10-10): guided steps first, then a draft the user approves — created switched off."""
    from marvin.services.ai.operations.base import ROLE_ADMIN
    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.categories import category_of

    builder = SYSTEM_AGENTS["builder"]
    assert builder.min_role == ROLE_ADMIN and builder.handoff_hint and "workflow" in builder.handoff_hint
    for name in builder.tool_allowlist:
        assert get_tool(name) is not None, name  # every tool it names exists
    assert not {"run_workflow", "set_automation_enabled"} & set(builder.tool_allowlist)
    for name in ("draft_workflow", "update_workflow_draft"):
        assert resolve_policy(builder, name, category_of(name, read_only=False), ROLE_ADMIN)[0] == POLICY_ASK
    assert resolve_policy(builder, "search_docs", "docs_read", ROLE_ADMIN)[0] == POLICY_ALLOW
    assert "section=editor" in builder.system_prompt and "switched off" in builder.system_prompt


# ── A read-only agent hands the job to one that may do it, with what it found ──────────────────────

from dataclasses import replace as _replace  # noqa: E402

from marvin.services.ai.agents import (  # noqa: E402
    AGENT_SETTINGS_URL,
    HANDOFF_WRITE_RULE,
    agents_that_can,
    clean_handoff_context,
    how_to_allow,
    workspace_preamble,
)

ASSET_A, ASSET_B = "0b0c1d2e-3f40-4152-8364-758697a8b9c0", "11111111-2222-4333-8444-555555555555"


def _editor():
    from marvin.db.models.users.roles import WorkspaceRole

    return SimpleNamespace(admin=False, workspace_memberships=[SimpleNamespace(group_id="g1", workspace_role=WorkspaceRole.EDITOR)])


def _writer_rows(**bot_over):
    """Workshop (read-only, as in the bug) and a writing bot — both with no allowlist, so only writes matter."""
    return [
        _row(slug="workshop", name="Workshop", allow_writes=False, tool_allowlist=None),
        _row(slug="editor-bot", name="Editor bot", allow_writes=True, tool_allowlist=None, **bot_over),
    ]


def test_agents_that_can_match_per_tool_marvin_first_then_allow_before_ask():
    marvin = SYSTEM_AGENTS["marvin"]
    bot = spec_from_row(_row(slug="a-bot", name="A bot", allow_writes=True, tool_allowlist=None))  # writes ask first
    sure = spec_from_row(_row(slug="z-sure", name="Z sure", allow_writes=True, tool_allowlist=None, tool_policy={"links": "allow"}))
    ro = spec_from_row(_row(slug="workshop", name="Workshop", allow_writes=False, tool_allowlist=None))
    off = spec_from_row(_row(slug="off", name="Off", allow_writes=True, tool_allowlist=None, enabled=False))
    cat = category_of("attach_asset", read_only=False)
    found = agents_that_can([ro, bot, sure, off, marvin, SYSTEM_AGENTS["chat"]], "attach_asset", cat, ROLE_EDITOR, "agent")
    assert [(s.slug, d) for s, d in found] == [("marvin", "allow"), ("z-sure", "allow"), ("a-bot", "ask")]
    # a different tool is a different answer: this bot may attach tags but not assets
    picky = spec_from_row(_row(slug="picky", name="Picky", allow_writes=True, tool_allowlist=None, tool_policy={"attach_asset": "block"}))
    assert "picky" not in [s.slug for s, _ in agents_that_can([picky], "attach_asset", cat, ROLE_EDITOR, "agent")]
    assert "picky" in [s.slug for s, _ in agents_that_can([picky], "attach_tag", category_of("attach_tag"), ROLE_EDITOR, "agent")]
    # a tool outside an agent's own list, a role below Editor and a source the agent isn't open to all rule it out
    listed = spec_from_row(_row(slug="listed", name="Listed", allow_writes=True, tool_allowlist=["search_content"]))
    assert agents_that_can([listed], "attach_asset", cat, ROLE_EDITOR, "agent") == []
    assert agents_that_can([marvin], "attach_asset", cat, ROLE_AUTHOR, "agent") == []
    mcp_only = spec_from_row(_row(slug="m", name="M", allow_writes=True, tool_allowlist=None, sources=["mcp"]))
    assert agents_that_can([mcp_only], "attach_asset", cat, ROLE_EDITOR, "agent") == []


def test_suggest_agent_with_a_tool_refers_to_the_agent_that_may_run_it_and_carries_what_was_found():
    ctx = _ctx(_writer_rows(), user=_editor())
    context = {"entry": "bench-note-14", "assetIds": [ASSET_A, ASSET_B, ASSET_A, "not-an-id"], "summary": "two denim shots", "extra": "x"}
    out = json.loads(suggest_agent(ctx, {"agent": "workshop", "tool": "attach_asset", "question": "Attach these", "context": context}))
    assert out["recorded"] is True and out["agent"] == "marvin" and "instead" in out["next"]  # workshop can't, marvin first
    assert ctx.referrals == [
        {
            "agent": "marvin",
            "name": "Marvin",
            "question": "Attach these",
            "reason": "Marvin may run attach_asset for you",
            "tool": "attach_asset",
            "context": {"entry": "bench-note-14", "assetIds": [ASSET_A, ASSET_B], "summary": "two denim shots"},
        }
    ]


def test_suggest_agent_with_a_tool_honours_a_named_agent_that_may_and_needs_no_agent():
    ctx = _ctx(_writer_rows(), user=_editor())
    out = json.loads(suggest_agent(ctx, {"agent": "editor-bot", "tool": "attach_tag", "question": "Tag it"}))
    assert out["agent"] == "editor-bot" and "instead" not in out["next"]
    assert "asks you first" in ctx.referrals[0]["reason"]  # its writes ask first
    ctx = _ctx(_writer_rows(), user=_editor())
    assert json.loads(suggest_agent(ctx, {"tool": "create_draft", "question": "Draft it"}))["agent"] == "marvin"


def test_suggest_agent_with_a_tool_skips_an_agent_whose_matrix_blocks_that_tool(monkeypatch):
    rows = _writer_rows(tool_policy={"links": "allow"})
    marvin_blocked = _replace(SYSTEM_AGENTS["marvin"], tool_policy={"attach_asset": "block"})
    monkeypatch.setattr("marvin.services.ai.agents.list_agents", lambda session, group_id: [marvin_blocked, *(spec_from_row(r) for r in rows)])
    ctx = _ctx(rows, user=_editor())
    out = json.loads(suggest_agent(ctx, {"agent": "marvin", "tool": "attach_asset", "question": "Attach"}))
    assert out["agent"] == "editor-bot"  # marvin is preferred, but this workspace blocked attach_asset for it


def test_suggest_agent_names_the_setting_when_no_agent_may(monkeypatch):
    rows = _writer_rows()
    marvin_off = _replace(SYSTEM_AGENTS["marvin"], tool_policy={"links": "block"})
    bot_off = spec_from_row(_row(slug="editor-bot", name="Editor bot", allow_writes=False, tool_allowlist=None))
    ws = spec_from_row(rows[0])
    monkeypatch.setattr("marvin.services.ai.agents.list_agents", lambda session, group_id: [marvin_off, ws, bot_off])
    ctx = _ctx(rows, user=_editor())
    out = json.loads(suggest_agent(ctx, {"agent": "workshop", "tool": "attach_asset", "question": "Attach"}))
    assert out["recorded"] is False and ctx.referrals == []
    assert "Settings → AI → Agents" in out["blocked"] and AGENT_SETTINGS_URL in out["next"]
    assert "set “Links” to Allow (or Ask first) for Marvin" in out["blocked"]
    assert "turn on Allow writes for Editor bot" in out["blocked"] and "turn on Allow writes for Workshop" in out["blocked"]


def test_how_to_allow_gives_the_role_answer_and_a_fix_per_agent():
    cat = category_of("attach_asset", read_only=False)
    ws = spec_from_row(_row(slug="workshop", name="Workshop", allow_writes=False, tool_allowlist=None))
    assert "Editor role" in how_to_allow([SYSTEM_AGENTS["marvin"], ws], "attach_asset", cat, ROLE_AUTHOR, "agent")
    only_ws = how_to_allow([ws], "attach_asset", cat, ROLE_EDITOR, "agent")
    assert only_ws == "To allow it, in Settings → AI → Agents: turn on Allow writes for Workshop."
    per_tool = spec_from_row(_row(slug="p", name="P", allow_writes=True, tool_allowlist=None, tool_policy={"attach_asset": "block"}))
    assert "set attach_asset to Allow (or Ask first) for P" in how_to_allow([per_tool], "attach_asset", cat, ROLE_EDITOR, "agent")
    off = spec_from_row(_row(slug="o", name="O", allow_writes=True, tool_allowlist=None, enabled=False))
    assert "switch O on" in how_to_allow([off], "attach_asset", cat, ROLE_EDITOR, "agent")
    listed = spec_from_row(_row(slug="l", name="L", allow_writes=True, tool_allowlist=["search_content"]))
    assert "nothing in Settings" in how_to_allow([listed], "attach_asset", cat, ROLE_EDITOR, "agent")


def test_a_viewer_is_told_it_is_the_role_not_an_agent_setting():
    ctx = _ctx(_writer_rows(), user=None)
    out = json.loads(suggest_agent(ctx, {"tool": "attach_asset", "question": "Attach"}))
    assert out["recorded"] is False and "Editor role" in out["blocked"] and ctx.referrals == []


def test_suggest_agent_with_an_unknown_tool_lists_the_write_tools():
    out = json.loads(suggest_agent(_ctx(_writer_rows(), user=_editor()), {"tool": "attach_pictures", "question": "x"}))
    assert "unknown tool 'attach_pictures'" in out["error"] and "attach_asset" in out["error"] and "search_content" not in out["error"]


def test_list_agents_can_say_per_tool_who_may_run_it():
    ctx = _ctx(_writer_rows(), user=_editor())
    by = {a["slug"]: a for a in json.loads(list_agents_tool(ctx, {"tool": "attach_asset"}))["agents"]}
    assert by["marvin"]["canUseTool"] and by["marvin"]["toolPolicy"] == "allow"
    assert by["editor-bot"]["toolPolicy"] == "ask" and by["workshop"]["canUseTool"] is False
    assert "canUseTool" not in json.loads(list_agents_tool(ctx, {}))["agents"][0]
    assert "unknown tool" in json.loads(list_agents_tool(ctx, {"tool": "nope"}))["error"]


def test_the_handoff_context_keeps_only_ids_slugs_and_a_short_note():
    assert clean_handoff_context(None) == {} and clean_handoff_context("x") == {} and clean_handoff_context({"entry": "has space"}) == {}
    many = [f"00000000-0000-4000-8000-{i:012d}" for i in range(30)]
    clean = clean_handoff_context({"entry": " Bench_Note-14 ", "assetIds": many, "summary": "a\n\n b " + "x" * 400, "token": "secret"})
    assert clean["entry"] == "Bench_Note-14" and len(clean["assetIds"]) == 20 and len(clean["summary"]) == 300
    assert set(clean) == {"entry", "assetIds", "summary"} and "\n" not in clean["summary"]
    assert clean_handoff_context({"assetIds": "not a list"}) == {}


def test_a_read_only_agent_is_told_how_to_hand_a_change_over_and_a_writing_one_is_not():
    assert HANDOFF_WRITE_RULE in workspace_preamble("W", ["search_content", "suggest_agent"])
    assert HANDOFF_WRITE_RULE not in workspace_preamble("W", ["search_content", "suggest_agent", "attach_asset"])
    assert HANDOFF_WRITE_RULE not in workspace_preamble("W", ["search_content"])  # nobody to hand it to


def test_check_work_is_off_unless_turned_on():
    """An agent checks its work only when asked (services/ai/work_check.py): off on the wire, on a row without the column
    set, and on every built-in."""
    assert not AgentCreate.model_validate({"slug": "writer2", "name": "W"}).check_work
    assert AgentCreate.model_validate({"slug": "writer2", "name": "W", "checkWork": True}).check_work is True
    assert AgentUpdate.model_validate({}).model_dump(exclude_unset=True) == {}
    assert spec_from_row(_row()).check_work is False and spec_from_row(_row(check_work=True)).check_work is True
    assert not any(s.check_work for s in SYSTEM_AGENTS.values())
