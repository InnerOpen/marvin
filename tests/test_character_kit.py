"""src/dev/character_kit/make_prompt.py: the pose-sheet prompt is filled from the recipe and a character's bible, and the
background colour and layout guide keep clear of the character. (Building the pack from the returned sheet is Marvin's own,
services/ai/character_sheets.py, tested in tests/test_character_sheets.py.) Dev tooling, not shipped."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from marvin.services.ai.character_sheets import key_background, load_recipe

KIT = Path(__file__).resolve().parents[1] / "src" / "dev" / "character_kit"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"character_kit_{name}", KIT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prompts = _load("make_prompt")


def test_the_prompt_lists_every_pose_in_sheet_order_and_the_bible(tmp_path, monkeypatch):
    _prompt_kit(tmp_path, monkeypatch)
    text = prompts.make_prompt("testy")
    poses = load_recipe()["poses"]
    assert '"Testy": a small test cube' in text and "Always: always blue." in text
    positions = [text.index(f"{i + 1} {p['prompt']}") for i, p in enumerate(poses)]
    assert positions == sorted(positions)
    assert "#FF00FF" in text and "{" not in text  # every placeholder filled


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


# --- ChatGPT pet sheets ----------------------------------------------------------------------------------------------


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
