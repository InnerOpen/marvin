"""Build a bubble-character pack from ONE pose sheet — no AI past the image itself.

    uv run src/dev/character_kit/character_from_poses.py seedy
    uv run src/dev/character_kit/character_from_poses.py --sheet some/poses.png --out /tmp/pack

The sheet is the image make_prompt.py asks for: 16 still poses (4 rows of 4, in recipe.json's order) on flat
magenta (#FF00FF). Every pose is cut at ONE scale (the first pose is `height` px tall) with its feet on the same
ground line, so the character is the same size and colour in every animation; the motion — bobs, blinks, jumps,
wobbles, runs, peeks — is recipe.json, and the peek ledges are drawn here so they never move. Writes one GIF per
animation (named so Marvin's uploader fills each slot), `<slug>-pack.zip` and `preview.png`.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

KIT = Path(__file__).parent
SOLID = 128  # GIF has no partial alpha: at or above shows, below is transparent


class SheetError(ValueError):
    """The sheet can't be read as the recipe's poses (wrong count, no magenta…)."""


def load_recipe(path: Path = KIT / "recipe.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- cutting the poses -----------------------------------------------------------------------------------------
BACKGROUND_NEAR = 60  # this close to the sheet's background colour: background, wherever it is (gaps between limbs too)
BACKGROUND_EDGE = 150  # this close, and right beside background: the soft blend around an outline


def key_background(img: Image.Image) -> np.ndarray:
    """RGBA with the sheet's flat background made transparent — whichever colour make_prompt.py chose (magenta,
    green, cyan…). Judged by distance from the background's ACTUAL colour, sampled from the border: a crimson cap or a
    purple body stays, while the blended pixels around each outline, which touch the background, go too."""
    rgb = np.array(img.convert("RGB")).astype(int)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    colour = np.median(border, axis=0)
    saturated = colour.max() - colour.min() > 150
    flat = float(np.median(np.sqrt(((border - colour) ** 2).sum(axis=1)))) < 30
    if not (saturated and flat):
        raise SheetError(
            f"no flat background colour found (its border is {tuple(int(v) for v in colour)}) — the sheet must be on the one "
            "flat colour the prompt names (#FF00FF magenta unless it chose another)"
        )
    distance = np.sqrt(((rgb - colour) ** 2).sum(axis=2))
    near = distance < BACKGROUND_NEAR
    beside = np.array(Image.fromarray((near * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    background = near | (beside & (distance < BACKGROUND_EDGE))
    if background.mean() < 0.2:
        raise SheetError("too little background — the sheet must be on one flat colour with space around every pose")
    alpha = Image.fromarray(np.where(background, 0, 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))
    return np.dstack([rgb.astype(np.uint8), np.array(alpha)])


def _runs(mask: np.ndarray, gap: int) -> list[list[int]]:
    """[start, end] of each run of True, joining runs closer than `gap` (a raised arm, a laptop)."""
    runs: list[list[int]] = []
    start = None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        if not on and start is not None:
            runs.append([start, i - 1])
            start = None
    if start is not None:
        runs.append([start, len(mask) - 1])
    merged: list[list[int]] = []
    for a0, a1 in runs:
        if merged and a0 - merged[-1][1] < gap:
            merged[-1][1] = a1
        else:
            merged.append([a0, a1])
    return [m for m in merged if m[1] - m[0] > gap]


def _split(occupied: np.ndarray, parts: int) -> list[tuple[int, int]] | None:
    """`parts` spans of `occupied`, cut at its parts-1 WIDEST empty gaps — the gaps between poses. A pose's own gaps
    (a raised arm, separate feet, a sparkle) are narrower, so they never split it. None: not enough gaps."""
    on = np.nonzero(occupied)[0]
    if not len(on):
        return None
    gaps = [(b - a - 1, a, b) for a, b in zip(on[:-1], on[1:], strict=True) if b - a > 1]  # (width, last on, next on)
    if len(gaps) < parts - 1:
        return None
    cuts = sorted(gaps, reverse=True)[: parts - 1]
    edges = sorted((a, b) for _, a, b in cuts)
    starts = [int(on[0])] + [b for _, b in edges]
    ends = [a for a, _ in edges] + [int(on[-1])]
    return list(zip(starts, ends, strict=True))


def cut_poses(rgba: np.ndarray, count: int, per_row: int = 4) -> list[np.ndarray]:
    """The sheet's drawings, row by row, left to right, each cropped to itself. The sheet is a grid of `per_row`
    columns, so it is split at its widest gaps rather than every gap: big poses close together stay apart, and a
    pose's detached pieces stay with it."""
    alpha = rgba[..., 3] > 0
    poses = []
    rows = _split(alpha.sum(axis=1) > 2, count // per_row)
    for y0, y1 in rows or []:
        band = alpha[y0 : y1 + 1]
        for x0, x1 in _split(band.sum(axis=0) > 2, per_row) or []:
            tile = rgba[y0 : y1 + 1, x0 : x1 + 1]
            ys = np.nonzero(tile[..., 3].any(axis=1))[0]
            poses.append(tile[ys.min() : ys.max() + 1])
    if len(poses) != count:
        gap = max(8, rgba.shape[1] // 100)
        found = sum(len(_runs(alpha[y0 : y1 + 1].sum(axis=0) > 2, gap)) for y0, y1 in _runs(alpha.sum(axis=1) > 2, gap))
        raise SheetError(
            f"found {found} drawings, the recipe has {count} poses — check the sheet is a clean {per_row}-wide grid with "
            "magenta between every pose (no text, no touching poses)"
        )
    return poses


# --- composing frames -------------------------------------------------------------------------------------------
def place(canvas: Image.Image, im: Image.Image, x: int, y: int) -> None:
    """Composite `im` onto `canvas` at (x, y), cropping whatever falls outside. (`paste` with a mask would square the
    alpha of soft edge pixels and thin the outline.)"""
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(im.width, canvas.width - x), min(im.height, canvas.height - y)
    if x1 > x0 and y1 > y0:
        canvas.alpha_composite(im.crop((x0, y0, x1, y1)), (x + x0, y + y0))


def clipped_edges(frame: Image.Image, ledge: str | None = None, ledge_width: int = 0) -> list[str]:
    """The frame edges the drawing touches — cut off there. A peek's own edge (and its ledge's strip along the others)
    doesn't count: hiding behind it is the point."""
    a = np.array(frame)[..., 3] > SOLID
    n, w = a.shape[0], ledge_width
    keep = np.ones(n, dtype=bool)  # positions along a border that aren't ledge
    rows = {"top": a[0, :], "bottom": a[-1, :]}
    cols = {"left": a[:, 0], "right": a[:, -1]}
    touched = []
    for name, line in {**rows, **cols}.items():
        if name == ledge:
            continue
        mask = keep.copy()
        if ledge == "left" and name in rows:
            mask[:w] = False
        elif ledge == "right" and name in rows:
            mask[n - w :] = False
        elif ledge == "top" and name in cols:
            mask[:w] = False
        elif ledge == "bottom" and name in cols:
            mask[n - w :] = False
        if (line & mask).any():
            touched.append(name)
    return touched


class Builder:
    def __init__(self, sheet: Image.Image | None, recipe: dict, tiles: dict[str, np.ndarray] | None = None):
        """From a pose sheet, or from `tiles` already cut ({pose id: RGBA drawing}, the first one standing)."""
        self.recipe = recipe
        self.frame_size, self.ground = recipe["frame"], recipe["ground"]
        if tiles is None:
            ids = [p["id"] for p in recipe["poses"]]
            tiles = dict(zip(ids, cut_poses(key_background(sheet), len(ids)), strict=True))
        self.drawn = tiles  # as drawn, full size: what a reference shows
        self.scale = recipe["height"] / next(iter(tiles.values())).shape[0]
        self.pose = {pid: self._sized(t) for pid, t in tiles.items()}

    def _sized(self, tile: np.ndarray) -> Image.Image:
        im = Image.fromarray(tile)
        return im.resize((max(1, round(im.width * self.scale)), max(1, round(im.height * self.scale))), Image.LANCZOS)

    @staticmethod
    def feet_x(im: Image.Image) -> float:
        """Centre of the feet (bottom 12% of the drawing): what stays planted."""
        a = np.array(im)[..., 3]
        xs = np.nonzero((a[int(a.shape[0] * 0.88) :] > SOLID).any(axis=0))[0]
        return (xs.min() + xs.max()) / 2 if len(xs) else im.width / 2

    def frame(self, pose: str, dy: int = 0, dx: int = 0, squash: float = 1.0, angle: float = 0.0, flip: bool = False) -> Image.Image:
        im = self.pose[pose]
        if flip:
            im = ImageOps.mirror(im)
        if squash != 1.0:
            im = im.resize((round(im.width / squash**0.5), round(im.height * squash)), Image.NEAREST)
        canvas = Image.new("RGBA", (self.frame_size, self.frame_size), (0, 0, 0, 0))
        # A lift (a jump) tops out where the frame does: higher would cut the head off, not jump higher.
        top = max(self.ground - im.height + dy, min(1, self.ground - im.height))
        place(canvas, im, round(self.frame_size / 2 - self.feet_x(im)) + dx, top)
        if angle:  # wobble about the feet
            canvas = canvas.rotate(angle, resample=Image.NEAREST, center=(self.frame_size / 2, self.ground))
            canvas = self._on_ground(canvas)
        return canvas

    def _on_ground(self, canvas: Image.Image) -> Image.Image:
        """Lift a tilted drawing until its lowest point is back on the ground line: tilting about the feet's centre
        swings the far corner below it — off the frame, for a wide character."""
        rows = np.nonzero((np.array(canvas)[..., 3] > 0).any(axis=1))[0]
        sink = int(rows.max()) - (self.ground - 1) if len(rows) else 0
        if sink <= 0:
            return canvas
        lifted = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        place(lifted, canvas, 0, -sink)
        return lifted

    def _ledge(self, a: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
        x0, y0, x1, y1 = box
        a[y0:y1, x0:x1, :3] = self.recipe["ledge"]["rgb"]
        a[y0:y1, x0:x1, 3] = 255
        return a

    def _leaned(self, pose: str, edge: str, angle: float) -> tuple[Image.Image, tuple[float, float]]:
        """The pose tilted `angle` degrees away from `edge` about its feet, on a canvas with room for it, and the feet."""
        body = self.pose[pose] if edge == "left" else ImageOps.mirror(self.pose[pose])
        pad = body.height
        big = Image.new("RGBA", (body.width + 2 * pad, body.height + 2 * pad), (0, 0, 0, 0))
        place(big, body, pad, pad)
        pivot = (pad + self.feet_x(body), pad + body.height)
        return big.rotate(-angle if edge == "left" else angle, resample=Image.BICUBIC, center=pivot), pivot

    def side_feet(self, spec: dict) -> float:
        """Where a side peek's feet stand (x, for the left edge): far enough behind the ledge that at the deepest lean
        `reveal` of the body's AREA clears it — whatever the shape (a tall sprout, a wide rock). Area, not the farthest
        pixel: a thin leaf or antenna sticking out mustn't push the face back behind the ledge."""
        big, pivot = self._leaned(spec["poses"][0], "left", max(spec["lean"]))
        mass = (np.array(big)[..., 3] > SOLID).sum(axis=0)  # opaque pixels per column
        from_right = np.cumsum(mass[::-1])[::-1]  # opaque pixels at or right of each column
        edge_col = int(np.argmax(from_right <= spec.get("reveal", 0.4) * mass.sum()))  # where the ledge must fall
        return self.recipe["ledge"]["width"] - (edge_col - pivot[0])

    def lean_peek(self, edge: str, pose: str, angle: float, feet_left: float) -> Image.Image:
        """Sideways: the body stays behind the ledge and leans out from its feet, so only the head clears the edge.
        `feet_left` is side_feet() — the same for every frame, so the feet never shift."""
        size, w = self.frame_size, self.recipe["ledge"]["width"]
        big, pivot = self._leaned(pose, edge, angle)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        feet_at = feet_left if edge == "left" else size - feet_left
        place(canvas, big, round(feet_at - pivot[0]), round(self.ground - pivot[1]))
        canvas = self._on_ground(canvas)
        a = np.array(canvas)
        if edge == "left":
            a[:, :w] = 0  # behind the screen edge
            return Image.fromarray(self._ledge(a, (0, 6, w, size - 1)))
        a[:, size - w :] = 0
        return Image.fromarray(self._ledge(a, (size - w, 6, size, size - 1)))

    def slide_peek(self, edge: str, pose: str, share: float) -> Image.Image:
        """Up or down: out from behind the ledge by `share` of its height (from the top it hangs head-down)."""
        size, w = self.frame_size, self.recipe["ledge"]["width"]
        body = self.pose[pose] if edge == "bottom" else ImageOps.flip(self.pose[pose])
        shown = round(body.height * share)
        y = size - w - shown if edge == "bottom" else w + shown - body.height
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        place(canvas, body, round(size / 2 - body.width / 2), y)
        a = np.array(canvas)
        if edge == "bottom":
            a[size - w :] = 0
            return Image.fromarray(self._ledge(a, (4, size - w, size - 4, size)))
        a[:w] = 0
        return Image.fromarray(self._ledge(a, (4, 0, size - 4, w)))

    def animation(self, spec) -> tuple[list[Image.Image], list[int] | int]:
        ms = self.recipe["frame_ms"]
        if isinstance(spec, list):
            return [self.frame(**f) for f in spec], ms
        if "peek" in spec:
            edge = spec["peek"]
            if edge in ("left", "right"):
                feet = self.side_feet(spec)
                frames = [self.lean_peek(edge, p, a, feet) for p, a in zip(spec["poses"], spec["lean"], strict=True)]
            else:
                frames = [self.slide_peek(edge, p, s) for p, s in zip(spec["poses"], spec["share"], strict=True)]
            return frames, spec.get("timing", ms)
        raise SheetError(f"unknown animation spec: {spec}")

    def clip_warnings(self, pack: dict) -> list[str]:
        """Each animation whose drawing runs off the frame somewhere, and in which frames — cut off when it plays."""
        warnings = []
        for name, (frames, _) in pack.items():
            spec = self.recipe["animations"][name]
            ledge = spec.get("peek") if isinstance(spec, dict) else None
            if isinstance(spec, dict) and "mirror" in spec:
                source = self.recipe["animations"][spec["mirror"]]
                ledge = {"left": "right", "right": "left"}.get(source.get("peek")) if isinstance(source, dict) else None
            hits: dict[str, list[int]] = {}
            for i, f in enumerate(frames):
                for edge in clipped_edges(f, ledge, self.recipe["ledge"]["width"]):
                    hits.setdefault(edge, []).append(i + 1)
            for edge, at in hits.items():
                warnings.append(f"{name}: cut off at the {edge} edge in frame{'s' if len(at) > 1 else ''} {', '.join(map(str, at))}")
        return warnings

    def build(self) -> dict[str, tuple[list[Image.Image], list[int] | int]]:
        out = {}
        for name, spec in self.recipe["animations"].items():
            if isinstance(spec, dict) and "mirror" in spec:
                continue
            out[name] = self.animation(spec)
        for name, spec in self.recipe["animations"].items():
            if isinstance(spec, dict) and "mirror" in spec:
                frames, timing = out[spec["mirror"]]
                out[name] = ([ImageOps.mirror(f) for f in frames], timing)
        return {name: out[name] for name in self.recipe["animations"]}  # the recipe's order


# --- writing ------------------------------------------------------------------------------------------------------
def save_gif(frames: list[Image.Image], path: Path, durations) -> None:
    imgs = []
    for f in frames:
        a = np.array(f)
        pal = Image.fromarray(a[..., :3]).quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        px = np.array(pal)
        px[a[..., 3] < SOLID] = 255
        p = Image.fromarray(px, "P")
        p.putpalette((pal.getpalette() + [0, 0, 0] * 256)[:768])
        imgs.append(p)
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=durations, loop=0, transparency=255, disposal=2)


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


def reference_from(builder: Builder, path: Path, tile: int = 384) -> None:
    """A reference.png from the sheet's own poses (front, wave, happy, dizzy, laptop, run) on white — so a character the
    model designed keeps that design when it's redrawn."""
    poses = [builder.drawn[p] for p in REFERENCE_POSES if p in builder.drawn]
    sheet = Image.new("RGB", (tile * len(poses), tile), (255, 255, 255))
    for i, drawn in enumerate(poses):
        im = Image.fromarray(drawn)
        k = tile * 0.9 / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        cell = Image.new("RGBA", (tile, tile), (255, 255, 255, 255))
        cell.alpha_composite(im, ((tile - im.width) // 2, tile - im.height - tile // 20))
        sheet.paste(cell.convert("RGB"), (i * tile, 0))
    sheet.save(path)


def write_pack(sheet_path: Path, out: Path, slug: str, recipe: dict | None = None, warn=None, reference: Path | None = None) -> Path:
    """Build and write the pack; `warn` gets each clipping warning (default: stderr)."""
    builder = Builder(Image.open(sheet_path), recipe or load_recipe())
    if reference is not None and not reference.exists():
        reference_from(builder, reference)  # a new character: its first sheet is its look from now on
    pack = builder.build()
    for message in builder.clip_warnings(pack):
        (warn or (lambda m: sys.stderr.write(f"warning: {slug}: {m}\n")))(message)
    gifs = out / "gifs"
    gifs.mkdir(parents=True, exist_ok=True)
    for name, (frames, timing) in pack.items():
        save_gif(frames, gifs / f"{name}.gif", timing)
    preview(pack, out / "preview.png")
    zip_path = out / f"{slug}-pack.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in pack:
            zf.write(gifs / f"{name}.gif", f"{name}.gif")
    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slug", nargs="?", help="a folder under characters/ holding poses.png")
    parser.add_argument("--sheet", type=Path, help="a pose sheet anywhere (instead of characters/<slug>/poses.png)")
    parser.add_argument("--out", type=Path, help="where to write (default characters/<slug>/out)")
    parser.add_argument(
        "--height", type=int, help="this character's standing height in px (recipe.json's for everyone); lower it if poses get cut off"
    )
    args = parser.parse_args(argv)
    if not args.slug and not args.sheet:
        parser.error("give a character slug or --sheet")
    slug = args.slug or args.sheet.stem
    sheet = args.sheet or KIT / "characters" / slug / "poses.png"
    if not sheet.exists():
        parser.error(f"no pose sheet at {sheet} — generate one with make_prompt.py {slug}")
    out = args.out or KIT / "characters" / slug / "out"
    try:
        recipe = load_recipe()
        bible = KIT / "characters" / slug / "character.json"
        own_height = json.loads(bible.read_text(encoding="utf-8")).get("height") if bible.exists() else None
        recipe["height"] = args.height or own_height or recipe["height"]  # a wide character keeps its own, smaller
        warnings: list[str] = []
        reference = KIT / "characters" / slug / "reference.png" if not args.sheet else None
        had_reference = reference is not None and reference.exists()
        zip_path = write_pack(sheet, out, slug, recipe, warn=warnings.append, reference=reference)
        if reference is not None and not had_reference:
            sys.stderr.write(f"saved {reference} from this sheet: redraws of {slug} will keep this look\n")
        for message in warnings:
            sys.stderr.write(f"warning: {slug}: {message}\n")
        if warnings:
            sys.stderr.write(f'  → check preview.png; to build {slug} smaller, add "height": {recipe["height"] - 10} to its character.json\n')
    except SheetError as e:
        sys.stderr.write(f"{sheet}: {e}\n")
        return 1
    sys.stdout.write(f"{zip_path}\n{out / 'preview.png'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
