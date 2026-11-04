"""Speech an integration step returns is kept as an asset — the run carries references, never the audio data.

A fake `speech.synthesize` provider answers with base64 audio. The kept asset records how it was made (the text, the
voice, the duration); the step's output and the run's snapshot stay small. A `repeat` over lines makes one asset per
line — the loop a narrated story's text-to-speech step is.
"""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import base64
import json

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from tests.test_workflow_authoring import workspace, ws  # noqa: E402, F401 — fixtures
from tests.test_workflow_media import _entry, _fire, _last_run, _workflow, media  # noqa: E402, F401 — fixtures

AUDIO = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 64  # an MP3-looking blob; the type comes from the extension
AUDIO_B64 = base64.b64encode(AUDIO).decode()


class _Narrator(IntegrationProvider):
    slug = "wf_narrator"
    name = "Narrator"
    actions = (
        ProviderAction(key="say", label="Say", capability="speech.synthesize", input_schema={"properties": {"text": {"type": "string"}}}),
        ProviderAction(key="say_paid", label="Say (paid)", capability="speech.synthesize", requires_approval=True),
        ProviderAction(key="say_wav", label="Say (wav)", capability="speech.synthesize"),
        ProviderAction(key="say_odd", label="Say (odd)", capability="speech.synthesize"),
        ProviderAction(key="voices", label="Voices", input_schema={"properties": {}}),
        ProviderAction(key="sfx", label="Sound effect", capability="audio.sound_effect", input_schema={"properties": {"text": {"type": "string"}}}),
        ProviderAction(key="score", label="Music", capability="audio.music", input_schema={"properties": {"prompt": {"type": "string"}}}),
        ProviderAction(key="listen", label="Transcribe", capability="speech.transcribe"),
        ProviderAction(key="listen_paid", label="Transcribe (paid)", capability="speech.transcribe", requires_approval=True),
    )

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run_action(self, key, args, ctx):
        self.calls.append((key, args))
        usage = {"model": "tts-1", "total_tokens": 0}
        if key in ("say", "say_paid"):
            text = args.get("text", "")
            return {
                "audio_b64": AUDIO_B64,
                "mime": "audio/mpeg",
                "duration_seconds": 1.5,
                "characters": len(text),
                "voice_id": "v1",
                "usage": usage,
                "words": WORDS,
            }
        if key in ("sfx", "score"):
            return {"audio_b64": AUDIO_B64, "mime": "audio/mpeg", "duration_seconds": 3.0}
        if key in ("listen", "listen_paid"):
            return {"text": "Hello there", "words": [{"text": "Hello", "start": 0.0, "end": 0.4}]}
        if key == "say_wav":
            return {"audio_b64": AUDIO_B64, "mime": "audio/wav"}
        if key == "say_odd":
            return {"audio_b64": AUDIO_B64, "mime": "application/x-nothing"}
        return {"voices": [{"id": "v1", "name": "Old Salt"}]}


@pytest.fixture
def narrator(media, monkeypatch):
    provider = _Narrator()
    monkeypatch.setitem(INTEGRATION_REGISTRY, _Narrator.slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    media.session.add(
        IntegrationModel(session=media.session, group_id=media.gid, provider=_Narrator.slug, name="Narrator", slug="narrator", enabled=True)
    )
    media.session.commit()
    media.narrator = provider
    return media


def _kept(ws):
    from marvin.db.models.platform.assets import Assets

    rows = ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()
    return [a for a in rows if str((a.metadata_json or {}).get("derivation", "")).startswith("generated:")]


ON_PUBLISH = {"type": "event", "event": "entry_published"}


def _publish(ws, entry, correlation_id="corr-1"):
    _fire(ws, "entry_published", {"entry_id": str(entry.id)}, entity=entry.id, entity_type="entry", correlation_id=correlation_id)


def _say(**step):
    return {"kind": "integration", "id": "line", "integration": "narrator", "action": "say", **step}


WORDS = [{"text": "Two", "start": 0.0, "end": 0.3}, {"text": "scraps", "start": 0.35, "end": 0.8}]


def test_a_speech_assets_word_timings_are_kept_on_the_asset(narrator):
    """A take's timings belong to that take: picking another recording for an entry must bring its own timings with it."""
    entry = _entry(narrator, "Beat 03")
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": [_say(args={"text": "Two scraps of pork. One onion."})]})

    _publish(narrator, entry)

    (asset,) = _kept(narrator)
    assert asset.metadata_json["words"] == WORDS


def test_word_timings_that_are_odd_or_far_too_many_are_left_out():
    from marvin.services.automation.actions import media

    assert media.speech_facts({"words": "no"}) == {} and media.speech_facts({"words": []}) == {}
    assert media.speech_facts({"words": [1, 2]}) == {}
    assert media.speech_facts({"words": [{"text": "x"}] * (media.MAX_KEPT_WORDS + 1)}) == {}
    assert media.speech_facts({"duration_seconds": 2.0, "words": WORDS}) == {"duration_seconds": 2.0, "words": WORDS}


def test_speech_becomes_an_audio_asset_and_the_run_keeps_a_reference(narrator):
    entry = _entry(narrator, "Beat 03")
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": [_say(args={"text": "Two scraps of pork. One onion."})]})

    _publish(narrator, entry)

    (asset,) = _kept(narrator)
    assert (asset.mime_type, asset.asset_type, asset.extension) == ("audio/mpeg", "audio", "mp3")
    assert asset.name == "Two scraps of pork. One onion."  # a line is named for what it says
    meta = asset.metadata_json
    assert meta["generated_by"] == "wf_narrator.say" and meta["text"] == "Two scraps of pork. One onion." and meta["duration_seconds"] == 1.5
    assert (
        meta["characters"] == len("Two scraps of pork. One onion.")
        and meta["voice_id"] == "v1"
        and meta["made_for_entry"] == str(entry.id)
        and "derived_from" not in meta
    )
    output = _last_run(narrator).actions[0].output_snapshot
    assert output["asset"]["id"] == str(asset.id) and output["asset"]["duration_seconds"] == 1.5 and output["asset"]["mime_type"] == "audio/mpeg"
    assert "audio_b64" not in json.dumps(output) and len(json.dumps(output)) < 2048
    assert output["usage"]["model"] == "tts-1"


def test_a_repeat_over_lines_makes_one_asset_per_line_and_a_redelivery_makes_none_again(narrator):
    entry = _entry(narrator)
    lines = ["Your feast.", "Make do.", "Breakfast."]
    repeat = {
        "kind": "repeat",
        "id": "lines",
        "for_each": lines,
        "as": "line",
        "steps": [_say(id="speak", name="${each.number}", args={"text": "${line}"})],
    }
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": [repeat]})

    _publish(narrator, entry)
    _publish(narrator, entry)  # the same event again: nothing new

    assert sorted(a.metadata_json["text"] for a in _kept(narrator)) == sorted(lines)
    assert len({a.slug for a in _kept(narrator)}) == 3
    assert [args["text"] for _, args in narrator.narrator.calls][:3] == lines


def test_a_new_event_makes_new_audio(narrator):
    entry = _entry(narrator)
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": [_say(args={"text": "Hello"})]})
    _publish(narrator, entry)
    _publish(narrator, entry, correlation_id="corr-2")
    assert len(_kept(narrator)) == 2


def test_attach_as_links_the_audio_to_the_entry(narrator):
    from marvin.db.models.platform.entry_assets import EntryAssets

    entry = _entry(narrator, "Line")
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": [_say(attach_as="audio", args={"text": "Hello"})]})

    _publish(narrator, entry)

    (asset,) = _kept(narrator)
    assert narrator.session.query(EntryAssets).filter_by(entry_id=entry.id, asset_id=asset.id).one().role == "audio"


def test_wav_is_kept_as_wav_and_a_type_that_isnt_audio_fails_the_step(narrator):
    entry = _entry(narrator)
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": [_say(action="say_wav", args={"text": "x"})]})
    _publish(narrator, entry)
    (asset,) = _kept(narrator)
    assert (asset.mime_type, asset.extension) == ("audio/x-wav", "wav") or asset.extension == "wav"

    from marvin.services.automation.actions.base import AutomationActionError
    from marvin.services.automation.actions.media import keep_generated_audio

    with pytest.raises(AutomationActionError, match="isn't audio Marvin keeps"):
        keep_generated_audio(
            narrator.session,
            narrator.gid,
            {"audio_b64": AUDIO_B64, "mime": "application/x-nothing"},
            generated_by="wf_narrator.say_odd",
            args={"text": "x"},
            context={"_step": {"workflow": "w", "index": 0}, "entry": {"id": str(entry.id), "title": "t"}},
            user_id=narrator.uid,
        )


def test_a_dry_run_says_the_audio_would_be_kept_and_calls_nothing(narrator):
    from marvin.services.automation.engine import run_automation_now

    wf = _workflow(
        narrator,
        {"trigger": {"type": "manual"}, "target": {"entity": "entry", "query": {}}, "actions": [_say(attach_as="audio", args={"text": "x"})]},
    )
    _entry(narrator)

    result = run_automation_now(narrator.session, narrator.gid, wf, user_id=narrator.uid, dry_run=True)

    (row,) = result["plan"]
    assert row["resolved"]["keeps_audio_as_asset"] is True and row["resolved"]["attach_as"] == "audio"
    assert narrator.narrator.calls == [] and _kept(narrator) == []


def test_a_paid_speech_action_needs_an_approval_step_in_the_draft(narrator):
    from marvin.services.automation.authoring import draft_issues

    step = _say(action="say_paid", args={"text": "x"})
    issues = draft_issues(narrator.session, narrator.gid, {"trigger": ON_PUBLISH, "actions": [step]})
    assert any("Approval step" in i["message"] for i in issues), issues


def test_attach_as_is_allowed_on_speech_but_source_is_not(narrator):
    from marvin.services.automation.authoring import draft_issues

    ok = draft_issues(narrator.session, narrator.gid, {"trigger": ON_PUBLISH, "actions": [_say(attach_as="audio", args={"text": "x"})]})
    assert not [i for i in ok if i.get("path") == "actions[0].attach_as"], ok
    bad = draft_issues(narrator.session, narrator.gid, {"trigger": ON_PUBLISH, "actions": [_say(source="${asset.id}", args={"text": "x"})]})
    assert any(i.get("path") == "actions[0].source" for i in bad), bad
    other = draft_issues(
        narrator.session,
        narrator.gid,
        {"trigger": ON_PUBLISH, "actions": [{"kind": "integration", "integration": "narrator", "action": "voices", "attach_as": "x"}]},
    )
    assert any(i.get("path") == "actions[0].attach_as" for i in other), other


def test_sound_effects_and_music_are_kept_as_audio_assets_named_for_their_description(narrator):
    entry = _entry(narrator)
    steps = [
        {"kind": "integration", "id": "chop", "integration": "narrator", "action": "sfx", "args": {"text": "knife chopping an onion"}},
        {"kind": "integration", "id": "theme", "integration": "narrator", "action": "score", "args": {"prompt": "a sea shanty on a fiddle"}},
    ]
    _workflow(narrator, {"trigger": ON_PUBLISH, "actions": steps})

    _publish(narrator, entry)

    kept = {a.name: a for a in _kept(narrator)}
    assert set(kept) == {"knife chopping an onion", "a sea shanty on a fiddle"}
    assert {a.metadata_json["generated_by"] for a in kept.values()} == {"wf_narrator.sfx", "wf_narrator.score"}
    assert all(a.asset_type == "audio" and a.metadata_json["duration_seconds"] == 3.0 for a in kept.values())


def test_a_transcribe_step_is_handed_the_audio_asset_and_answers_text_with_nothing_kept(narrator):
    from tests.test_workflow_media import _stored

    line = _stored(narrator, "line", AUDIO, mime="audio/mpeg")
    entry = _entry(narrator)
    _workflow(
        narrator,
        {
            "trigger": ON_PUBLISH,
            "actions": [{"kind": "integration", "id": "ear", "integration": "narrator", "action": "listen", "source": line.slug}],
        },
    )

    _publish(narrator, entry)

    (key, args) = narrator.narrator.calls[0]
    assert key == "listen" and base64.b64decode(args["audio_b64"]) == AUDIO and args["audio_mime"] == "audio/mpeg" and "image_b64" not in args
    out = _last_run(narrator).actions[0].output_snapshot
    assert out["text"] == "Hello there" and "asset" not in out and _kept(narrator) == []


def test_a_transcribe_source_that_is_not_audio_or_video_is_refused(narrator):
    from tests.test_workflow_media import _png, _stored

    picture = _stored(narrator, "photo", _png())
    entry = _entry(narrator)
    _workflow(
        narrator,
        {
            "trigger": ON_PUBLISH,
            "actions": [{"kind": "integration", "id": "ear", "integration": "narrator", "action": "listen", "source": picture.slug}],
        },
    )

    _publish(narrator, entry)

    assert narrator.narrator.calls == []
    run = _last_run(narrator)
    assert run.status == "failed" and "is not audio or video" in run.actions[0].error


def test_every_paid_audio_capability_wants_an_approval_step_but_a_free_transcribe_does_not(narrator):
    from marvin.services.automation.authoring import draft_issues

    def issues(action, **extra):
        step = {"kind": "integration", "integration": "narrator", "action": action, **extra}
        return draft_issues(narrator.session, narrator.gid, {"trigger": ON_PUBLISH, "actions": [step]})

    assert any("Approval step" in i["message"] for i in issues("listen_paid", source="${asset.id}"))
    assert not [i for i in issues("listen", source="${asset.id}") if i.get("path") == "actions[0].source"]
    assert any(i.get("path") == "actions[0].attach_as" for i in issues("listen", source="${asset.id}", attach_as="x"))
    assert not [i for i in issues("sfx", attach_as="sound", args={"text": "x"}) if i.get("path") == "actions[0].attach_as"]
