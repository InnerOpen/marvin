"""Workspace agents: schema contract, system agents, allowlist filtering, and run gates.

Pure-level tests (no DB, no network) for services/ai/agents.py and schemas/group/agent.py.
"""

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
    assert SYSTEM_AGENTS["ask"].tool_allowlist == ("search_content",)
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


def test_category_of_falls_back_sensibly():
    assert category_of("mcp__n8n__send_telegram") == "mcp"
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
    assert "entries_read" in ids and "entries_author" in ids and "ai_ops" in ids and "mcp" in ids
    entries = next(r for r in rows if r["id"] == "entries_read")
    assert entries["default"] == POLICY_ALLOW and all(t["decision"] == POLICY_ALLOW for t in entries["tools"])
    author = next(r for r in rows if r["id"] == "entries_author")
    assert author["default"] == POLICY_BLOCK and {t["name"] for t in author["tools"]} == {"compose_entry", "revise_entry"}
    assert next(r for r in rows if r["id"] == "mcp")["tools"] == []


def test_schema_validates_policy_values_and_suggestions():
    ok = AgentCreate(slug="w2", name="w", tool_policy={"links": "block"}, icon="🧵", suggestions=["What's on the bench?"])
    assert ok.tool_policy == {"links": "block"} and ok.suggestions == ["What's on the bench?"]
    with pytest.raises(ValidationError):
        AgentCreate(slug="w2", name="w", tool_policy={"links": "ask"})  # ask-first is v2
    with pytest.raises(ValidationError):
        AgentCreate(slug="w2", name="w", suggestions=[str(i) for i in range(9)])
