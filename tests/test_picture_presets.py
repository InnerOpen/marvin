"""Picture presets (services/assets/picture_presets.py): a named recipe of media treatments on an entry type, applied to
pictures (one new picture each, kept as a version of the original, reused on a re-run, never an asset_uploaded), to
entries (the treated picture takes the original's place) and through a template (each new entry shows the treated
picture). Also the media step's free grade settings and fixed crop focus, and the background job that does the work.

Pictures here are real PNGs in a temporary local storage. The workspace is committed for real (the job runs in a thread
with its own session), as tests/test_entry_templates.py does; its `ws` fixture is reused.
"""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import hashlib
import io
import threading
import time
import uuid

import numpy as np
import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from PIL import Image, ImageDraw

from marvin.db.models.platform import Entries, EntryTypes
from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.media import transforms
from marvin.services.assets import picture_presets as P
from marvin.services.automation.actions import media
from marvin.services.entries import templates as T
from marvin.services.event_bus_service.event_bus_service import EventBusService as RealEventBus
from tests.test_entry_templates import ORNAMENT, SCHEMA, _sign_in, ws  # noqa: F401 — fixtures and helpers

LOOK = {
    "slug": "ornament-look",
    "name": "Ornament look",
    "steps": [
        {"op": "crop", "aspect": "1:1", "focus": "0.25,0.5"},
        {"op": "grade", "brightness": 1.2, "warmth": 1.1},
        {"op": "resize", "width": 60},
        {"op": "convert", "format": "webp", "quality": 80},
    ],
}
TREATED = {**ORNAMENT, "slug": "treated", "name": "Treated ornament", "picture_preset": "ornament-look"}


def _png(size=(120, 80), color=(100, 100, 100)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def _halves(size=(120, 80)) -> bytes:
    """Left half red, right half blue: where a crop came from shows in its colour."""
    img = Image.new("RGB", size, (0, 0, 255))
    ImageDraw.Draw(img).rectangle((0, 0, size[0] // 2 - 1, size[1]), fill=(255, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@pytest.fixture
def pw(ws, tmp_path, monkeypatch):
    """`ws` with a real local storage, the Ornament look preset and a template naming it on the artwork type, and every
    event recorded (the real bus's dispatch, whoever holds it)."""
    from marvin.services.storage import provider_factory
    from marvin.services.storage.local_provider import LocalStorageProvider

    store = LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")
    monkeypatch.setattr(provider_factory, "get_storage_provider", lambda *a, **k: store)
    monkeypatch.setattr(provider_factory, "provider_for", lambda slug: store)
    sent: list = []
    monkeypatch.setattr(RealEventBus, "dispatch", lambda self, **kw: sent.append(kw["event_type"].name))
    row = ws.session.get(EntryTypes, ws.type.id)
    row.picture_presets_json = P.check_presets([LOOK])
    row.templates_json = T.check_templates([ORNAMENT, TREATED], SCHEMA, row.picture_presets_json)
    ws.session.commit()

    def stored(name: str, data: bytes | None = None, *, who: str = "editor", filename: str | None = None) -> Assets:
        data = data or _halves()
        slug = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"
        key = f"test/{slug}.png"
        store.put(storage_key=key, file_data=io.BytesIO(data), content_type="image/png")
        w, h = _open(data).size
        a = Assets(
            session=ws.session, group_id=ws.gid, slug=slug, name=name, original_filename=filename or f"{name}.png", filename=slug,
            extension="png", file_size=len(data), mime_type="image/png", asset_type="image", checksum=hashlib.sha256(data).hexdigest(),
            width=w, height=h, storage_provider="local", storage_key=key, uploaded_by=ws.users[who],
        )  # fmt: skip
        ws.session.add(a)
        ws.session.commit()
        return a

    ws.store, ws.sent, ws.stored = store, sent, stored
    return ws


def _assets(ws) -> list:
    ws.session.expire_all()
    return ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()


def _links(ws, entry_id) -> list:
    ws.session.expire_all()
    return [(link.asset_id, link.role) for link in ws.session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id)]


def _treat(ws, ids, **kw) -> dict:
    plan = P.plan_for_assets(ws.session, ws.gid, "artwork", [str(i) for i in ids], preset="ornament-look", **kw)
    return P.execute(ws.session, ws.gid, P.work_of(plan), actor_id=ws.users["editor"])


# ── The treatments ─────────────────────────────────────────────────────────────


class TestGrade:
    def test_free_settings_change_the_pixels_as_they_say(self):
        grey = Image.new("RGB", (8, 8), (100, 100, 100))
        assert transforms.grade_image(grey, {"brightness": 1.5}).getpixel((4, 4)) == (150, 150, 150)
        assert transforms.grade_image(grey, {"warmth": 1.2}).getpixel((4, 4)) == (120, 100, 80)
        assert transforms.grade_image(grey, {"contrast": 2.0}).getpixel((4, 4)) == (100, 100, 100)  # a flat picture has no contrast
        r, g, b = transforms.grade_image(Image.new("RGB", (8, 8), (200, 40, 40)), {"saturation": 0.0}).getpixel((4, 4))
        assert r == g == b and 80 <= r <= 95  # no colour left: its grey
        assert transforms.grade_image(grey, {}).getpixel((4, 4)) == (100, 100, 100)

    def test_the_vignette_darkens_the_corners_only_and_matches_the_old_formula(self):
        white = Image.new("RGB", (64, 48), (255, 255, 255))
        out = transforms._apply_vignette(white, 0.8)
        assert out.getpixel((32, 24))[0] >= 254 and out.getpixel((0, 0))[0] <= 60
        w, h = white.size
        cx, cy = w / 2, h / 2
        max_d = (cx**2 + cy**2) ** 0.5
        old = np.array([[int(255 * (1 - min(1.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / max_d) * 0.8)) for x in range(w)] for y in range(h)])
        assert np.abs(np.asarray(out.convert("L"), dtype=int) - old).max() <= 1

    def test_a_phone_photo_is_vignetted_in_well_under_a_second(self):
        photo = Image.new("RGB", (4032, 3024), (180, 160, 140))
        started = time.monotonic()
        transforms._apply_vignette(photo, 0.3)
        assert time.monotonic() - started < 2.0

    def test_the_media_step_takes_free_settings_alone_or_over_a_preset(self, pw):
        args = media.derive_args(pw.session, pw.gid, "grade", {"brightness": "1.10", "contrast": 1}, {})
        assert args == {"brightness": 1.1}  # a setting left at "as it is" is no setting
        assert media.derive_args(pw.session, pw.gid, "grade", {"preset": "warm", "vignette": 0.2}, {}) == {"preset": "warm", "vignette": 0.2}
        assert media.grade_params(pw.session, pw.gid, {"preset": "warm", "warmth": 1.0, "brightness": 1.2})["brightness"] == 1.2
        with pytest.raises(media.AutomationActionError, match="grade needs a preset or a setting"):
            media.derive_args(pw.session, pw.gid, "grade", {"brightness": 1}, {})
        with pytest.raises(media.AutomationActionError, match="brightness must be from 0 to 3"):
            media.derive_args(pw.session, pw.gid, "grade", {"brightness": 7}, {})


class TestCropFocus:
    def test_a_fixed_point_is_parsed_and_named_one_way(self):
        assert transforms.parse_focus("0.50, .3") == (0.5, 0.3)
        assert transforms.parse_focus("center") == "center" and transforms.parse_focus("subject") == "subject"
        assert transforms.parse_focus("1.5,0.2") is None and transforms.parse_focus("left") is None
        assert media.crop_focus("0.50, .3") == "0.5,0.3" and media.crop_focus("0.5,0.5") == "center" and media.crop_focus(None) == "center"

    def test_the_media_step_crops_where_the_point_says(self, pw):
        src = pw.stored("Halves")
        context = {"asset": {"id": str(src.id)}}
        left = media.run_media_action(pw.session, pw.gid, {"op": "crop", "aspect": "1:2", "focus": "0.1,0.5"}, context)
        right = media.run_media_action(pw.session, pw.gid, {"op": "crop", "aspect": "1:2", "focus": "0.9,0.5"}, context)
        read = lambda out: _open(media._read_bytes(pw.session, pw.gid, pw.session.get(Assets, uuid.UUID(out["asset"]["id"])))).convert("RGB")  # noqa: E731
        assert read(left).getpixel((5, 5)) == (255, 0, 0) and read(right).getpixel((30, 5)) == (0, 0, 255)
        assert left["asset"]["name"] == "Halves (crop 1:2 at 0.1,0.5)"

    def test_existing_steps_keep_the_names_their_pictures_were_made_with(self, pw):
        """A derivative's slug hashes its canonical arguments: a crop or a named grade defined before free settings and
        fixed points existed must name the same picture, or every recipe would make it again."""
        src = pw.stored("Pinned")
        for op, step, canon in (
            ("crop", {"aspect": "4x5"}, "aspect=4:5,focus=center"),
            ("crop", {"aspect": "1:1", "focus": "subject"}, "aspect=1:1,focus=subject"),
            ("grade", {"preset": "warm"}, "preset=warm"),
            ("resize", {"width": "800"}, "fit=inside,width=800"),
        ):
            args = media.derive_args(pw.session, pw.gid, op, step, {})
            expected = hashlib.sha256(f"{op}|{canon}|{src.checksum}".encode()).hexdigest()[:8]
            assert media.derivative_slug(src, op, args) == f"{src.slug}--{op}-{expected}"


# ── Presets ────────────────────────────────────────────────────────────────────


class TestPresets:
    def test_a_recipe_is_canonical_so_spellings_make_one_picture(self):
        from marvin.schemas.platform.picture_presets import PicturePreset

        a = PicturePreset.model_validate(
            {"slug": "a", "name": "A", "steps": [{"op": "crop", "aspect": "4x5", "focus": "0.50,.3"}, {"op": "grade", "brightness": "1.10"}]}
        )
        b = PicturePreset.model_validate(
            {
                "slug": "b",
                "name": "B",
                "steps": [{"op": "crop", "aspect": "4:5", "focus": "0.5,0.3"}, {"op": "grade", "brightness": 1.1, "warmth": 1}],
            }
        )
        assert P.canonical(P.recipe_of(a)) == P.canonical(P.recipe_of(b))
        assert P.steps_text(P.recipe_of(a)) == "crop 4:5 at 0.5,0.3, grade brightness 1.1"

    @pytest.mark.parametrize(
        "steps,said",
        [
            ([], "steps"),
            ([{"op": "crop"}], "crop needs an aspect"),
            ([{"op": "grade"}], "grade needs a preset or a setting"),
            ([{"op": "resize", "aspect": "1:1", "width": 10}], "aspect goes with another treatment"),
            ([{"op": "grade", "brightness": 1}], "it does nothing"),
            ([{"op": "crop", "aspect": "1:1", "focus": "left"}], "focus"),
        ],
    )
    def test_a_preset_that_cannot_work_is_refused_naming_why(self, steps, said):
        with pytest.raises(P.PresetError, match=said):
            P.check_presets([{"slug": "x", "name": "X", "steps": steps}])

    def test_the_type_keeps_them_and_its_templates_may_only_name_its_own(self, pw):
        from marvin.repos.repository_factory import AllRepositories

        repos = AllRepositories(pw.session, group_id=pw.gid)
        read = repos.entry_types.get_one(pw.type.id)
        assert [p.slug for p in read.picture_presets] == ["ornament-look"]
        assert read.model_dump(by_alias=True)["picturePresetsJson"][0]["steps"][0]["focus"] == "0.25,0.5"
        with pytest.raises(HTTPException) as e:
            repos.entry_types.update(pw.type.id, {"templates": [ORNAMENT, {**TREATED, "picture_preset": "vase-look"}]})
        assert e.value.status_code == 400 and "no picture preset 'vase-look'" in e.value.detail
        with pytest.raises(HTTPException) as e:  # a preset a template names can't be taken away from under it
            repos.entry_types.update(pw.type.id, {"picture_presets": []})
        assert "no picture preset 'ornament-look'" in e.value.detail
        with pytest.raises(HTTPException) as e:
            repos.entry_types.update(pw.type.id, {"picture_presets": [{**LOOK, "steps": [{"op": "crop"}]}]})
        assert e.value.status_code == 400 and "crop needs an aspect" in e.value.detail

    def test_a_package_brings_presets_with_its_type_and_an_update_adds_only_the_ones_lacking(self, pw):
        from marvin.schemas.platform.blueprints import Blueprint
        from marvin.services.blueprints.apply import apply_blueprint, update_entry_type

        payload = {"name": "Vase", "schema_json": SCHEMA, "picture_presets_json": [LOOK], "templates_json": [TREATED]}
        made = apply_blueprint(pw.session, pw.gid, Blueprint(kind="entry_type", slug="vase", name="Vase", payload=payload))
        assert made.created, made.detail
        row = pw.session.query(EntryTypes).filter_by(group_id=pw.gid, slug="vase").one()
        row.picture_presets_json = [{**row.picture_presets_json[0], "name": "Edited here"}]
        pw.session.flush()
        newer = {**payload, "picture_presets_json": [{**LOOK, "name": "Upstream"}, {**LOOK, "slug": "square", "name": "Square"}]}
        done = update_entry_type(pw.session, pw.gid, Blueprint(kind="entry_type", slug="vase", name="Vase", payload=newer), row)
        assert done.updated and "picture preset square" in done.detail
        assert [(p["slug"], p["name"]) for p in row.picture_presets_json] == [("ornament-look", "Edited here"), ("square", "Square")]
        bad = {"name": "Bad", "schema_json": SCHEMA, "templates_json": [TREATED]}  # names a preset the package doesn't bring
        refused = apply_blueprint(pw.session, pw.gid, Blueprint(kind="entry_type", slug="bad", name="Bad", payload=bad))
        assert not refused.created and "no picture preset 'ornament-look'" in refused.detail


# ── Treating pictures ──────────────────────────────────────────────────────────


class TestTreating:
    def test_one_new_picture_per_original_with_its_lineage_and_the_original_untouched(self, pw):
        src = pw.stored("Snowy Owl")
        before = media._read_bytes(pw.session, pw.gid, src)
        preview = P.describe(P.plan_for_assets(pw.session, pw.gid, "artwork", [str(src.id)], preset="ornament-look"))
        assert preview["create"] == 1 and preview["todo"] == 1 and len(_assets(pw)) == 1  # a preview changes nothing
        assert preview["steps"] == "crop 1:1 at 0.25,0.5, grade brightness 1.2 warmth 1.1, resize 60×auto, webp"
        done = _treat(pw, [src.id])
        assert done["made"] == 1 and done["failed"] == 0
        treated = pw.session.get(Assets, uuid.UUID(done["treated"][str(src.id)]))
        assert treated.origin == "derived" and treated.source_asset_id == src.id
        assert treated.slug.startswith(f"{src.slug}--preset-") and treated.slug == preview["rows"][0]["slug"]
        assert treated.name == "Snowy Owl (preset ornament-look)" and treated.mime_type == "image/webp"
        assert (
            treated.metadata_json["picture_preset"] == "ornament-look" and treated.metadata_json["derivation"] == "media:preset:preset=ornament-look"
        )
        img = _open(media._read_bytes(pw.session, pw.gid, treated)).convert("RGB")
        assert img.size == (60, 60)
        r, g, b = img.getpixel((30, 30))  # the left (red) square, brighter and warmer: red stays full, blue stays none
        assert r > 240 and b < 20
        assert media._read_bytes(pw.session, pw.gid, pw.session.get(Assets, src.id)) == before  # the original's file as it was
        assert "asset_uploaded" not in pw.sent

    def test_a_rerun_reuses_and_a_treated_picture_is_never_treated_again(self, pw):
        src = pw.stored("Blue Jay")
        first = _treat(pw, [src.id])
        treated_id = first["treated"][str(src.id)]
        count = len(_assets(pw))
        again = _treat(pw, [src.id])
        assert again == {**again, "made": 0, "reused": 1} and again["treated"][str(src.id)] == treated_id
        plan = P.plan_for_assets(pw.session, pw.gid, "artwork", [treated_id], preset="ornament-look")
        assert [(r.action, r.source_id) for r in plan.rows] == [("reuse", src.id)]  # traced back to its original
        assert len(_assets(pw)) == count

    def test_editing_the_preset_makes_new_pictures(self, pw):
        src = pw.stored("Cardinal")
        old = _treat(pw, [src.id])["treated"][str(src.id)]
        row = pw.session.get(EntryTypes, pw.type.id)
        row.picture_presets_json = P.check_presets([{**LOOK, "steps": [*LOOK["steps"][:1], {"op": "grade", "brightness": 1.3}]}])
        pw.session.commit()
        new = _treat(pw, [src.id])
        assert new["made"] == 1 and new["treated"][str(src.id)] != old

    def test_a_bad_picture_fails_alone(self, pw):
        good, bad = pw.stored("Good"), pw.stored("Bad")
        pw.store.put(storage_key=bad.storage_key, file_data=io.BytesIO(b"not a picture"), content_type="image/png")
        done = _treat(pw, [bad.id, good.id])
        assert done["made"] == 1 and done["failed"] == 1 and done["errors"][0].startswith("Bad:")

    def test_the_statement_count_grows_only_with_the_pictures_made(self, pw):
        """Planning reads a fixed number of statements, whatever the number of pictures."""
        engine = pw.session.get_bind()

        def statements(n: int) -> int:
            ids = [str(pw.stored(f"P{i}", _png(color=(i, 10, 10))).id) for i in range(n)]
            seen: list = []
            listen = lambda *a: seen.append(a[2])  # noqa: E731
            sa.event.listen(engine, "before_cursor_execute", listen)
            try:
                P.describe(P.plan_for_assets(pw.session, pw.gid, "artwork", ids, preset="ornament-look"))
            finally:
                sa.event.remove(engine, "before_cursor_execute", listen)
            return len(seen)

        assert statements(2) == statements(12)


# ── Entries: templates and existing ones ───────────────────────────────────────


class TestTemplates:
    def test_a_treated_picture_made_before_is_the_new_entry_s_featured_one(self, pw):
        src = pw.stored("Snowy Owl")
        treated_id = uuid.UUID(_treat(pw, [src.id])["treated"][str(src.id)])
        plan = T.plan_from_assets(pw.session, pw.gid, "artwork", "treated", [str(src.id)])
        preview = T.describe(plan)
        assert preview["picture_preset"] == "ornament-look" and preview["rows"][0]["treated"]["id"] == str(treated_id)
        assert preview["rows"][0]["title"] == "Snowy Owl"  # named after the original, not "Snowy Owl (preset …)"
        done = T.execute(pw.session, pw.gid, plan, actor_id=pw.users["editor"])
        assert done["treatment_job"] is None  # nothing left to treat
        entry = pw.session.get(Entries, uuid.UUID(done["entry_ids"][0]))
        assert _links(pw, entry.id) == [(treated_id, "featured")]  # the original is not attached: it is the treated one's source
        assert entry.data_json["image"] == str(treated_id)

    def test_without_one_the_original_stands_in_until_the_background_job_swaps_it(self, pw):
        src = pw.stored("Blue Jay")
        plan = T.plan_from_assets(pw.session, pw.gid, "artwork", "treated", [str(src.id)])
        assert plan.rows[0].pending and "made in the background" in plan.rows[0].note
        done = T.execute(pw.session, pw.gid, plan, actor_id=pw.users["editor"])
        job = P.wait(done["treatment_job"])
        assert job["state"] == "done" and job["made"] == 1 and job["placed"] == 1, job
        treated_id = uuid.UUID(job["treated"][str(src.id)])
        entry = pw.session.get(Entries, uuid.UUID(done["entry_ids"][0]))
        pw.session.refresh(entry)
        assert _links(pw, entry.id) == [(treated_id, "featured")] and entry.data_json["image"] == str(treated_id)
        assert "asset_uploaded" not in pw.sent

    def test_running_it_again_on_the_original_fills_that_entry_instead_of_making_another(self, pw):
        src = pw.stored("Cardinal")
        done = T.execute(pw.session, pw.gid, T.plan_from_assets(pw.session, pw.gid, "artwork", "treated", [str(src.id)]))
        P.wait(done["treatment_job"])
        pw.session.expire_all()
        again = T.plan_from_assets(pw.session, pw.gid, "artwork", "treated", [str(src.id)])
        assert [(r.action, str(r.entry_id)) for r in again.rows] == [("skip", done["entry_ids"][0])]
        assert again.rows[0].pending is False

    def test_a_picture_changed_before_the_swap_is_left_alone(self, pw):
        src, other = pw.stored("Robin"), pw.stored("Their own pick")
        gate = threading.Event()
        real = P.treat
        P.treat = lambda *a, **k: (gate.wait(10), real(*a, **k))[1]
        try:
            done = T.execute(pw.session, pw.gid, T.plan_from_assets(pw.session, pw.gid, "artwork", "treated", [str(src.id)]))
            entry_id = uuid.UUID(done["entry_ids"][0])
            link = pw.session.query(EntryAssets).filter_by(entry_id=entry_id).one()
            link.asset_id = other.id  # the person chose another featured picture meanwhile
            pw.session.commit()
            gate.set()
            job = P.wait(done["treatment_job"])
        finally:
            P.treat = real
        assert job["made"] == 1 and job["placed"] == 1  # the asset field still held the original: that one is switched
        assert _links(pw, entry_id) == [(other.id, "featured")]
        assert any("featured picture was changed since" in e for e in job["errors"])

    def test_apply_template_treats_existing_entries_pictures(self, pw):
        src = pw.stored("Ornament 7")
        e = pw.entry("Ornament 7", image=str(src.id))
        pw.session.add(EntryAssets(id=uuid.uuid4(), entry_id=e.id, asset_id=src.id, role="featured", position=0))
        pw.session.commit()
        plan = T.plan_for_entries(pw.session, pw.gid, "artwork", "treated", [str(e.id)])
        assert plan.rows[0].action == "fill" and plan.rows[0].pending
        done = T.execute(pw.session, pw.gid, plan)
        job = P.wait(done["treatment_job"])
        treated_id = uuid.UUID(job["treated"][str(src.id)])
        assert _links(pw, e.id) == [(treated_id, "featured")]

    def test_mark_unnamed_tags_entries_titled_by_their_file_name(self, pw):
        named, camera = pw.stored("Snowy Owl"), pw.stored("IMG_4491", filename="IMG_4491.jpeg")
        plan = T.plan_from_assets(pw.session, pw.gid, "artwork", "ornament", [str(named.id), str(camera.id)], mark_unnamed=True)
        rows = T.describe(plan)["rows"]
        assert "Needs a name" not in rows[0]["tags"] and "Needs a name" in rows[1]["tags"] and "give it a name" in rows[1]["note"]
        plain = T.describe(T.plan_from_assets(pw.session, pw.gid, "artwork", "ornament", [str(camera.id)]))
        assert "Needs a name" not in plain["rows"][0]["tags"]  # only when asked
        assert T.named_after_file("img 4491") and T.named_after_file("DSC_0042.jpeg") and T.named_after_file("20241201_143022")
        assert not T.named_after_file("Snowy Owl") and not T.named_after_file("Ornament 7")


class TestEntries:
    def test_apply_preset_to_entries_puts_the_treated_picture_in_place(self, pw):
        src = pw.stored("Vase 3")
        e = pw.entry("Vase 3")
        pw.session.add(EntryAssets(id=uuid.uuid4(), entry_id=e.id, asset_id=src.id, role="featured", position=0))
        published = pw.entry("Vase 4", status="published")
        pw.session.commit()
        plan = P.plan_for_entries(pw.session, pw.gid, "artwork", [str(e.id), str(published.id)], template="treated")
        said = P.describe(plan)
        assert [r["action"] for r in said["rows"]] == ["create", "skip"] and said["rows"][0]["place"]
        assert "published" in said["rows"][1]["note"]
        done = P.execute(pw.session, pw.gid, P.work_of(plan))
        assert done["placed"] == 1 and _links(pw, e.id) == [(uuid.UUID(done["treated"][str(src.id)]), "featured")]


# ── REST, the job and the workflow step ────────────────────────────────────────


class TestRest:
    def test_preview_then_a_job_and_requests_are_answered_meanwhile(self, pw):
        srcs = [pw.stored(f"Owl {i}") for i in range(3)]
        client = _sign_in(pw, WorkspaceRole.EDITOR)
        body = {"entryType": "artwork", "preset": "ornament-look", "assets": [str(a.id) for a in srcs]}
        preview = client.post("/api/platform/assets/apply-preset", json=body)
        assert preview.status_code == 200, preview.text
        assert preview.json()["create"] == 3 and preview.json()["job"] is None and len(_assets(pw)) == 3
        gate = threading.Event()
        real = P.treat
        P.treat = lambda *a, **k: (gate.wait(10), real(*a, **k))[1]
        try:
            started = time.monotonic()
            run = client.post("/api/platform/assets/apply-preset", json={**body, "preview": False})
            assert run.status_code == 200 and time.monotonic() - started < 2.0  # answered while the work waits
            job = run.json()["job"]
            assert job["state"] in ("queued", "running") and job["total"] == 3
            status = client.get(f"/api/platform/assets/apply-preset/jobs/{job['id']}")  # another request, answered meanwhile
            assert status.status_code == 200 and status.json()["state"] in ("queued", "running") and status.json()["done"] == 0
        finally:
            gate.set()
            P.treat = real
        done = P.wait(job["id"])
        assert done["state"] == "done" and done["made"] == 3 and set(done["treated"]) == {str(a.id) for a in srcs}
        assert client.get(f"/api/platform/assets/apply-preset/jobs/{job['id']}").json()["state"] == "done"
        assert client.get("/api/platform/assets/apply-preset/jobs/nope").status_code == 404

    def test_an_author_treats_their_own_pictures_only(self, pw):
        mine, theirs = pw.stored("Mine", who="author"), pw.stored("Theirs")
        client = _sign_in(pw, WorkspaceRole.AUTHOR, "author")
        body = {"entryType": "artwork", "template": "treated", "preview": False}
        refused = client.post("/api/platform/assets/apply-preset", json={**body, "assets": [str(theirs.id)]})
        assert refused.status_code == 403 and "uploaded by someone else" in refused.text
        ok = client.post("/api/platform/assets/apply-preset", json={**body, "assets": [str(mine.id)]})
        assert ok.status_code == 200 and P.wait(ok.json()["job"]["id"])["made"] == 1
        viewer = _sign_in(pw, WorkspaceRole.VIEWER, "other")
        assert viewer.post("/api/platform/assets/apply-preset", json={**body, "assets": [str(mine.id)]}).status_code == 403

    def test_unknown_presets_are_404_and_a_template_without_one_400(self, pw):
        src = pw.stored("Owl")
        client = _sign_in(pw, WorkspaceRole.EDITOR)
        nope = client.post("/api/platform/assets/apply-preset", json={"entryType": "artwork", "preset": "nope", "assets": [str(src.id)]})
        assert nope.status_code == 404 and "presets: ornament-look" in nope.text
        bare = client.post("/api/platform/assets/apply-preset", json={"entryType": "artwork", "template": "ornament", "assets": [str(src.id)]})
        assert bare.status_code == 400 and "has no picture preset" in bare.text

    def test_from_template_with_mark_unnamed_and_a_preset(self, pw):
        src = pw.stored("IMG_0007", filename="IMG_0007.jpeg")
        client = _sign_in(pw, WorkspaceRole.EDITOR)
        body = {"entryType": "artwork", "template": "treated", "assets": [str(src.id)], "markUnnamed": True}
        preview = client.post("/api/platform/entries/from-template", json=body).json()
        assert preview["picturePreset"] == "ornament-look" and "Needs a name" in preview["rows"][0]["tags"]
        made = client.post("/api/platform/entries/from-template", json={**body, "preview": False}).json()
        assert made["created"] == 1 and made["treatmentJob"]
        assert P.wait(made["treatmentJob"])["placed"] == 1


class TestWorkflowStep:
    def test_preview_then_apply_with_the_preview_s_todo(self, pw):
        from marvin.services.automation.actions.base import AutomationActionError
        from marvin.services.automation.actions.picture_presets import run_apply_picture_preset_action as run
        from marvin.services.automation.authz import ROLE_AUTHOR

        a, b = pw.stored("One"), pw.stored("Two")
        step = {"kind": "apply_picture_preset", "entry_type": "artwork", "preset": "ornament-look", "assets": "${steps.pick.output.ids}"}
        context = {"steps": {"pick": {"output": {"ids": [str(a.id), {"id": str(b.id)}]}}}}
        preview = run(pw.session, pw.gid, step, context)
        assert preview["todo"] == 2 and len(_assets(pw)) == 2
        with pytest.raises(AutomationActionError, match="the preview counted 5 to do, there are 2 now"):
            run(pw.session, pw.gid, {**step, "mode": "apply", "confirm_total": 5}, context)
        done = run(
            pw.session,
            pw.gid,
            {**step, "mode": "apply", "confirm_total": "${steps.p.output.todo}"},
            {**context, "steps": {**context["steps"], "p": {"output": {"todo": 2}}}},
        )
        assert done["made"] == 2 and len(done["ids"]) == 2 and len(_assets(pw)) == 4
        e = pw.entry("Three")
        with pytest.raises(AutomationActionError, match="putting treated pictures in entries\\) requires role"):
            run(pw.session, pw.gid, {**step, "assets": None, "entries": [str(e.id)]}, {}, authorizer_role=ROLE_AUTHOR)

    def test_the_definition_and_its_validation(self):
        from pydantic import TypeAdapter, ValidationError

        from marvin.schemas.group.automation_definition import Action

        adapter = TypeAdapter(Action)
        adapter.validate_python({"kind": "apply_picture_preset", "entry_type": "artwork", "template": "treated", "assets": "${steps.x.output.ids}"})
        for bad, said in (
            ({"assets": ["a"]}, "name a preset"),
            ({"preset": "p"}, "assets"),
            ({"preset": "p", "assets": ["a"], "mode": "apply"}, "confirm_total"),
        ):
            with pytest.raises(ValidationError, match=said):
                adapter.validate_python({"kind": "apply_picture_preset", "entry_type": "artwork", **bad})
        adapter.validate_python({"kind": "media", "op": "grade", "brightness": 1.1, "vignette": 0.2})
        adapter.validate_python({"kind": "media", "op": "crop", "aspect": "1:1", "focus": "0.3,0.7"})
        with pytest.raises(ValidationError):
            adapter.validate_python({"kind": "media", "op": "crop", "aspect": "1:1", "focus": "top"})
        with pytest.raises(ValidationError, match="grade needs a preset or a setting"):
            adapter.validate_python({"kind": "media", "op": "grade"})
