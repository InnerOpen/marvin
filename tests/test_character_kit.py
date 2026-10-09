"""src/dev/character_kit: a 16-pose sheet on magenta becomes a whole bubble-character pack, the pose prompt is filled
from the recipe and a character's bible, and library packs become reference sheets. Dev tooling (not shipped), tested
here so a recipe or cutting change can't silently break every character's pack."""

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageSequence

KIT = Path(__file__).resolve().parents[1] / "src" / "dev" / "character_kit"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"character_kit_{name}", KIT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kit = _load("character_from_poses")
prompts = _load("make_prompt")
references = _load("export_references")


def _sheet(poses: int = 16, size: int = 1024) -> Image.Image:
    """A pose sheet like the image model's: figures on flat magenta, 4 to a row. Each is a beige body with a dark
    outline and two 'feet', a little different from the next so the cut keeps the order visible."""
    img = Image.new("RGB", (size, size), (255, 0, 255))
    d = ImageDraw.Draw(img)
    cell = size // 4
    for i in range(poses):
        x0, y0 = (i % 4) * cell + cell // 4, (i // 4) * cell + cell // 6
        w, h = cell // 2, cell * 2 // 3
        d.rectangle([x0, y0, x0 + w, y0 + h - 12], fill=(200, 180, 140), outline=(40, 30, 20), width=3)
        d.rectangle([x0 + 4, y0 + h - 12, x0 + w // 3, y0 + h], fill=(40, 30, 20))  # left foot
        d.rectangle([x0 + w - w // 3, y0 + h - 12, x0 + w - 4, y0 + h], fill=(40, 30, 20))  # right foot
        d.rectangle([x0 + 6, y0 + 6, x0 + 6 + i * 3, y0 + 12], fill=(20, 120, 40))  # a bar as long as its number
    return img


@pytest.fixture(scope="module")
def pack():
    return kit.Builder(_sheet(), kit.load_recipe()).build()


def _alpha(frame: Image.Image) -> np.ndarray:
    return np.array(frame)[..., 3]


def test_every_animation_in_the_recipe_is_built_in_its_order_at_the_frame_size(pack):
    recipe = kit.load_recipe()
    assert list(pack) == list(recipe["animations"])
    size = recipe["frame"]
    assert all(f.size == (size, size) for frames, _ in pack.values() for f in frames)
    assert all(len(frames) == 8 for frames, _ in pack.values())


def test_poses_are_cut_in_order_and_magenta_is_gone():
    builder = kit.Builder(_sheet(), kit.load_recipe())
    ids = [p["id"] for p in kit.load_recipe()["poses"]]
    bars = []
    for pid in ids:
        a = np.array(builder.pose[pid])
        green = (a[..., 1] > 90) & (a[..., 0] < 60) & (a[..., 3] > 0)
        bars.append(int(green.any(axis=0).sum()))
        assert not ((a[..., 0] > 200) & (a[..., 2] > 200) & (a[..., 1] < 60) & (a[..., 3] > 0)).any()  # no magenta
    assert bars == sorted(bars)  # pose i has the i-th longest bar: row by row, left to right


def test_standing_poses_share_one_scale_and_ground_line(pack):
    recipe = kit.load_recipe()
    first = _alpha(pack["idle"][0][0])
    rows = np.nonzero((first > 0).any(axis=1))[0]
    assert rows.max() == recipe["ground"] - 1  # feet on the ground line
    assert rows.max() - rows.min() + 1 == pytest.approx(recipe["height"], abs=2)


def test_a_jump_leaves_the_ground_and_lands(pack):
    bottoms = [np.nonzero((_alpha(f) > 0).any(axis=1))[0].max() for f in pack["jumping"][0]]
    assert min(bottoms) < bottoms[0] - 10 and bottoms[-1] == bottoms[0]


def test_running_right_is_running_left_mirrored(pack):
    left, right = pack["running-left"][0], pack["running-right"][0]
    assert all((_alpha(a)[:, ::-1] == _alpha(b)).all() for a, b in zip(left, right, strict=True))


LEDGES = [("left", np.s_[:, :12]), ("right", np.s_[:, -12:]), ("top", np.s_[:12, 4:-4]), ("bottom", np.s_[-12:, 4:-4])]


@pytest.mark.parametrize(("edge", "ledge"), LEDGES)
def test_each_peek_has_a_still_ledge_flush_with_its_edge_and_plays_once(pack, edge, ledge):
    recipe = kit.load_recipe()
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
    with pytest.raises(kit.SheetError, match="found 12 drawings"):
        kit.Builder(_sheet(poses=12), kit.load_recipe())
    with pytest.raises(kit.SheetError, match="magenta"):
        kit.Builder(Image.new("RGB", (512, 512), (255, 255, 255)), kit.load_recipe())


def test_write_pack_zips_one_gif_per_animation_named_for_the_uploader(tmp_path):
    sheet = tmp_path / "poses.png"
    _sheet().save(sheet)
    zip_path = kit.write_pack(sheet, tmp_path / "out", "testy")
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())
        gif = Image.open(io.BytesIO(zf.read("peek-left.gif")))
        durations = [f.info["duration"] for f in ImageSequence.Iterator(gif)]
    assert names == sorted(f"{n}.gif" for n in kit.load_recipe()["animations"])
    assert sum(durations) >= 1800
    assert (tmp_path / "out" / "preview.png").exists()


def test_the_prompt_lists_every_pose_in_sheet_order_and_the_bible(tmp_path, monkeypatch):
    (tmp_path / "characters" / "testy").mkdir(parents=True)
    bible = {"name": "Testy", "description": "a small test cube", "style": "pixel-art", "rules": ["always blue"]}
    (tmp_path / "characters" / "testy" / "character.json").write_text(json.dumps(bible))
    (tmp_path / "recipe.json").write_text((KIT / "recipe.json").read_text())
    (tmp_path / "prompt.md").write_text((KIT / "prompt.md").read_text())
    monkeypatch.setattr(prompts, "KIT", tmp_path)
    text = prompts.make_prompt("testy")
    poses = kit.load_recipe()["poses"]
    assert '"Testy": a small test cube' in text and "Always: always blue." in text
    positions = [text.index(f"{i + 1} {p['prompt']}") for i, p in enumerate(poses)]
    assert positions == sorted(positions)
    assert "#FF00FF" in text and "{" not in text  # every placeholder filled


def test_a_reference_sheet_shows_each_states_clearest_frame_the_same_size():
    def gif(frames):
        buf = io.BytesIO()
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], transparency=0, disposal=2)
        return buf.getvalue()

    def figure(w, h, canvas=64):
        im = Image.new("P", (canvas, canvas), 0)
        im.putpalette([255, 255, 255, 30, 30, 200] + [0, 0, 0] * 254)
        ImageDraw.Draw(im).rectangle([2, canvas - h, 2 + w, canvas - 1], fill=1)
        return im

    blank_then_full = gif([figure(2, 2), figure(40, 50)])  # a wave whose first frame shows almost nothing
    small = gif([figure(10, 12, canvas=24)])
    sheet = references.reference_sheet([blank_then_full, small])
    assert sheet.size == (2 * references.TILE, references.TILE)
    a = np.array(sheet.convert("L")) < 128
    heights = [int(a[:, i * references.TILE : (i + 1) * references.TILE].any(axis=1).sum()) for i in range(2)]
    assert heights[0] > references.TILE * 0.8 and abs(heights[0] - heights[1]) < references.TILE * 0.1


# --- clipping -------------------------------------------------------------------------------------------------------


def test_a_drawing_running_off_the_frame_is_reported_but_a_peeks_own_edge_is_not():
    clear = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(clear).rectangle([20, 20, 100, 124], fill=(10, 10, 10, 255))
    assert kit.clipped_edges(clear) == []
    off = clear.copy()
    ImageDraw.Draw(off).rectangle([0, 40, 30, 60], fill=(10, 10, 10, 255))  # an arm out of the left side
    assert kit.clipped_edges(off) == ["left"]
    assert kit.clipped_edges(off, ledge="left", ledge_width=12) == []  # hiding behind its own ledge is the point


def test_too_wide_a_character_gets_a_warning_and_a_smaller_height_clears_it():
    def wide_sheet():  # 16 squat, wide figures, like Rocky
        img = Image.new("RGB", (1024, 1024), (255, 0, 255))
        d = ImageDraw.Draw(img)
        for i in range(16):
            x0, y0 = (i % 4) * 256 + 18, (i // 4) * 256 + 90
            d.rectangle([x0, y0, x0 + 220, y0 + 110], fill=(150, 120, 90), outline=(40, 30, 20), width=3)
        return img

    recipe = kit.load_recipe()
    builder = kit.Builder(wide_sheet(), recipe)
    assert any("cut off" in w for w in builder.clip_warnings(builder.build()))
    smaller = {**recipe, "height": 40}
    builder = kit.Builder(wide_sheet(), smaller)
    assert builder.clip_warnings(builder.build()) == []


def test_tilting_and_jumping_keep_the_drawing_inside_the_frame(pack):
    recipe = kit.load_recipe()
    for name, beside_ledge in (("failed", np.s_[:, :]), ("peek-left", np.s_[:, 12:])):  # not the drawn ledge
        for f in pack[name][0]:
            rows = np.nonzero((_alpha(f)[beside_ledge] > 0).any(axis=1))[0]
            assert rows.max() <= recipe["ground"] - 1  # a tilt never sinks below the ground line
    tops = [np.nonzero((_alpha(f) > 0).any(axis=1))[0].min() for f in pack["jumping"][0]]
    assert min(tops) >= 1  # the jump tops out at the frame, the head isn't cut off


def test_a_characters_own_height_is_used(tmp_path, monkeypatch):
    folder = tmp_path / "characters" / "testy"
    folder.mkdir(parents=True)
    _sheet().save(folder / "poses.png")
    (folder / "character.json").write_text(json.dumps({"name": "Testy", "description": "x", "height": 80}))
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.main(["testy"]) == 0
    idle = Image.open(folder / "out" / "gifs" / "idle.gif").convert("RGBA")
    rows = np.nonzero((np.array(idle)[..., 3] > 0).any(axis=1))[0]
    assert rows.max() - rows.min() + 1 == pytest.approx(80, abs=2)
