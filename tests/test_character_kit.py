"""src/dev/character_kit: the command lines over Marvin's character building (services/ai/character_sheets.py,
tested in tests/test_character_sheets.py) — a character's sheet becomes its pack's files, the pose prompt is filled
from the recipe and a character's bible, and library packs become reference sheets. Dev tooling (not shipped), tested
here so a change can't silently break every character's pack."""

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageSequence

from marvin.services.ai.character_sheets import key_background, load_recipe
from tests.character_images import pet_sheet, pose_sheet

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
pets = _load("pet_to_pack")


def _standing_height(gif_path: Path) -> int:
    rows = np.nonzero((np.array(Image.open(gif_path).convert("RGBA"))[..., 3] > 0).any(axis=1))[0]
    return int(rows.max() - rows.min() + 1)


def test_write_pack_zips_one_gif_per_animation_named_for_the_uploader(tmp_path):
    sheet = tmp_path / "poses.png"
    pose_sheet().save(sheet)
    zip_path, built = kit.write_pack(sheet, tmp_path / "out", "testy")
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())
        gif = Image.open(io.BytesIO(zf.read("peek-left.gif")))
        durations = [f.info["duration"] for f in ImageSequence.Iterator(gif)]
    assert names == sorted(f"{n}.gif" for n in load_recipe()["animations"])
    assert sum(durations) >= 1800
    assert (tmp_path / "out" / "preview.png").exists() and built.warnings == []


def test_the_prompt_lists_every_pose_in_sheet_order_and_the_bible(tmp_path, monkeypatch):
    _prompt_kit(tmp_path, monkeypatch)
    text = prompts.make_prompt("testy")
    poses = load_recipe()["poses"]
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


def test_a_characters_own_height_is_used(tmp_path, monkeypatch):
    folder = tmp_path / "characters" / "testy"
    folder.mkdir(parents=True)
    pose_sheet().save(folder / "poses.png")
    (folder / "character.json").write_text(json.dumps({"name": "Testy", "description": "x", "height": 80}))
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.main(["testy"]) == 0
    assert _standing_height(folder / "out" / "gifs" / "idle.gif") == pytest.approx(80, abs=2)


def test_without_a_height_a_character_is_built_as_large_as_fits(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "characters" / "wide"
    folder.mkdir(parents=True)
    img = Image.new("RGB", (1024, 1024), (255, 0, 255))
    d = ImageDraw.Draw(img)
    for i in range(16):  # squat, wide figures, like Rocky: cut off at the recipe's height
        x0, y0 = (i % 4) * 256 + 18, (i // 4) * 256 + 90
        d.rectangle([x0, y0, x0 + 150, y0 + 110], fill=(150, 120, 90), outline=(40, 30, 20), width=3)
    img.save(folder / "poses.png")
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.main(["wide"]) == 0
    assert "built at height" in capsys.readouterr().err
    assert _standing_height(folder / "out" / "gifs" / "idle.gif") < load_recipe()["height"]


# --- a new character from a description ----------------------------------------------------------------------------


def _prompt_kit(tmp_path, monkeypatch):
    (tmp_path / "characters" / "testy").mkdir(parents=True)
    bible = {"name": "Testy", "description": "a small test cube", "style": "pixel-art", "rules": ["always blue"]}
    (tmp_path / "characters" / "testy" / "character.json").write_text(json.dumps(bible))
    for name in ("prompt.md", "intro-reference.md", "intro-new.md"):
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
    pose_sheet().save(folder / "poses.png")
    (folder / "character.json").write_text(json.dumps({"name": "Testy", "description": "x"}))
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.main(["testy"]) == 0
    reference = Image.open(folder / "reference.png")
    assert reference.size == (384 * len(kit.REFERENCE_POSES), 384)
    before = (folder / "reference.png").read_bytes()
    assert kit.main(["testy"]) == 0
    assert (folder / "reference.png").read_bytes() == before  # an existing reference is never replaced


# --- ChatGPT pet sheets ----------------------------------------------------------------------------------------------


def test_a_pet_sheet_becomes_a_zip_named_after_the_pet(tmp_path):
    path = tmp_path / "pet.png"
    pet_sheet().save(path)
    zip_path, warnings, height = pets.write(path, tmp_path / "out", "null-signal")
    assert zip_path.name == "Null Signal.zip" and warnings == [] and height <= load_recipe()["height"]
    with zipfile.ZipFile(zip_path) as zf:
        assert {"idle.gif", "running.gif", "look-loop.gif", "peek-left.gif"} <= set(zf.namelist())


def test_a_sheet_that_isnt_a_pet_sheet_is_refused(tmp_path, capsys):
    odd = tmp_path / "odd.png"
    Image.new("RGBA", (800, 300), (0, 0, 0, 0)).save(odd)
    assert pets.main([str(odd), "odd", "--out", str(tmp_path / "out")]) == 1
    assert "isn't a ChatGPT pet sheet" in capsys.readouterr().err


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


def test_the_layout_guides_lines_vanish_when_the_sheet_is_keyed(tmp_path):
    guide = tmp_path / "guide.png"
    prompts.layout_guide((0, 255, 0), guide)
    assert (key_background(Image.open(guide))[..., 3] == 0).all()  # copied guide lines would be keyed away


def test_the_prompt_names_its_background_and_asks_for_the_guide(tmp_path, monkeypatch):
    _prompt_kit(tmp_path, monkeypatch)
    text = prompts.make_prompt("testy", new=True)
    assert "exactly #FF00FF (magenta)" in text and "layout guide" in text
    assert (tmp_path / "characters" / "testy" / "layout-guide.png").exists()


def test_the_zip_is_named_after_the_character_so_uploading_it_names_the_pack(tmp_path, monkeypatch):
    folder = tmp_path / "characters" / "testy"
    folder.mkdir(parents=True)
    pose_sheet().save(folder / "poses.png")
    (folder / "character.json").write_text(json.dumps({"name": "Testy: The Cube?", "description": "x"}))
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.main(["testy"]) == 0
    assert [p.name for p in (folder / "out").glob("*.zip")] == ["Testy The Cube.zip"]  # Windows-safe
    assert pets.display_name("null-signal") == "Null Signal"


def test_the_newest_download_named_like_the_character_becomes_its_sheet(tmp_path, monkeypatch):
    import os
    import time

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    folder = tmp_path / "characters" / "testy"
    folder.mkdir(parents=True)
    (folder / "character.json").write_text(json.dumps({"name": "Testy Bot", "description": "x"}))
    (folder / "layout-guide.png").write_bytes(b"made by make_prompt")
    started = time.time()
    os.utime(folder / "layout-guide.png", (started - 60, started - 60))
    old = downloads / "Testy Bot old.png"
    pose_sheet().save(old)
    os.utime(old, (started - 3600, started - 3600))  # before the prompt: never taken
    tall = downloads / "testy-bot-spritesheet.png"
    Image.new("RGB", (300, 600), (255, 0, 255)).save(tall)  # not a square pose sheet
    zipped = downloads / "Testy Bot’s 16-pose grid.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        buf = io.BytesIO()
        pose_sheet().save(buf, "PNG")
        zf.writestr("grid/poses.png", buf.getvalue())
    monkeypatch.setenv("CHARACTER_KIT_DOWNLOADS", str(downloads))
    monkeypatch.setattr(kit, "KIT", tmp_path)
    assert kit.find_download(["Testy Bot", "testy"], started - 60, [downloads]) == zipped
    assert kit.main(["testy"]) == 0
    assert Image.open(folder / "poses.png").size == (1024, 1024) and (folder / "out" / "Testy Bot.zip").exists()
    assert kit.find_download(["Testy Bot"], (folder / "poses.png").stat().st_mtime, [downloads]) is None  # nothing newer
