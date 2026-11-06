"""An integration step's paid call is written to AI executions under the provider's name, and only when the provider reports usage."""

import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.groups import Groups
from marvin.services.integrations import usage_log

SPEECH = {"audio_b64": "x", "usage": {"provider_type": "elevenlabs", "model": "eleven_v3", "characters": 120, "multiplier": 0.5}}


@fixture
def group(db_session):
    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"ul-{gid.hex[:8]}", slug=f"ul-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(AIExecutionModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _integration():
    return SimpleNamespace(provider="elevenlabs", slug="elevenlabs-v3", id=uuid.uuid4())


def test_a_call_with_usage_is_recorded_as_the_provider_with_what_it_used(db_session, group):
    usage_log.record_call(db_session, group, _integration(), "speech.synthesize", SPEECH, elapsed_ms=900)
    db_session.commit()

    [row] = db_session.query(AIExecutionModel).filter_by(group_id=group).all()
    assert (row.provider_type, row.model_id, row.operation_slug, row.trigger_type) == ("elevenlabs", "eleven_v3", "speech.synthesize", "integration")
    assert row.estimated_cost_usd is None
    assert row.metadata_json["units"] == 120 and row.metadata_json["multiplier"] == 0.5 and row.metadata_json["integration"] == "elevenlabs-v3"


@pytest.mark.parametrize("out", [{"audio_b64": "x"}, {"usage": "nope"}, None, []])
def test_a_call_that_reports_no_usage_leaves_no_row(db_session, group, out):
    usage_log.record_call(db_session, group, _integration(), "speech.synthesize", out)
    db_session.commit()

    assert db_session.query(AIExecutionModel).filter_by(group_id=group).count() == 0


def test_a_provider_with_no_characters_is_counted_as_one_call():
    assert usage_log.units_used({"provider_type": "openai_images"}) == ("calls", 1)
    assert usage_log.units_used({"characters": "30"}) == ("characters", 30)


def test_what_was_sent_and_what_came_back_are_kept_without_the_audio(db_session, group):
    sent = {"text": "x" * 5000, "voice_id": "v1", "audio_b64": "QUJD" * 100}
    answer = {**SPEECH, "audio_b64": "QUJD" * 1000, "words": [{"text": "a"}] * 120}
    usage_log.record_call(db_session, group, _integration(), "speech.synthesize", answer, args=sent)
    db_session.commit()

    [row] = db_session.query(AIExecutionModel).filter_by(group_id=group).all()
    assert row.input_json["args"]["voice_id"] == "v1"
    assert row.input_json["args"]["text"].startswith("xxx") and "5,000 characters" in row.input_json["args"]["text"]
    assert len(row.input_json["args"]["text"]) < 2100  # cut, not kept whole
    assert row.input_json["args"]["audio_b64"] == "‹300 bytes›"  # a size note, never the bytes
    assert row.output_json["audio_b64"] == "‹3,000 bytes›" and row.output_json["usage"]["multiplier"] == 0.5
    assert len(row.output_json["words"]) == 51 and row.output_json["words"][-1] == "‹70 more›"


def test_a_call_with_no_arguments_keeps_no_input(db_session, group):
    usage_log.record_call(db_session, group, _integration(), "speech.synthesize", SPEECH)
    db_session.commit()
    [row] = db_session.query(AIExecutionModel).filter_by(group_id=group).all()
    assert row.input_json is None and row.output_json["usage"]["characters"] == 120
