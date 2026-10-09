"""Print the pose-sheet prompt for one character, and write the layout guide to attach with it.

    uv run src/dev/character_kit/make_prompt.py seedy          # redraw Seedy: attach its reference.png + the guide
    uv run src/dev/character_kit/make_prompt.py bottle --new   # design a new one from character.json alone

The prompt is the same for every character (prompt.md) — only characters/<slug>/character.json fills it in — and its
16 poses come from Marvin's character recipe (services/ai/character_recipe.json), in the order they are cut. The background is a flat colour
picked to be far from the character's own (magenta unless the character is pink or purple…), or character.json's
"background". Save the image the model returns as characters/<slug>/poses.png.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from marvin.services.ai.character_sheets import load_recipe

KIT = Path(__file__).parent

# Flat backgrounds the sheet can be drawn on, in order of preference. The builder keys whichever it finds.
BACKGROUNDS = {
    "magenta": (255, 0, 255),
    "green": (0, 255, 0),
    "cyan": (0, 255, 255),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
}
# Words in a description that rule a background out (a green character on green can't be cut out).
COLOUR_WORDS = {
    "magenta": r"magenta|pink|purple|violet|lilac|lavender|fuchsia",
    "green": r"green|moss|leaf|leaves|lime|sprout|grass",
    "cyan": r"cyan|teal|aqua|turquoise",
    "blue": r"blue|navy",
    "yellow": r"yellow|gold|golden|amber|lemon",
}
GUIDE_SIZE = 1024
GUIDE_SHADE = 0.85  # guide lines at 85% of the background colour: close enough that the builder keys them away


def choose_background(character: dict, reference: Path | None) -> tuple[str, tuple[int, int, int]]:
    """character.json's "background", else the flat colour farthest from the reference's colours (its nearest 2% of
    pixels), else the first one the description's colour words don't rule out."""
    chosen = character.get("background")
    if chosen:
        if chosen in BACKGROUNDS:
            return chosen, BACKGROUNDS[chosen]
        hex_ = chosen.lstrip("#")
        return f"#{hex_.upper()}", tuple(int(hex_[i : i + 2], 16) for i in (0, 2, 4))
    if reference is not None and reference.exists():
        rgb = np.array(Image.open(reference).convert("RGB")).reshape(-1, 3).astype(int)
        drawn = rgb[~((rgb.min(axis=1) > 230) & (rgb.max(axis=1) - rgb.min(axis=1) < 20))]  # not the white page
        if len(drawn):
            sample = drawn[:: max(1, len(drawn) // 20000)]

            def clearance(colour):
                return float(np.percentile(np.sqrt(((sample - colour) ** 2).sum(axis=1)), 2))

            name = max(BACKGROUNDS, key=lambda n: clearance(np.array(BACKGROUNDS[n])))
            return name, BACKGROUNDS[name]
    text = " ".join([character.get("description", ""), *character.get("rules", [])]).lower()
    for name, colour in BACKGROUNDS.items():
        if not re.search(rf"\b({COLOUR_WORDS[name]})\b", text):
            return name, colour
    return "magenta", BACKGROUNDS["magenta"]


def layout_guide(colour: tuple[int, int, int], path: Path, size: int = GUIDE_SIZE) -> None:
    """A 4×4 grid on the background colour: each cell's border, a box for the pose and its ground line, drawn in a
    shade of the background so close that, if the model copies them, the builder keys them away with it."""
    img = Image.new("RGB", (size, size), colour)
    d = ImageDraw.Draw(img)
    shade = tuple(int(c * GUIDE_SHADE) for c in colour)
    cell = size // 4
    for row in range(4):
        for col in range(4):
            x0, y0 = col * cell, row * cell
            d.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], outline=shade, width=2)
            ground = y0 + int(cell * 0.9)
            d.line([x0 + int(cell * 0.08), ground, x0 + int(cell * 0.92), ground], fill=shade, width=3)
            d.rectangle([x0 + int(cell * 0.16), y0 + int(cell * 0.1), x0 + int(cell * 0.84), ground], outline=shade, width=1)
    img.save(path)


def make_prompt(slug: str, new: bool = False) -> str:
    """The pose-sheet prompt. `new`: the model designs the character from its description (no reference image);
    otherwise it redraws the one in characters/<slug>/reference.png."""
    folder = KIT / "characters" / slug
    character = json.loads((folder / "character.json").read_text(encoding="utf-8"))
    poses = load_recipe()["poses"]
    rows = []
    for row in range(0, len(poses), 4):
        cells = [f"{i + 1} {poses[i]['prompt']}" for i in range(row, min(row + 4, len(poses)))]
        rows.append(f"Row {row // 4 + 1}: " + " · ".join(cells))
    background_name, colour = choose_background(character, None if new else folder / "reference.png")
    fields = {
        "name": character["name"],
        "description": character["description"],
        "style": character.get("style", "pixel-art"),
        "rules": "; ".join(character.get("rules") or []) or "keep the design the same in every pose",
        "rows": "\n".join(rows),
        "background_name": background_name,
        "background_hex": "#{:02X}{:02X}{:02X}".format(*colour),
    }
    intro = (KIT / ("intro-new.md" if new else "intro-reference.md")).read_text(encoding="utf-8").format(**fields).rstrip()
    layout_guide(colour, folder / "layout-guide.png")
    return (KIT / "prompt.md").read_text(encoding="utf-8").format(intro=intro, **fields)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    new = "--new" in args
    args = [a for a in args if a != "--new"]
    if len(args) != 1:
        sys.stderr.write("usage: make_prompt.py <character slug> [--new]\n")
        return 2
    slug = args[0]
    folder = KIT / "characters" / slug
    if not (folder / "character.json").exists():
        sys.stderr.write(f"no characters/{slug}/character.json\n")
        return 1
    reference = folder / "reference.png"
    if not new and not reference.exists():
        sys.stderr.write(f"no {reference} — add one, or use --new to have the model design {slug} from its description\n")
        return 1
    sys.stdout.write(make_prompt(slug, new) + "\n")
    attach = [folder / "layout-guide.png"] if new else [reference, folder / "layout-guide.png"]
    sys.stderr.write("\nAttach: " + "  +  ".join(str(a) for a in attach) + f"\nSave the result as: {folder / 'poses.png'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
