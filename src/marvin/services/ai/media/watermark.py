"""Watermarks: text and/or a logo laid over a picture — in a corner, the centre, or tiled diagonally across it so
cropping can't remove it. Pure (bytes in, bytes out), local, free; the media step keeps the result as a version.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ops, transforms

POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left", "center", "tiled")
DEFAULT_POSITION = "bottom-right"
DEFAULT_OPACITY = 60  # percent
DEFAULT_SIZE = 25  # the mark's width, as a percent of the picture's width
MARGIN = 0.03  # of the picture's shorter side, between a corner mark and the edge
TILE_ANGLE = 30  # degrees
FONT_FILES = ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")  # the image's fonts when installed; else Pillow's own


def watermark(
    data: bytes,
    *,
    text: str | None = None,
    logo: bytes | None = None,
    position: str = DEFAULT_POSITION,
    opacity: int = DEFAULT_OPACITY,
    size: int = DEFAULT_SIZE,
    fmt: str | None = None,
    quality: int | None = None,
) -> bytes:
    """The picture with the mark laid over it, encoded as ``fmt`` (default: the picture's own format)."""
    if not (text or logo):
        raise ValueError("a watermark needs text or a logo")
    if position not in POSITIONS:
        raise ValueError(f"position is one of {', '.join(POSITIONS)}")
    fmt = fmt or ops.format_of(data)
    base = transforms._load(data)[0].convert("RGBA")
    mark = _mark(base.size, text, logo, size, opacity)
    overlay = _tiled(base.size, mark) if position == "tiled" else _placed(base.size, mark, position)
    out = Image.alpha_composite(base, overlay)
    return ops._encode(out if fmt != "jpeg" else out.convert("RGB"), fmt, quality)


def _mark(picture: tuple[int, int], text: str | None, logo: bytes | None, size: int, opacity: int) -> Image.Image:
    """The mark itself (logo above text when both), ``size``% of the picture's width, at ``opacity``%."""
    width = max(8, picture[0] * max(1, min(size, 100)) // 100)
    parts = []
    if logo:
        parts.append(_logo(logo, width))
    if text:
        parts.append(_text(text, width))
    gap = parts[0].height // 8 if len(parts) > 1 else 0
    mark = Image.new("RGBA", (max(p.width for p in parts), sum(p.height for p in parts) + gap), (0, 0, 0, 0))
    y = 0
    for part in parts:
        mark.alpha_composite(part, ((mark.width - part.width) // 2, y))
        y += part.height + gap
    alpha = mark.getchannel("A").point(lambda a: a * max(1, min(opacity, 100)) // 100)
    mark.putalpha(alpha)
    return mark


def _logo(data: bytes, width: int) -> Image.Image:
    logo = transforms._load(data)[0].convert("RGBA")
    height = max(1, round(logo.height * width / logo.width))
    return logo.resize((width, height), Image.Resampling.LANCZOS)


def _text(text: str, width: int) -> Image.Image:
    """White text with a soft dark shadow (readable on light and dark pictures), as wide as ``width`` at most."""
    size = 64
    font = _font(size)
    measured = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    size = max(8, int(size * width / max(1, measured[2] - measured[0])))
    font = _font(size)
    left, top, right, bottom = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    shadow = max(1, size // 18)
    canvas = Image.new("RGBA", (right - left + shadow * 3, bottom - top + shadow * 3), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((shadow * 2 - left, shadow * 2 - top), text, font=font, fill=(0, 0, 0, 140))
    canvas = canvas.filter(ImageFilter.GaussianBlur(shadow))
    ImageDraw.Draw(canvas).text((shadow - left, shadow - top), text, font=font, fill=(255, 255, 255, 255))
    return canvas


@lru_cache(maxsize=32)
def _font(size: int):
    for name in FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _placed(picture: tuple[int, int], mark: Image.Image, position: str) -> Image.Image:
    overlay = Image.new("RGBA", picture, (0, 0, 0, 0))
    margin = int(min(picture) * MARGIN)
    x = {"left": margin, "right": picture[0] - mark.width - margin}.get(position.split("-")[-1], (picture[0] - mark.width) // 2)
    y = {"top": margin, "bottom": picture[1] - mark.height - margin}.get(position.split("-")[0], (picture[1] - mark.height) // 2)
    overlay.alpha_composite(mark, (max(0, x), max(0, y)))
    return overlay


def _tiled(picture: tuple[int, int], mark: Image.Image) -> Image.Image:
    """The mark repeated on a diagonal grid over the whole picture."""
    turned = mark.rotate(TILE_ANGLE, expand=True, resample=Image.Resampling.BICUBIC)
    # Rotated, the mark's box is mostly empty corners: rows a little apart, each row's tiles nearly touching.
    step_x, step_y = int(turned.width * 1.1), max(1, int(turned.height * 0.75))
    reach = int(math.hypot(*picture))
    overlay = Image.new("RGBA", picture, (0, 0, 0, 0))
    for row, y in enumerate(range(-turned.height, min(reach, picture[1]), max(1, step_y))):
        for x in range(-turned.width + (row % 2) * step_x // 2, min(reach, picture[0]), max(1, step_x)):
            overlay.paste(turned, (x, y), turned)  # tiles don't overlap; a partly-off-picture one is clipped
    return overlay
