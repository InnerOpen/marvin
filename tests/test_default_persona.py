"""Blank persona means Marvin's built-in voice — what the AI settings page promises ("Leave blank for
the default voice"). It used to mean no voice at all, so the bubble greeted in character and then
answered in a neutral one."""

from marvin.services.ai.persona import DEFAULT_PERSONA_PROMPT, resolve_persona


def test_blank_settings_get_marvins_voice():
    assert resolve_persona(None, None) == ("Marvin", DEFAULT_PERSONA_PROMPT)


def test_a_workspace_persona_replaces_the_default():
    assert resolve_persona(None, "Warm and upbeat; a leathercraft studio's helper.") == (
        "Marvin",
        "Warm and upbeat; a leathercraft studio's helper.",
    )


def test_a_renamed_assistant_with_no_persona_gets_a_neutral_voice():
    # "Ada" shouldn't be told she is Marvin.
    assert resolve_persona("Ada", "") == ("Ada", "")


def test_whitespace_counts_as_blank():
    assert resolve_persona("  ", "   ") == ("Marvin", DEFAULT_PERSONA_PROMPT)


def test_the_default_voice_frames_but_never_hides_the_help():
    assert "helpful" in DEFAULT_PERSONA_PROMPT and "never actually mean" in DEFAULT_PERSONA_PROMPT


# --- the bubble icon -------------------------------------------------------------------------------

import pytest  # noqa: E402

from marvin.services.ai.persona import icon_problem  # noqa: E402


@pytest.mark.parametrize("icon", [None, "", "🦉", "✨🎨", "https://api.iwobble.com/assets/x/owl.png", "/assets/owl.png"])
def test_an_emoji_or_an_image_url_is_a_valid_icon(icon):
    assert icon_problem(icon) is None


@pytest.mark.parametrize("icon", ["a very long name that is not an emoji", "https://example.com/has space.png"])
def test_long_text_or_a_broken_url_is_refused(icon):
    assert icon_problem(icon)


def test_saving_a_bad_icon_is_refused():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from marvin.routes.groups.ai_settings_controller import AISettingsController
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    ctrl = SimpleNamespace(_require_admin=lambda: None, _allow_workspace_credentials=lambda: True)
    with pytest.raises(HTTPException) as exc:
        AISettingsController.update_ai_settings(ctrl, WorkspaceAISettingsUpdate(assistant_icon="not an emoji at all, clearly"))
    assert exc.value.status_code == 422


# --- the main agent carries the workspace's assistant name ------------------------------------------
# Regression: renaming the assistant in AI settings left the Ask page's agent dropdown (and the bubble's
# /agents list, MCP list_agents, hand-offs) saying "Marvin" — the system agent's name was a constant.


@pytest.fixture
def named_workspace(db_session):
    import uuid

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"nm-{gid.hex[:8]}", slug=f"nm-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, assistant_name="Ada"))
    db_session.commit()
    yield gid
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def test_the_main_agent_is_listed_under_the_workspace_name(db_session, named_workspace):
    from marvin.services.ai.agents import list_agents, resolve_agent

    names = {a.slug: a.name for a in list_agents(db_session, named_workspace)}
    assert names["marvin"] == "Ada" and names["ask"] == "Ask"
    assert resolve_agent(db_session, named_workspace, "marvin").name == "Ada"


def test_without_a_name_the_main_agent_is_marvin(db_session):
    import uuid

    from marvin.services.ai.agents import resolve_agent

    assert resolve_agent(db_session, uuid.uuid4(), "marvin").name == "Marvin"


def test_the_chat_agent_points_to_the_main_agent_by_its_name():
    from marvin.services.ai.agents import model_agent_system_prompt

    assert "the Ada agent (full tools)" in model_agent_system_prompt("Ada", router_name="Ada")
