"""Print the pose-sheet prompt for one character, ready to paste into an image model with its reference.png.

    uv run src/dev/character_kit/make_prompt.py seedy

The prompt is the same for every character (prompt.md) — only characters/<slug>/character.json fills it in — and its
16 poses come from recipe.json, in the order character_from_poses.py cuts them. Save the image the model returns as
characters/<slug>/poses.png.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).parent


def make_prompt(slug: str) -> str:
    character = json.loads((KIT / "characters" / slug / "character.json").read_text(encoding="utf-8"))
    poses = json.loads((KIT / "recipe.json").read_text(encoding="utf-8"))["poses"]
    rows = []
    for row in range(0, len(poses), 4):
        cells = [f"{i + 1} {poses[i]['prompt']}" for i in range(row, min(row + 4, len(poses)))]
        rows.append(f"Row {row // 4 + 1}: " + " · ".join(cells))
    return (
        (KIT / "prompt.md")
        .read_text(encoding="utf-8")
        .format(
            name=character["name"],
            description=character["description"],
            style=character.get("style", "pixel-art"),
            rules="; ".join(character.get("rules") or []) or "keep the design exactly as shown",
            rows="\n".join(rows),
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("usage: make_prompt.py <character slug>\n")
        return 2
    slug = args[0]
    if not (KIT / "characters" / slug / "character.json").exists():
        sys.stderr.write(f"no characters/{slug}/character.json\n")
        return 1
    sys.stdout.write(make_prompt(slug) + "\n")
    reference = KIT / "characters" / slug / "reference.png"
    sys.stderr.write(f"\nAttach: {reference}\nSave the result as: {KIT / 'characters' / slug / 'poses.png'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
