"""Bubble-character images for the character tests: a small figure on a solid background (a matte) or on
a transparent one, drawn like the generated packs that need clearing."""

import io

import numpy as np
from PIL import Image, ImageSequence

SIZE = 24
MATTE = (0, 0, 0)
BODY = (255, 128, 0)
OUTLINE = (4, 1, 0)  # near-black, a few levels off the matte, as generated characters' outlines are
EYE = (0, 0, 0)  # the matte's own colour, but enclosed by the body: not background
UNUSED = (84, 25, 6)  # the palette's declared-transparent entry, which a broken GIF never paints with
DURATIONS = [100, 150, 200]
LOOP = 0

# Palette indexes of a frame (a GIF stores the eye and the matte as separate entries of one colour).
_CLEAR, _MATTE, _BODY, _OUTLINE, _EYE = range(5)
_PALETTE = [UNUSED, MATTE, BODY, OUTLINE, EYE]


def figure_indexes(offset: int, background: int) -> np.ndarray:
    """A frame's palette indexes: an outlined square body with an eye, `offset` px right and down."""
    frame = np.full((SIZE, SIZE), background, np.uint8)
    lo, hi = 6 + offset, 18 + offset
    frame[lo:hi, lo:hi] = _OUTLINE
    frame[lo + 1 : hi - 1, lo + 1 : hi - 1] = _BODY
    frame[lo + 5 : lo + 7, lo + 5 : lo + 7] = _EYE
    return frame


def eye(offset: int) -> tuple[int, int]:
    """(x, y) of a pixel of the eye in the frame drawn at `offset`."""
    return 11 + offset, 11 + offset


def body(offset: int) -> tuple[int, int]:
    return 8 + offset, 8 + offset


def outline(offset: int) -> tuple[int, int]:
    return 6 + offset, 12 + offset


def _gif(background: int, frames: int) -> bytes:
    images = []
    for offset in range(frames):
        image = Image.frombytes("P", (SIZE, SIZE), figure_indexes(offset, background).tobytes())
        image.putpalette([c for rgb in _PALETTE for c in rgb])
        images.append(image)
    buf = io.BytesIO()
    images[0].save(
        buf, "GIF", save_all=True, append_images=images[1:], duration=DURATIONS[:frames], loop=LOOP, transparency=_CLEAR, disposal=2, optimize=False
    )
    return buf.getvalue()


def matted_gif(frames: int = len(DURATIONS)) -> bytes:
    """An animated GIF that declares a transparent colour but paints its background opaque black."""
    return _gif(_MATTE, frames)


def clean_gif(frames: int = len(DURATIONS)) -> bytes:
    """The same animation on a really transparent background."""
    return _gif(_CLEAR, frames)


def matted_png(matte: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """A still PNG of the figure on an opaque solid background."""
    colors = np.array([(*matte, 255), (*matte, 255), (*BODY, 255), (*OUTLINE, 255), (*EYE, 255)], np.uint8)
    rgba = colors[figure_indexes(0, _MATTE)]
    buf = io.BytesIO()
    Image.frombytes("RGBA", (SIZE, SIZE), rgba.tobytes()).save(buf, "PNG")
    return buf.getvalue()


def frames_rgba(data: bytes) -> list[Image.Image]:
    """Every frame of an image, whole, as RGBA."""
    with Image.open(io.BytesIO(data)) as img:
        return [frame.convert("RGBA") for frame in ImageSequence.Iterator(img)]
