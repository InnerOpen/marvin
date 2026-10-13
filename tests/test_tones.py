"""Custom tones (services/ai/tones.py, /groups/ai-settings/tones).

A workspace names its own tones — instructions plus a persona rule (frame / everywhere / drop) — next to
the built-ins auto / professional / playful. The persona is labelled "Character:" (who the assistant is),
the tone "Tone (<name>):" (how it delivers), and when both apply a precedence rule says the tone wins on
formality, length and mood. The golden tests below pin the exact wording; an unknown slug never fails a
run, and a tone agents depend on can't be deleted out from under them.
"""

import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.services.ai import tones as t
from marvin.services.ai.tones import ToneError, ToneSpec, WorkspaceTones

PERSONA = "Marvin the Paranoid Android; deadpan and gloomy."
WARM = {"name": "Warm", "instructions": "Write warmly and encouragingly.", "persona": "frame"}


def _custom(persona="frame", name="Warm", instructions="Write warmly and encouragingly.", slug="warm"):
    return ToneSpec(slug=slug, name=name, instructions=instructions, persona=persona)


def _builtin(slug):
    return WorkspaceTones().get(slug)


# ── Golden: the exact prompt wording ────────────────────────────────────────────────────────────
# These strings ARE the contract: changing one changes every workspace's prompts. They changed on purpose
# (2026-10-04) from "Voice and tone: <persona>" to a "Character:" block plus an explicit precedence rule;
# the built-ins' behaviour is unchanged (auto frames chat with plain work product, professional drops the
# character, playful uses it everywhere).

RULE = (
    "Where the tone and the character disagree on formality, length or mood, follow the tone; "
    "keep the character's identity and way of speaking otherwise."
)
EVERYWHERE = "\nThe character applies to everything you write, work product included."
GOLDEN_PROFESSIONAL = (
    "\n\nWrite plainly, specifically and professionally. Do not adopt a persona, "
    "voice, or character; skip pleasantries and lead with the substance. Be concrete: "
    "name the field, section, or line you mean, and say what to change and why."
)
GOLDEN_PLAYFUL = f"\n\nCharacter: {PERSONA}{EVERYWHERE}"
GOLDEN_AUTO = (
    f"\n\nCharacter: {PERSONA}"
    "\nThe character applies ONLY to how you address the user — greetings, framing, brief "
    "asides. Work product itself — reviews, critiques, findings, summaries, suggested "
    "copy — must be written plainly, specifically, and professionally. Never let the "
    "character soften, exaggerate, or obscure a finding, and never write generated "
    "content in the character's voice unless the user explicitly asks for it."
)
GOLDEN_FRAME = (
    f"\n\nCharacter: {PERSONA}"
    "\nThe character applies ONLY to how you address the user — greetings, framing, brief "
    "asides. Work product itself — reviews, critiques, findings, summaries, suggested "
    "copy — follows the tone below, not the character. Never let the character soften, "
    "exaggerate, or obscure a finding."
    "\n\nTone (Warm): Write warmly and encouragingly."
    f"\n\n{RULE}"
)
GOLDEN_EVERYWHERE = f"\n\nCharacter: {PERSONA}{EVERYWHERE}\n\nTone (Warm): Write warmly and encouragingly.\n\n{RULE}"
GOLDEN_DROP = "\n\nDo not adopt a persona, voice, or character.\n\nTone (Warm): Write warmly and encouragingly."


@pytest.mark.parametrize(
    ("slug", "persona", "expected"),
    [
        ("auto", PERSONA, GOLDEN_AUTO),
        ("auto", "", ""),
        ("playful", PERSONA, GOLDEN_PLAYFUL),
        ("playful", "", ""),
        ("professional", PERSONA, GOLDEN_PROFESSIONAL),
        ("professional", "", GOLDEN_PROFESSIONAL),
    ],
)
def test_builtin_tone_clause_matches_the_golden_wording(slug, persona, expected):
    assert t.tone_clause(_builtin(slug), persona) == expected


def test_precedence_rule_constant_is_the_pinned_wording():
    assert t.PRECEDENCE_RULE == RULE


# ── Custom tone clauses: persona rule × persona present/absent ───────────────────────────────────


def test_drop_tone_withholds_the_character_and_carries_the_instructions():
    assert t.tone_clause(_custom("drop"), PERSONA) == GOLDEN_DROP


def test_drop_tone_without_a_persona_is_the_same_clause():
    assert t.tone_clause(_custom("drop"), "") == GOLDEN_DROP


def test_everywhere_tone_is_character_then_tone_then_the_precedence_rule():
    assert t.tone_clause(_custom("everywhere"), PERSONA) == GOLDEN_EVERYWHERE


def test_frame_tone_scopes_the_character_and_hands_work_product_to_the_tone():
    out = t.tone_clause(_custom("frame"), PERSONA)
    assert out == GOLDEN_FRAME
    assert "must be written plainly" not in out  # that's auto's rule, not a custom tone's


@pytest.mark.parametrize("persona_rule", ["frame", "everywhere"])
def test_custom_tone_without_a_persona_is_just_the_instructions(persona_rule):
    assert t.tone_clause(_custom(persona_rule), "") == "\n\nTone (Warm): Write warmly and encouragingly."


def test_no_clause_uses_the_old_voice_and_tone_label():
    tones = [_builtin("auto"), _builtin("playful"), _builtin("professional"), *(_custom(r) for r in t.PERSONA_MODES)]
    assert all("Voice and tone" not in t.tone_clause(tone, PERSONA) for tone in tones)


def test_tone_parts_label_where_each_line_comes_from():
    parts = t.tone_parts(_custom("frame"), PERSONA)
    assert parts.character == f"\n\nCharacter: {PERSONA}"
    assert parts.scope.startswith("\nThe character applies ONLY")
    assert parts.tone == "\n\nTone (Warm): Write warmly and encouragingly."
    assert parts.rule == f"\n\n{RULE}"
    assert parts.text == GOLDEN_FRAME


def test_tone_parts_of_a_drop_tone_have_no_character_or_rule():
    parts = t.tone_parts(_custom("drop"), PERSONA)
    assert (parts.character, parts.scope, parts.rule) == ("", "", "")
    assert parts.tone == GOLDEN_DROP


@pytest.mark.parametrize(
    ("tone", "expected"),
    [
        (_custom("frame"), "Frame only: the character talks, work product follows this tone."),
        (_custom("everywhere"), "Everywhere: the character and this tone apply to everything, work product included."),
        (_custom("drop"), "Drop: no character, just this tone."),
        (WorkspaceTones().get("auto"), "Frame only: the character talks, work product stays plain."),
        (WorkspaceTones().get("playful"), "Everywhere: the character applies to everything, work product included."),
        (WorkspaceTones().get("professional"), "Drop: no character, just plain and professional."),
    ],
)
def test_persona_summary_says_the_rule_in_plain_words(tone, expected):
    assert t.persona_summary(tone) == expected


# ── Validation ───────────────────────────────────────────────────────────────────────────────────


def test_validate_tones_makes_a_slug_from_the_name():
    (tone,) = t.validate_tones([{"name": "  Board Report! ", "instructions": " Terse. ", "persona": "drop"}])
    assert (tone.slug, tone.name, tone.instructions, tone.persona) == ("board-report", "Board Report!", "Terse.", "drop")


def test_validate_tones_keeps_the_slug_on_rename():
    (tone,) = t.validate_tones([{**WARM, "slug": "warm", "name": "Cosy"}], existing=[_custom()])
    assert tone.slug == "warm" and tone.name == "Cosy"


def test_validate_tones_new_tone_never_reuses_an_existing_slug():
    tones = t.validate_tones([{**WARM, "slug": "warm", "name": "Cosy"}, WARM], existing=[_custom()])
    assert [x.slug for x in tones] == ["warm", "warm-2"]


def test_validate_tones_defaults_persona_to_frame_and_keeps_description():
    (tone,) = t.validate_tones([{"name": "A", "instructions": "B", "description": " short "}])
    assert tone.persona == "frame" and tone.description == "short"


def test_validate_tones_accepts_a_forty_char_slug():
    slug = "a" * t.MAX_SLUG_CHARS
    (tone,) = t.validate_tones([{**WARM, "slug": slug}])
    assert tone.slug == slug


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([{**WARM, "name": f"T{i}"} for i in range(t.MAX_CUSTOM_TONES + 1)], "at most 20"),
        ([{**WARM, "name": "  "}], "name is required"),
        ([{**WARM, "name": "x" * (t.MAX_NAME_CHARS + 1)}], "at most 60"),
        ([WARM, {**WARM, "name": "warm"}], "already has that name"),
        ([{**WARM, "name": "Professional"}], "already has that name"),
        ([{**WARM, "instructions": ""}], "instructions is required"),
        ([{**WARM, "instructions": "x" * (t.MAX_INSTRUCTIONS_CHARS + 1)}], "at most 1500"),
        ([{**WARM, "persona": "sometimes"}], "persona must be one of"),
        ([{**WARM, "slug": "auto"}], "built-in"),
        ([{**WARM, "slug": "Not A Slug"}], "slug must be"),
        ([{**WARM, "slug": "a" * (t.MAX_SLUG_CHARS + 1)}], "slug must be"),
        ([{**WARM, "slug": "w"}, {**WARM, "name": "Other", "slug": "w"}], "used twice"),
    ],
)
def test_validate_tones_rejects(items, message):
    with pytest.raises(ToneError, match=message):
        t.validate_tones(items)


def test_validate_tones_allows_exactly_the_limit():
    assert len(t.validate_tones([{**WARM, "name": f"T{i}"} for i in range(t.MAX_CUSTOM_TONES)])) == t.MAX_CUSTOM_TONES


def test_validate_hidden_dedupes_and_rejects_unknown_slugs():
    known = t.BUILTIN_TONES + (_custom(),)
    assert t.validate_hidden(["playful", "warm", "playful"], known) == ["playful", "warm"]
    with pytest.raises(ToneError, match="no such tone"):
        t.validate_hidden(["ghost"], known)


def test_parse_stored_skips_malformed_items():
    raw = [WARM | {"slug": "warm"}, "junk", {"slug": "auto", "name": "Fake"}, {"name": "no slug"}, {"slug": "x", "name": "X", "persona": "?"}]
    tones = t.parse_stored(raw)
    assert [x.slug for x in tones] == ["warm", "x"] and tones[1].persona == "frame"


# ── Resolution / fallback ────────────────────────────────────────────────────────────────────────


def test_resolve_prefers_the_first_known_candidate():
    ws = WorkspaceTones(custom=(_custom(),), default_slug="professional")
    assert ws.resolve("warm", "playful").slug == "warm"
    assert ws.resolve(None, "playful").slug == "playful"
    assert ws.resolve().slug == "professional"


def test_resolve_skips_an_unknown_slug_with_a_warning(caplog):
    ws = WorkspaceTones(custom=(_custom(),), default_slug="warm")
    with caplog.at_level(logging.WARNING, logger="marvin.services.ai.tones"):
        assert ws.resolve("deleted-tone").slug == "warm"
    assert "deleted-tone" in caplog.text


def test_resolve_falls_back_agent_then_workspace_then_auto():
    ws = WorkspaceTones(custom=(_custom(),), default_slug="gone-too")
    assert ws.resolve("gone", "warm").slug == "warm"  # caller's tone deleted → the agent's
    assert ws.resolve("gone", "gone-agent").slug == "auto"  # both gone and the workspace default too


def test_resolve_hidden_tones_still_resolve():
    ws = WorkspaceTones(custom=(_custom(),), hidden=frozenset({"warm", "playful"}))
    assert ws.resolve("warm").slug == "warm" and ws.resolve("playful").slug == "playful"


def test_find_matches_slug_or_name_case_insensitively():
    ws = WorkspaceTones(custom=(_custom(name="Board Report", slug="board-report"),))
    assert ws.find("BOARD REPORT").slug == "board-report"
    assert ws.find("board-report").slug == "board-report"
    assert ws.find("Professional").slug == "professional"
    assert ws.find("nope") is None


def test_workspace_tones_reads_a_row_defensively():
    row = SimpleNamespace(tones=[WARM | {"slug": "warm"}], hidden_tones=["playful", 3], default_register="warm")
    ws = t.workspace_tones(row)
    assert [x.slug for x in ws.custom] == ["warm"] and ws.hidden == {"playful"} and ws.default.slug == "warm"
    assert t.workspace_tones(None).default.slug == "auto"
    assert t.workspace_tones(SimpleNamespace(tones="?", hidden_tones=None, default_register=None)).default.slug == "auto"


def test_controller_effective_register_skips_a_deleted_caller_tone_for_the_agents():
    from marvin.routes.ai.operations_controller import AIOperationsController as C

    ctrl = SimpleNamespace(_tones=lambda: WorkspaceTones(custom=(_custom(),), default_slug="playful"))
    spec = SimpleNamespace(default_register="warm")
    assert C._effective_register(ctrl, "deleted", spec) == "warm"
    assert C._effective_register(ctrl, "auto", SimpleNamespace(default_register=None)) == "playful"


def test_controller_register_clause_renders_a_custom_tone():
    from marvin.routes.ai.operations_controller import AIOperationsController as C

    ctrl = SimpleNamespace(_tones=lambda: WorkspaceTones(custom=(_custom("drop"),)))
    assert C._register_clause(ctrl, "warm", PERSONA) == t.tone_clause(_custom("drop"), PERSONA)
    assert C._register_clause(ctrl, "deleted", PERSONA) == GOLDEN_AUTO


@pytest.mark.parametrize(
    ("requested", "expected_tail"),
    [
        (None, GOLDEN_DROP),  # no tone on the request → the workspace default (a custom drop tone here)
        ("playful", GOLDEN_PLAYFUL),  # the request's tone wins
    ],
)
def test_plain_chat_applies_the_tone_like_the_default_agent(monkeypatch, requested, expected_tail):
    """/chat used to append "Voice and tone: <persona>" and ignore tones; it now resolves them like Marvin."""
    from unittest.mock import MagicMock

    from marvin.routes.ai import operations_controller as oc
    from marvin.schemas.group.ai_execution import AIAgentRequest
    from marvin.services.ai import factory
    from marvin.services.ai.base import CompletionResult

    seen = {}

    class _Provider:
        provider_type = "openai"

        def complete(self, messages, model, opts):
            seen["system"] = messages[0].content
            return CompletionResult(content="ok", prompt_tokens=1, completion_tokens=1, total_tokens=2, model=model)

    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a: _Provider())
    monkeypatch.setattr(oc, "AIExecutionModel", lambda **kw: SimpleNamespace(id=uuid.uuid4(), **kw))
    C = oc.AIOperationsController
    ctrl = MagicMock()
    ctrl._user_role.return_value = 99
    ctrl._check_invocation_source.return_value = "api"
    ctrl._default_model.return_value = "m"
    ctrl._persona.return_value = ("Marvin", PERSONA)
    ctrl._logging_policy.return_value = (False, False)
    ctrl._max_output_tokens.return_value = None
    ctrl._tones = lambda: WorkspaceTones(custom=(_custom("drop"),), default_slug="warm")
    for name in ("_default_register", "_register_clause"):
        setattr(ctrl, name, getattr(C, name).__get__(ctrl))

    C.chat(ctrl, AIAgentRequest.model_validate({"message": "hi", "register": requested}))
    assert seen["system"].endswith(expected_tail)
    assert "Voice and tone" not in seen["system"]


def test_controller_rejects_an_agent_default_tone_the_workspace_lacks():
    from marvin.routes.ai.operations_controller import AIOperationsController as C

    ctrl = SimpleNamespace(_tones=lambda: WorkspaceTones(custom=(_custom(),)))
    C._require_known_tone(ctrl, "warm")
    C._require_known_tone(ctrl, None)
    with pytest.raises(HTTPException) as e:
        C._require_known_tone(ctrl, "shouty")
    assert e.value.status_code == 422


def test_agent_schema_accepts_any_tone_slug_shape_but_not_garbage():
    from pydantic import ValidationError

    from marvin.schemas.group.agent import AgentCreate, AgentUpdate

    assert AgentCreate(slug="a1", name="a", default_register=" Board-Report ").default_register == "board-report"
    assert AgentUpdate(default_register="").default_register is None
    with pytest.raises(ValidationError):
        AgentCreate(slug="a1", name="a", default_register="not a slug!")
    with pytest.raises(ValidationError):
        AgentUpdate(default_register="a" * (t.MAX_SLUG_CHARS + 1))


# ── Column length + migration ────────────────────────────────────────────────────────────────────


def test_agent_default_register_column_fits_the_longest_tone_slug():
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    assert WorkspaceAgentModel.__table__.c.default_register.type.length >= t.MAX_SLUG_CHARS


def test_custom_tones_migration_widens_the_column_and_follows_the_previous_head():
    path = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_a8d4b0f6c3e9_*.py"))
    text = path.read_text()
    assert 'down_revision: str | None = "f7c3a9e5b2d8"' in text
    assert f"NEW_LENGTH = {t.MAX_SLUG_CHARS}" in text


# ── Endpoints (/groups/ai-settings/tones) ────────────────────────────────────────────────────────


@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"tone-{gid.hex[:8]}", slug=f"tone-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, assistant_name="Ada", persona_prompt="You are Ada."))
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(WorkspaceAgentModel).filter_by(group_id=gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def ctrl(db_session, workspace):
    from marvin.routes.groups.ai_settings_controller import AISettingsController as C

    c = SimpleNamespace(session=db_session, group_id=workspace, user=SimpleNamespace(id=None, admin=True), logger=logging.getLogger("test"))
    for name in ("_settings_row", "_usable_default_tone", "_agents_by_tone", "_tones_state", "_require_admin", "_allow_workspace_credentials"):
        setattr(c, name, getattr(C, name).__get__(c))
    c._effective_character = lambda row: None
    c.get = lambda: C.get_tones(c)
    c.put = lambda **kw: C.put_tones(c, _tones_update(**kw))
    c.preview = lambda **kw: C.preview_tone(c, _preview(**kw))
    c.patch = lambda **kw: C.update_ai_settings(c, _settings_update(**kw))
    return c


def _tones_update(**kw):
    from marvin.schemas.group.ai_settings import TonesUpdate

    return TonesUpdate(**kw)


def _preview(**kw):
    from marvin.schemas.group.ai_settings import TonePreviewRequest

    return TonePreviewRequest(**kw)


def _settings_update(**kw):
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    return WorkspaceAISettingsUpdate(**kw)


def _add_agent(db_session, gid, slug, tone):
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    db_session.add(WorkspaceAgentModel(session=db_session, group_id=gid, slug=slug, name=slug.title(), default_register=tone))
    db_session.commit()


def _status(fn, **kw):
    with pytest.raises(HTTPException) as e:
        fn(**kw)
    return e.value


def test_get_tones_lists_builtins_first_with_the_default(ctrl):
    state = ctrl.get()
    assert [x.slug for x in state.tones] == ["auto", "professional", "playful"]
    assert state.default_tone == "auto" and all(x.builtin for x in state.tones)


def test_put_tones_saves_custom_hidden_and_default(ctrl, db_session, workspace):
    state = ctrl.put(tones=[WARM], hidden=["playful"], default_tone="warm")
    warm = next(x for x in state.tones if x.slug == "warm")
    assert not warm.builtin and state.default_tone == "warm"
    assert next(x for x in state.tones if x.slug == "playful").hidden
    _add_agent(db_session, workspace, "scout", "warm")
    assert next(x for x in ctrl.get().tones if x.slug == "warm").used_by == ["scout"]


def test_put_tones_rename_keeps_the_slug(ctrl):
    ctrl.put(tones=[WARM])
    state = ctrl.put(tones=[{**WARM, "slug": "warm", "name": "Cosy"}])
    assert [(x.slug, x.name) for x in state.tones if not x.builtin] == [("warm", "Cosy")]


def test_put_tones_blocks_deleting_a_tone_agents_use(ctrl, db_session, workspace):
    ctrl.put(tones=[WARM])
    _add_agent(db_session, workspace, "scout", "warm")
    err = _status(ctrl.put, tones=[])
    assert err.status_code == 409
    assert err.detail["tones"] == {"warm": ["scout"]} and "scout" in err.detail["message"]
    assert [x.slug for x in ctrl.get().tones if not x.builtin] == ["warm"]  # nothing saved


def test_put_tones_may_hide_a_tone_agents_use(ctrl, db_session, workspace):
    ctrl.put(tones=[WARM])
    _add_agent(db_session, workspace, "scout", "warm")
    assert next(x for x in ctrl.put(tones=[{**WARM, "slug": "warm"}], hidden=["warm"]).tones if x.slug == "warm").hidden


def test_put_tones_invalid_list_is_422(ctrl):
    assert _status(ctrl.put, tones=[{**WARM, "instructions": ""}]).status_code == 422


def test_put_tones_removing_the_default_needs_a_new_default(ctrl):
    ctrl.put(tones=[WARM], default_tone="warm")
    assert _status(ctrl.put, tones=[]).status_code == 422
    assert ctrl.put(tones=[], default_tone="professional").default_tone == "professional"


def test_put_tones_default_cannot_be_hidden_or_unknown(ctrl):
    assert _status(ctrl.put, hidden=["auto"]).status_code == 422  # auto is the default
    assert _status(ctrl.put, hidden=["playful"], default_tone="playful").status_code == 422
    assert _status(ctrl.put, default_tone="ghost").status_code == 422


def test_put_tones_requires_a_workspace_admin(ctrl, workspace):
    ctrl.user = SimpleNamespace(id=None, admin=False, platform_role=None, get_workspace_role=lambda gid: "EDITOR")
    assert _status(ctrl.put, tones=[WARM]).status_code == 403


def test_patch_settings_rejects_an_unknown_default_tone(ctrl):
    assert _status(ctrl.patch, default_register="ghost").status_code == 422
    ctrl.put(tones=[WARM])
    assert ctrl.patch(default_register="Warm".lower()).default_register == "warm"


def test_preview_returns_the_clause_with_the_workspace_persona_and_a_token_estimate(ctrl):
    out = ctrl.preview(name="Warm", instructions="Write warmly.", persona="everywhere")
    assert out.clause == f"\n\nCharacter: You are Ada.{EVERYWHERE}\n\nTone (Warm): Write warmly.\n\n{RULE}"
    assert out.tokens == t.estimate_tokens(out.clause) and out.tokens > 0
    assert ctrl.preview(slug="professional").clause == GOLDEN_PROFESSIONAL
    assert _status(ctrl.preview, slug="ghost").status_code == 404
    assert _status(ctrl.preview, name="X", instructions="").status_code == 422


def test_preview_returns_the_parts_so_the_editor_never_parses_the_text(ctrl):
    out = ctrl.preview(name="Warm", instructions="Write warmly.", persona="frame")
    assert out.character == "Character: You are Ada."
    assert out.from_tone.startswith("The character applies ONLY") and out.from_tone.endswith("Tone (Warm): Write warmly.")
    assert out.rule == RULE
    assert (out.persona, out.has_persona) == ("frame", True)
    assert out.persona_summary == "Frame only: the character talks, work product follows this tone."
    wire = out.model_dump(by_alias=True)
    assert {"personaSummary", "hasPersona", "fromTone"} <= wire.keys()


def test_preview_of_a_drop_tone_has_no_character_part(ctrl):
    out = ctrl.preview(name="Client", instructions="Formal.", persona="drop")
    assert (out.character, out.rule) == ("", "")
    assert out.from_tone == "Do not adopt a persona, voice, or character.\n\nTone (Client): Formal."
    assert out.persona_summary == "Drop: no character, just this tone."


def test_preview_without_a_slug_or_draft_is_the_workspace_default_tone(ctrl):
    ctrl.put(tones=[WARM], default_tone="warm")
    out = ctrl.preview()
    assert (out.tone_slug, out.tone_name) == ("warm", "Warm")
    assert out.from_tone.endswith("Tone (Warm): Write warmly and encouragingly.") and out.rule == RULE


def test_preview_names_the_tone_it_previewed(ctrl):
    assert (ctrl.preview(slug="playful").tone_slug, ctrl.preview(slug="playful").tone_name) == ("playful", "Playful")


def test_preview_uses_an_unsaved_character_in_place_of_the_stored_one(ctrl, db_session, workspace):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    assert ctrl.preview(slug="auto", persona_prompt="You are Bea.").character == "Character: You are Bea."
    assert ctrl.preview(slug="auto").character == "Character: You are Ada."  # nothing sent → the stored one
    stored = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=workspace).one()
    assert stored.persona_prompt == "You are Ada."


def test_preview_of_a_cleared_character_follows_the_unsaved_assistant_name(ctrl):
    from marvin.services.ai.persona import DEFAULT_PERSONA_PROMPT

    marvin = ctrl.preview(slug="auto", persona_prompt="", assistant_name="Marvin")
    assert marvin.character == f"Character: {DEFAULT_PERSONA_PROMPT.strip()}" and marvin.has_persona
    renamed = ctrl.preview(slug="auto", persona_prompt="  ", assistant_name="Ada")
    assert (renamed.character, renamed.has_persona) == ("", False)


def test_preview_requires_a_workspace_admin(ctrl):
    ctrl.user = SimpleNamespace(id=None, admin=False, workspace_memberships=[])
    assert _status(ctrl.preview, slug="auto").status_code == 403


# ── Export / import ──────────────────────────────────────────────────────────────────────────────


def test_export_import_round_trips_tones(db_session, workspace, ctrl):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    ctrl.put(tones=[WARM], hidden=["playful"], default_tone="warm")
    repos = get_repositories(db_session, group_id=workspace)
    data = WorkspaceExporter(repos).export_workspace()
    assert data["ai_settings"]["tones"][0]["slug"] == "warm" and data["ai_settings"]["hiddenTones"] == ["playful"]

    target = uuid.uuid4()
    g = Groups(session=db_session, name=f"tone-{target.hex[:8]}", slug=f"tone-{target.hex[:8]}")
    g.id = target
    db_session.add(g)
    db_session.commit()
    try:
        WorkspaceSeedLoader(repos)._load_data(data, overwrite=True, target_group_id=str(target))
        row = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).one()
        assert row.tones == [t.validate_tones([WARM])[0].to_json()]
        assert row.hidden_tones == ["playful"] and row.default_register == "warm"

        # A bundle whose tones don't validate keeps the target on the built-ins instead of failing.
        data["ai_settings"]["tones"] = [{"name": "", "instructions": "x"}]
        WorkspaceSeedLoader(repos)._load_data(data, overwrite=True, target_group_id=str(target))
        db_session.refresh(row)
        assert row.tones is None and row.hidden_tones is None
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).delete()
        db_session.query(Groups).filter_by(id=target).delete()
        db_session.commit()


# ── Drafts: the entry type's voice wins; the tone fills in where it has none ─────────────────────


def _voice(db_session, gid, recipe, register=None):
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe
    from marvin.services.ai.authoring import AuthoringService

    svc = AuthoringService(db_session, gid, user=None, provider=None, model=None)
    return svc._voice_suffix(EntryTypeRecipe.model_validate(recipe), register)


def test_draft_voice_entry_type_voice_wins_over_the_tone(db_session, workspace, ctrl):
    ctrl.put(tones=[WARM], default_tone="warm")
    assert _voice(db_session, workspace, {"enrichment": {"voice": "wry"}}, "warm") == " Voice: wry"


def test_draft_voice_uses_the_tone_when_the_entry_type_has_none(db_session, workspace, ctrl):
    ctrl.put(tones=[WARM], default_tone="warm")
    assert _voice(db_session, workspace, {}) == "\n\nTone (Warm): Write warmly and encouragingly."  # workspace default
    assert _voice(db_session, workspace, {}, "professional") == ""  # a per-call tone beats it; plain as before


def test_draft_voice_everywhere_tones_bring_the_persona(db_session, workspace, ctrl):
    ctrl.put(tones=[{**WARM, "persona": "everywhere"}])
    assert _voice(db_session, workspace, {}, "warm") == (
        f"\n\nCharacter: You are Ada.\nWrite the draft in this character.\nTone (Warm): Write warmly and encouragingly.\n{RULE}"
    )
    assert _voice(db_session, workspace, {}, "playful") == "\n\nCharacter: You are Ada.\nWrite the draft in this character."
    assert _voice(db_session, workspace, {}, "auto") == ""


class _CaptureProvider:
    provider_type = "openai"

    def __init__(self):
        self.messages = None

    def execute_operation(self, messages, model, output_schema, options=None):
        from marvin.services.ai.base import CompletionResult

        self.messages = messages
        return {"tags": [], "resources": []}, CompletionResult(content="", prompt_tokens=1, completion_tokens=1, total_tokens=2, model=model)


def test_revise_honours_the_per_call_tone(db_session, workspace, ctrl):
    """Revise used to ignore the caller's tone; it now reaches the editor's system prompt."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.services.ai.authoring import AuthoringService

    ctrl.put(tones=[WARM])
    et = EntryTypes(session=db_session, group_id=workspace, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(session=db_session, group_id=workspace, entry_type_id=et.id, title="T", slug=f"t-{workspace.hex[:8]}")
    db_session.add(entry)
    db_session.commit()
    provider = _CaptureProvider()
    try:
        svc = AuthoringService(db_session, workspace, user=None, provider=provider, model="m")
        svc.revise(entry=entry, instruction="tidy", register="warm", ground=False)
        assert provider.messages[0].content.endswith("\n\nTone (Warm): Write warmly and encouragingly.")
    finally:
        db_session.rollback()
        db_session.query(AIExecutionModel).filter_by(group_id=workspace).delete()
        db_session.query(Entries).filter_by(group_id=workspace).delete()
        db_session.query(EntryTypes).filter_by(group_id=workspace).delete()
        db_session.commit()


# ── Agent authoring tools draft in the run's tone (ToolContext.tone_register) ─


@pytest.mark.parametrize("tool", ["compose_entry", "revise_entry"])
def test_authoring_tools_draft_in_the_runs_tone(monkeypatch, tool):
    from marvin.services.ai.tools import builtins_authoring as authoring
    from marvin.services.ai.tools.base import ToolContext

    seen = {}

    class _Svc:
        def recipe_asset_attachments(self, *a):
            return None

        def compose(self, **kw):
            seen.update(kw)
            return {"ok": True}

        def revise(self, **kw):
            seen.update(kw)
            return {"ok": True}

    entry_type = SimpleNamespace(group_id=None)
    entry = SimpleNamespace(group_id="g1")

    class _Query:
        def filter(self, *a):
            return self

        def first(self):
            return entry_type

    session = SimpleNamespace(query=lambda *a: _Query(), get=lambda model, eid: entry)
    monkeypatch.setattr(authoring, "_service", lambda ctx: (_Svc(), None))
    monkeypatch.setattr(authoring, "resolve_entity_id", lambda *a: uuid.uuid4())
    ctx = ToolContext(session=session, group_id="g1", tone_register="board-report")

    if tool == "compose_entry":
        authoring.compose_entry(ctx, {"entry_type": "post", "brief": "b"})
    else:
        authoring.revise_entry(ctx, {"entry": "e", "instruction": "i"})
    assert seen["register"] == "board-report"
