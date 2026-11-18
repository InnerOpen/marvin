"""A video an integration step returns is kept as an asset (services/automation/actions/media.py: keep_generated_video), the
way speech and pictures are: the run carries a reference, never the video's bytes.

A fake `video.from_image` provider stands in for ElevenLabs' `make_video` (marvin-integration-elevenlabs 0.4.0): it answers
with base64 MP4 bytes, or raises the codes the real one raises (`still_generating` with the generation it is waiting on,
`moderated`). Nothing here calls a real service.

The retry half pins down what the Studio's moving-shot workflow relies on: a workflow that starts on
`gen_video_status changed_to queued` is still that workflow on its retry (the retry re-checks its conditions against the
event it started from, kept in the snapshot, and the entry as it is now), and an edit to the beat while it waits starts no
second run.
"""

# ruff: noqa: F811 — `ws` and `media` are fixtures, not redefinitions
import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, Handle, IntegrationError, IntegrationProvider, ProviderAction, Retry  # noqa: E402

from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from tests.test_workflow_authoring import workspace, ws  # noqa: E402, F401 — fixtures
from tests.test_workflow_media import _entry, _png, _stored, _workflow, media  # noqa: E402, F401 — fixtures

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64  # an MP4-looking blob; the type comes from the mime
MP4_B64 = base64.b64encode(MP4).decode()


class _Moviemaker(IntegrationProvider):
    slug = "wf_moviemaker"
    name = "Moviemaker"
    actions = (
        ProviderAction(
            key="make",
            label="Make a video",
            capability="video.from_image",
            cost_hint="paid",
            requires_approval=True,
            error_policy={"still_generating": Handle(retry=Retry((60, 120), max_attempts=4)), "moderated": Handle()},
        ),
        ProviderAction(key="say", label="Say", capability="speech.synthesize"),
    )

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.contexts: list = []
        self.failures: list = []
        self.video = MP4_B64

    def run_action(self, key, args, ctx):
        self.calls.append((key, args))
        self.contexts.append(ctx)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        if key == "say":
            return {"audio_b64": base64.b64encode(b"ID3" + b"\x00" * 32).decode(), "mime": "audio/mpeg"}
        return {
            "video_b64": self.video,
            "mime": "video/mp4",
            "duration_seconds": 6,
            "model_id": "veo-3.1-fast-generate-001",
            "resolution": "720p",
            "generate_audio": False,
            "generation_id": "gen-1",
            "usage": {"provider_type": "moviemaker", "model": "veo-3.1-fast-generate-001", "total_tokens": 0},
        }


@pytest.fixture
def movies(media, monkeypatch):
    provider = _Moviemaker()
    monkeypatch.setitem(INTEGRATION_REGISTRY, _Moviemaker.slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    media.session.add(
        IntegrationModel(session=media.session, group_id=media.gid, provider=_Moviemaker.slug, name="Movies", slug="movies", enabled=True)
    )
    media.session.commit()
    media.movies = provider
    yield media
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel, IntegrationRetryModel
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel

    media.session.rollback()
    for model in (IntegrationRetryModel, IntegrationAlertModel, WorkflowApprovalModel):
        media.session.query(model).filter(model.group_id == media.gid).delete(synchronize_session=False)
    media.session.commit()


def _kept_videos(ws):
    from marvin.db.models.platform.assets import Assets

    rows = ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()
    return [a for a in rows if str((a.metadata_json or {}).get("derivation", "")).startswith("generated:") and a.mime_type == "video/mp4"]


def _retries(ws):
    from marvin.db.models.groups.integration_errors import IntegrationRetryModel

    return ws.session.query(IntegrationRetryModel).filter_by(group_id=ws.gid).all()


def _pending(ws):
    from marvin.services.automation import approvals
    from marvin.services.automation.authz import ROLE_ADMIN

    return approvals.pending(ws.session, ws.gid, ROLE_ADMIN)


def _approve(ws, row):
    from marvin.services.automation import approvals
    from marvin.services.automation.authz import ROLE_ADMIN

    return approvals.decide(ws.session, ws.gid, row.id, "approve", user_id=ws.uid, role=ROLE_ADMIN)


def _retry_now(ws):
    """Make the pending retry due, claim it like the sweep does, and run it."""
    from marvin.services.automation.engine import run_retry
    from marvin.services.automation.recorder import ExecutionRecorder
    from marvin.services.integrations import errors

    (row,) = [r for r in _retries(ws) if r.status == "pending"]
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    ws.session.commit()
    (claimed,) = errors.claim_due(ws.session)
    outcome = run_retry(ws.session, ws.gid, claimed, recorder=ExecutionRecorder(ws.session, ws.gid))
    ws.session.expire_all()
    return outcome


# ── `changed_to` on a retry: the open check behind the Studio's moving shot ──────────────────────────────────────────

MAKE_VIDEO = {
    "trigger": {"type": "event", "event": "entry_updated"},
    # Starts on the change, not on the value: an edit to the beat while its card waits (up to 72 h) starts no second run.
    "conditions": [
        {"field": "entry.data.gen_video_status", "op": "changed_to", "value": "queued"},
        {"field": "entry.data.still", "op": "longer_than", "value": 0},
    ],
    "actions": [
        {"kind": "approval", "id": "spend", "message": "Make a moving shot?", "fields": [{"name": "prompt", "value": "slow push-in"}]},
        {
            "kind": "integration",
            "id": "make",
            "integration": "movies",
            "action": "make",
            "source": "${entry.data.still}",
            "args": {"prompt": "${steps.spend.output.fields.prompt}", "duration_seconds": 6, "resolution": "720p", "generate_audio": False},
        },
    ],
}


def _update(ws, entry, **data):
    """Change the entry's data the way the app does (EntryService.update), then run the workflows on the entry_updated
    event it really sent — its own changed_fields / before / after, not a hand-made one."""
    from fastapi.encoders import jsonable_encoder

    from marvin.db.models.platform.entries import Entries
    from marvin.services.automation.context import event_context
    from marvin.services.automation.engine import run_automations_for_event
    from marvin.services.automation.recorder import ExecutionRecorder
    from marvin.services.entries.entry_service import EntryService

    ws.sent.clear()
    current = dict(ws.session.get(Entries, entry.id).data_json or {})
    EntryService(ws.session, ws.gid, actor_id=ws.uid).update(entry.id, {"data_json": {**current, **data}})
    ws.session.commit()
    (doc,) = [d for name, d in ws.sent if name == "entry_updated"]
    document = jsonable_encoder(doc, by_alias=False) if not isinstance(doc, dict) else doc
    ctx = event_context("entry_updated", document, entity_id=entry.id, entity_type="entry", user_id=ws.uid, correlation_id=uuid.uuid4().hex)
    run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))
    ws.session.expire_all()
    return ctx


def _beat(movies):
    still = _stored(movies, "still", _png())
    entry = _entry(movies, "Beat 04")
    entry.data_json = {"still": str(still.id), "gen_video_status": "draft", "direction": "Grace looks up"}
    movies.session.commit()
    return entry, still


def _waiting_on_a_generation(movies):
    """A beat queued for a moving shot, approved, whose generation is still running when the call gives up."""
    entry, still = _beat(movies)
    _workflow(movies, MAKE_VIDEO, slug="make-beat-video")
    event = _update(movies, entry, gen_video_status="queued")
    assert event["after"]["data"]["gen_video_status"] == "queued"  # the event the bus really sends
    (spend,) = _pending(movies)
    movies.movies.failures = [IntegrationError("still generating", code="still_generating", partial={"generation_id": "gen-1"}, retry_after=60)]
    _approve(movies, spend)
    (row,) = _retries(movies)
    assert row.status == "pending" and row.partial == {"generation_id": "gen-1"}
    return entry, still, row


def test_a_changed_to_workflow_still_matches_on_its_retry_and_an_edit_meanwhile_starts_no_second_run(movies):
    entry, still, row = _waiting_on_a_generation(movies)
    # The retry keeps the run's event (with its before/after) and its approval.
    assert row.snapshot["event"]["after"]["data"]["gen_video_status"] == "queued" and row.snapshot.get("approved") is True
    assert row.snapshot["gated"] is True  # so the retry re-checks the conditions (it is not let through unchecked)

    _update(movies, entry, direction="Grace looks up, then away")  # an edit while it generates

    assert _pending(movies) == []  # no second spend card: the status did not change this time
    assert _retry_now(movies) == "succeeded"
    first, retried = movies.movies.contexts
    assert retried.resume == {"generation_id": "gen-1"}  # it polls the generation it paid for, never starts another
    assert retried.idempotency_seed == first.idempotency_seed
    (row,) = _retries(movies)
    assert row.status == "succeeded"


def test_a_retry_is_superseded_once_the_beat_no_longer_has_its_still(movies):
    entry, _, _ = _waiting_on_a_generation(movies)

    _update(movies, entry, still="")

    assert _retry_now(movies) == "superseded"
    assert len(movies.movies.calls) == 1  # the retry made no call


def test_with_eq_queued_beside_changed_to_a_beat_set_back_to_draft_meanwhile_is_not_made(movies):
    """`changed_to` reads the event the run started from, so on its own it still holds on the retry after the beat was set
    back to draft; `eq queued` beside it reads the beat as it is now, and the retry stands down."""
    entry, _ = _beat(movies)
    both = {**MAKE_VIDEO, "conditions": [*MAKE_VIDEO["conditions"], {"field": "entry.data.gen_video_status", "op": "eq", "value": "queued"}]}
    _workflow(movies, both, slug="make-beat-video")
    _update(movies, entry, gen_video_status="queued")
    movies.movies.failures = [IntegrationError("still generating", code="still_generating", partial={"generation_id": "gen-1"})]
    _approve(movies, _pending(movies)[0])

    _update(movies, entry, gen_video_status="draft")

    assert _pending(movies) == [] and _retry_now(movies) == "superseded"


# ── keeping the video ────────────────────────────────────────────────────────────────────────────────────────────────


def _make(**step):
    return {"kind": "integration", "id": "make", "integration": "movies", "action": "make", **step}


def _approved_run(movies, steps, entry=None):
    entry = entry or _entry(movies, "Beat 05")
    _workflow(
        movies,
        {"trigger": {"type": "event", "event": "entry_published"}, "actions": [{"kind": "approval", "id": "spend", "message": "Make it?"}, *steps]},
    )
    from tests.test_workflow_media import _fire

    _fire(movies, "entry_published", {"entry_id": str(entry.id)}, entity=entry.id, entity_type="entry", correlation_id=uuid.uuid4().hex)
    _approve(movies, _pending(movies)[0])
    return entry


def test_a_video_becomes_a_video_asset_and_the_run_keeps_a_reference_and_its_facts(movies):
    still = _stored(movies, "still", _png())
    _approved_run(movies, [_make(source=str(still.id), args={"prompt": "Slow push-in on the onion", "duration_seconds": 6})])

    (video,) = _kept_videos(movies)
    assert (video.mime_type, video.asset_type, video.extension) == ("video/mp4", "video", "mp4")
    assert video.name == "Slow push-in on the onion"
    meta = video.metadata_json
    assert meta["generated_by"] == "wf_moviemaker.make" and meta["prompt"] == "Slow push-in on the onion" and meta["made_from"] == str(still.id)
    assert (meta["duration_seconds"], meta["model_id"], meta["resolution"], meta["generate_audio"]) == (6, "veo-3.1-fast-generate-001", "720p", False)
    assert "derived_from" not in meta  # a clip is not another version of its still
    # The still went to the provider as the picture to start from, for this call only.
    (key, args) = movies.movies.calls[0]
    assert args["image_mime"] == "image/png" and base64.b64decode(args["image_b64"]) == _png()
    from tests.test_workflow_media import _last_run

    output = _last_run(movies).actions[-1].output_snapshot
    assert output["asset"]["id"] == str(video.id) and output["asset"]["duration_seconds"] == 6 and output["asset"]["mime_type"] == "video/mp4"
    assert output["asset"]["url"].split("?")[0].endswith(".mp4")  # what a Keep card's `image` plays as a video (lib/approvalMedia.ts)
    assert output["model_id"] == "veo-3.1-fast-generate-001" and output["resolution"] == "720p" and output["generation_id"] == "gen-1"
    assert "video_b64" not in json.dumps(output) and "image_b64" not in json.dumps(output) and len(json.dumps(output)) < 2048


def test_a_video_over_the_old_5_mb_response_cap_is_downloaded_and_kept(movies):
    big = MP4 + b"\x00" * 6_000_000  # a few seconds of 720p: more than an API answer may be
    movies.movies.video = base64.b64encode(big).decode()

    _approved_run(movies, [_make(args={"prompt": "Rain on the window"})])

    (video,) = _kept_videos(movies)
    assert video.file_size == len(big) > 5_000_000
    from marvin.services.automation.actions.media import max_video_bytes

    assert movies.movies.contexts[0].http._max_bytes == max_video_bytes() == 100 * 1024 * 1024  # the asset cap, for this call


def test_the_raised_cap_is_for_video_actions_only(movies):
    _workflow(
        movies,
        {
            "trigger": {"type": "event", "event": "entry_published"},
            "actions": [{"kind": "integration", "id": "say", "integration": "movies", "action": "say"}],
        },
    )
    entry = _entry(movies)
    from tests.test_workflow_media import _fire

    _fire(movies, "entry_published", {"entry_id": str(entry.id)}, entity=entry.id, entity_type="entry", correlation_id=uuid.uuid4().hex)

    assert movies.movies.contexts[0].http._max_bytes == 5_000_000  # INTEGRATION_HTTP_MAX_BYTES, as before


def test_the_http_client_takes_a_body_past_the_usual_cap_only_when_raised(monkeypatch):
    from marvin.services.integrations import http_client

    class _Resp:
        status, headers = 200, {"Content-Type": "video/mp4"}

        def __init__(self, body):
            self.body = body

        def read(self, n):
            return self.body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = b"\x00" * 6_000_000
    monkeypatch.setattr(http_client, "_guard", lambda url, hosts=None: None)  # no DNS in a unit test
    usual, raised = http_client.build_http(), http_client.build_http(max_bytes=100 * 1024 * 1024)
    for helper in (usual, raised):
        monkeypatch.setattr(helper._opener, "open", lambda req, timeout=None: _Resp(body))

    with pytest.raises(ValueError, match="size cap"):
        usual.get("https://cdn.example.test/clip.mp4")
    assert len(raised.get("https://cdn.example.test/clip.mp4").content) == len(body)


def test_a_moderated_generation_fails_the_step_with_the_providers_reason_and_is_not_retried(movies):
    """A failed or moderated generation is not charged (ElevenLabs); the step fails with its message and code, which an
    `on_failure` step reads as `error.message` / `error.code`."""
    movies.movies.failures = [
        IntegrationError("ElevenLabs declined it: moderated (the prompt or picture broke its content policy)", code="moderated")
    ]
    on_failure = [
        {"kind": "entry", "op": "set_data", "data": {"gen_video_status": "draft", "gen_video_error": "${error.message}", "code": "${error.code}"}}
    ]
    entry = _entry(movies, "Beat 06")
    _workflow(
        movies,
        {
            "trigger": {"type": "event", "event": "entry_published"},
            "actions": [{"kind": "approval", "id": "spend", "message": "Make it?"}, _make(args={"prompt": "x"})],
            "on_failure": on_failure,
        },
    )
    from tests.test_workflow_media import _fire

    _fire(movies, "entry_published", {"entry_id": str(entry.id)}, entity=entry.id, entity_type="entry", correlation_id=uuid.uuid4().hex)
    _approve(movies, _pending(movies)[0])

    from marvin.db.models.platform.entries import Entries

    movies.session.expire_all()
    data = movies.session.get(Entries, entry.id).data_json
    assert data["gen_video_status"] == "draft" and data["code"] == "moderated" and "moderated" in data["gen_video_error"]
    assert [r for r in _retries(movies) if r.status == "pending"] == [] and _kept_videos(movies) == []


def test_source_goes_with_a_video_action_and_references_do_not():
    from marvin.services.automation.authoring import _picture_fields_issue

    actions = [{"action": "make", "capability": "video.from_image"}]
    said: list = []
    _picture_fields_issue({"source": "${entry.data.still}", "attach_as": "clip"}, actions, "movies", "make", lambda f, m: said.append(f))
    assert said == []
    _picture_fields_issue({"references": ["a"]}, actions, "movies", "make", lambda f, m: said.append(f))
    assert said == ["references"]


# ── the real plugin, end to end, against a stub of ElevenLabs (runs where the plugins group is installed) ──────────────


def test_the_elevenlabs_plugin_makes_a_kept_video_through_the_step(movies, monkeypatch):
    elevenlabs = pytest.importorskip("marvin_integration_elevenlabs", reason="the ElevenLabs plugin isn't installed (uv sync --group plugins)")
    if not hasattr(elevenlabs.ElevenLabsProvider, "estimate_cost"):
        pytest.skip("the installed ElevenLabs plugin predates make_video (0.4.0)")
    from marvin_integration_sdk import Response

    from marvin.services.integrations.estimate import approval_estimate

    clip = MP4 + b"\x00" * 6_000_000
    seen: dict = {"max_bytes": [], "cdn_headers": [], "posts": []}

    class _ElevenLabs:
        def get(self, url, *, headers=None, timeout=15):
            if url.endswith("/v1/user/subscription"):
                return Response(status_code=200, content=b'{"character_count": 100, "character_limit": 600000}')
            if url.startswith("https://cdn."):
                seen["cdn_headers"].append(dict(headers or {}))
                return Response(status_code=200, content=clip)
            done = {"id": "gen-9", "status": "completed", "content_url": "https://cdn.example.test/c.mp4?sig=x", "content_mime_type": "video/mp4"}
            return Response(status_code=200, content=json.dumps(done).encode())

        def post(self, url, *, json=None, data=None, headers=None, timeout=15):
            seen["posts"].append(json)
            return Response(status_code=200, content=b'{"id": "gen-9", "status": "pending"}')

    def build_http(max_bytes=None):
        seen["max_bytes"].append(max_bytes)
        return _ElevenLabs()

    monkeypatch.setattr("marvin.services.integrations.build_http", build_http)
    monkeypatch.setattr("marvin_integration_elevenlabs.video._wait", lambda s: None)
    monkeypatch.setitem(INTEGRATION_REGISTRY, "elevenlabs", elevenlabs.ElevenLabsProvider())
    movies.session.add(
        IntegrationModel(
            session=movies.session,
            group_id=movies.gid,
            provider="elevenlabs",
            name="ElevenLabs",
            slug="elevenlabs",
            enabled=True,
            secret_ref="ELEVENLABS_TOKEN",
        )
    )
    movies.session.commit()
    still = _stored(movies, "still", _png())
    make = {
        "kind": "integration",
        "id": "make",
        "integration": "elevenlabs",
        "action": "make_video",
        "source": str(still.id),
        "args": {
            "prompt": "slow push-in",
            "duration_seconds": 5,
            "model_id": "veo-3.1-fast-generate-001",
            "resolution": "720p",
            "generate_audio": False,
        },
    }
    entry = _entry(movies, "Beat 07")
    _workflow(
        movies,
        {"trigger": {"type": "event", "event": "entry_published"}, "actions": [{"kind": "approval", "id": "spend", "message": "Make it?"}, make]},
    )
    from tests.test_workflow_media import _fire, _last_run

    _fire(movies, "entry_published", {"entry_id": str(entry.id)}, entity=entry.id, entity_type="entry", correlation_id=uuid.uuid4().hex)
    (spend,) = _pending(movies)
    estimate = approval_estimate(movies.session, spend)
    assert spend.paid is True and estimate["items"][0]["guess"] is True and "ElevenLabs publishes no price" in estimate["text"]

    _approve(movies, spend)

    (video,) = _kept_videos(movies)
    assert video.file_size == len(clip) and video.metadata_json["duration_seconds"] == 6 and video.metadata_json["generation_id"] == "gen-9"
    (body,) = seen["posts"]
    assert body["duration_secs"] == 6 and body["generate_audio"] is False and body["start_frame"]["mime_type"] == "image/png"
    assert all("xi-api-key" not in h for h in seen["cdn_headers"]) and 100 * 1024 * 1024 in seen["max_bytes"]
    output = _last_run(movies).actions[-1].output_snapshot
    assert output["asset"]["id"] == str(video.id) and output["duration_seconds"] == 6 and "sig=x" not in json.dumps(output)
