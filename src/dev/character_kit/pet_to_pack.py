"""Turn a ChatGPT pet sprite sheet into a Marvin bubble-character pack.

    uv run src/dev/character_kit/pet_to_pack.py ~/Downloads/rocky-spritesheet-v5.webp rocky-pet
    uv run src/dev/character_kit/pet_to_pack.py sheet.webp hoots --out /tmp/hoots --height 100

ChatGPT's pets (its built-ins, and ones its Create Pet skill makes — reference/chatgpt-create-pet-skill.md) share one
sheet layout: 8 columns of 192×208 cells, 9 rows of animation and, on a v2 sheet, 2 of look directions. The building
is Marvin's own (services/ai/character_sheets.py: PetPack) — uploading the sheet itself in Marvin does the same — so
this is the command line: it writes GIFs named for the uploader, a zip and a preview.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from character_from_poses import KIT, write_out  # noqa: E402 - the kit's own module, beside this one

from marvin.services.ai.character_sheets import SheetError, build_pet, load_recipe, sheet_rgba  # noqa: E402


def display_name(slug: str) -> str:
    """'null-signal' → 'Null Signal': the pack's name when --name doesn't give one."""
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", slug) if w)


def write(sheet: Path, out: Path, slug: str, height: int | None = None, name: str | None = None) -> tuple[Path, list[str], int]:
    """Writes the pack — at `height`, or the largest at which no frame is cut off; the zip, any clipping warnings
    left, and the height used."""
    built = build_pet(sheet_rgba(Image.open(sheet)), load_recipe(), height)
    return write_out(built, out, name or display_name(slug)), built.warnings, built.height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sheet", type=Path, help="a ChatGPT pet sprite sheet (WebP or PNG)")
    parser.add_argument("slug", help="a short name for its folder, e.g. null-signal")
    parser.add_argument("--name", help="the character's name, which names the zip and so the pack (default: from slug, 'Null Signal')")
    parser.add_argument("--out", type=Path, help="where to write (default characters/<slug>/out)")
    parser.add_argument("--height", type=int, help="standing height in px (default: the largest at which nothing is cut off)")
    args = parser.parse_args(argv)
    out = args.out or KIT / "characters" / args.slug / "out"
    try:
        zip_path, warnings, used = write(args.sheet, out, args.slug, args.height, args.name)
    except SheetError as e:
        sys.stderr.write(f"{args.sheet}: {e}\n")
        return 1
    for message in warnings:
        sys.stderr.write(f"warning: {args.slug}: {message}\n")
    if warnings:
        sys.stderr.write("  → check preview.png; try a smaller --height\n")
    elif not args.height and used != load_recipe()["height"]:
        sys.stderr.write(f"built at height {used} (smaller than {load_recipe()['height']}) so no frame is cut off\n")
    sys.stdout.write(f"{zip_path}\n{out / 'preview.png'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
