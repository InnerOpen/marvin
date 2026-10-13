"""Provider logos: read from the plugin, validated here, cached in memory.

A provider may ship its official mark as package data (SDK 0.6+, ``IntegrationProvider.logo`` read by
``load_logo``). The SDK only finds the bytes; **this module is the security boundary**. A logo is
served to browsers from Marvin's own origin, so an SVG that could run script, pull in a remote
resource or point a link elsewhere is refused (logged, and the UI falls back to the provider's emoji).
The endpoint adds a locked-down CSP on top; the checks here mean a bad file never gets that far.

Validation is deliberately strict and simple — a clean, self-contained mark passes, anything clever is
refused. Parsing uses the stdlib only, and only once a DOCTYPE/ENTITY has been ruled out (so no entity
expansion or external DTD can happen).
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

MAX_LOGO_BYTES = 64 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SVG_TYPE = "image/svg+xml"
PNG_TYPE = "image/png"

_DTD = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_STYLESHEET_PI = re.compile(r"<\?\s*xml-stylesheet", re.IGNORECASE)
_SCRIPT = re.compile(r"<\s*([\w.-]+:)?script\b", re.IGNORECASE)
_FOREIGN = re.compile(r"<\s*([\w.-]+:)?foreignObject\b", re.IGNORECASE)
_EVENT_ATTR = re.compile(r"<[^>]*\s([\w.-]+:)?on[\w.-]*\s*=", re.IGNORECASE | re.DOTALL)
_JAVASCRIPT = re.compile(r"javascript\s*:", re.IGNORECASE)
_URL_REF = re.compile(r"url\s*\(\s*['\"]?\s*([^'\")\s]*)", re.IGNORECASE)
_IMPORT = re.compile(r"@import\s*(?:url\s*\()?\s*['\"]?\s*([^'\");\s]*)", re.IGNORECASE)
_HREF_ATTR = re.compile(r"\s(?:[\w.-]+:)?href\s*=\s*(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)


class LogoRejected(ValueError):
    """Why a logo was refused — logged, never shown to end users."""


@dataclass(frozen=True)
class Logo:
    data: bytes
    content_type: str
    etag: str


def _local(name: str) -> str:
    """`{namespace}local` or `prefix:local` → `local`, lowercased."""
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _check_text(text: str, where: str) -> None:
    """The rules that apply to raw markup and to decoded attribute values/text alike."""
    if _JAVASCRIPT.search(text.replace("\x00", "")):
        raise LogoRejected(f"{where}: contains javascript:")
    for match in _URL_REF.finditer(text):
        if not match.group(1).startswith("#"):
            raise LogoRejected(f"{where}: url() points outside the document")
    for match in _IMPORT.finditer(text):
        if not match.group(1).startswith("#"):
            raise LogoRejected(f"{where}: @import points outside the document")


def _validate_svg(data: bytes) -> None:
    if _DTD.search(data):
        raise LogoRejected("SVG contains a DOCTYPE or ENTITY declaration")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise LogoRejected("SVG is not UTF-8") from e

    # Raw-markup checks first: cheap, and they catch the obvious before the parser sees anything.
    if _STYLESHEET_PI.search(text):
        raise LogoRejected("SVG references an external stylesheet")
    if _SCRIPT.search(text):
        raise LogoRejected("SVG contains <script>")
    if _FOREIGN.search(text):
        raise LogoRejected("SVG contains <foreignObject>")
    if _EVENT_ATTR.search(text):
        raise LogoRejected("SVG has an on* event attribute")
    for match in _HREF_ATTR.finditer(text):
        if not match.group(2).strip().startswith("#"):
            raise LogoRejected("SVG has an href that is not a #fragment")
    _check_text(text, "SVG")

    # Then the parsed tree, where entities and character references are decoded and namespace prefixes
    # are resolved — so `<svg:script>`, `on&#x6c;oad` style tricks or encoded URLs can't slip past.
    try:
        root = ET.fromstring(data)  # noqa: S314 — no DTD can be present (checked above); stdlib expat, no network
    except ET.ParseError as e:
        raise LogoRejected(f"SVG does not parse: {e}") from e
    if _local(root.tag) != "svg":
        raise LogoRejected("root element is not <svg>")
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = _local(el.tag)
        if tag in ("script", "foreignobject"):
            raise LogoRejected(f"SVG contains <{tag}>")
        for name, value in el.attrib.items():
            attr = _local(name)
            if attr.startswith("on"):
                raise LogoRejected(f"SVG has an event attribute '{attr}'")
            if attr == "href" and not value.strip().startswith("#"):
                raise LogoRejected("SVG has an href that is not a #fragment")
            if tag in ("set", "animate") and attr == "attributename" and (_local(value) == "href" or _local(value).startswith("on")):
                raise LogoRejected(f"SVG animates '{value}'")
            if attr == "style" and "\\" in value:
                raise LogoRejected("SVG style uses CSS escapes")
            _check_text(value, f"<{tag} {attr}>")
        if tag == "style" and el.text and "\\" in el.text:
            raise LogoRejected("SVG <style> uses CSS escapes")
        for chunk in (el.text, el.tail):
            if chunk:
                _check_text(chunk, f"<{tag}> text")


def validate_logo(data: bytes, content_type: str) -> None:
    """Raise ``LogoRejected`` unless ``data`` is a logo Marvin is willing to serve."""
    if not isinstance(data, bytes | bytearray) or not data:
        raise LogoRejected("logo is empty")
    if len(data) > MAX_LOGO_BYTES:
        raise LogoRejected(f"logo is {len(data)} bytes (max {MAX_LOGO_BYTES})")
    if content_type == PNG_TYPE:
        if not bytes(data).startswith(PNG_MAGIC):
            raise LogoRejected("PNG does not start with the PNG signature")
        return
    if content_type == SVG_TYPE:
        _validate_svg(bytes(data))
        return
    raise LogoRejected(f"unsupported logo type '{content_type}'")


# slug → validated Logo, or None when the provider has none (or it was refused). Filled on provider
# load and lazily for providers registered later (tests, late plugins).
_cache: dict[str, Logo | None] = {}


def _sdk_load_logo():
    """The SDK's ``load_logo``, or None on an SDK older than 0.6 (no logo support → emoji only)."""
    try:
        import marvin_integration_sdk
    except ImportError:
        return None
    return getattr(marvin_integration_sdk, "load_logo", None)


def _read(provider) -> Logo | None:
    loader = _sdk_load_logo()
    if loader is None:
        return None
    slug = getattr(provider, "slug", "?")
    try:
        found = loader(provider)
    except Exception as e:  # noqa: BLE001 — a plugin's logo must never break loading
        logger.warning(f"[integrations] could not read the logo for '{slug}': {e}")
        return None
    if not found:
        return None
    try:
        data, content_type = found
        validate_logo(data, content_type)
    except (LogoRejected, TypeError, ValueError) as e:
        logger.warning(f"[integrations] refused the logo for '{slug}', using its emoji instead: {e}")
        return None
    data = bytes(data)
    return Logo(data=data, content_type=content_type, etag=f'"{hashlib.sha256(data).hexdigest()[:32]}"')


def prime(providers) -> None:
    """Read, validate and cache every provider's logo (called when providers load)."""
    _cache.clear()
    for provider in providers:
        _cache[provider.slug] = _read(provider)


def get_logo(slug: str) -> Logo | None:
    """The validated logo for a registered provider, or None."""
    if slug not in _cache:
        try:
            from marvin_integration_sdk import INTEGRATION_REGISTRY
        except ImportError:  # no SDK installed: no integrations, so no logos
            return None

        provider = INTEGRATION_REGISTRY.get(slug)
        if provider is None:
            return None
        _cache[slug] = _read(provider)
    return _cache[slug]


def has_logo(slug: str) -> bool:
    return get_logo(slug) is not None


def clear_cache() -> None:
    _cache.clear()
