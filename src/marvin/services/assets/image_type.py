"""An image's real type from its first bytes. A stored label can be wrong: a version saved by the media pipeline took
its original's extension, so an AI-generated PNG made from a JPEG was labelled image/jpeg — and Anthropic refuses an
image whose bytes don't match the type it is told."""

from __future__ import annotations

EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def sniff_image_mime(data: bytes) -> str | None:
    """PNG, JPEG, GIF or WebP from the first bytes, or None when it isn't one of those."""
    head = data[:12]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None
