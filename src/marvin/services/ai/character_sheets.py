"""Bubble characters from ONE image: a character sheet becomes a whole pack of animations.

Two kinds of sheet are recognised, strictly — anything else stays an ordinary image (character.py: expand_sheet):

- A 16-pose sheet: still poses, 4 rows of 4 in character_recipe.json's order, on one flat colour (or transparent) —
  what the dev kit's make_prompt.py asks an image model for. Every pose is cut at ONE scale (the first pose is the
  recipe's `height` tall) with its feet on the same ground line; the motion (bobs, blinks, jumps, wobbles, runs,
  peeks) is the recipe's, and the peek ledges are drawn here so they never move.
- A ChatGPT pet sheet (its built-in pets, and those its Create Pet skill makes): 8 columns of 192×208 cells; rows 0-8
  are idle, running-right, running-left, waving, jumping, failed, waiting, running (active work), review, each using
  its first N cells; a v2 sheet adds rows 9-10, sixteen look directions clockwise from up. Its animation is
  hand-drawn, so every frame is kept as drawn at one scale and one offset (idle's first frame stands on the ground
  line); look-loop comes from the look rows and the four edge peeks from the recipe's ledges.

Either way the pack is fitted: built at the largest height (from the recipe's down) at which no frame is cut off.
Each animation is a list of square RGBA frames named like the uploader's aliases (idle, waving, peek-left…), so
encoded as GIFs (gif_bytes) they fill every state. The dev kit (src/dev/character_kit) is a command line over this.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageFilter, ImageOps

RECIPE_PATH = Path(__file__).with_name("character_recipe.json")
SOLID = 128  # GIF has no partial alpha: at or above shows, below is transparent

POSE_SHEET, PET_SHEET = "16-pose sheet", "ChatGPT pet sheet"
POSES_PER_ROW = 4
POSE_SHEET_ASPECT = (0.8, 1.25)  # width / height: square-ish
MIN_POSE_SHARE = 1 / 3  # every pose at least this share of the tallest one's height: a sheet of poses, not bits
# Decoding a sheet holds a few copies of it as int arrays; a real one is ~1-4 Mpx.
MAX_SHEET_PIXELS = 16_000_000
# The real transparency that makes a sheet's background its alpha, not its border colour.
TRANSPARENT_SHARE = 0.2

MIN_HEIGHT, HEIGHT_STEP = 64, 4  # fitting: the smallest height tried, and the step down

Animation = tuple[list[Image.Image], int | list[int]]  # frames, and one duration (ms) for all or one each


class SheetError(ValueError):
    """The image can't be read as a sheet of that kind (wrong count, no flat background…)."""


def load_recipe(path: Path = RECIPE_PATH) -> dict:
    """A fresh copy (callers set their own height on it)."""
    return json.loads(path.read_text(encoding="utf-8"))


# --- the background -------------------------------------------------------------------------------------------------
BACKGROUND_NEAR = 60  # this close to the sheet's background colour: background, wherever it is (gaps between limbs too)
BACKGROUND_EDGE = 150  # this close, and right beside background: the soft blend around an outline
BACKGROUND_SATURATION = 150  # a background colour's channels span at least this: magenta, green, cyan — not white
BACKGROUND_FLATNESS = 30  # the border's median distance from its colour: one flat colour, not a scene


def key_background(img: Image.Image) -> np.ndarray:
    """RGBA with the sheet's flat background made transparent — whichever colour make_prompt.py chose (magenta,
    green, cyan…). Judged by distance from the background's ACTUAL colour, sampled from the border: a crimson cap or a
    purple body stays, while the blended pixels around each outline, which touch the background, go too."""
    rgb = np.array(img.convert("RGB")).astype(int)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    colour = np.median(border, axis=0)
    saturated = colour.max() - colour.min() > BACKGROUND_SATURATION
    flat = float(np.median(np.sqrt(((border - colour) ** 2).sum(axis=1)))) < BACKGROUND_FLATNESS
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


def sheet_rgba(img: Image.Image) -> np.ndarray:
    """RGBA: as it is when the sheet has real transparency, else keyed by its border colour (key_background)."""
    rgba = np.array(img.convert("RGBA"))
    return rgba if (rgba[..., 3] < 255).mean() > TRANSPARENT_SHARE else key_background(img)


# --- cutting the poses ------------------------------------------------------------------------------------------------
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


def cut_poses(rgba: np.ndarray, count: int, per_row: int = POSES_PER_ROW) -> list[np.ndarray]:
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


def pose_tiles(rgba: np.ndarray, recipe: dict) -> dict[str, np.ndarray]:
    """{pose id: its drawing} in the recipe's order, cut from a keyed sheet."""
    ids = [p["id"] for p in recipe["poses"]]
    return dict(zip(ids, cut_poses(rgba, len(ids)), strict=True))


# --- composing frames -------------------------------------------------------------------------------------------------
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


def _clip_warnings(pack: dict[str, Animation], ledge_of: Callable[[str], str | None], ledge_width: int) -> list[str]:
    """Each animation whose drawing runs off the frame somewhere, and in which frames — cut off when it plays."""
    warnings = []
    for name, (frames, _) in pack.items():
        hits: dict[str, list[int]] = {}
        for i, f in enumerate(frames):
            for edge in clipped_edges(f, ledge_of(name), ledge_width):
                hits.setdefault(edge, []).append(i + 1)
        for edge, at in hits.items():
            warnings.append(f"{name}: cut off at the {edge} edge in frame{'s' if len(at) > 1 else ''} {', '.join(map(str, at))}")
    return warnings


class Builder:
    """A 16-pose sheet's pack: the recipe's animations, played with the sheet's poses."""

    def __init__(self, sheet: Image.Image | None, recipe: dict, tiles: dict[str, np.ndarray] | None = None):
        """From a pose sheet, or from `tiles` already cut ({pose id: RGBA drawing}, the first one standing)."""
        self.recipe = recipe
        self.frame_size, self.ground = recipe["frame"], recipe["ground"]
        if tiles is None:
            tiles = pose_tiles(key_background(sheet), recipe)
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

    def animation(self, spec) -> Animation:
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

    def _ledge_of(self, name: str) -> str | None:
        spec = self.recipe["animations"][name]
        if isinstance(spec, dict) and "mirror" in spec:
            source = self.recipe["animations"][spec["mirror"]]
            return {"left": "right", "right": "left"}.get(source.get("peek")) if isinstance(source, dict) else None
        return spec.get("peek") if isinstance(spec, dict) else None

    def clip_warnings(self, pack: dict[str, Animation]) -> list[str]:
        return _clip_warnings(pack, self._ledge_of, self.recipe["ledge"]["width"])

    def build(self) -> dict[str, Animation]:
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


# --- ChatGPT pet sheets -----------------------------------------------------------------------------------------------
PET_COLUMNS = 8
PET_CELL_ASPECT = 208 / 192  # height / width
PET_STATES = ("idle", "running-right", "running-left", "waving", "jumping", "failed", "waiting", "running", "review")
LOOK_ROWS = (9, 10)  # v2: 000…157.5, then 180…337.5
LOOK_LEFT, LOOK_RIGHT = (10, 4), (9, 4)  # 270 screen-left, 090 screen-right (row, column)
PET_ROW_COUNTS = (len(PET_STATES), len(PET_STATES) + len(LOOK_ROWS))
PET_ROWS_TOLERANCE = 0.02  # how far from a whole number of 192:208 rows the sheet's shape may be
MIN_PIXELS = 200  # a cell with fewer drawn pixels is empty
# Each drawing stays inside its cell, so the lines between cells are clear (exactly, on every sheet seen); a poster or
# a form that happens to have the shape runs across them.
MAX_GRID_LINE_SHARE = 0.002


def pet_rows(width: int, height: int) -> int | None:
    """How many rows a sheet of this size has as a ChatGPT pet sheet (9, or 11 for v2); None when it isn't one."""
    exact = height / (width / PET_COLUMNS * PET_CELL_ASPECT)
    return next((n for n in PET_ROW_COUNTS if abs(exact - n) <= n * PET_ROWS_TOLERANCE), None)


def cells(rgba: np.ndarray) -> list[list[np.ndarray]]:
    """The sheet as rows of its drawn cells (empty trailing cells dropped), each cell full size."""
    height, width = rgba.shape[:2]
    rows = pet_rows(width, height)
    if rows is None:
        raise SheetError(f"{width}×{height} isn't a ChatGPT pet sheet: 8 columns of 192×208-shaped cells, 9 or 11 rows")
    cw, ch = width / PET_COLUMNS, height / rows
    drawn = rgba[..., 3] > SOLID
    on_lines = [drawn[:, round(c * cw)] for c in range(1, PET_COLUMNS)] + [drawn[round(r * ch), :] for r in range(1, rows)]
    if np.concatenate(on_lines).mean() > MAX_GRID_LINE_SHARE:
        raise SheetError("its drawings cross the lines between cells — a ChatGPT pet sheet keeps each frame in its cell")
    out = []
    for r in range(rows):
        row = []
        for c in range(PET_COLUMNS):
            cell = rgba[round(r * ch) : round((r + 1) * ch), round(c * cw) : round((c + 1) * cw)]
            if (cell[..., 3] > SOLID).sum() >= MIN_PIXELS:
                row.append(cell)
        out.append(row)
    return out


def _bbox(cell: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(cell[..., 3] > 0)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _crop(cell: np.ndarray) -> np.ndarray:
    x0, y0, x1, y1 = _bbox(cell)
    return cell[y0 : y1 + 1, x0 : x1 + 1]


def _feet_centre(cell: np.ndarray) -> float:
    x0, y0, x1, y1 = _bbox(cell)
    feet = cell[y1 - max(1, (y1 - y0) // 8) : y1 + 1, :, 3] > SOLID
    xs = np.nonzero(feet.any(axis=0))[0]
    return (xs.min() + xs.max()) / 2 if len(xs) else (x0 + x1) / 2


class PetPack:
    """A ChatGPT pet sheet's pack: its own drawn rows, plus look-loop and the recipe's peeks."""

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

    def build(self) -> dict[str, Animation]:
        ms = self.recipe["frame_ms"]
        pack: dict[str, Animation] = {}
        for state, row in zip(PET_STATES, self.rows, strict=False):
            if row:
                pack[state] = ([self.frame(c) for c in row], ms)
        idle = self.rows[0][0]
        left, right = self.cell(*LOOK_LEFT), self.cell(*LOOK_RIGHT)
        if left is not None and right is not None:  # v2: look around — left, back, right, back
            look = [idle, left, left, left, idle, right, right, right]
            pack["look-loop"] = ([self.frame(c) for c in look], ms)
        # Peeks: the recipe's ledges and lean, with this pet's own drawings as its poses.
        tiles = {"neutral": _crop(idle), "happy": _crop(idle)}
        tiles["glance-right"] = _crop(right) if right is not None else _crop(idle)
        tiles["glance-left"] = _crop(left) if left is not None else _crop(idle)
        builder = Builder(None, self.recipe, tiles=tiles)
        for name, spec in self.recipe["animations"].items():
            if isinstance(spec, dict) and "peek" in spec:
                pack[name] = builder.animation(spec)
        return pack

    def clip_warnings(self, pack: dict[str, Animation]) -> list[str]:
        ledge_of = lambda name: name.removeprefix("peek-") if name.startswith("peek-") else None  # noqa: E731
        return _clip_warnings(pack, ledge_of, self.recipe["ledge"]["width"])


# --- building a pack, fitted ------------------------------------------------------------------------------------------
class _Pack(Protocol):
    def build(self) -> dict[str, Animation]: ...
    def clip_warnings(self, pack: dict[str, Animation]) -> list[str]: ...


@dataclass
class BuiltSheet:
    """A sheet's pack: what it was, the height it was built at, its animations, and any frames still cut off."""

    kind: str
    height: int
    animations: dict[str, Animation]
    warnings: list[str] = field(default_factory=list)
    drawn: dict[str, np.ndarray] = field(default_factory=dict)  # a pose sheet's poses as drawn (the kit's reference)


def _fit(make: Callable[[int], _Pack], height: int | None, start: int) -> tuple[dict[str, Animation], list[str], int]:
    """Built at `height`; or, when None, at the largest height from `start` down at which no frame is cut off — a
    smaller character is the only fix for a drawing that runs off the frame. Below MIN_HEIGHT it stops, warnings and
    all. Each try builds frames only; nothing is encoded until the height is settled."""
    tried = height or start
    while True:
        maker = make(tried)
        pack = maker.build()
        warnings = maker.clip_warnings(pack)
        if height or not warnings or tried - HEIGHT_STEP < MIN_HEIGHT:
            return pack, warnings, tried
        tried -= HEIGHT_STEP


def build_poses(rgba: np.ndarray, recipe: dict, height: int | None = None) -> BuiltSheet:
    """A 16-pose sheet's pack (`rgba` keyed); fitted unless `height` is given. SheetError when it isn't 16 poses."""
    return _poses_pack(pose_tiles(rgba, recipe), recipe, height)


def _poses_pack(tiles: dict[str, np.ndarray], recipe: dict, height: int | None = None) -> BuiltSheet:
    pack, warnings, used = _fit(lambda h: Builder(None, {**recipe, "height": h}, tiles=tiles), height, recipe["height"])
    return BuiltSheet(POSE_SHEET, used, pack, warnings, drawn=tiles)


def build_pet(rgba: np.ndarray, recipe: dict, height: int | None = None) -> BuiltSheet:
    """A ChatGPT pet sheet's pack; fitted unless `height` is given. SheetError when it isn't one."""
    pack, warnings, used = _fit(lambda h: PetPack(rgba, {**recipe, "height": h}), height, recipe["height"])
    return BuiltSheet(PET_SHEET, used, pack, warnings)


def _sheet_poses(rgba: np.ndarray, recipe: dict) -> dict[str, np.ndarray] | None:
    """The 16 poses, when `rgba` is 16 drawings in a 4×4 grid, each a figure rather than a fleck beside the others."""
    try:
        tiles = pose_tiles(rgba, recipe)
    except SheetError:
        return None
    heights = [t.shape[0] for t in tiles.values()]
    return tiles if min(heights) >= MIN_POSE_SHARE * max(heights) else None


def build_from_sheet(img: Image.Image, recipe: dict | None = None) -> BuiltSheet | None:
    """The fitted pack a character sheet makes, or None when `img` isn't one: only a still image shaped exactly like a
    ChatGPT pet sheet (with a drawn idle row) or a square-ish 16-pose sheet (on one flat colour, or transparent) is."""
    if getattr(img, "n_frames", 1) > 1 or img.width * img.height > MAX_SHEET_PIXELS:
        return None
    recipe = recipe or load_recipe()
    if pet_rows(img.width, img.height):
        try:
            return build_pet(sheet_rgba(img), recipe)
        except SheetError:
            pass  # shaped like one, but not one: it may still be a pose sheet
    low, high = POSE_SHEET_ASPECT
    if not low <= img.width / img.height <= high:
        return None
    try:
        rgba = sheet_rgba(img)
    except SheetError:
        return None
    tiles = _sheet_poses(rgba, recipe)
    return _poses_pack(tiles, recipe) if tiles else None


# --- encoding ---------------------------------------------------------------------------------------------------------
GIF_TRANSPARENT = 255  # the palette entry transparent pixels use; the drawing gets the other 255


def gif_bytes(frames: list[Image.Image], durations: int | list[int]) -> bytes:
    """An animation as a looping GIF, each frame whole on a cleared canvas."""
    imgs = []
    for f in frames:
        a = np.array(f)
        pal = Image.fromarray(a[..., :3]).quantize(colors=GIF_TRANSPARENT, method=Image.Quantize.MEDIANCUT)
        px = np.array(pal)
        px[a[..., 3] < SOLID] = GIF_TRANSPARENT
        p = Image.fromarray(px, "P")
        p.putpalette((pal.getpalette() + [0, 0, 0] * 256)[:768])
        imgs.append(p)
    out = io.BytesIO()
    imgs[0].save(out, "GIF", save_all=True, append_images=imgs[1:], duration=durations, loop=0, transparency=GIF_TRANSPARENT, disposal=2)
    return out.getvalue()
