"""Turn a ChatGPT pet sprite sheet into a Marvin bubble-character pack.

    uv run src/dev/character_kit/pet_to_pack.py ~/Downloads/rocky-spritesheet-v5.webp rocky-pet
    uv run src/dev/character_kit/pet_to_pack.py sheet.webp hoots --out /tmp/hoots --height 100

ChatGPT's pets (its built-ins, and ones its Create Pet skill makes — reference/chatgpt-create-pet-skill.md) share one
sheet layout: 8 columns of 192×208 cells; rows 0-8 are idle, running-right, running-left, waving, jumping, failed,
waiting, running (the active-work row), review, each using its first N cells; a v2 sheet adds rows 9-10, sixteen
look directions clockwise from up (000, 022.5 … 337.5). Its animation is hand-made, so every frame is kept as drawn:
one scale and one offset for the whole sheet (idle's first frame stands on the ground line), so jumps leave the
ground and runs bob exactly as on the sheet. Marvin's extras come from the kit: look-loop from the look rows (v2),
and the four edge peeks from the kit's drawn ledges. Writes GIFs named for the uploader, a zip and a preview.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from character_from_poses import (  # noqa: E402 - the kit's own module, beside this one
    KIT,
    SOLID,
    Builder,
    SheetError,
    clipped_edges,
    key_background,
    load_recipe,
    place,
    preview,
    save_gif,
)

COLUMNS = 8
CELL_ASPECT = 208 / 192  # height / width
STATES = ("idle", "running-right", "running-left", "waving", "jumping", "failed", "waiting", "running", "review")
LOOK_ROWS = (9, 10)  # v2: 000…157.5, then 180…337.5
LOOK_LEFT, LOOK_RIGHT = (10, 4), (9, 4)  # 270 screen-left, 090 screen-right (row, column)
MIN_PIXELS = 200  # a cell with fewer drawn pixels is empty


def read_sheet(path: Path) -> np.ndarray:
    """RGBA; a sheet without real transparency is keyed by its border colour like a pose sheet."""
    img = Image.open(path)
    rgba = np.array(img.convert("RGBA"))
    return rgba if (rgba[..., 3] < 255).mean() > 0.2 else key_background(img)


def cells(rgba: np.ndarray) -> list[list[np.ndarray]]:
    """The sheet as rows of its drawn cells (empty trailing cells dropped), each cell full size."""
    height, width = rgba.shape[:2]
    cw = width / COLUMNS
    rows = round(height / (cw * CELL_ASPECT))
    if rows not in (len(STATES), len(STATES) + len(LOOK_ROWS)):
        raise SheetError(f"{width}×{height} isn't a ChatGPT pet sheet: 8 columns of 192×208-shaped cells, 9 or 11 rows")
    ch = height / rows
    out = []
    for r in range(rows):
        row = []
        for c in range(COLUMNS):
            cell = rgba[round(r * ch) : round((r + 1) * ch), round(c * cw) : round((c + 1) * cw)]
            if (cell[..., 3] > SOLID).sum() >= MIN_PIXELS:
                row.append(cell)
        out.append(row)
    return out


def _bbox(cell: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(cell[..., 3] > 0)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _feet_centre(cell: np.ndarray) -> float:
    x0, y0, x1, y1 = _bbox(cell)
    feet = cell[y1 - max(1, (y1 - y0) // 8) : y1 + 1, :, 3] > SOLID
    xs = np.nonzero(feet.any(axis=0))[0]
    return (xs.min() + xs.max()) / 2 if len(xs) else (x0 + x1) / 2


class PetPack:
    def __init__(self, rgba: np.ndarray, recipe: dict):
        self.recipe = recipe
        self.rows = cells(rgba)
        if not self.rows[0]:
            raise SheetError("the idle row is empty")
        size, ground = recipe["frame"], recipe["ground"]
        idle = self.rows[0][0]
        _, y0, _, y1 = _bbox(idle)
        self.scale = recipe["height"] / (y1 - y0 + 1)
        # One placement for every cell of the sheet: idle's first frame, measured AFTER scaling (rounding moves it),
        # with its feet centred on the ground line.
        scaled = np.array(self._scaled(idle))
        self.dx = round(size / 2 - _feet_centre(scaled))
        self.dy = ground - 1 - _bbox(scaled)[3]

    def _scaled(self, cell: np.ndarray) -> Image.Image:
        im = Image.fromarray(cell)
        return im.resize((round(im.width * self.scale), round(im.height * self.scale)), Image.LANCZOS)

    def frame(self, cell: np.ndarray) -> Image.Image:
        canvas = Image.new("RGBA", (self.recipe["frame"], self.recipe["frame"]), (0, 0, 0, 0))
        place(canvas, self._scaled(cell), self.dx, self.dy)
        return canvas

    def cell(self, row: int, column: int) -> np.ndarray | None:
        cells_ = self.rows[row] if row < len(self.rows) else []
        return cells_[column] if column < len(cells_) else None

    def build(self) -> dict[str, tuple[list[Image.Image], int | list[int]]]:
        ms = self.recipe["frame_ms"]
        pack: dict[str, tuple[list[Image.Image], int | list[int]]] = {}
        for state, row in zip(STATES, self.rows, strict=False):
            if row:
                pack[state] = ([self.frame(c) for c in row], ms)
        idle = self.rows[0][0]
        left, right = self.cell(*LOOK_LEFT), self.cell(*LOOK_RIGHT)
        if left is not None and right is not None:  # v2: look around — left, back, right, back
            look = [idle, left, left, left, idle, right, right, right]
            pack["look-loop"] = ([self.frame(c) for c in look], ms)
        # Peeks: the kit's ledges and lean, with this pet's own drawings as its poses.
        crop = lambda c: c[_bbox(c)[1] : _bbox(c)[3] + 1, _bbox(c)[0] : _bbox(c)[2] + 1]  # noqa: E731
        tiles = {"neutral": crop(idle), "happy": crop(idle)}
        tiles["glance-right"] = crop(right) if right is not None else crop(idle)
        tiles["glance-left"] = crop(left) if left is not None else crop(idle)
        builder = Builder(None, self.recipe, tiles=tiles)
        for name, spec in self.recipe["animations"].items():
            if isinstance(spec, dict) and "peek" in spec:
                pack[name] = builder.animation(spec)
        return pack

    def clip_warnings(self, pack: dict) -> list[str]:
        out = []
        for name, (frames, _) in pack.items():
            ledge = name.removeprefix("peek-") if name.startswith("peek-") else None
            hits: dict[str, list[int]] = {}
            for i, f in enumerate(frames):
                for edge in clipped_edges(f, ledge, self.recipe["ledge"]["width"]):
                    hits.setdefault(edge, []).append(i + 1)
            out += [f"{name}: cut off at the {edge} edge in frames {', '.join(map(str, at))}" for edge, at in hits.items()]
        return out


MIN_HEIGHT, HEIGHT_STEP = 64, 4


def fit(rgba: np.ndarray, recipe: dict) -> tuple[PetPack, dict, list[str]]:
    """The largest height (from recipe.json's down) at which no frame is cut off — the frames are hand-drawn, so a
    smaller pet is the only fix. Below MIN_HEIGHT it stops and returns the warnings."""
    height = recipe["height"]
    while True:
        pet = PetPack(rgba, {**recipe, "height": height})
        pack = pet.build()
        warnings = pet.clip_warnings(pack)
        if not warnings or height - HEIGHT_STEP < MIN_HEIGHT:
            return pet, pack, warnings
        height -= HEIGHT_STEP


def write(sheet: Path, out: Path, slug: str, height: int | None = None) -> tuple[Path, list[str], int]:
    """Writes the pack; returns the zip, any clipping warnings left, and the height used."""
    recipe = load_recipe()
    rgba = read_sheet(sheet)
    if height:
        recipe["height"] = height
        pet = PetPack(rgba, recipe)
        pack = pet.build()
        warnings = pet.clip_warnings(pack)
    else:
        pet, pack, warnings = fit(rgba, recipe)
    gifs = out / "gifs"
    gifs.mkdir(parents=True, exist_ok=True)
    for name, (frames, timing) in pack.items():
        save_gif(frames, gifs / f"{name}.gif", timing)
    preview(pack, out / "preview.png")
    zip_path = out / f"{slug}-pack.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in pack:
            zf.write(gifs / f"{name}.gif", f"{name}.gif")
    return zip_path, warnings, pet.recipe["height"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sheet", type=Path, help="a ChatGPT pet sprite sheet (WebP or PNG)")
    parser.add_argument("slug", help="the pack's name")
    parser.add_argument("--out", type=Path, help="where to write (default characters/<slug>/out)")
    parser.add_argument("--height", type=int, help="standing height in px (default: the largest at which nothing is cut off)")
    args = parser.parse_args(argv)
    out = args.out or KIT / "characters" / args.slug / "out"
    try:
        zip_path, warnings, used = write(args.sheet, out, args.slug, args.height)
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
