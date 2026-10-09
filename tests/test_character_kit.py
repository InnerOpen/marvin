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
    _prompt_kit(tmp_path, monkeypatch)
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


# --- a new character from a description ----------------------------------------------------------------------------


def _prompt_kit(tmp_path, monkeypatch):
    (tmp_path / "characters" / "testy").mkdir(parents=True)
    bible = {"name": "Testy", "description": "a small test cube", "style": "pixel-art", "rules": ["always blue"]}
    (tmp_path / "characters" / "testy" / "character.json").write_text(json.dumps(bible))
    for name in ("recipe.json", "prompt.md", "intro-reference.md", "intro-new.md"):
        (tmp_path / name).write_text((KIT / name).read_text())
    monkeypatch.setattr(prompts, "KIT", tmp_path)


def test_a_new_character_is_designed_from_its_description_without_a_reference(tmp_path, monkeypatch, capsys):
    _prompt_kit(tmp_path, monkeypatch)
    text = prompts.make_prompt("testy", new=True)
    assert 'Design a new mascot character called "Testy": a small test cube' in text
    assert "attached image shows my character" not in text and "{" not in text  # only the layout guide is attached
    assert prompts.main(["testy"]) == 1  # redrawing needs a reference.png
    assert "--new" in capsys.readouterr().err
    assert prompts.main(["testy", "--new"]) == 0


def test_a_new_characters_first_sheet_becomes_its_reference(tmp_path, monkeypatch):
    folder = tmp_path / "characters" / "testy"
    folder.mkdir(parents=True)
    _sheet().save(folder / "poses.png")
    (folder / "character.json").write_text(json.dumps({"name": "Testy", "description": "x"}))
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.main(["testy"]) == 0
    reference = Image.open(folder / "reference.png")
    assert reference.size == (384 * len(kit.REFERENCE_POSES), 384)
    before = (folder / "reference.png").read_bytes()
    assert kit.main(["testy"]) == 0
    assert (folder / "reference.png").read_bytes() == before  # an existing reference is never replaced


def test_big_poses_close_together_with_loose_pieces_still_cut_into_sixteen():
    """Like Mossy: wide poses only a little apart, each with a detached piece (a stone foot) set off from its body."""
    img = Image.new("RGB", (1024, 1024), (255, 0, 255))
    d = ImageDraw.Draw(img)
    for i in range(16):
        x0, y0 = (i % 4) * 256 + 6, (i // 4) * 256 + 20
        d.rectangle([x0, y0, x0 + 220, y0 + 180], fill=(150, 150, 140), outline=(40, 40, 40), width=3)  # 30 px apart
        d.rectangle([x0 + 20, y0 + 196, x0 + 80, y0 + 226], fill=(120, 120, 110))  # a separate foot, 16 px below
        d.rectangle([x0 + 6 + i * 8, y0 + 10, x0 + 14 + i * 8, y0 + 20], fill=(20, 120, 40))  # a mark of its order
    poses = kit.cut_poses(kit.key_background(img), 16)
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
    a = kit.key_background(img)[..., 3]
    assert (a[115:155, 115:285] == 255).all()  # crimson kept
    assert (a[175:215, 115:285] == 255).all()  # purple kept
    assert (a[245:300, 185:215] == 0).all()  # the gap between the legs is background
    assert (a[99, 120:280] == 0).all()  # the blend beside the background goes too
    assert a[0, 0] == 0


# --- ChatGPT pet sheets ----------------------------------------------------------------------------------------------

pets = _load("pet_to_pack")


def _pet_sheet(rows: int = 11, cell: tuple[int, int] = (96, 104), empty_after: dict | None = None) -> Image.Image:
    """A ChatGPT-style pet sheet: 8 columns of 192×208-shaped cells, a transparent background, a figure per cell;
    the jumping row (4) lifted off the ground, each row ending early where `empty_after` says."""
    w, h = cell
    img = Image.new("RGBA", (8 * w, rows * h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    empty_after = empty_after or {0: 7, 3: 4, 4: 5}
    for r in range(rows):
        for c in range(empty_after.get(r, 8)):
            x0, y0 = c * w + w // 4, r * h + h // 4
            lift = 10 + c * 2 if r == 4 else 0
            d.rectangle([x0, y0 - lift, x0 + w // 2, y0 + h // 2 - lift], fill=(200, 120, 40, 255), outline=(40, 20, 10, 255), width=2)
    return img


def test_a_pet_sheet_keeps_every_row_as_drawn_with_one_placement(tmp_path):
    path = tmp_path / "pet.png"
    _pet_sheet().save(path)
    pet = pets.PetPack(pets.read_sheet(path), kit.load_recipe())
    pack = pet.build()
    assert len(pack["idle"][0]) == 7 and len(pack["waving"][0]) == 4 and len(pack["jumping"][0]) == 5
    bottom = lambda f: np.nonzero((_alpha(f) > 0).any(axis=1))[0].max()  # noqa: E731
    idle_bottom = bottom(pack["idle"][0][0])
    assert idle_bottom == kit.load_recipe()["ground"] - 1
    assert all(bottom(f) < idle_bottom - 4 for f in pack["jumping"][0])  # the drawn jump still leaves the ground
    assert {"look-loop", "peek-left", "peek-right", "peek-top", "peek-bottom"} <= set(pack)  # v2 + the kit's peeks


def test_a_v1_pet_sheet_has_no_look_rows_and_a_wrong_sheet_is_refused(tmp_path):
    v1 = tmp_path / "v1.png"
    _pet_sheet(rows=9).save(v1)
    pack = pets.PetPack(pets.read_sheet(v1), kit.load_recipe()).build()
    assert "look-loop" not in pack and "idle" in pack
    odd = tmp_path / "odd.png"
    Image.new("RGBA", (800, 300), (0, 0, 0, 0)).save(odd)
    with pytest.raises(pets.SheetError, match="isn't a ChatGPT pet sheet"):
        pets.PetPack(pets.read_sheet(odd), kit.load_recipe())


def test_a_pet_too_big_for_the_frame_is_built_smaller_until_nothing_is_cut_off(tmp_path):
    path = tmp_path / "pet.png"
    img = _pet_sheet()
    d = ImageDraw.Draw(img)
    d.rectangle([7 * 96 + 2, 4 * 104 + 2, 8 * 96 - 2, 4 * 104 + 30], fill=(200, 120, 40, 255))  # a wide prop in one frame
    img.save(path)
    zip_path, warnings, height = pets.write(path, tmp_path / "out", "testy")
    assert warnings == [] and height < kit.load_recipe()["height"]
    with zipfile.ZipFile(zip_path) as zf:
        assert "running.gif" in zf.namelist() and "look-loop.gif" in zf.namelist()


# --- background colour and layout guide --------------------------------------------------------------------------------


def test_the_background_keeps_clear_of_the_characters_colours(tmp_path):
    assert prompts.choose_background({"description": "a small grey robot"}, None)[0] == "magenta"
    assert prompts.choose_background({"description": "a purple robot with pink cheeks"}, None)[0] != "magenta"
    assert prompts.choose_background({"description": "x", "rules": ["green moss"]}, None)[0] == "magenta"
    assert prompts.choose_background({"description": "x", "background": "cyan"}, None) == ("cyan", (0, 255, 255))
    reference = tmp_path / "reference.png"
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    ImageDraw.Draw(img).rectangle([20, 20, 180, 80], fill=(170, 60, 230))  # a purple character on the white page
    img.save(reference)
    name, colour = prompts.choose_background({"description": "x"}, reference)
    assert name != "magenta" and np.sqrt(((np.array(colour) - (170, 60, 230)) ** 2).sum()) > 200


def test_a_sheet_on_any_flat_background_is_cut_and_its_guide_lines_vanish(tmp_path):
    green = _sheet().convert("RGB")
    a = np.array(green)
    a[(a == (255, 0, 255)).all(axis=2)] = (0, 255, 0)  # the same sheet, drawn on green
    builder = kit.Builder(Image.fromarray(a), kit.load_recipe())
    assert len(builder.pose) == 16
    guide = tmp_path / "guide.png"
    prompts.layout_guide((0, 255, 0), guide)
    assert (kit.key_background(Image.open(guide))[..., 3] == 0).all()  # copied guide lines would be keyed away


def test_the_prompt_names_its_background_and_asks_for_the_guide(tmp_path, monkeypatch):
    _prompt_kit(tmp_path, monkeypatch)
    text = prompts.make_prompt("testy", new=True)
    assert "exactly #FF00FF (magenta)" in text and "layout guide" in text
    assert (tmp_path / "characters" / "testy" / "layout-guide.png").exists()
