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
