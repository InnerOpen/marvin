"""Media transforms must preserve transparency (regression: crop/grade turned it black).

A transparent RGBA source (e.g. a logo/seal PNG) used to come out RGB with a black background,
because `convert("RGB")` drops alpha and JPEG has none. Grades are RGB-only work with the alpha
restored; JPEG flattens onto white, never black.
"""

import io

from PIL import Image

from marvin.services.ai.media import transforms


def _transparent_png() -> bytes:
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))  # fully transparent
    for x in range(15, 25):  # an opaque denim square in the middle
        for y in range(15, 25):
            img.putpixel((x, y), (40, 57, 74, 255))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _corner_alpha(data: bytes) -> int:
    return Image.open(io.BytesIO(data)).convert("RGBA").getpixel((1, 1))[3]


def test_grade_preserves_transparency():
    graded = transforms.color_grade(_transparent_png(), "rustic-warm")  # warmth + vignette
    assert graded is not None
    assert _corner_alpha(graded) == 0  # corner still transparent, not flattened to black


def test_crop_preserves_transparency():
    cropped = transforms.crop_to_box(_transparent_png(), (0.1, 0.1, 0.8, 0.8))
    assert cropped is not None
    assert _corner_alpha(cropped) == 0


def test_jpeg_dump_flattens_transparency_onto_white_not_black():
    data = transforms._dump(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "JPEG")
    assert Image.open(io.BytesIO(data)).convert("RGB").getpixel((1, 1)) == (255, 255, 255)
