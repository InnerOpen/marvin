"""Bubble-character images for the character tests: a small figure on a solid background (a matte) or on
a transparent one, drawn like the generated packs that need clearing; and whole character sheets (a 16-pose sheet, a
ChatGPT pet sheet) that an upload builds into a pack."""

import io

import numpy as np
from PIL import Image, ImageDraw, ImageSequence

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


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


MAGENTA = (255, 0, 255)


def pose_sheet(poses: int = 16, size: int = 1024) -> Image.Image:
    """A pose sheet like the image model's: figures on flat magenta, 4 to a row. Each is a beige body with a dark
    outline and two 'feet', a little different from the next so the cut keeps the order visible."""
    img = Image.new("RGB", (size, size), MAGENTA)
    d = ImageDraw.Draw(img)
    cell = size // 4
    for i in range(poses):
        x0, y0 = (i % 4) * cell + cell // 4, (i // 4) * cell + cell // 6
        w, h = cell // 2, cell * 2 // 3
        d.rectangle([x0, y0, x0 + w, y0 + h - 12], fill=(200, 180, 140), outline=(40, 30, 20), width=3)
        d.rectangle([x0 + 4, y0 + h - 12, x0 + w // 3, y0 + h], fill=(40, 30, 20))  # left foot
        d.rectangle([x0 + w - w // 3, y0 + h - 12, x0 + w - 4, y0 + h], fill=(40, 30, 20))  # right foot
        d.rectangle([x0 + 6, y0 + 6, x0 + 6 + i * 3, y0 + 12], fill=(20, 120, 40))  # a bar as long as its number
    return img


def pet_sheet(rows: int = 11, cell: tuple[int, int] = (96, 104), empty_after: dict | None = None) -> Image.Image:
    """A ChatGPT-style pet sheet: 8 columns of 192×208-shaped cells, a transparent background, a figure per cell;
    the jumping row (4) lifted off the ground, each row ending early where `empty_after` says."""
    w, h = cell
    img = Image.new("RGBA", (8 * w, rows * h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    empty_after = empty_after or {0: 7, 3: 4, 4: 5}
    for r in range(rows):
        for c in range(empty_after.get(r, 8)):
            x0, y0 = c * w + w // 4, r * h + h // 4
            lift = 10 + c * 2 if r == 4 else 0
            d.rectangle([x0, y0 - lift, x0 + w // 2, y0 + h // 2 - lift], fill=(200, 120, 40, 255), outline=(40, 20, 10, 255), width=2)
    return img
