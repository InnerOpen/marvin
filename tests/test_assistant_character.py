"""The bubble's animated character (services/ai/character.py, POST/PUT/DELETE /groups/ai-settings/character).

An upload is a .zip or loose images; file names pick states through the alias table, unmatched images
are kept unassigned for the picker, and only real GIF/WebP/PNG bytes get in. Zips are hostile until
proven otherwise: capped from the directory before decompressing and again while reading.
"""

import io
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from marvin.services.ai import character as ch
from marvin.services.ai.character import CharacterError, assign_state, character_problem, plan_character, state_for
from tests import character_images as images

# The names in the pack this was built for, plus its demo reel, which matches no state.
SAMPLE_NAMES = [
    "idle",
    "look-loop",
    "waving",
    "review",
    "running",
    "running-left",
    "running-right",
    "waiting",
    "jumping",
    "idle-jump-idle",
    "failed",
    "all-states",
]


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("P", (2, 2)).save(buf, "GIF")
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (2, 2)).save(buf, "PNG")
    return buf.getvalue()


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


# --- naming -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "state"),
    [
        ("idle.gif", "idle"),
        ("Look_Loop.GIF", "idle_variant"),
        ("pack/RUNNING LEFT.webp", "move_left"),
        ("walk-right.png", "move_right"),
        ("idle-jump-idle.gif", "success"),
        ("all-states.gif", None),
        ("peek-cycle.gif", None),  # the plain peek is retired: only an edge's own peek has a slot
        ("Peek_Left.gif", "peek_left"),
        ("peak-bottom.webp", "peek_bottom"),
    ],
)
def test_state_for_maps_aliases_to_canonical_states(filename, state):
    assert (state_for(filename) or (None,))[0] == state


def test_plan_prefers_the_primary_alias_when_two_files_claim_a_state():
    plan = plan_character([("idle-jump-idle.gif", _gif()), ("idle.gif", _gif()), ("jumping.gif", _gif())])
    assert plan.states["success"].name == "jumping.gif"
    assert [i.name for i in plan.images] == ["idle-jump-idle.gif", "idle.gif", "jumping.gif"]  # the loser is kept, unassigned


# --- reading uploads ----------------------------------------------------------------------------


def test_a_sample_like_zip_fills_every_state_and_keeps_the_rest():
    entries = {f"marvin-gifs/{n}.gif": _gif() for n in SAMPLE_NAMES}
    entries |= {"marvin-gifs/": b"", "README.txt": b"hi", "__MACOSX/marvin-gifs/._idle.gif": b"junk", ".DS_Store": b"junk"}
    plan = plan_character([("marvin-gifs.zip", _zip(entries))])
    # The sample pack predates the peeks, which fall back to the wave in the browser (lib/marvin/character.ts).
    assert set(plan.states) == set(ch.CHARACTER_STATES) - {"peek_left", "peek_right", "peek_top", "peek_bottom"}
    assert plan.states["greeting"].name == "waving.gif" and plan.states["success"].name == "jumping.gif"
    assert {i.name for i in plan.images} == {f"{n}.gif" for n in SAMPLE_NAMES}
    assert plan.ignored == ["README.txt"]  # junk entries are skipped silently, not reported
    assert plan.name == "marvin-gifs" and not plan.idle_guessed


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"just some text renamed to .gif",
        b"\xff\xd8\xff\xe0 a jpeg is not an animation",
    ],
)
def test_non_gif_webp_png_bytes_are_ignored_whatever_the_name(data):
    plan = plan_character([("idle.png", _png()), ("waving.gif", data)])
    assert plan.ignored == ["waving.gif"] and "greeting" not in plan.states


def test_an_upload_with_no_real_images_is_refused():
    with pytest.raises(CharacterError):
        plan_character([("idle.svg", b"<svg/>"), ("idle.gif", b"GIF? no")])


def test_without_an_idle_file_the_first_image_stands_in():
    plan = plan_character([("happy.gif", _gif()), ("sad.gif", _gif())])
    assert plan.idle_guessed and plan.states == {"idle": plan.images[0]}


def test_webp_is_recognised_by_its_riff_header():
    assert ch.sniff_image(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == ("image/webp", "webp")
    assert ch.sniff_image(b"RIFF\x10\x00\x00\x00WAVEfmt ") is None


def test_a_zip_declaring_a_huge_entry_is_refused_before_decompressing(monkeypatch):
    data = _zip({"idle.gif": _gif()})
    real_infolist = zipfile.ZipFile.infolist

    def bomb_infolist(self):
        infos = real_infolist(self)
        for info in infos:
            info.file_size = ch.MAX_CHARACTER_FILE_BYTES * 100
        return infos

    def no_reading(*_a, **_k):
        raise AssertionError("decompressed before checking the directory")

    monkeypatch.setattr(zipfile.ZipFile, "infolist", bomb_infolist)
    monkeypatch.setattr(zipfile.ZipFile, "open", no_reading)
    with pytest.raises(CharacterError, match="MB"):
        plan_character([("bomb.zip", data)])


def test_a_zip_whose_entries_add_up_past_the_total_is_refused(monkeypatch):
    monkeypatch.setattr(ch, "MAX_CHARACTER_TOTAL_BYTES", 3 * len(_gif()))
    with pytest.raises(CharacterError, match="in all"):
        plan_character([("pack.zip", _zip({f"{n}.gif": _gif() for n in SAMPLE_NAMES[:4]}))])


def test_a_zip_with_too_many_files_is_refused():
    entries = {f"frame-{i}.gif": _gif() for i in range(ch.MAX_CHARACTER_FILES + 1)}
    with pytest.raises(CharacterError, match="at most"):
        plan_character([("pack.zip", _zip(entries))])


def test_a_zip_that_understates_an_entry_still_cannot_sneak_it_past_the_cap(monkeypatch):
    monkeypatch.setattr(ch, "MAX_CHARACTER_FILE_BYTES", 1024)
    data = _zip({"idle.gif": b"GIF89a" + b"\0" * 10_000})  # compresses to almost nothing
    real_infolist = zipfile.ZipFile.infolist

    def lying_infolist(self):
        infos = real_infolist(self)
        for info in infos:
            info.file_size = 10
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", lying_infolist)
    with pytest.raises(CharacterError):
        plan_character([("liar.zip", data)])


def test_a_corrupt_zip_is_refused():
    with pytest.raises(CharacterError):
        plan_character([("pack.zip", b"PK\x03\x04 not really a zip")])


# --- clearing a solid background ---------------------------------------------------------------


def _gif_image(data: bytes, name: str = "look-loop.gif") -> ch.CharacterImage:
    return ch.CharacterImage(name=name, data=data, mime_type="image/gif", extension="gif")


def _corners(frame: Image.Image) -> list[tuple[int, int, int, int]]:
    last = images.SIZE - 1
    return [frame.getpixel(xy) for xy in ((0, 0), (last, 0), (0, last), (last, last))]


def test_clear_matte_on_a_matted_gif_clears_the_background_and_keeps_the_character():
    assert all(c[3] == 255 for f in images.frames_rgba(images.matted_gif()) for c in _corners(f))  # the box being fixed
    cleared = ch.clear_matte(_gif_image(images.matted_gif()))
    frames = images.frames_rgba(cleared.data)
    assert all(c[3] == 0 for f in frames for c in _corners(f))
    for offset, frame in enumerate(frames):
        assert frame.getpixel(images.body(offset)) == (*images.BODY, 255)
        # Near-black but not the matte: within any loose tolerance, so it would go with the background.
        assert frame.getpixel(images.outline(offset)) == (*images.OUTLINE, 255)
        # The matte's very colour, but no background reaches it: only edge-connected matte is cleared.
        assert frame.getpixel(images.eye(offset)) == (*images.EYE, 255)


def test_clear_matte_keeps_the_animations_timing_and_format():
    cleared = ch.clear_matte(_gif_image(images.matted_gif()))
    with Image.open(io.BytesIO(cleared.data)) as img:
        assert img.format == "GIF" and img.n_frames == len(images.DURATIONS) and img.info["loop"] == images.LOOP
        durations = []
        for i in range(img.n_frames):
            img.seek(i)
            durations.append(img.info["duration"])
    assert durations == images.DURATIONS
    assert (cleared.name, cleared.mime_type, cleared.extension) == ("look-loop.gif", "image/gif", "gif")


@pytest.mark.parametrize("data", [images.clean_gif(), _gif(), _png()], ids=["transparent", "one-colour", "empty"])
def test_clear_matte_leaves_an_image_without_a_matte_alone(data):
    assert ch.clear_matte(_gif_image(data)) is None


def test_clear_matte_on_a_still_png_with_a_matte():
    image = ch.CharacterImage(name="idle.png", data=images.matted_png(), mime_type="image/png", extension="png")
    (frame,) = images.frames_rgba(ch.clear_matte(image).data)
    assert all(c[3] == 0 for c in _corners(frame)) and frame.getpixel(images.body(0)) == (*images.BODY, 255)


def test_clear_matte_keeps_the_original_when_it_cannot_redo_it(monkeypatch):
    def broken(*_a, **_k):
        raise OSError("encoder exploded")

    monkeypatch.setattr(ch, "_encode", broken)
    assert ch.clear_matte(_gif_image(images.matted_gif())) is None


def test_clear_matte_never_makes_a_file_bigger_than_the_cap(monkeypatch):
    monkeypatch.setattr(ch, "MAX_CHARACTER_FILE_BYTES", 10)
    assert ch.clear_matte(_gif_image(images.matted_gif())) is None


def test_the_plan_lists_the_files_whose_background_was_cleared():
    matted = images.matted_gif()
    plan = plan_character([("idle.gif", images.clean_gif()), ("look-loop.gif", matted)])
    assert plan.cleared == ["look-loop.gif"]
    assert plan.states["idle_variant"].data != matted and plan.states["idle"].data == images.clean_gif()


# --- the stored character, through the controller -----------------------------------------------


@pytest.fixture
def workspace(db_session):
    """A throwaway workspace with an admin user; cleaned up after."""
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.platform import Assets
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"ch-{marker}", slug=f"ch-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    # A core insert: the ORM Users.__init__ has side effects (notifier seeding) a unit test doesn't want.
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Test User",
            username=f"u-{marker}",
            email=f"u-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=True,
        )
    )
    db_session.commit()
    yield gid, uid
    db_session.rollback()
    db_session.query(Assets).filter_by(group_id=gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(Users).filter_by(id=uid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def ctrl(db_session, workspace, tmp_path):
    """The controller's character methods, against the test DB and local storage under tmp_path."""
    import logging

    from marvin.repos.all_repositories import get_repositories
    from marvin.routes.groups.ai_settings_controller import AISettingsController
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.local_provider import LocalStorageProvider

    gid, uid = workspace
    repos = get_repositories(db_session, group_id=gid)
    storage = LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")
    c = SimpleNamespace(session=db_session, group_id=gid, user=SimpleNamespace(id=uid), repos=repos, logger=logging.getLogger("test"))
    c._require_admin = lambda: None
    c._allow_workspace_credentials = lambda: True
    c._settings_row = lambda: AISettingsController._settings_row(c)
    c._asset_service = lambda: AssetStorageService(repos, storage)
    c._character_store = lambda: AISettingsController._character_store(c)
    c._effective_character = lambda row: AISettingsController._effective_character(c, row)
    c._described = lambda row: AISettingsController._described(c, row)
    c.upload = lambda files: AISettingsController.upload_character(c, [UploadFile(io.BytesIO(d), filename=n) for n, d in files])
    c.assign = lambda state, file: AISettingsController.assign_character_state(c, ch_assign(state, file))
    c.delete = lambda: AISettingsController.delete_character(c)
    c.patch = lambda **kw: AISettingsController.update_ai_settings(c, ch_update(**kw))
    c.storage = storage
    return c


def ch_assign(state, file):
    from marvin.schemas.group.ai_settings import AssistantCharacterAssign

    return AssistantCharacterAssign(state=state, file=file)


def ch_update(**kw):
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    return WorkspaceAISettingsUpdate(**kw)


def _asset_ids(db_session, gid) -> set[str]:
    from marvin.db.models.platform import Assets

    db_session.expire_all()
    return {str(a.id) for a in db_session.query(Assets).filter_by(group_id=gid)}


def test_upload_stores_every_image_as_an_asset_and_maps_states(ctrl, db_session, workspace):
    res = ctrl.upload([("idle.gif", _gif()), ("waving.gif", _gif()), ("happy.gif", _gif()), ("notes.txt", b"hi")])
    assert set(res.states) == {"idle", "greeting"}
    assert [f.name for f in res.files] == ["idle.gif", "waving.gif", "happy.gif"]  # happy.gif kept, unassigned
    assert res.ignored == ["notes.txt"] and "thinking" in res.missing
    assert {f.asset_id for f in res.files} == _asset_ids(db_session, workspace[0])
    # The bubble loads each file by the same public URL the asset pages display.
    assert all(f.url == ctrl.repos.assets.get_one(uuid.UUID(f.asset_id)).public_url for f in res.files)


def test_upload_result_lists_the_files_whose_background_was_cleared(ctrl):
    res = ctrl.upload([("idle.gif", images.clean_gif()), ("look-loop.gif", images.matted_gif())])
    assert res.cleared == ["look-loop.gif"]


def test_path_traversal_names_only_label_the_file(ctrl, tmp_path):
    res = ctrl.upload([("evil.zip", _zip({"../../idle.gif": _gif(), "/etc/waving.gif": _gif()}))])
    assert [f.name for f in res.files] == ["idle.gif", "waving.gif"]
    assert not (tmp_path / "idle.gif").exists() and not (tmp_path.parent / "idle.gif").exists()
    stored = [p for p in (tmp_path / "store").rglob("*") if p.is_file()]
    assert len(stored) == 2 and all(p.resolve().is_relative_to((tmp_path / "store").resolve()) for p in stored)


def test_an_upload_without_images_is_a_422(ctrl):
    with pytest.raises(HTTPException) as exc:
        ctrl.upload([("idle.svg", b"<svg/>")])
    assert exc.value.status_code == 422


def test_replacing_the_character_deletes_all_its_old_assets(ctrl, db_session, workspace):
    first = ctrl.upload([("idle.gif", _gif()), ("happy.gif", _gif())])
    second = ctrl.upload([("idle.gif", _gif())])
    remaining = _asset_ids(db_session, workspace[0])
    assert remaining == {f.asset_id for f in second.files}
    assert not remaining & {f.asset_id for f in first.files}  # the unassigned happy.gif went too


def test_deleting_the_character_clears_it_and_its_assets(ctrl, db_session, workspace):
    ctrl.upload([("idle.gif", _gif()), ("happy.gif", _gif())])
    ctrl.delete()
    assert ctrl._settings_row().assistant_character is None
    assert _asset_ids(db_session, workspace[0]) == set()


def test_assigning_a_file_to_a_state(ctrl):
    up = ctrl.upload([("idle.gif", _gif()), ("happy.gif", _gif())])
    happy = next(f for f in up.files if f.name == "happy.gif")
    assert ctrl.assign("success", "happy.gif").states["success"] == happy.url
    assert ctrl.assign("greeting", happy.asset_id).states["greeting"] == happy.url  # by asset id too
    assert ctrl.assign("idle", "happy.gif").states["idle"] == happy.url  # idle can be reassigned


def test_clearing_a_state_lets_it_fall_back(ctrl):
    ctrl.upload([("idle.gif", _gif()), ("waving.gif", _gif())])
    res = ctrl.assign("greeting", None)
    assert "greeting" not in res.states and "greeting" in res.missing


@pytest.mark.parametrize(("state", "file"), [("idle", None), ("dancing", "idle.gif"), ("success", "someone-elses.gif")])
def test_bad_assignments_are_a_422(ctrl, state, file):
    ctrl.upload([("idle.gif", _gif())])
    with pytest.raises(HTTPException) as exc:
        ctrl.assign(state, file)
    assert exc.value.status_code == 422


def test_assigning_without_a_character_is_refused():
    with pytest.raises(CharacterError):
        assign_state(None, "idle", "idle.gif")


# --- the settings PATCH -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        {"states": {"idle": "/assets/a.gif", "dancing": "/assets/b.gif"}},
        {"states": {"greeting": "/assets/a.gif"}},
        {"states": {"idle": "javascript:alert(1)"}},
        {"states": {"idle": "/assets/a b.gif"}},
        {"idle": "/assets/a.gif"},
    ],
)
def test_character_problem_refuses_bad_values(value):
    assert character_problem(value)


@pytest.mark.parametrize("value", [None, {"states": {"idle": "https://cdn.example.com/a.gif", "error": "/assets/e.webp"}}])
def test_character_problem_accepts_good_values(value):
    assert character_problem(value) is None


def test_patching_a_bad_character_is_a_422():
    from marvin.routes.groups.ai_settings_controller import AISettingsController

    c = SimpleNamespace(_require_admin=lambda: None, _allow_workspace_credentials=lambda: True)
    with pytest.raises(HTTPException) as exc:
        AISettingsController.update_ai_settings(c, ch_update(assistant_character={"states": {"wave": "/x.gif"}}))
    assert exc.value.status_code == 422


def test_patching_states_keeps_the_servers_file_list(ctrl):
    up = ctrl.upload([("idle.gif", _gif())])
    res = ctrl.patch(assistant_character={"states": {"idle": "https://cdn.example.com/x.gif"}, "files": [{"assetId": "forged"}]})
    assert res.assistant_character["states"] == {"idle": "https://cdn.example.com/x.gif"}
    assert [f["assetId"] for f in res.assistant_character["files"]] == [f.asset_id for f in up.files]


def test_patching_null_removes_the_character_and_its_assets(ctrl, db_session, workspace):
    ctrl.upload([("idle.gif", _gif())])
    assert ctrl.patch(assistant_character=None).assistant_character is None
    assert _asset_ids(db_session, workspace[0]) == set()


def test_patching_other_fields_leaves_the_character_alone(ctrl):
    up = ctrl.upload([("idle.gif", _gif())])
    assert ctrl.patch(assistant_name="Ada").assistant_character["states"] == up.states


# --- where the drawing sits in its frame ----------------------------------------------------------


def _drawn_png(size: tuple[int, int], box: tuple[int, int, int, int]) -> ch.CharacterImage:
    """A transparent frame of `size` with an opaque rectangle filling `box` (left, top, right, bottom inclusive)."""
    from PIL import ImageDraw

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle(box, fill=(40, 90, 200, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return ch.CharacterImage(name="peek-top.png", data=buf.getvalue(), mime_type="image/png", extension="png")


def test_measure_inset_gives_the_empty_frame_on_each_side_as_a_share():
    inset = ch.measure_inset(_drawn_png((100, 50), (10, 5, 59, 39)))
    assert inset == {"top": 0.1, "right": 0.4, "bottom": 0.2, "left": 0.1}


def test_measure_inset_covers_every_frame_and_ignores_a_faint_fringe():
    frames = []
    for box in ((10, 10, 19, 19), (30, 20, 39, 29)):
        img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        img.paste((200, 0, 0, 255), box)
        img.putpixel((0, 0), (200, 0, 0, ch.INSET_ALPHA))  # antialiasing haze in the corner: still empty
        frames.append(img)
    buf = io.BytesIO()
    frames[0].save(buf, "PNG", save_all=True, append_images=frames[1:])
    inset = ch.measure_inset(ch.CharacterImage(name="a.png", data=buf.getvalue(), mime_type="image/png", extension="png"))
    assert inset == {"top": 0.2, "right": 0.22, "bottom": 0.42, "left": 0.2}


def test_measure_inset_is_none_for_an_empty_frame_or_unreadable_bytes():
    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buf, "PNG")
    assert ch.measure_inset(ch.CharacterImage(name="e.png", data=buf.getvalue(), mime_type="image/png", extension="png")) is None
    assert ch.measure_inset(ch.CharacterImage(name="x.gif", data=b"GIF89a-not-really", mime_type="image/gif", extension="gif")) is None
