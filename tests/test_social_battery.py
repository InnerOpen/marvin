"""The Social Battery (services/ai/mood.py): a mood meter per character about the person it talks to — the scoring rules,
the guardrails, the line between the Character and the tone, the run's reply, the endpoints, and the workspace switch."""

# ruff: noqa: F811 — fixtures are imported from other tests
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai import mood
from marvin.services.ai import tones as t
from marvin.services.ai.mood import MoodState, effective_settings, message_signals, prompt_line
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import workspace  # noqa: F401 — the fixture (two real users)
from tests.test_playbooks import model  # noqa: F401 — the scripted provider that records system prompts

NOW = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
TREATMENT = effective_settings(None, None)
USE = effective_settings({"drains": "use"}, None)
NAMES = ("Marvin",)


def deltas(text, settings=TREATMENT, state=None, now=NOW):
    return dict(message_signals(text, state or {}, now, settings, NAMES))


# ── the rules ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_unset_choices_take_the_defaults_and_an_agents_own_settings_win():
    assert {k: TREATMENT[k] for k in ("drains", "meter", "memory", "absence")} == {
        "drains": "treatment", "meter": "visible", "memory": "weeks", "absence": "neutral",
    }  # fmt: skip
    own = effective_settings({"drains": "use", "low": {"greetings": ["Hm."]}}, {"meter": "hidden"})
    assert (own["drains"], own["meter"], own["low"]["greetings"]) == ("treatment", "hidden", [])  # the agent's, whole
    assert effective_settings({"drains": "bogus"}, None)["drains"] == "treatment"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("thanks, that's it", {"thanks": 6}),
        ("Perfect, that worked!", {"praise": 6}),
        ("brilliant, thank you", {"thanks_and_praise": 10}),
        ("you're useless", {"insult": -12}),
        ("what a stupid bot", {"insult": -12}),
        ("Marvin, you are hopeless", {"insult": -12}),
        ("shut up and do it", {"insult": -12}),
        ("you are being stupid", {"insult": -12}),
        ("are you dumb or something", {"insult": -12}),
        ("you idiot", {"insult": -12}),
        ("Marvin is such a hopeless bot", {"insult": -12}),
        ("Marvin, you're completely incompetent", {"insult": -12}),
    ],
)
def test_thanks_and_praise_charge_and_rudeness_at_the_assistant_drains(text, expected):
    assert deltas(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "this is useless, the export is broken again",
        "stupid bug, the page still won't load",
        "this doesn't work and I'm getting frustrated",
        "the useless feature deleted my draft",
        "you're wrong, the slug is lowercase",  # a correction, not an insult
        "Can you trash these drafts?",  # "trash" and "garbage" are CMS nouns, not insults
        "can you delete the garbage assets",
        "can you delete the useless drafts?",  # "you", then an insult about the drafts
        "please trash the old entries, you know the ones",
        "do you think this is useless?",
    ],
)
def test_frustration_with_the_problem_never_drains(text):
    assert deltas(text) == {}


def test_use_drains_every_message_treatment_does_not():
    assert deltas("what is the price?", USE) == {"use": -2}
    assert deltas("what is the price?", TREATMENT) == {}


def test_the_same_correction_again_drains_but_a_short_repeat_or_thanks_does_not():
    state = {"texts": [mood._fingerprint("no, put the summary first, not the body"), mood._fingerprint("thanks")]}
    assert deltas("No, put the summary first — not the body", state=state) == {"repeat": -4}
    assert deltas("thanks", state=state) == {"thanks": 6}
    assert deltas("yes", state={"texts": [mood._fingerprint("yes")]}) == {}


def test_rapid_fire_and_a_very_long_session_drain():
    recent = [(NOW - timedelta(seconds=10 * i)).replace(tzinfo=None).isoformat() for i in range(4)]
    assert deltas("and this one", state={"messages": recent}) == {"rapid_fire": -3}
    spread = [(NOW - timedelta(minutes=3 * i)).replace(tzinfo=None).isoformat() for i in range(24)]
    assert deltas("and this one", state={"messages": spread}) == {"long_session": -2}
    assert deltas("and this one", state={"messages": spread[:3]}) == {}


def test_weeks_memory_drifts_toward_the_middle_and_daily_memory_starts_each_day_over():
    last = (NOW - timedelta(days=1)).replace(tzinfo=None)
    assert mood.drifted(90, last, NOW, TREATMENT) == (86, [("drift", -4)])
    assert mood.drifted(10, last, NOW, TREATMENT) == (14, [("drift", 4)])
    assert mood.drifted(90, last, NOW, effective_settings({"memory": "daily"}, None)) == (50, [("new_day", -40)])
    same_day = (NOW - timedelta(hours=2)).replace(tzinfo=None)
    assert mood.drifted(90, same_day, NOW, effective_settings({"memory": "daily"}, None)) == (90, [])
    assert mood.drifted(90, None, NOW, TREATMENT) == (90, [])


def test_a_long_absence_recharges_or_cools_as_the_character_is_set():
    away = (NOW - timedelta(days=5)).replace(tzinfo=None)
    level, signals = mood.drifted(50, away, NOW, effective_settings({"absence": "recharges"}, None))
    assert level == 65 and signals == [("absence", 15)]
    level, signals = mood.drifted(50, away, NOW, effective_settings({"absence": "cools"}, None))
    assert level == 40 and signals == [("absence", -10)]
    assert mood.drifted(50, away, NOW, TREATMENT) == (50, [])
    assert mood.drifted(50, (NOW - timedelta(days=2)).replace(tzinfo=None), NOW, effective_settings({"absence": "cools"}, None)) == (50, [])


def test_bands_and_the_clamp():
    assert [mood.band_of(x) for x in (0, 30, 31, 69, 70, 100)] == ["low", "low", "neutral", "neutral", "high", "high"]
    assert mood._clamp(140) == 100 and mood._clamp(-3) == 0


# ── the prompt line ──────────────────────────────────────────────────────────────────────────────────────────────


def test_the_line_names_the_mood_by_band_and_what_drains_it_and_insists_on_flavour_only():
    low_use = prompt_line(MoodState(20, "low", True, "use"))
    assert low_use.startswith("Mood: drained") and "never the help" in low_use and "never refuse" in low_use
    assert prompt_line(MoodState(20, "low", True, "treatment")).startswith("Mood: cool")
    assert prompt_line(MoodState(80, "high", True, "use")).startswith("Mood: rested")
    assert prompt_line(MoodState(80, "high", True, "treatment")).startswith("Mood: warm")
    assert prompt_line(MoodState(50, "neutral", True, "use")) == "" and prompt_line(None) == ""
    assert "first time in a while" in prompt_line(MoodState(80, "high", True, "use", crossed=True))
    assert "first time" not in prompt_line(MoodState(80, "high", True, "use"))


def test_the_line_sits_between_the_character_and_the_tone_and_goes_where_the_character_goes():
    line = "Mood: warm — a dry compliment is fair."
    auto = t.tone_clause(t.BUILTIN_TONES[0], "A dry butler.", line)
    assert "Character: A dry butler.\n\nMood: warm" in auto
    assert auto.index("Mood:") < auto.index("The character applies ONLY")
    everywhere = t.tone_parts(next(x for x in t.BUILTIN_TONES if x.slug == t.PLAYFUL), "A dry butler.", line)
    assert everywhere.text == everywhere.character + everywhere.mood + everywhere.scope
    professional = t.tone_clause(next(x for x in t.BUILTIN_TONES if x.slug == t.PROFESSIONAL), "A dry butler.", line)
    assert "Mood:" not in professional  # no character, no mood
    assert "Mood:" not in t.tone_clause(t.BUILTIN_TONES[0], "", line)  # no persona at all
    assert t.tone_clause(t.BUILTIN_TONES[0], "A dry butler.", "") == t.tone_clause(t.BUILTIN_TONES[0], "A dry butler.")


# ── the meter, stored ────────────────────────────────────────────────────────────────────────────────────────────


def _settings(db_session, gid, **values):
    row = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).first()
    if row is None:
        row = WorkspaceAISettingsModel(session=db_session, group_id=gid, enabled=True)
        db_session.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    db_session.commit()
    return row


def test_a_message_moves_the_persons_meter_for_that_agent_only_and_a_reset_starts_over(db_session, workspace):
    gid, uid, other = workspace.gid, workspace.uid, workspace.other
    first = mood.score(db_session, gid, uid, "marvin", TREATMENT, "thanks, perfect!", now=NOW)
    assert (first.level, first.band, first.crossed) == (60, "neutral", False)
    assert mood.current(db_session, gid, uid, "scout", TREATMENT, now=NOW).level == 50  # another agent: untouched
    assert mood.current(db_session, gid, other, "marvin", TREATMENT, now=NOW).level == 50  # another person: untouched

    later = mood.score(db_session, gid, uid, "marvin", TREATMENT, "brilliant, thanks", now=NOW + timedelta(minutes=1))
    assert (later.level, later.band, later.crossed) == (70, "high", True)  # the first message in a new band
    again = mood.score(db_session, gid, uid, "marvin", TREATMENT, "thank you", now=NOW + timedelta(minutes=2))
    assert (again.level, again.crossed) == (76, False)

    mood.reset(db_session, gid, uid, "marvin", now=NOW + timedelta(minutes=3))
    assert mood.current(db_session, gid, uid, "marvin", TREATMENT, now=NOW + timedelta(minutes=3)).level == 50
    mood.reset(db_session, gid, uid, "never-talked-to")  # a meter that never existed: nothing to do, no error


def test_current_counts_time_without_writing(db_session, workspace):
    gid, uid = workspace.gid, workspace.uid
    mood.score(db_session, gid, uid, "marvin", TREATMENT, "you're useless", now=NOW)
    week_later = NOW + timedelta(days=7)
    drifted = mood.current(db_session, gid, uid, "marvin", TREATMENT, now=week_later).level
    assert 38 < drifted < 50 and drifted == mood.current(db_session, gid, uid, "marvin", TREATMENT, now=week_later).level
    assert mood.current(db_session, gid, uid, "marvin", effective_settings({"meter": "hidden"}, None), now=NOW).public()["level"] is None


# ── the run and the endpoints ────────────────────────────────────────────────────────────────────────────────────


def _say(workspace, text, *, source="agent", user_id=None, role=WorkspaceRole.AUTHOR) -> dict:
    res = gates._sign_in(workspace, role, user_id=user_id).post("/api/ai/agent", json={"message": text, "source": source})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_run_scores_the_message_tells_the_model_the_mood_and_carries_it_back(db_session, workspace, model):
    _settings(db_session, workspace.gid, mood_enabled=True, persona_prompt="A dry butler.", mood={"drains": "use"})
    for _ in range(8):
        mood.score(db_session, workspace.gid, workspace.uid, "marvin", USE, "you're useless", now=NOW)

    out = _say(workspace, "where are my drafts?")

    assert out["mood"] == {"level": 0, "band": "low", "visible": True}
    system = model.systems[-1]
    assert "Character: A dry butler.\n\nMood: drained" in system and system.index("Mood:") < system.index("The character applies")


def test_a_hidden_meter_keeps_the_number_to_itself(db_session, workspace, model):
    _settings(db_session, workspace.gid, mood_enabled=True, persona_prompt="A dry butler.", mood={"meter": "hidden"})
    assert _say(workspace, "thanks!")["mood"] == {"level": None, "band": "neutral", "visible": False}


def test_off_by_default_and_never_for_automations_or_assistants(db_session, workspace, model):
    _settings(db_session, workspace.gid, persona_prompt="A dry butler.")  # mood_enabled stays False
    assert "mood" not in _say(workspace, "thanks!") and "Mood:" not in model.systems[-1]
    _settings(db_session, workspace.gid, mood_enabled=True)
    for source in ("api", "mcp"):
        assert "mood" not in _say(workspace, "thanks!", source=source)
    assert mood.current(db_session, workspace.gid, workspace.uid, "marvin", TREATMENT).level == 50  # nothing scored


def test_the_endpoints_read_and_reset_the_callers_own_meter(db_session, workspace, model):
    client = gates._sign_in(workspace, WorkspaceRole.VIEWER)
    assert client.get("/api/ai/mood").json() == {"agent": "marvin", "enabled": False, "level": None, "band": None, "visible": True}

    _settings(db_session, workspace.gid, mood_enabled=True, persona_prompt="A dry butler.")
    _say(workspace, "brilliant, thanks")
    assert client.get("/api/ai/mood", params={"agent": "marvin"}).json() == {
        "agent": "marvin", "enabled": True, "level": 60, "band": "neutral", "visible": True,
    }  # fmt: skip
    other = gates._sign_in(workspace, WorkspaceRole.VIEWER, user_id=workspace.other)
    assert other.get("/api/ai/mood").json()["level"] == 50  # their own meter

    assert client.post("/api/ai/mood/reset", json={"agent": "marvin"}).json()["level"] == 50
    assert client.get("/api/ai/mood", params={"agent": "no-such-agent"}).status_code == 404


def test_the_settings_say_whether_it_is_on_and_each_agents_mood_travels_with_its_voice(db_session, workspace):
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    admin = gates._sign_in(workspace, WorkspaceRole.ADMIN)
    assert admin.get("/api/groups/ai-settings").json()["moodEnabled"] is False
    assert admin.patch("/api/groups/ai-settings", json={"moodEnabled": True}).json()["moodEnabled"] is True
    row = WorkspaceAgentModel(
        session=db_session, group_id=workspace.gid, slug="scout", name="Scout", mood={"meter": "hidden", "low": {"greetings": ["Mm-hmm."]}}
    )
    db_session.add(row)
    db_session.commit()
    try:
        voices = admin.get("/api/groups/ai-settings").json()["agentVoices"]
        assert voices["scout"]["mood"]["meter"] == "hidden" and voices["scout"]["mood"]["low"]["greetings"] == ["Mm-hmm."]
    finally:
        db_session.delete(row)
        db_session.commit()


def test_the_migration_has_the_table_and_the_switch(db_session):
    import sqlalchemy as sa

    insp = sa.inspect(db_session.get_bind())
    assert {c["name"] for c in insp.get_columns("ai_mood_meters")} >= {"group_id", "user_id", "agent_slug", "level", "state", "band_since"}
    assert "mood_enabled" in {c["name"] for c in insp.get_columns("workspace_ai_settings")}
    assert uuid.UUID(int=0)  # the table's ids are GUIDs like the rest
