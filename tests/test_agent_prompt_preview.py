"""An agent's prompt preview (POST /ai/agents/{slug}/preview-prompt, and /ai/agents/preview-prompt for one not saved yet).

The Agents page's **Preview prompt** shows what a run of the agent actually sends: the workspace preamble, the
agent's instructions (or its kind's default), the Character and tone with the rule for which wins, and who it
may hand off to — assembled by the same helpers as a run, from the Edit form's unsaved values. Tools are only
counted, and nothing reaches a model.
"""

import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.agent import AgentCreate, AgentDefinitionPreviewRequest
from marvin.services.ai.tones import PRECEDENCE_RULE

C = oc.AIOperationsController
WARM = {"slug": "warm", "name": "Warm", "instructions": "Write warmly.", "persona": "frame"}
REAL = (
    "_agent_or_404",
    "_persona",
    "_tones",
    "_effective_register",
    "_named_agent_instructions",
    "_register_clause",
    "_bind_agent_tools",
    "_system_frame",
    "_require_role",
    "_workspace_name",
    "_external_mcp_tools",
    "_require_preview_role",
    "_prompt_preview",
    "_require_known_tone",
    "_agent_character",
)


@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"Preview {gid.hex[:8]}", slug=f"preview-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, assistant_name="Ada", persona_prompt="You are Ada.", tones=[WARM]))
    db_session.add(WorkspaceAgentModel(session=db_session, group_id=gid, slug="scout", name="Scout", system_prompt="Scout the bench."))
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(WorkspaceAgentModel).filter_by(group_id=gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def ctrl(db_session, workspace, monkeypatch):
    """The agents controller's real prompt code on a stand-in, as a workspace admin; any provider lookup fails."""
    from marvin.services.ai import factory
    from marvin.services.ai.operations.base import ROLE_ADMIN

    def no_provider(*a, **k):
        raise AssertionError("a prompt preview must not reach a provider")

    monkeypatch.setattr(factory, "get_workspace_ai_provider", no_provider)
    c = SimpleNamespace(session=db_session, group_id=workspace, user=SimpleNamespace(id=None, admin=False), logger=logging.getLogger("test"))
    for name in REAL:
        setattr(c, name, getattr(C, name).__get__(c))
    static = ("_agent_with_overrides", "_agent_read", "_default_agent_system_prompt", "_framed")
    static += ("_handoff_max_depth", "_restrict_tools", "_tool_categories")
    for name in static:
        setattr(c, name, getattr(C, name))
    c.role = ROLE_ADMIN
    c._user_role = lambda: c.role
    c.execute_operation = lambda *a, **k: pytest.fail("a prompt preview must not run an AI operation")
    c.preview = lambda slug, **kw: C.preview_agent_prompt(c, slug, _request(**kw))
    c.preview_new = lambda **kw: C.preview_new_agent_prompt(c, AgentDefinitionPreviewRequest(**kw))
    return c


def _request(**kw):
    from marvin.schemas.group.agent import AgentPromptPreviewRequest

    return AgentPromptPreviewRequest(**kw)


def _set_workspace_default(db_session, gid, slug):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).one().default_register = slug
    db_session.commit()


def test_preview_is_the_preamble_then_the_agents_instructions_then_the_tone_section(ctrl):
    out = ctrl.preview("scout")
    assert out.instructions == "Scout the bench." and not out.default_instructions
    assert out.workspace.startswith('You are working inside the "Preview ')
    expected = f"{out.workspace}\n\n{out.instructions}{out.tone.clause}"
    assert out.system == (f"{expected}\n\n{out.roster}" if out.roster else expected)
    assert out.tokens > 0 and out.kind == "persona"


def test_preview_uses_the_forms_unsaved_instructions_and_leaves_the_agent_alone(ctrl, db_session, workspace):
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    assert ctrl.preview("scout", system_prompt="Draft instructions.").instructions == "Draft instructions."
    assert db_session.query(WorkspaceAgentModel).filter_by(group_id=workspace, slug="scout").one().system_prompt == "Scout the bench."


def test_preview_of_cleared_instructions_is_the_default_the_run_would_use(ctrl):
    out = ctrl.preview("scout", system_prompt=None, name="Bench")
    assert out.default_instructions
    assert out.instructions == C._default_agent_system_prompt("Bench")


def test_preview_tone_is_the_agents_default_and_carries_the_precedence_rule(ctrl):
    out = ctrl.preview("scout", default_register="warm")
    assert (out.tone_source, out.tone.tone_slug) == ("agent", "warm")
    assert out.tone.character == "Character: You are Ada."
    assert out.tone.rule == PRECEDENCE_RULE
    assert "Tone (Warm): Write warmly." in out.system and out.system.count(PRECEDENCE_RULE) == 1


def test_preview_tone_falls_back_to_the_workspace_default(ctrl, db_session, workspace):
    _set_workspace_default(db_session, workspace, "playful")
    for over in ({}, {"default_register": None}, {"default_register": "deleted-tone"}):
        out = ctrl.preview("scout", **over)
        assert (out.tone_source, out.tone.tone_slug) == ("workspace", "playful"), over


def test_preview_under_a_drop_tone_has_no_character(ctrl):
    out = ctrl.preview("scout", default_register="professional")
    assert out.tone.character == "" and out.tone.rule == ""
    assert "Character:" not in out.system and "You are Ada." not in out.system


def test_preview_of_a_model_agent_has_no_preamble_or_tools(ctrl):
    out = ctrl.preview("scout", kind="model", system_prompt=None)
    assert (out.workspace, out.roster, out.tool_count, out.tool_categories) == ("", "", 0, [])
    assert "You have NO tools" in out.instructions
    assert out.system == out.instructions + out.tone.clause


def test_preview_counts_tools_per_category_and_writes_follow_the_form(ctrl):
    read_only = ctrl.preview("scout", allow_writes=False)
    assert read_only.tool_count == sum(c.count for c in read_only.tool_categories) > 0
    assert "entries_author" not in {c.id for c in read_only.tool_categories}
    writes = ctrl.preview("scout", allow_writes=True)
    assert writes.ask_first_count > 0  # a custom agent's write groups ask first
    assert writes.tool_count > read_only.tool_count


def test_preview_of_the_main_agent_includes_its_hand_off_roster(ctrl):
    out = ctrl.preview("marvin")
    assert out.instructions == C._default_agent_system_prompt("Ada")  # the assistant name, not "Marvin"
    assert "scout" in out.roster and out.system.endswith(out.roster)


def test_preview_requires_a_workspace_admin(ctrl):
    ctrl.role = 3  # EDITOR
    with pytest.raises(HTTPException) as e:
        ctrl.preview("scout")
    assert e.value.status_code == 403


def test_preview_of_an_unknown_agent_is_404(ctrl):
    with pytest.raises(HTTPException) as e:
        ctrl.preview("ghost")
    assert e.value.status_code == 404


def test_preview_matches_the_system_prompt_a_run_sends(ctrl, monkeypatch):
    """The run path builds its prompt with the same helpers: what it hands the loop is what the preview shows."""
    from marvin.schemas.group.ai_execution import AIAgentRequest

    seen = {}
    ctrl._agent_provider = lambda: SimpleNamespace(provider_type="openai")
    ctrl._default_model = lambda: "m"
    ctrl._check_budget = lambda: None
    ctrl._check_invocation_source = lambda source, allowed: source
    ctrl._require_tool_capable = lambda *a: None
    ctrl._resolve_entity_id = lambda *a: None
    ctrl._agent_max_steps = lambda body: 4

    def capture(**kw):
        names = {t.name for t in kw["tools"]}
        seen["system"] = C._framed(kw["system"], *ctrl._system_frame(names, kw["agent_slug"]))
        return {}

    ctrl._run_agent_core = capture
    C.run_named_agent(ctrl, "scout", AIAgentRequest.model_validate({"message": "hi", "source": "agent", "threadId": "new"}))
    assert seen["system"] == ctrl.preview("scout").system


def test_preview_route_is_registered_under_the_agents():
    assert any(getattr(r, "path", "") == "/ai/agents/{slug}/preview-prompt" for r in oc.router.routes)


# ── An agent not saved yet (the New form) ──

NEW_AGENTS = (
    {
        "slug": "critic",
        "name": "Critic",
        "system_prompt": "Review drafts.",
        "default_register": "warm",
        "allow_writes": True,
        "tool_policy": {"entries_author": "block"},
    },
    {"slug": "helper", "name": "Helper", "kind": "model"},
    {"slug": "plain", "name": "Plain"},
)


@pytest.mark.parametrize("definition", NEW_AGENTS, ids=lambda d: d["slug"])
def test_new_agent_preview_matches_the_preview_once_saved_with_the_same_values(ctrl, definition):
    before = ctrl.preview_new(**definition)
    C.create_agent(ctrl, AgentCreate(**definition))
    assert before == ctrl.preview(definition["slug"])


def test_new_agent_preview_keeps_the_agent_off_its_own_roster_and_stores_nothing(ctrl, db_session, workspace):
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    out = ctrl.preview_new(slug="scout-two", name="Scout Two", system_prompt="Help.")
    assert out.instructions == "Help." and "scout-two" not in out.roster
    assert db_session.query(WorkspaceAgentModel).filter_by(group_id=workspace, slug="scout-two").first() is None


def test_new_agent_preview_without_a_slug_yet_uses_the_default_instructions(ctrl):
    out = ctrl.preview_new(name="Drafty")
    assert out.default_instructions and out.instructions == C._default_agent_system_prompt("Drafty")


def test_new_agent_preview_requires_a_workspace_admin(ctrl):
    ctrl.role = 3  # EDITOR
    with pytest.raises(HTTPException) as e:
        ctrl.preview_new(name="Critic")
    assert e.value.status_code == 403


def test_new_agent_preview_never_reaches_a_provider(ctrl):
    ctrl._agent_provider = lambda: pytest.fail("a prompt preview must not look up a provider")
    ctrl._default_model = lambda: pytest.fail("a prompt preview must not pick a model")
    assert ctrl.preview_new(name="Critic", allow_writes=True).tool_count > 0


def test_new_agent_preview_route_is_registered_beside_the_agents():
    assert any(getattr(r, "path", "") == "/ai/agents/preview-prompt" and "POST" in r.methods for r in oc.router.routes)
