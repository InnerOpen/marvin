"""Image operations a workflow's media step runs (services/automation/actions/media.py) — Pillow, local, free.

Pure bytes in → bytes (or facts) out, like ``transforms``: no DB, no provider. ``transforms`` holds the recipe-token
ops an entry type's enrichment shares (grade, aspect crop); these add what a workflow needs on top — resize, convert,
inspect, palette — reusing its load/dump so EXIF orientation, alpha and JPEG flattening behave the same everywhere.
"""

from __future__ import annotations

import io

from PIL import Image

from . import transforms

# The formats a media step reads and writes: name → (Pillow format, mime type, file extension).
FORMATS: dict[str, tuple[str, str, str]] = {
    "jpeg": ("JPEG", "image/jpeg", "jpg"),
    "png": ("PNG", "image/png", "png"),
    "webp": ("WEBP", "image/webp", "webp"),
}
_BY_PIL = {pil: name for name, (pil, _mime, _ext) in FORMATS.items()} | {"MPO": "jpeg"}  # MPO: a camera's multi-picture JPEG

DEFAULT_QUALITY = 90
MAX_DIMENSION = 10_000  # a resize target larger than this is a typo, not a size
SHARPNESS_SIDE = 512  # sharpness is measured on a copy this big, so a 6000 px photo and its 1200 px copy score alike
PALETTE_SIDE = 128
MAX_PALETTE_COLORS = 16


class NotAnImage(ValueError):
    """The bytes aren't a raster image Marvin can process (jpeg, png, webp)."""


def format_of(data: bytes) -> str:
    """The format name (``jpeg`` / ``png`` / ``webp``) of image bytes; NotAnImage for anything else."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            name = _BY_PIL.get((img.format or "").upper())
    except Exception as e:  # noqa: BLE001 — Pillow raises a handful of types for "not an image"
        raise NotAnImage("not an image Marvin can process") from e
    if name is None:
        raise NotAnImage("not an image Marvin can process (jpeg, png or webp)")
    return name


def _encode(img: Image.Image, fmt: str, quality: int | None) -> bytes:
    return transforms._dump(img, FORMATS[fmt][0], quality or DEFAULT_QUALITY)


def resize(data: bytes, *, width: int | None = None, height: int | None = None, fit: str = "inside", fmt: str | None = None, quality=None) -> bytes:
    """Scale down to ``width`` × ``height``. ``inside`` keeps the whole picture within the box (either side may be
    left out); ``cover`` fills the box exactly and trims the overflow from the centre. Never scales up: a picture
    already smaller stays its size (``cover`` still trims it to the box's shape)."""
    if not (width or height):
        raise ValueError("resize needs a width or a height")
    img, _ = transforms._load(data)
    fmt = fmt or format_of(data)
    w, h = img.size
    if fit == "cover" and width and height:
        scale = min(1.0, max(width / w, height / h))
        scaled = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS) if scale < 1 else img
        box = transforms.aspect_box(scaled.size, (width, height))
        return _encode(scaled.crop(box), fmt, quality)
    scale = min(1.0, (width / w) if width else 1.0, (height / h) if height else 1.0)
    if scale < 1:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
    return _encode(img, fmt, quality)


def convert(data: bytes, fmt: str, *, quality=None) -> bytes:
    """Re-encode as ``fmt`` (jpeg flattens transparency onto white; png and webp keep it)."""
    img, _ = transforms._load(data)
    return _encode(img, fmt, quality)


def reencode(transformed: bytes, fmt: str | None, quality=None) -> bytes:
    """A transform's output in the step's ``format``/``quality`` when it asks for one; else as it came."""
    return convert(transformed, fmt or format_of(transformed), quality=quality) if fmt or quality else transformed


def sharpness(img: Image.Image) -> float:
    """How sharp a picture looks: the variance of a Laplacian over a downscaled grey copy. Blurry pictures score low
    (single digits to tens), crisp ones in the hundreds and up; compare against a threshold that suits the images."""
    import numpy as np

    grey = img.convert("L")
    grey.thumbnail((SHARPNESS_SIDE, SHARPNESS_SIDE))
    a = np.asarray(grey, dtype=np.float32)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    lap = a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1]
    return round(float(lap.var()), 2)


def inspect(data: bytes) -> dict:
    """The facts a quality check reads: size, orientation, aspect (width / height), sharpness, type and byte size."""
    fmt = format_of(data)
    img, _ = transforms._load(data)
    w, h = img.size
    orientation = "square" if w == h else ("landscape" if w > h else "portrait")
    return {
        "width": w,
        "height": h,
        "orientation": orientation,
        "aspect": round(w / h, 3),
        "sharpness": sharpness(img),
        "mime_type": FORMATS[fmt][1],
        "file_size": len(data),
    }


def palette(data: bytes, colors: int = 5) -> list[str]:
    """The picture's main colours, most common first, as ``#rrggbb``. Transparent pixels don't count."""
    import numpy as np

    format_of(data)
    colors = max(1, min(int(colors), MAX_PALETTE_COLORS))
    img, _ = transforms._load(data)
    img = img.convert("RGBA")
    img.thumbnail((PALETTE_SIDE, PALETTE_SIDE), Image.Resampling.NEAREST)  # sampled, not blended: no in-between colours
    px = np.asarray(img).reshape(-1, 4)
    opaque = px[px[:, 3] > 127][:, :3]
    if not len(opaque):
        return []
    strip = Image.fromarray(opaque.reshape(1, -1, 3).astype("uint8"), "RGB")
    quantized = strip.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    pal = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], reverse=True)
    return [f"#{pal[i * 3]:02x}{pal[i * 3 + 1]:02x}{pal[i * 3 + 2]:02x}" for _n, i in counts[:colors]]
