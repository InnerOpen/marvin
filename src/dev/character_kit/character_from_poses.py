"""Build a bubble-character pack from ONE pose sheet — no AI past the image itself.

    uv run src/dev/character_kit/character_from_poses.py seedy
    uv run src/dev/character_kit/character_from_poses.py --sheet some/poses.png --out /tmp/pack

The sheet is the image make_prompt.py asks for: 16 still poses (4 rows of 4, in the recipe's order) on one flat colour.
The building is Marvin's own (services/ai/character_sheets.py, the recipe beside it) — uploading the sheet itself in
Marvin does the same — so this is the command line: the character's folder, its reference.png, the Downloads pickup,
and the files. Writes one GIF per animation (named so Marvin's uploader fills each slot), `<name>.zip` and
`preview.png`, at the largest height at which nothing is cut off unless the character's own `height` says otherwise.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from marvin.services.ai.character_sheets import BuiltSheet, SheetError, build_poses, gif_bytes, key_background, load_recipe

KIT = Path(__file__).parent


# --- writing ------------------------------------------------------------------------------------------------------
def preview(pack: dict, path: Path, cell: int = 112) -> None:
    """Every animation as a row, on dark grey: what to look at before uploading."""
    width = max(len(frames) for frames, _ in pack.values())
    sheet = Image.new("RGB", (width * cell, len(pack) * cell), (34, 34, 34))
    for row, (frames, _) in enumerate(pack.values()):
        for col, f in enumerate(frames):
            tile = Image.new("RGBA", f.size, (34, 34, 34, 255))
            tile.alpha_composite(f)
            sheet.paste(tile.resize((cell, cell), Image.NEAREST).convert("RGB"), (col * cell, row * cell))
    sheet.save(path)


REFERENCE_POSES = ("neutral", "arm-high", "happy", "dizzy", "laptop", "run-a")


def reference_from(drawn: dict[str, np.ndarray], path: Path, tile: int = 384) -> None:
    """A reference.png from the sheet's own poses (front, wave, happy, dizzy, laptop, run) on white — so a character the
    model designed keeps that design when it's redrawn."""
    poses = [drawn[p] for p in REFERENCE_POSES if p in drawn]
    sheet = Image.new("RGB", (tile * len(poses), tile), (255, 255, 255))
    for i, drawn in enumerate(poses):
        im = Image.fromarray(drawn)
        k = tile * 0.9 / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        cell = Image.new("RGBA", (tile, tile), (255, 255, 255, 255))
        cell.alpha_composite(im, ((tile - im.width) // 2, tile - im.height - tile // 20))
        sheet.paste(cell.convert("RGB"), (i * tile, 0))
    sheet.save(path)


def zip_name(name: str) -> str:
    """The pack's zip file name: the character's display name, which Marvin's uploader takes as the pack's name when
    none is typed — so uploading the zip names the character too. Only characters Windows forbids in a file name go."""
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "character"


def write_out(built: BuiltSheet, out: Path, name: str) -> Path:
    """The pack's GIFs, preview.png and zip under `out`; the zip."""
    gifs = out / "gifs"
    gifs.mkdir(parents=True, exist_ok=True)
    for animation, (frames, timing) in built.animations.items():
        (gifs / f"{animation}.gif").write_bytes(gif_bytes(frames, timing))
    preview(built.animations, out / "preview.png")
    zip_path = out / f"{zip_name(name)}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for animation in built.animations:
            zf.write(gifs / f"{animation}.gif", f"{animation}.gif")
    return zip_path


def write_pack(
    sheet_path: Path, out: Path, slug: str, height: int | None = None, reference: Path | None = None, name: str | None = None
) -> tuple[Path, BuiltSheet]:
    """Build and write the pack — at `height`, or the largest that fits; the zip, and what was built (its warnings)."""
    built = build_poses(key_background(read_sheet_file(sheet_path)), load_recipe(), height)
    if reference is not None and not reference.exists():
        reference_from(built.drawn, reference)  # a new character: its first sheet is its look from now on
    return write_out(built, out, name or slug), built


# --- picking the sheet up from Downloads -------------------------------------------------------------------------------
SHEET_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def downloads_dirs() -> list[Path]:
    """Where a browser saves the model's image: $CHARACTER_KIT_DOWNLOADS, ~/Downloads, and (in WSL) Windows' Downloads."""
    dirs = [Path(os.environ["CHARACTER_KIT_DOWNLOADS"])] if os.environ.get("CHARACTER_KIT_DOWNLOADS") else []
    dirs += [Path.home() / "Downloads", *sorted(Path("/mnt/c/Users").glob("*/Downloads"))]
    return [d for d in dirs if d.is_dir()]


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def read_sheet_file(path: Path) -> Image.Image:
    """An image, or the largest image inside a zip (in case the model hands the sheet over zipped)."""
    if path.suffix.lower() != ".zip":
        return Image.open(path)
    with zipfile.ZipFile(path) as zf:
        images = [i for i in zf.infolist() if Path(i.filename).suffix.lower() in SHEET_SUFFIXES and not i.filename.startswith("__MACOSX")]
        if not images:
            raise SheetError(f"{path.name} holds no image")
        biggest = max(images, key=lambda i: i.file_size)
        return Image.open(io.BytesIO(zf.read(biggest)))


def find_download(names: list[str], newer_than: float = 0.0, dirs: list[Path] | None = None) -> Path | None:
    """The newest image or zip in Downloads named like the character ("Mossy’s 16-pose magenta character grid.png" for
    Mossy), newer than `newer_than` — skipping anything that isn't a square-ish pose sheet (a ChatGPT pet's tall sprite
    sheet, an atlas) so a same-named file of another kind is never picked up."""
    wanted = [w for w in (_words(n) for n in names) if w]
    best: tuple[float, Path] | None = None
    for folder in dirs if dirs is not None else downloads_dirs():
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in SHEET_SUFFIXES | {".zip"}:
                continue
            mtime = path.stat().st_mtime
            if mtime <= newer_than or (best and mtime <= best[0]) or not any(w in _words(path.stem) for w in wanted):
                continue
            try:
                width, height = read_sheet_file(path).size
            except Exception:  # noqa: BLE001 - not an image we can read: not a sheet
                continue
            if 0.8 <= width / height <= 1.25:
                best = (mtime, path)
    return best[1] if best else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slug", nargs="?", help="a folder under characters/ holding poses.png")
    parser.add_argument("--sheet", type=Path, help="a pose sheet anywhere (instead of characters/<slug>/poses.png)")
    parser.add_argument("--out", type=Path, help="where to write (default characters/<slug>/out)")
    parser.add_argument(
        "--height", type=int, help="standing height in px (default: the character's own, else the largest at which nothing is cut off)"
    )
    args = parser.parse_args(argv)
    if not args.slug and not args.sheet:
        parser.error("give a character slug or --sheet")
    slug = args.slug or args.sheet.stem
    bible_path = KIT / "characters" / slug / "character.json"
    bible = json.loads(bible_path.read_text(encoding="utf-8")) if bible_path.exists() else {}
    sheet = args.sheet or KIT / "characters" / slug / "poses.png"
    if not args.sheet:  # a newer sheet in Downloads, named like the character, replaces poses.png (the old one is kept)
        # Only what arrived after the prompt was made (make_prompt.py writes the layout guide) or the last sheet: an
        # old download that happens to share the name ("marvin-gifs.zip", a screenshot) is never taken.
        guide = KIT / "characters" / slug / "layout-guide.png"
        since = max((p.stat().st_mtime for p in (sheet, guide) if p.exists()), default=time.time())
        download = find_download([bible.get("name", ""), slug], since)
        if download is not None:
            if sheet.exists():
                sheet.rename(sheet.with_name(f"poses-{time.strftime('%Y%m%d-%H%M%S', time.localtime(sheet.stat().st_mtime))}.png"))
            read_sheet_file(download).save(sheet)
            sys.stderr.write(f"using {download.name} from Downloads as {sheet}\n")
    if not sheet.exists():
        parser.error(f"no pose sheet at {sheet}, nor one named like {slug} in Downloads — generate one with make_prompt.py {slug}")
    out = args.out or KIT / "characters" / slug / "out"
    height = args.height or bible.get("height")  # a character's own, when it has one; else the largest that fits
    reference = KIT / "characters" / slug / "reference.png" if not args.sheet else None
    had_reference = reference is not None and reference.exists()
    try:
        zip_path, built = write_pack(sheet, out, slug, height, reference=reference, name=bible.get("name"))
    except SheetError as e:
        sys.stderr.write(f"{sheet}: {e}\n")
        return 1
    if reference is not None and not had_reference:
        sys.stderr.write(f"saved {reference} from this sheet: redraws of {slug} will keep this look\n")
    for message in built.warnings:
        sys.stderr.write(f"warning: {slug}: {message}\n")
    if built.warnings:
        sys.stderr.write(f'  → check preview.png; to build {slug} smaller, set a smaller "height" in its character.json\n')
    elif not height and built.height != load_recipe()["height"]:
        sys.stderr.write(f"built at height {built.height} (smaller than {load_recipe()['height']}) so no frame is cut off\n")
    sys.stdout.write(f"{zip_path}\n{out / 'preview.png'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
