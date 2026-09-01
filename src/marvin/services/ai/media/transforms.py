"""Local, deterministic image transforms (Phase 1 media pipeline).

Pure byte-in/byte-out operations backed by Pillow — no model, no provider, no network,
no cost. These execute the recipe's ``derive`` media tokens (``grade:*``, ``crop:*``) on an
entry's raster images. Model-driven ops (restyle / generate-similar) are a later phase.

A token is ``"<op>:<arg>"`` — e.g. ``"grade:rustic-warm"``, ``"crop:4x5"``. Non-media tokens
(``thumbnail``, ``palette``, ``alt_text``, …) are ignored here.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

# Formats we can transform. SVGs (icons) and anything else pass through untouched.
_RASTER_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

# Named color-grade presets. Each is a set of gentle, deterministic adjustments.
#   warmth: >1 pushes toward warm (red up, blue down); <1 cools.
#   contrast/saturation/brightness: Pillow ImageEnhance factors (1.0 = unchanged).
#   vignette: 0..1 strength of an edge darkening (0 = off).
GRADE_PRESETS: dict[str, dict[str, float]] = {
    "rustic-warm": {"warmth": 1.10, "contrast": 1.12, "saturation": 0.92, "brightness": 0.98, "vignette": 0.18},
    "warm": {"warmth": 1.08, "contrast": 1.05, "saturation": 1.00, "brightness": 1.00, "vignette": 0.00},
    "cool": {"warmth": 0.92, "contrast": 1.05, "saturation": 0.98, "brightness": 1.00, "vignette": 0.00},
    "muted": {"warmth": 1.00, "contrast": 0.96, "saturation": 0.82, "brightness": 1.00, "vignette": 0.10},
}


def is_media_token(token: str) -> bool:
    """True for tokens this module executes (``grade:*`` / ``crop:*``)."""
    return isinstance(token, str) and (token.startswith("grade:") or token.startswith("crop:"))


def can_transform(mime_type: str | None) -> bool:
    """Whether a source asset's mime type is a raster image we can process."""
    return (mime_type or "").lower() in _RASTER_MIMES


def _load(data: bytes) -> tuple[Image.Image, str]:
    img = Image.open(io.BytesIO(data))
    fmt = (img.format or "JPEG").upper()
    return img, fmt


def _dump(img: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    if fmt in ("JPG", "JPEG"):
        # JPEG has no alpha channel. Composite transparency onto WHITE — the naive `convert("RGB")`
        # keeps whatever RGB sits under a transparent pixel (usually black), turning transparent
        # backgrounds black. PNG/WEBP below keep their alpha untouched.
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, (255, 255, 255))
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            img = flattened
        img.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)
    elif fmt == "WEBP":
        img.save(out, format="WEBP", quality=90)
    else:
        img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _alpha_of(img: Image.Image) -> Image.Image | None:
    """The alpha channel if the image carries one, so grades can restore it after RGB-only work."""
    return img.getchannel("A") if img.mode in ("RGBA", "LA") else None


def _apply_warmth(img: Image.Image, warmth: float) -> Image.Image:
    """Shift white balance: scale the red channel up and blue down (or vice-versa)."""
    if warmth == 1.0:
        return img
    alpha = _alpha_of(img)
    r, g, b = img.convert("RGB").split()
    r = r.point(lambda v: min(255, int(v * warmth)))
    b = b.point(lambda v: min(255, int(v * (2.0 - warmth))))
    out = Image.merge("RGB", (r, g, b))
    if alpha is not None:
        out.putalpha(alpha)  # keep transparency — grading is an RGB-only operation
    return out


def _apply_vignette(img: Image.Image, strength: float) -> Image.Image:
    """Darken toward the corners with a soft radial mask."""
    if strength <= 0:
        return img
    alpha = _alpha_of(img)
    img = img.convert("RGB")
    w, h = img.size
    # Radial gradient mask: bright center → dark edges.
    mask = Image.new("L", (w, h), 0)
    cx, cy = w / 2, h / 2
    max_d = (cx**2 + cy**2) ** 0.5
    px = mask.load()
    for y in range(h):
        for x in range(w):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / max_d
            px[x, y] = int(255 * (1 - min(1.0, d) * strength))
    black = Image.new("RGB", (w, h), (0, 0, 0))
    out = Image.composite(img, black, mask)
    if alpha is not None:
        out.putalpha(alpha)  # the vignette darkens RGB toward the edges; transparency is preserved
    return out


def color_grade_params(data: bytes, params: dict) -> bytes | None:
    """Apply an explicit color-grade params dict (``warmth/contrast/saturation/brightness/vignette``).

    Pure: params in, bytes out — no preset lookup, no DB. The caller (service layer) resolves the
    effective params (built-in defaults + workspace overrides) and passes them here. Returns None
    for empty/invalid params."""
    if not isinstance(params, dict) or not params:
        return None
    img, fmt = _load(data)
    img = _apply_warmth(img, params.get("warmth", 1.0))
    if params.get("contrast", 1.0) != 1.0:
        img = ImageEnhance.Contrast(img).enhance(params["contrast"])
    if params.get("saturation", 1.0) != 1.0:
        img = ImageEnhance.Color(img).enhance(params["saturation"])
    if params.get("brightness", 1.0) != 1.0:
        img = ImageEnhance.Brightness(img).enhance(params["brightness"])
    if params.get("vignette", 0.0) > 0:
        # Vignette on a downscaled copy is far cheaper; skip for very large images is fine here.
        img = _apply_vignette(img, params["vignette"])
    return _dump(img, fmt)


def color_grade(data: bytes, preset: str) -> bytes | None:
    """Apply a named BUILT-IN color-grade preset. Returns None for an unknown preset.

    Convenience wrapper over ``color_grade_params`` for the standalone/built-in path. Workspace
    preset overrides are resolved in the service layer, which calls ``color_grade_params`` directly."""
    params = GRADE_PRESETS.get(preset)
    if params is None:
        logger.warning("media: unknown grade preset %r", preset)
        return None
    return color_grade_params(data, params)


def crop_to_aspect(data: bytes, aspect: tuple[int, int]) -> bytes | None:
    """Center-crop to the given aspect ratio (e.g. (4, 5))."""
    aw, ah = aspect
    if aw <= 0 or ah <= 0:
        return None
    img, fmt = _load(data)
    w, h = img.size
    target = aw / ah
    current = w / h
    if abs(current - target) < 1e-3:
        return _dump(img, fmt)
    if current > target:  # too wide → trim sides
        new_w = int(h * target)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:  # too tall → trim top/bottom
        new_h = int(w / target)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)
    return _dump(img.crop(box), fmt)


def crop_to_box(data: bytes, box: tuple[float, float, float, float]) -> bytes | None:
    """Crop to a normalized box ``(x, y, w, h)`` in ``0..1`` (``x, y`` = top-left corner).

    Center-safe: the box is clamped to the image bounds so a slightly out-of-range box from a
    vision model (or an integration's detector) still produces a valid, non-empty crop. Returns
    ``None`` for a degenerate (zero-area) box.
    """
    if not box or len(box) != 4:
        return None
    x, y, w, h = (float(v) for v in box)
    if w <= 0 or h <= 0:
        return None
    img, fmt = _load(data)
    iw, ih = img.size
    left = int(round(min(max(x, 0.0), 1.0) * iw))
    top = int(round(min(max(y, 0.0), 1.0) * ih))
    right = int(round(min(max(x + w, 0.0), 1.0) * iw))
    bottom = int(round(min(max(y + h, 0.0), 1.0) * ih))
    # Guarantee a non-empty box within bounds.
    left = max(0, min(left, iw - 1))
    top = max(0, min(top, ih - 1))
    right = max(left + 1, min(right, iw))
    bottom = max(top + 1, min(bottom, ih))
    return _dump(img.crop((left, top, right, bottom)), fmt)


def _parse_aspect(arg: str) -> tuple[int, int] | None:
    for sep in ("x", ":", "/"):
        if sep in arg:
            a, _, b = arg.partition(sep)
            if a.strip().isdigit() and b.strip().isdigit():
                return int(a), int(b)
    return None


def apply_token(token: str, data: bytes) -> bytes | None:
    """Execute one media token against image bytes. Returns transformed bytes, or None if the
    token isn't a (valid) media token or the transform produced nothing."""
    if not is_media_token(token):
        return None
    op, _, arg = token.partition(":")
    try:
        if op == "grade":
            return color_grade(data, arg)
        if op == "crop":
            aspect = _parse_aspect(arg)
            return crop_to_aspect(data, aspect) if aspect else None
    except Exception as e:  # noqa: BLE001 — a bad image must not break enrichment
        logger.warning("media: token %r failed: %s", token, e)
    return None
