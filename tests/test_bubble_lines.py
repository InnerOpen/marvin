"""The bubble's canned lines in the workspace's own voice (services/ai/bubble_lines.py, /groups/ai-settings/bubble-lines).

Regression: the bubble showed Marvin's gloomy lines only for a plain "Marvin", so any workspace with its
own persona — Ada, the warm Southern helper, or Mash & Burn's own long Marvin — got a bland neutral set.
Now one model call writes lines in the persona's voice. The model is always stubbed here.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.services.ai import bubble_lines as bl
from marvin.services.ai.base import CompletionResult

ADA = "You are Ada, a warm Southern mother figure. Kind, unhurried. Avoid clichés and phonetic dialect."


def _reply(**over) -> dict:
    lines = {
        "greetings": ["Well hello there. What can I help you with today?", "Come on in. What are we working on?", "Good to see you. Ask away."],
        "taglines": ["here whenever you need me", "one thing at a time", "no question too small"],
        "thinking": ["Let me take a look.", "Give me just a moment.", "Working on it, dear."],
        "errors": ["Oh, that didn't go right.", "Something went sideways."],
        "emotes": ["*smiles warmly*", "*pours sweet tea*", "*nods kindly*"],
    }
    return {**lines, **over}


class FakeProvider:
    provider_type = "openai"

    def __init__(self, reply=None, error: Exception | None = None):
        self.reply = reply if reply is not None else _reply()
        self.error = error
        self.calls: list[list] = []

    def execute_operation(self, messages, model, output_schema, options=None):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply, CompletionResult(content="", prompt_tokens=900, completion_tokens=300, total_tokens=1200, model=model)


@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"bl-{gid.hex[:8]}", slug=f"bl-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, assistant_name="Ada", persona_prompt=ADA))
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(AIExecutionModel).filter_by(group_id=gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("marvin.services.ai.factory.get_workspace_ai_provider", lambda session, gid: fake)
    monkeypatch.setattr("marvin.services.ai.authoring.default_authoring_model", lambda session, gid, provider=None: "gpt-5.6-luna")
    return fake


@pytest.fixture
def started(monkeypatch):
    """Background generations the code asked for, instead of running them."""
    calls: list[dict] = []
    monkeypatch.setattr(bl, "start", lambda gid, user_id=None, *, force=False: calls.append({"gid": gid, "force": force}) or True)
    return calls


def _row(db_session, gid):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    row = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).first()
    db_session.refresh(row)
    return row


def _set_lines(db_session, gid, lines, source):
    row = _row(db_session, gid)
    bl.store(row, lines, source)
    db_session.commit()


def _executions(db_session, gid):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    return db_session.query(AIExecutionModel).filter_by(group_id=gid).all()


OLD = {"greetings": ["old hi"], "taglines": ["old tag"], "thinking": ["old think"], "errors": ["old err"], "emotes": ["*old*"]}


# --- generation ------------------------------------------------------------------------------------


def test_generate_with_valid_reply_stores_generated_lines(db_session, workspace, provider):
    lines = bl.generate(db_session, workspace)

    row = _row(db_session, workspace)
    assert row.bubble_lines == lines and lines["emotes"] == ["*smiles warmly*", "*pours sweet tea*", "*nods kindly*"]
    assert row.bubble_lines_source == bl.SOURCE_GENERATED and row.bubble_lines_updated_at and row.bubble_lines_warning is None


def test_generate_records_a_normal_ai_execution_with_its_cost(db_session, workspace, provider):
    bl.generate(db_session, workspace)

    [run] = _executions(db_session, workspace)
    assert (run.operation_slug, run.status, run.trigger_type, run.total_tokens) == ("generate-bubble-lines", "completed", "settings", 1200)
    assert run.estimated_cost_usd is not None


def test_generate_prompt_carries_the_persona_and_name_and_uses_marvin_only_as_format(db_session, workspace, provider):
    bl.generate(db_session, workspace)

    prompt = provider.calls[0][-1].content
    assert ADA in prompt and "Assistant name: Ada" in prompt
    assert "FORMAT EXAMPLE ONLY" in prompt and "never their voice" in prompt and "here to help, allegedly" in prompt
    assert "clichés" in prompt and "never mean" in prompt and "placeholders" in prompt


def test_clean_generated_drops_unusable_lines_and_wraps_bare_emotes():
    reply = _reply(
        greetings=["Hi there!", "x" * 200, "See [the docs](#)", "Hello {name}!", "  hi   THERE! ", "Morning.", "Ask me anything."],
        emotes=["smiles", "*hums*", "**waves**"],
    )

    lines = bl.clean_generated(reply)

    assert lines["greetings"] == ["Hi there!", "Morning.", "Ask me anything."]
    assert lines["emotes"] == ["*smiles*", "*hums*", "*waves*"]


@pytest.mark.parametrize(
    "reply", [{"raw": "Sure! Here are some lines…"}, ["a list"], _reply(errors="nope"), _reply(taglines=["one", "http://x.test"])]
)
def test_clean_generated_with_bad_shape_or_too_few_lines_raises(reply):
    with pytest.raises(bl.BubbleLinesError):
        bl.clean_generated(reply)


def test_generate_with_thin_reply_keeps_previous_lines_and_records_warning(db_session, workspace, provider):
    _set_lines(db_session, workspace, OLD, bl.SOURCE_GENERATED)
    provider.reply = _reply(thinking=["Hm."])

    with pytest.raises(bl.BubbleLinesError):
        bl.generate(db_session, workspace)

    row = _row(db_session, workspace)
    assert row.bubble_lines == OLD
    assert "too few usable thinking" in row.bubble_lines_warning and "previous lines were kept" in row.bubble_lines_warning


def test_generate_with_provider_error_keeps_previous_lines_and_fails_the_execution(db_session, workspace, provider):
    _set_lines(db_session, workspace, OLD, bl.SOURCE_GENERATED)
    provider.error = RuntimeError("upstream 503")

    with pytest.raises(bl.BubbleLinesError):
        bl.generate(db_session, workspace)

    row = _row(db_session, workspace)
    [run] = _executions(db_session, workspace)
    assert row.bubble_lines == OLD and "upstream 503" in row.bubble_lines_warning and run.status == "failed"


def test_generate_when_budget_blocked_makes_no_call_and_records_warning(db_session, workspace, provider):
    row = _row(db_session, workspace)
    row.budget_config = {"max_requests_per_day": 1}
    db_session.commit()
    bl.generate(db_session, workspace)  # the day's one run

    with pytest.raises(bl.BubbleLinesError, match="Daily request limit"):
        bl.generate(db_session, workspace)

    assert len(provider.calls) == 1 and "AI budget" in _row(db_session, workspace).bubble_lines_warning


def test_a_success_clears_the_previous_warning(db_session, workspace, provider):
    row = _row(db_session, workspace)
    row.bubble_lines_warning = "The model call failed: timeout"
    db_session.commit()

    bl.generate(db_session, workspace)

    assert _row(db_session, workspace).bubble_lines_warning is None


def test_generate_without_a_persona_is_refused(db_session, workspace, provider):
    row = _row(db_session, workspace)
    row.persona_prompt = "  "
    db_session.commit()

    with pytest.raises(bl.BubbleLinesError, match="no character to write lines from") as e:
        bl.generate(db_session, workspace)
    assert "Character field" in str(e.value) and "Voice / tone" not in str(e.value)  # the field's label
    assert provider.calls == []


def test_regenerate_overwrites_edited_lines(db_session, workspace, provider):
    _set_lines(db_session, workspace, OLD, bl.SOURCE_EDITED)

    bl.generate(db_session, workspace, force=True)

    row = _row(db_session, workspace)
    assert row.bubble_lines != OLD and row.bubble_lines_source == bl.SOURCE_GENERATED


def test_automatic_generation_never_overwrites_lines_edited_meanwhile(db_session, workspace, provider):
    _set_lines(db_session, workspace, OLD, bl.SOURCE_EDITED)

    assert bl.generate(db_session, workspace) is None
    assert _row(db_session, workspace).bubble_lines == OLD


# --- the background run ----------------------------------------------------------------------------


def test_start_runs_once_more_when_asked_again_mid_run(monkeypatch):
    runs: list[bool] = []
    gid = uuid.uuid4()

    class _Thread:
        def __init__(self, target, args, **_kw):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    def fake_generate(session, group_id, user_id=None, *, force=False):
        runs.append(force)
        if len(runs) == 1:
            # Regenerate is clicked while the first generation is still running.
            assert bl.start(gid, force=True) is False and bl.is_generating(gid)

    monkeypatch.setattr(bl.threading, "Thread", _Thread)
    monkeypatch.setattr(bl, "generate", fake_generate)
    monkeypatch.setattr("marvin.db.db_setup.session_context", lambda: _nullcontext())

    assert bl.start(gid) is True
    assert runs == [False, True] and not bl.is_generating(gid)


def test_start_generates_in_the_background_and_stores_the_lines(db_session, workspace, provider):
    import time as _time

    assert bl.start(workspace) is True
    deadline = _time.monotonic() + 5
    while bl.is_generating(workspace) and _time.monotonic() < deadline:
        _time.sleep(0.02)

    row = _row(db_session, workspace)
    assert not bl.is_generating(workspace) and row.bubble_lines_source == bl.SOURCE_GENERATED and row.bubble_lines["taglines"]


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


# --- the settings endpoints ------------------------------------------------------------------------


@pytest.fixture
def ctrl(db_session, workspace):
    import logging

    from marvin.routes.groups.ai_settings_controller import AISettingsController

    c = SimpleNamespace(session=db_session, group_id=workspace, user=SimpleNamespace(id=None), logger=logging.getLogger("test"))
    c._require_admin = lambda: None
    c._allow_workspace_credentials = lambda: True
    c._settings_row = lambda: AISettingsController._settings_row(c)
    c._effective_character = lambda row: None
    c._bubble_lines_state = lambda: AISettingsController._bubble_lines_state(c)
    c.patch = lambda **kw: AISettingsController.update_ai_settings(c, _update(**kw))
    c.edit = lambda **kw: AISettingsController.edit_bubble_lines(c, _lines(**kw))
    c.clear = lambda: AISettingsController.clear_bubble_lines(c)
    c.regenerate = lambda: AISettingsController.regenerate_bubble_lines(c)
    return c


def _update(**kw):
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    return WorkspaceAISettingsUpdate(**kw)


def _lines(**kw):
    from marvin.schemas.group.ai_settings import BubbleLines

    return BubbleLines(**kw)


def test_a_persona_change_regenerates_generated_lines(db_session, ctrl, started):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_GENERATED)

    ctrl.patch(persona_prompt=ADA + " Loves gardening.")

    assert started == [{"gid": ctrl.group_id, "force": False}]


def test_a_persona_change_leaves_edited_lines_alone(db_session, ctrl, started):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_EDITED)

    ctrl.patch(persona_prompt=ADA + " Loves gardening.")

    assert started == [] and _row(db_session, ctrl.group_id).bubble_lines == OLD


def test_saving_the_same_persona_with_lines_in_place_does_not_regenerate(db_session, ctrl, started):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_GENERATED)

    ctrl.patch(assistant_name="Ada", persona_prompt=ADA)

    assert started == []


def test_saving_a_persona_with_no_lines_yet_generates_them(ctrl, started):
    ctrl.patch(assistant_name="Ada", persona_prompt=ADA)

    assert len(started) == 1


def test_a_save_that_does_not_touch_the_persona_never_generates(ctrl, started):
    ctrl.patch(budget_config={"max_requests_per_day": 50})

    assert started == []


def test_clearing_the_persona_drops_generated_lines(db_session, ctrl, started):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_GENERATED)

    result = ctrl.patch(persona_prompt="")

    assert started == [] and result.bubble_lines is None and _row(db_session, ctrl.group_id).bubble_lines_source is None


def test_clearing_the_persona_keeps_edited_lines(db_session, ctrl, started):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_EDITED)

    ctrl.patch(persona_prompt="")

    assert _row(db_session, ctrl.group_id).bubble_lines == OLD


def test_editing_lines_marks_them_edited_and_drops_blank_rows(db_session, ctrl):
    state = ctrl.edit(greetings=["Hey y'all.", "  ", "What'll it be?"], emotes=["*waves*"])

    assert state.bubble_lines_source == "edited" and state.bubble_lines.greetings == ["Hey y'all.", "What'll it be?"]
    assert state.bubble_lines.taglines == []  # an empty list falls back to the built-in lines in the bubble


def test_editing_every_list_empty_goes_back_to_the_builtin_lines(db_session, ctrl):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_GENERATED)

    state = ctrl.edit(greetings=["   "])

    assert state.bubble_lines is None and state.bubble_lines_source is None


def test_editing_a_line_that_is_far_too_long_is_refused(ctrl):
    with pytest.raises(HTTPException) as exc:
        ctrl.edit(greetings=["x" * (bl.MAX_EDITED_CHARS + 1)])
    assert exc.value.status_code == 422


def test_clear_resets_to_the_builtin_lines(db_session, ctrl):
    _set_lines(db_session, ctrl.group_id, OLD, bl.SOURCE_EDITED)
    row = _row(db_session, ctrl.group_id)
    row.bubble_lines_warning = "stale"
    db_session.commit()

    state = ctrl.clear()

    assert (state.bubble_lines, state.bubble_lines_source, state.bubble_lines_updated_at, state.bubble_lines_warning) == (None, None, None, None)


def test_regenerate_starts_a_forced_generation(ctrl, started):
    state = ctrl.regenerate()

    assert started == [{"gid": ctrl.group_id, "force": True}] and state.bubble_lines_generating is False  # start is stubbed


def test_regenerate_when_budget_blocked_is_refused_with_the_reason(db_session, ctrl, started):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    row = _row(db_session, ctrl.group_id)
    row.budget_config = {"max_requests_per_day": 1}
    db_session.add(
        AIExecutionModel(
            session=db_session,
            group_id=ctrl.group_id,
            operation_slug="generate-summary",
            provider_type="openai",
            model_id="m",
            status="completed",
            trigger_type="api",
            created_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        ctrl.regenerate()

    assert exc.value.status_code == 429 and "Daily request limit" in exc.value.detail and started == []


def test_regenerate_without_a_persona_is_refused(db_session, ctrl, started):
    ctrl.patch(persona_prompt="")

    with pytest.raises(HTTPException) as exc:
        ctrl.regenerate()

    assert exc.value.status_code == 422 and started == []


def test_the_settings_the_bubble_reads_carry_the_lines(db_session, ctrl, workspace, monkeypatch):
    from marvin.routes.groups.ai_settings_controller import AISettingsController

    monkeypatch.setattr("marvin.services.ai.character_library.agent_characters", lambda session, gid: {})
    _set_lines(db_session, workspace, OLD, bl.SOURCE_GENERATED)

    result = AISettingsController.get_ai_settings(ctrl)

    dumped = result.model_dump(by_alias=True)
    assert dumped["bubbleLines"]["greetings"] == ["old hi"] and dumped["bubbleLinesSource"] == "generated"
