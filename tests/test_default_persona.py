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
