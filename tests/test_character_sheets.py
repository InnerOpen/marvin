"""services/ai/character_sheets.py: ONE character sheet — a 16-pose sheet on a flat colour, or a ChatGPT pet sheet —
becomes a whole bubble-character pack, fitted to the frame; anything else is recognised as not a sheet. (The dev kit's
command lines over it are tests/test_character_kit.py; an upload of a sheet is tests/test_assistant_character.py.)"""

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageSequence

from marvin.services.ai import character_sheets as sheets
from tests.character_images import pet_sheet, pose_sheet


@pytest.fixture(scope="module")
def pack():
    return sheets.Builder(pose_sheet(), sheets.load_recipe()).build()


def _alpha(frame: Image.Image) -> np.ndarray:
    return np.array(frame)[..., 3]


def _bottom(frame: Image.Image) -> int:
    return int(np.nonzero((_alpha(frame) > 0).any(axis=1))[0].max())


# --- a 16-pose sheet --------------------------------------------------------------------------------------------------


def test_every_animation_in_the_recipe_is_built_in_its_order_at_the_frame_size(pack):
    recipe = sheets.load_recipe()
    assert list(pack) == list(recipe["animations"])
    size = recipe["frame"]
    assert all(f.size == (size, size) for frames, _ in pack.values() for f in frames)
    assert all(len(frames) == 8 for frames, _ in pack.values())


def test_poses_are_cut_in_order_and_magenta_is_gone():
    builder = sheets.Builder(pose_sheet(), sheets.load_recipe())
    bars = []
    for pid in [p["id"] for p in sheets.load_recipe()["poses"]]:
        a = np.array(builder.pose[pid])
        green = (a[..., 1] > 90) & (a[..., 0] < 60) & (a[..., 3] > 0)
        bars.append(int(green.any(axis=0).sum()))
        assert not ((a[..., 0] > 200) & (a[..., 2] > 200) & (a[..., 1] < 60) & (a[..., 3] > 0)).any()  # no magenta
    assert bars == sorted(bars)  # pose i has the i-th longest bar: row by row, left to right


def test_standing_poses_share_one_scale_and_ground_line(pack):
    recipe = sheets.load_recipe()
    first = _alpha(pack["idle"][0][0])
    rows = np.nonzero((first > 0).any(axis=1))[0]
    assert rows.max() == recipe["ground"] - 1  # feet on the ground line
    assert rows.max() - rows.min() + 1 == pytest.approx(recipe["height"], abs=2)


def test_a_jump_leaves_the_ground_and_lands(pack):
    bottoms = [_bottom(f) for f in pack["jumping"][0]]
    assert min(bottoms) < bottoms[0] - 10 and bottoms[-1] == bottoms[0]


def test_running_right_is_running_left_mirrored(pack):
    left, right = pack["running-left"][0], pack["running-right"][0]
    assert all((_alpha(a)[:, ::-1] == _alpha(b)).all() for a, b in zip(left, right, strict=True))


LEDGES = [("left", np.s_[:, :12]), ("right", np.s_[:, -12:]), ("top", np.s_[:12, 4:-4]), ("bottom", np.s_[-12:, 4:-4])]


@pytest.mark.parametrize(("edge", "ledge"), LEDGES)
def test_each_peek_has_a_still_ledge_flush_with_its_edge_and_plays_once(pack, edge, ledge):
    recipe = sheets.load_recipe()
    frames, timing = pack[f"peek-{edge}"]
    ledges = [np.array(f)[ledge] for f in frames]
    if edge in ("left", "right"):
        ledges = [part[6:-1] for part in ledges]
    assert all((part[..., 3] == 255).all() for part in ledges)
    assert all((part[..., :3] == recipe["ledge"]["rgb"]).all() for part in ledges)
    assert sum(timing) >= 1800  # one slow peek fills the ~2 s the bubble is out, so it doesn't play twice


def test_a_side_peek_leans_out_and_stays_mostly_hidden(pack):
    frames = pack["peek-left"][0]
    shown = [int((_alpha(f)[:, 12:] > 0).sum()) for f in frames]
    assert shown[3] > shown[0] * 3  # out further at the peak
    standing = int((_alpha(pack["idle"][0][0]) > 0).sum())
    assert shown[3] < standing * 0.6  # a peek, not a step out


def test_a_sheet_with_the_wrong_number_of_poses_says_so():
    with pytest.raises(sheets.SheetError, match="found 12 drawings"):
        sheets.Builder(pose_sheet(poses=12), sheets.load_recipe())
    with pytest.raises(sheets.SheetError, match="magenta"):
        sheets.Builder(Image.new("RGB", (512, 512), (255, 255, 255)), sheets.load_recipe())


def test_tilting_and_jumping_keep_the_drawing_inside_the_frame(pack):
    recipe = sheets.load_recipe()
    for name, beside_ledge in (("failed", np.s_[:, :]), ("peek-left", np.s_[:, 12:])):  # not the drawn ledge
        for f in pack[name][0]:
            rows = np.nonzero((_alpha(f)[beside_ledge] > 0).any(axis=1))[0]
            assert rows.max() <= recipe["ground"] - 1  # a tilt never sinks below the ground line
    tops = [np.nonzero((_alpha(f) > 0).any(axis=1))[0].min() for f in pack["jumping"][0]]
    assert min(tops) >= 1  # the jump tops out at the frame, the head isn't cut off


def test_big_poses_close_together_with_loose_pieces_still_cut_into_sixteen():
    """Like Mossy: wide poses only a little apart, each with a detached piece (a stone foot) set off from its body."""
    img = Image.new("RGB", (1024, 1024), (255, 0, 255))
    d = ImageDraw.Draw(img)
    for i in range(16):
        x0, y0 = (i % 4) * 256 + 6, (i // 4) * 256 + 20
        d.rectangle([x0, y0, x0 + 220, y0 + 180], fill=(150, 150, 140), outline=(40, 40, 40), width=3)  # 30 px apart
        d.rectangle([x0 + 20, y0 + 196, x0 + 80, y0 + 226], fill=(120, 120, 110))  # a separate foot, 16 px below
        d.rectangle([x0 + 6 + i * 8, y0 + 10, x0 + 14 + i * 8, y0 + 20], fill=(20, 120, 40))  # a mark of its order
    poses = sheets.cut_poses(sheets.key_background(img), 16)
    assert len(poses) == 16
    assert all(p.shape[0] > 200 for p in poses)  # each kept its foot
    marks = [int(np.nonzero(((p[..., 1] > 100) & (p[..., 0] < 60)).any(axis=0))[0].min()) for p in poses]
    assert marks == sorted(marks)  # still in row-by-row order


def test_keying_keeps_reds_and_purples_and_clears_magenta_even_between_limbs():
    """Fireball Mini lost its crimson cap to a key that dropped anything 'more red and blue than green'."""
    img = Image.new("RGB", (400, 400), (246, 5, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([100, 100, 300, 300], fill=(40, 30, 20))  # a dark outline…
    d.rectangle([110, 110, 290, 160], fill=(208, 0, 48))  # …around a crimson cap
    d.rectangle([110, 170, 290, 220], fill=(150, 60, 200))  # a purple body
    d.rectangle([180, 240, 220, 300], fill=(246, 5, 245))  # magenta showing between two legs, closed in
    d.rectangle([99, 99, 301, 99], fill=(220, 70, 210))  # the soft blend along the outline's top edge
    a = sheets.key_background(img)[..., 3]
    assert (a[115:155, 115:285] == 255).all()  # crimson kept
    assert (a[175:215, 115:285] == 255).all()  # purple kept
    assert (a[245:300, 185:215] == 0).all()  # the gap between the legs is background
    assert (a[99, 120:280] == 0).all()  # the blend beside the background goes too
    assert a[0, 0] == 0


def test_a_sheet_on_any_flat_background_is_cut():
    a = np.array(pose_sheet())
    a[(a == (255, 0, 255)).all(axis=2)] = (0, 255, 0)  # the same sheet, drawn on green
    assert len(sheets.Builder(Image.fromarray(a), sheets.load_recipe()).pose) == 16


# --- clipping and fitting ---------------------------------------------------------------------------------------------


def test_a_drawing_running_off_the_frame_is_reported_but_a_peeks_own_edge_is_not():
    clear = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(clear).rectangle([20, 20, 100, 124], fill=(10, 10, 10, 255))
    assert sheets.clipped_edges(clear) == []
    off = clear.copy()
    ImageDraw.Draw(off).rectangle([0, 40, 30, 60], fill=(10, 10, 10, 255))  # an arm out of the left side
    assert sheets.clipped_edges(off) == ["left"]
    assert sheets.clipped_edges(off, ledge="left", ledge_width=12) == []  # hiding behind its own ledge is the point


def _wide_sheet() -> Image.Image:
    """16 squat, wide figures, like Rocky: cut off at the recipe's height, fine smaller."""
    img = Image.new("RGB", (1024, 1024), (255, 0, 255))
    d = ImageDraw.Draw(img)
    for i in range(16):
        x0, y0 = (i % 4) * 256 + 18, (i // 4) * 256 + 90
        d.rectangle([x0, y0, x0 + 150, y0 + 110], fill=(150, 120, 90), outline=(40, 30, 20), width=3)
    return img


def test_too_wide_a_character_at_full_height_is_cut_off_and_a_fitted_one_is_not():
    recipe = sheets.load_recipe()
    builder = sheets.Builder(_wide_sheet(), recipe)
    assert any("cut off" in w for w in builder.clip_warnings(builder.build()))
    rgba = sheets.key_background(_wide_sheet())
    assert sheets.build_poses(rgba, recipe, height=recipe["height"]).warnings  # a height given is kept
    fitted = sheets.build_poses(rgba, recipe)
    assert fitted.warnings == [] and sheets.MIN_HEIGHT <= fitted.height < recipe["height"]
    assert len(fitted.drawn) == 16  # the poses as drawn, for the kit's reference sheet


def test_a_character_that_fits_is_built_at_the_recipes_height():
    recipe = sheets.load_recipe()
    built = sheets.build_poses(sheets.key_background(pose_sheet()), recipe)
    assert (built.kind, built.height, built.warnings) == (sheets.POSE_SHEET, recipe["height"], [])


# --- ChatGPT pet sheets -----------------------------------------------------------------------------------------------


def test_a_pet_sheet_keeps_every_row_as_drawn_with_one_placement():
    pack = sheets.PetPack(np.array(pet_sheet()), sheets.load_recipe()).build()
    assert len(pack["idle"][0]) == 7 and len(pack["waving"][0]) == 4 and len(pack["jumping"][0]) == 5
    idle_bottom = _bottom(pack["idle"][0][0])
    assert idle_bottom == sheets.load_recipe()["ground"] - 1
    assert all(_bottom(f) < idle_bottom - 4 for f in pack["jumping"][0])  # the drawn jump still leaves the ground
    assert {"look-loop", "peek-left", "peek-right", "peek-top", "peek-bottom"} <= set(pack)  # v2 + the recipe's peeks


def test_a_v1_pet_sheet_has_no_look_rows_and_a_wrong_sheet_is_refused():
    pack = sheets.PetPack(np.array(pet_sheet(rows=9)), sheets.load_recipe()).build()
    assert "look-loop" not in pack and "idle" in pack
    with pytest.raises(sheets.SheetError, match="isn't a ChatGPT pet sheet"):
        sheets.PetPack(np.zeros((300, 800, 4), np.uint8), sheets.load_recipe())


def test_a_pet_too_big_for_the_frame_is_built_smaller_until_nothing_is_cut_off():
    img = pet_sheet()
    ImageDraw.Draw(img).rectangle([7 * 96 + 2, 4 * 104 + 2, 8 * 96 - 2, 4 * 104 + 30], fill=(200, 120, 40, 255))  # a wide prop
    recipe = sheets.load_recipe()
    plain = sheets.build_pet(sheets.sheet_rgba(pet_sheet()), recipe)
    built = sheets.build_pet(sheets.sheet_rgba(img), recipe)
    assert built.kind == sheets.PET_SHEET and built.warnings == [] and built.height < plain.height
    assert {"running", "look-loop"} <= set(built.animations)


# --- recognising a sheet ----------------------------------------------------------------------------------------------


def test_a_pose_sheet_is_recognised_and_built_whole():
    built = sheets.build_from_sheet(pose_sheet())
    assert built.kind == sheets.POSE_SHEET and list(built.animations) == list(sheets.load_recipe()["animations"])


def test_a_pose_sheet_on_a_transparent_background_is_recognised_too():
    a = np.array(pose_sheet().convert("RGBA"))
    a[(a[..., :3] == (255, 0, 255)).all(axis=2)] = 0
    assert sheets.build_from_sheet(Image.fromarray(a)).kind == sheets.POSE_SHEET


def test_a_pet_sheet_is_recognised_on_transparency_or_a_flat_colour():
    assert sheets.build_from_sheet(pet_sheet()).kind == sheets.PET_SHEET
    flat = Image.new("RGB", pet_sheet().size, (0, 255, 0))
    flat.paste(pet_sheet(), mask=pet_sheet())
    assert sheets.build_from_sheet(flat).kind == sheets.PET_SHEET


@pytest.mark.parametrize(
    "image",
    [
        pytest.param(lambda: pose_sheet(poses=12), id="12 poses"),
        pytest.param(lambda: Image.new("RGB", (1024, 1024), (255, 255, 255)), id="a white page"),
        pytest.param(lambda: Image.new("RGB", (2048, 1024), (255, 0, 255)), id="too wide for a pose sheet"),
    ],
)
def test_an_image_that_isnt_quite_a_pose_sheet_is_not_one(image):
    assert sheets.build_from_sheet(image()) is None


def test_a_single_character_is_not_a_sheet():
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([150, 100, 350, 460], fill=(200, 180, 140, 255), outline=(40, 30, 20, 255), width=4)
    d.ellipse([200, 160, 230, 190], fill=(0, 0, 0, 255))  # an eye
    d.ellipse([270, 160, 300, 190], fill=(0, 0, 0, 255))
    assert sheets.build_from_sheet(img) is None


def test_a_picture_shaped_like_a_pet_sheet_but_drawn_across_its_cells_is_not_one():
    """A transparent form (a poster with ruled lines) can have a pet sheet's exact shape; its lines cross the cells."""
    img = Image.new("RGBA", pet_sheet().size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, img.width - 5, img.height - 5], outline=(0, 0, 0, 255), width=3)
    for y in range(80, img.height - 40, 40):
        d.line([20, y, img.width - 20, y], fill=(0, 0, 0, 255), width=2)
    assert sheets.build_from_sheet(img) is None


def test_an_animation_is_never_a_sheet():
    frames = [pose_sheet().convert("P"), pose_sheet(poses=12).convert("P")]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:])
    with Image.open(io.BytesIO(buf.getvalue())) as gif:
        assert sheets.build_from_sheet(gif) is None


def test_gif_bytes_is_a_looping_transparent_animation_with_its_timing(pack):
    frames, timing = pack["peek-left"]
    with Image.open(io.BytesIO(sheets.gif_bytes(frames, timing))) as gif:
        played = [(f.info["duration"], f.convert("RGBA")) for f in ImageSequence.Iterator(gif)]
        assert gif.info["loop"] == 0
    assert sum(ms for ms, _ in played) == sum(timing)  # a held frame may be merged with the next, its time kept
    assert played[0][1].getpixel((127, 0))[3] == 0  # the corner away from the ledge is clear
