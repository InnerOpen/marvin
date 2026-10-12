"""A workflow's media step: images made from images, kept as new assets with their lineage, originals untouched.

The ops are Pillow on synthetic pictures (sizes, aspect maths, formats, sharpness, palette); the step runs through the
real engine on a workspace whose storage is a temporary local folder — chaining, attaching, dry runs, reuse, `when`
on an inspection, and no `asset_uploaded` for a derivative (so an "image added" workflow can't feed itself).
"""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import hashlib
import io
import uuid

import pytest
from PIL import Image, ImageDraw, ImageFilter

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.services.ai.media import ops, transforms
from marvin.services.automation.actions.media import derivative_slug, parse_aspect
from marvin.services.automation.authoring import draft_issues
from marvin.services.automation.context import event_context
from marvin.services.automation.engine import run_automation_now, run_automations_for_event
from marvin.services.automation.matcher import matches
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures


def _png(size=(400, 300), color=(200, 40, 40), mode="RGB", fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format=fmt)
    return out.getvalue()


def _halves(size=(400, 300)) -> bytes:
    """Left half red, right half blue — where a crop came from shows in its colour."""
    img = Image.new("RGB", size, (0, 0, 255))
    ImageDraw.Draw(img).rectangle((0, 0, size[0] // 2 - 1, size[1]), fill=(255, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _checker(size=(300, 300), blur=0) -> bytes:
    img = Image.new("L", size, 0)
    draw = ImageDraw.Draw(img)
    for x in range(0, size[0], 10):
        for y in range(0, size[1], 10):
            if (x // 10 + y // 10) % 2:
                draw.rectangle((x, y, x + 9, y + 9), fill=255)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# ── The ops ───────────────────────────────────────────────────────────────────
class TestOps:
    def test_resize_inside_keeps_the_shape_and_never_upscales(self):
        assert _open(ops.resize(_png(), width=200)).size == (200, 150)
        assert _open(ops.resize(_png(), height=30)).size == (40, 30)
        assert _open(ops.resize(_png(), width=200, height=50)).size == (67, 50)  # the tighter side wins
        assert _open(ops.resize(_png(), width=1600)).size == (400, 300)

    def test_resize_cover_fills_the_box_and_trims_without_upscaling(self):
        assert _open(ops.resize(_png(), width=100, height=100, fit="cover")).size == (100, 100)
        assert _open(ops.resize(_png(), width=800, height=800, fit="cover")).size == (300, 300)  # square, not upscaled

    def test_crop_takes_the_largest_window_of_the_aspect_and_follows_the_focus(self):
        assert _open(transforms.crop_to_aspect(_png(), (1, 1))).size == (300, 300)
        assert _open(transforms.crop_to_aspect(_png(), (4, 5))).size == (240, 300)
        assert _open(transforms.crop_to_aspect(_png(), (16, 9))).size == (400, 225)
        left = _open(transforms.crop_to_aspect(_halves(), (1, 2), focus=(0.1, 0.5))).convert("RGB")
        right = _open(transforms.crop_to_aspect(_halves(), (1, 2), focus=(0.9, 0.5))).convert("RGB")
        assert left.getpixel((10, 10)) == (255, 0, 0) and right.getpixel((140, 10)) == (0, 0, 255)
        assert transforms.aspect_box((400, 300), (1, 1), focus=(1.0, 1.0)) == (100, 0, 400, 300)  # kept in bounds

    def test_aspect_spellings(self):
        assert parse_aspect("4:5") == parse_aspect("4x5") == parse_aspect(" 4 / 5 ") == (4, 5)
        assert parse_aspect("0:5") is None and parse_aspect("square") is None

    def test_convert_sets_the_format_and_jpeg_flattens_transparency_onto_white(self):
        webp = ops.convert(_png(), "webp")
        assert ops.format_of(webp) == "webp" and _open(webp).format == "WEBP"
        jpeg = ops.convert(_png(mode="RGBA", color=(0, 0, 0, 0)), "jpeg", quality=70)
        assert ops.format_of(jpeg) == "jpeg" and _open(jpeg).convert("RGB").getpixel((5, 5)) == (255, 255, 255)

    def test_sharpness_ranks_a_blurred_picture_below_a_sharp_one(self):
        sharp = ops.inspect(_checker())["sharpness"]
        soft = ops.inspect(_checker(blur=4))["sharpness"]
        assert soft < sharp / 10

    def test_inspect_reports_the_facts_a_quality_check_reads(self):
        facts = ops.inspect(_png((300, 400), fmt="JPEG"))
        assert {k: facts[k] for k in ("width", "height", "orientation", "aspect", "mime_type")} == {
            "width": 300,
            "height": 400,
            "orientation": "portrait",
            "aspect": 0.75,
            "mime_type": "image/jpeg",
        }
        assert facts["file_size"] > 0

    def test_palette_finds_the_colours_most_common_first(self):
        img = Image.new("RGB", (300, 100), (255, 0, 0))
        ImageDraw.Draw(img).rectangle((200, 0, 299, 99), fill=(0, 0, 255))
        ImageDraw.Draw(img).rectangle((0, 0, 49, 99), fill=(0, 255, 0))
        out = io.BytesIO()
        img.save(out, format="PNG")
        colors = ops.palette(out.getvalue(), 3)
        assert colors == ["#ff0000", "#0000ff", "#00ff00"]
        assert ops.palette(_png(mode="RGBA", color=(0, 0, 0, 0))) == []  # transparent pixels don't count

    def test_anything_but_a_raster_image_is_refused(self):
        with pytest.raises(ops.NotAnImage):
            ops.format_of(b"%PDF-1.7 not a picture")
        gif = io.BytesIO()
        Image.new("RGB", (4, 4)).save(gif, format="GIF")
        with pytest.raises(ops.NotAnImage):
            ops.format_of(gif.getvalue())

    def test_a_sideways_camera_photo_is_turned_upright_first(self):
        img = Image.new("RGB", (300, 100))
        exif = img.getexif()
        exif[0x0112] = 6  # "rotate 90° clockwise to view"
        out = io.BytesIO()
        img.save(out, format="JPEG", exif=exif.tobytes())
        assert ops.inspect(out.getvalue())["orientation"] == "portrait"


def test_comparison_operators_read_numbers():
    ctx = {"steps": {"q": {"output": {"sharpness": 42.5, "width": 800}}}}
    assert matches([{"field": "steps.q.output.sharpness", "op": "lt", "value": "100"}], ctx)
    assert matches([{"field": "steps.q.output.width", "op": "gte", "value": 800}], ctx)
    assert not matches([{"field": "steps.q.output.width", "op": "gt", "value": "800"}], ctx)
    assert not matches([{"field": "steps.q.output.missing", "op": "lt", "value": 5}], ctx)  # nothing to compare: false
    assert not matches([{"field": "steps.q.output.width", "op": "lte", "value": "wide"}], ctx)


# ── The step, through the engine ──────────────────────────────────────────────
@pytest.fixture
def media(ws, tmp_path, monkeypatch):
    """`ws` with its storage in a temporary folder and the events the engine sends recorded instead of dispatched."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.storage import provider_factory
    from marvin.services.storage.local_provider import LocalStorageProvider

    store = LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")
    monkeypatch.setattr(provider_factory, "get_storage_provider", lambda *a, **k: store)
    monkeypatch.setattr(provider_factory, "provider_for", lambda slug: store)
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append((kw["event_type"].name, kw.get("document_data"))))
    ws.store, ws.sent = store, sent
    return ws


def _stored(ws, name: str, data: bytes, mime: str = "image/png"):
    """An asset whose bytes are really in the workspace's storage."""
    from marvin.db.models.platform.assets import Assets

    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    key = f"test/{slug}"
    ws.store.put(storage_key=key, file_data=io.BytesIO(data), content_type=mime)
    w, h = _open(data).size if mime.startswith("image/") else (None, None)
    row = Assets(
        session=ws.session, group_id=ws.gid, slug=slug, name=name, original_filename=f"{name}.png", filename=name, extension="png",
        file_size=len(data), mime_type=mime, asset_type="image" if mime.startswith("image/") else "document",
        checksum=hashlib.sha256(data).hexdigest(), width=w, height=h, storage_provider="local", storage_key=key, uploaded_by=ws.uid,
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    return row


def _workflow(ws, definition: dict, slug: str = "media-wf"):
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name=slug.replace("-", " ").title(), slug=slug, enabled=True, definition=definition, created_by=ws.uid
    )
    ws.session.add(row)
    ws.session.commit()
    return row


def _fire(ws, event_type: str, document: dict, *, entity=None, entity_type=None, correlation_id="corr-1"):
    ctx = event_context(event_type, document, entity_id=entity, entity_type=entity_type, user_id=ws.uid, correlation_id=correlation_id)
    run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))
    ws.session.expire_all()


def _derivatives(ws, source):
    from marvin.db.models.platform.assets import Assets

    rows = ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()
    return [a for a in rows if (a.metadata_json or {}).get("derived_from") == str(source.id)]


def _last_run(ws, slug="media-wf"):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    return (
        ws.session.query(AutomationExecutionModel)
        .filter_by(group_id=ws.gid, automation_slug=slug)
        .order_by(AutomationExecutionModel.started_at.desc())
        .first()
    )


def _entry(ws, title="Harbour"):
    from marvin.db.models.platform.entries import Entries

    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title,
        slug=f"{title.lower()}-{uuid.uuid4().hex[:6]}", status="draft", data_json={}, metadata_json={},
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _link(ws, entry, asset, role):
    from marvin.db.models.platform.entry_assets import EntryAssets

    ws.session.add(EntryAssets(entry_id=entry.id, asset_id=asset.id, role=role, position=0))
    ws.session.commit()


ON_UPLOAD = {"type": "event", "event": "asset_uploaded"}


def test_a_resize_makes_a_new_asset_with_its_lineage_and_leaves_the_original_alone(media):
    original_bytes = _png((800, 600))
    photo = _stored(media, "harbour", original_bytes)
    checksum = photo.checksum
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "id": "small", "op": "resize", "width": 200, "format": "webp"}]})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    (small,) = _derivatives(media, photo)
    assert (small.width, small.height, small.mime_type, small.extension) == (200, 150, "image/webp", "webp")
    meta = small.metadata_json
    assert meta["derivation"] == "media:resize:fit=inside,format=webp,width=200" and meta["workflow_slug"] == "media-wf"
    assert meta["step"] == "small" and meta["correlation_id"] == "corr-1" and meta["workflow_id"]
    assert small.slug == derivative_slug(photo, "resize", {"fit": "inside", "format": "webp", "width": 200})
    # The original: same row, same bytes.
    media.session.refresh(photo)
    assert photo.checksum == checksum and media.store.get(photo.storage_key).read() == original_bytes
    output = _last_run(media).actions[0].output_snapshot
    assert output["asset"]["id"] == str(small.id) and output["reused"] is False and output["asset"]["url"]
    # A derivative is not an upload: nothing for an "image added" workflow to react to.
    assert [name for name, _ in media.sent if name == "asset_uploaded"] == []


def test_the_same_derivation_is_made_once(media):
    photo = _stored(media, "harbour", _png((800, 600)))
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "crop", "aspect": "1:1"}]})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")
    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset", correlation_id="corr-2")

    (square,) = _derivatives(media, photo)
    assert (square.width, square.height) == (600, 600)
    assert _last_run(media).actions[0].output_snapshot["reused"] is True


def test_steps_chain_on_an_earlier_steps_asset(media):
    photo = _stored(media, "harbour", _png((800, 600)))
    _workflow(
        media,
        {
            "trigger": ON_UPLOAD,
            "actions": [
                {"kind": "media", "id": "sq", "op": "crop", "aspect": "1:1"},
                {"kind": "media", "id": "small", "op": "resize", "source": "${steps.sq.output.asset.id}", "width": 100, "format": "jpeg"},
            ],
        },
    )

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    (square,) = _derivatives(media, photo)
    (thumb,) = _derivatives(media, square)
    assert (thumb.width, thumb.height, thumb.mime_type) == (100, 100, "image/jpeg")


def test_attach_as_links_the_new_asset_to_the_runs_entry(media):
    from marvin.db.models.platform.entry_assets import EntryAssets

    article = _entry(media)
    hero = _stored(media, "hero", _png((1200, 800)))
    _link(media, article, hero, "hero")
    _workflow(
        media,
        {
            "trigger": {"type": "event", "event": "asset_attached_to_entry"},
            "conditions": [{"field": "event.role", "op": "eq", "value": "hero"}],
            "actions": [{"kind": "media", "op": "resize", "width": 400, "attach_as": "hero-400"}],
        },
    )
    doc = {"entry_id": str(article.id), "asset_id": str(hero.id), "role": "hero"}

    _fire(media, "asset_attached_to_entry", doc, entity=article.id, entity_type="entry")

    (small,) = _derivatives(media, hero)
    link = media.session.query(EntryAssets).filter_by(entry_id=article.id, asset_id=small.id).one()
    assert link.role == "hero-400"
    attached = [d for name, d in media.sent if name == "asset_attached_to_entry"]
    assert len(attached) == 1 and attached[0].role == "hero-400"  # the role travels on the event
    # A non-hero attach doesn't match the condition.
    _fire(media, "asset_attached_to_entry", {**doc, "role": "hero-400", "asset_id": str(small.id)}, entity=article.id, entity_type="entry")
    assert _derivatives(media, small) == []


def test_source_role_takes_the_entrys_image_in_that_role(media):
    article = _entry(media)
    _link(media, article, _stored(media, "gallery", _png((300, 300))), "gallery")
    hero = _stored(media, "hero", _png((900, 600)))
    _link(media, article, hero, "hero")
    _workflow(
        media,
        {
            "trigger": {"type": "event", "event": "entry_published"},
            "actions": [{"kind": "media", "op": "crop", "source": "role:hero", "aspect": "4:5", "attach_as": "portrait"}],
        },
    )

    _fire(media, "entry_published", {"entry_id": str(article.id)}, entity=article.id, entity_type="entry")

    (portrait,) = _derivatives(media, hero)
    assert (portrait.width, portrait.height) == (480, 600)


def test_a_dry_run_plans_and_writes_nothing(media):
    from marvin.db.models.platform.assets import Assets

    photo = _stored(media, "harbour", _png((800, 600)))
    wf = _workflow(
        media,
        {
            "trigger": {"type": "manual"},
            "target": {"entity": "asset", "query": {"asset_type": "image"}},
            "actions": [{"kind": "media", "id": "q", "op": "inspect"}, {"kind": "media", "op": "convert", "format": "webp"}],
        },
    )
    before = media.session.query(Assets).filter(Assets.group_id == media.gid).count()

    result = run_automation_now(media.session, media.gid, wf, user_id=media.uid, dry_run=True)

    assert media.session.query(Assets).filter(Assets.group_id == media.gid).count() == before
    inspect, convert = _plan_outputs(result)
    assert inspect["width"] == 800  # reading is free and writes nothing: a dry run shows it
    assert convert["would_create"].startswith(photo.slug) and convert["dry_run"] is True


def _plan_outputs(result) -> list[dict]:
    return [row["resolved"] for row in result["plan"]]


def test_when_reads_an_inspection(media):
    big = _stored(media, "big", _png((1600, 1200)))
    small = _stored(media, "small", _png((200, 150)))
    _workflow(
        media,
        {
            "trigger": ON_UPLOAD,
            "actions": [
                {"kind": "media", "id": "q", "op": "inspect"},
                {
                    "kind": "media",
                    "op": "resize",
                    "width": 800,
                    "when": [{"field": "steps.q.output.width", "op": "gt", "value": "800"}],
                },
            ],
        },
    )

    for asset in (big, small):
        _fire(media, "asset_uploaded", {"asset_id": str(asset.id)}, entity=asset.id, entity_type="asset")

    assert len(_derivatives(media, big)) == 1 and _derivatives(media, small) == []


def test_a_derivative_reads_as_one_in_the_run_context(media):
    from marvin.services.automation.engine import _item_context

    photo = _stored(media, "harbour", _png())
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "convert", "format": "jpeg"}]})
    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    (copy,) = _derivatives(media, photo)
    assert _item_context(media.session, media.gid, "asset", copy.id)["derived_from"] == str(photo.id)
    assert _item_context(media.session, media.gid, "asset", photo.id)["derived_from"] is None


def test_grade_uses_a_preset_and_the_workspace_may_add_its_own(media):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    media.session.query(WorkspaceAISettingsModel).filter_by(group_id=media.gid).update({"media_presets": {"brand": {"warmth": 1.2}}})
    media.session.commit()
    photo = _stored(media, "harbour", _png(color=(120, 120, 120)))
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "grade", "preset": "brand"}]})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    (graded,) = _derivatives(media, photo)
    r, _g, b = _open(media.store.get(graded.storage_key).read()).convert("RGB").getpixel((10, 10))
    assert r > 120 > b


def test_a_subject_crop_asks_the_vision_model_and_records_the_call(media, monkeypatch):
    from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport

    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai import factory

    transport = ScriptedTransport()
    transport.reply_text('{"box": [0.0, 0.0, 0.2, 1.0]}')
    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: FakeAIProvider(transport))
    photo = _stored(media, "halves", _halves((400, 200)))
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "crop", "aspect": "1:1", "focus": "subject"}]})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    (crop,) = _derivatives(media, photo)
    assert _open(media.store.get(crop.storage_key).read()).convert("RGB").getpixel((5, 5)) == (255, 0, 0)  # the left
    assert _last_run(media).actions[0].output_snapshot["focus_used"] == "subject"
    (call,) = media.session.query(AIExecutionModel).filter_by(group_id=media.gid, operation_slug="detect-subject").all()
    assert call.trigger_type == "automation" and call.total_tokens > 0


def test_crops_of_one_picture_share_one_subject_detection(media, monkeypatch):
    from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport

    from marvin.services.ai import factory

    transport = ScriptedTransport()
    transport.reply_text('{"box": [0.0, 0.0, 0.2, 1.0]}')
    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: FakeAIProvider(transport))
    photo = _stored(media, "halves", _halves((400, 200)))
    crops = [{"kind": "media", "op": "crop", "aspect": aspect, "focus": "subject"} for aspect in ("1:1", "1:2", "3:2")]
    _workflow(media, {"trigger": ON_UPLOAD, "actions": crops})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    assert len(transport.requests) == 1
    assert [a.output_snapshot["focus_used"] for a in _last_run(media).actions] == ["subject", "subject", "subject"]


def test_no_subject_found_is_remembered_for_the_runs_other_crops(media, monkeypatch):
    from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport

    from marvin.services.ai import factory

    transport = ScriptedTransport()
    transport.reply_text('{"box": [0, 0, 0, 0]}')  # a degenerate box: no subject
    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: FakeAIProvider(transport))
    photo = _stored(media, "fog", _png((400, 200)))
    crops = [{"kind": "media", "op": "crop", "aspect": aspect, "focus": "subject"} for aspect in ("1:1", "1:2")]
    _workflow(media, {"trigger": ON_UPLOAD, "actions": crops})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    assert len(transport.requests) == 1
    outputs = [a.output_snapshot for a in _last_run(media).actions]
    assert [o["focus_used"] for o in outputs] == ["center", "center"] and all("no subject" in o["focus_note"] for o in outputs)


def test_a_subject_crop_without_ai_centres_and_says_so(media):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    media.session.query(WorkspaceAISettingsModel).filter_by(group_id=media.gid).update({"enabled": False})
    media.session.commit()
    photo = _stored(media, "halves", _halves((400, 200)))
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "crop", "aspect": "1:1", "focus": "subject"}]})

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    out = _last_run(media).actions[0].output_snapshot
    assert out["focus_used"] == "center" and "AI is off" in out["focus_note"]
    (crop,) = _derivatives(media, photo)
    assert crop.slug == derivative_slug(photo, "crop", {"aspect": "1:1", "focus": "center"})
    assert crop.metadata_json["derivation"] == "media:crop:aspect=1:1,focus=center"  # what was done, not what was asked


def test_a_file_that_is_not_a_raster_image_fails_the_step(media):
    pdf = _stored(media, "manual", b"%PDF-1.7", mime="application/pdf")
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "resize", "width": 100}]})

    _fire(media, "asset_uploaded", {"asset_id": str(pdf.id)}, entity=pdf.id, entity_type="asset")

    run = _last_run(media)
    assert run.status == "failed" and "not an image Marvin can process" in run.actions[0].error


def test_a_trashed_derivative_is_not_silently_brought_back(media):
    from datetime import UTC, datetime

    photo = _stored(media, "harbour", _png((800, 600)))
    _workflow(media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "convert", "format": "webp"}]})
    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")
    (copy,) = _derivatives(media, photo)
    copy.trashed_at = datetime.now(UTC)
    media.session.commit()

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset", correlation_id="corr-2")

    assert "is in the Trash" in _last_run(media).actions[0].error


# ── Validation ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("step", "path"),
    [
        ({"kind": "media", "op": "crop"}, "actions[0].media"),  # no aspect
        ({"kind": "media", "op": "crop", "aspect": "wide"}, "actions[0].aspect"),
        ({"kind": "media", "op": "resize", "width": 100, "preset": "warm"}, "actions[0].media"),  # preset goes with grade
        ({"kind": "media", "op": "resize", "width": 100, "fit": "cover"}, "actions[0].media"),  # cover needs both sides
        ({"kind": "media", "op": "convert"}, "actions[0].media"),
        ({"kind": "media", "op": "inspect", "attach_as": "x"}, "actions[0].media"),
        ({"kind": "media", "op": "grade", "preset": "sepia-dreams"}, "actions[0].preset"),
        ({"kind": "media", "op": "resize", "width": 100, "attach_as": "small"}, "actions[0].attach_as"),  # no entry here
        ({"kind": "media", "op": "resize", "width": 100, "source": "role:hero"}, "actions[0].source"),
    ],
)
def test_the_validator_names_what_cant_run(ws, step, path):
    issues = draft_issues(ws.session, ws.gid, {"trigger": ON_UPLOAD, "actions": [step]})
    assert path in [i.get("path") for i in issues], issues


def test_a_media_workflow_on_entries_drafts_cleanly(ws):
    definition = {
        "trigger": {"type": "event", "event": "asset_attached_to_entry"},
        "actions": [
            {"kind": "media", "id": "sq", "op": "crop", "aspect": "1:1", "focus": "subject", "attach_as": "square"},
            {"kind": "media", "op": "grade", "preset": "warm", "source": "${steps.sq.output.asset.id}", "format": "webp", "quality": 80},
            {"kind": "media", "op": "resize", "source": "role:hero", "width": 400, "height": 400, "fit": "cover"},
        ],
    }
    assert draft_issues(ws.session, ws.gid, definition) == []


def test_a_media_step_tags_what_it_makes(media):
    photo = _stored(media, "harbour", _png((800, 600)))
    _workflow(
        media, {"trigger": ON_UPLOAD, "actions": [{"kind": "media", "op": "convert", "format": "webp", "tags": ["web-sizes", "${asset.name}"]}]}
    )

    _fire(media, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

    (copy,) = _derivatives(media, photo)
    assert sorted(t.slug for t in copy.tags) == ["harbour", "web-sizes"]
    assert _last_run(media).actions[0].output_snapshot["tags"] == ["harbour", "web-sizes"]
