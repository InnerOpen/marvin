"""Render an HTML/CSS template to an image with headless Chromium — the media step's `render` op.

A template is an HTML fragment (built-in, under ``render_templates/``, or a workflow step's own ``html``) filled in by
a sandboxed Jinja environment with autoescaping: ``{{ fields.<name> }}`` for text and ``{{ images.<name> }}`` for
pictures, which arrive as ``data:`` URIs (the caller reads the assets and inlines them). The page is wrapped in a
document whose Content-Security-Policy allows nothing but inline styles and ``data:`` images and fonts — no network
request, no script — so a template can't reach the cluster's network or run code, whoever wrote it.

The screenshot is ``chromium-headless-shell --screenshot`` in a subprocess with its own temporary profile: a crash or
a hang (``MEDIA_RENDER_TIMEOUT_SECONDS``) fails the step, never the worker. The full Chrome binary is not used: its
"new" headless mode hangs on ``--screenshot`` without a display.

A *paged* render (``print_pdf``) is printed instead (``--print-to-pdf``): width × height is the page, the content flows
onto as many pages as it needs, and the result is a PDF — a printable guide, a handout.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "render_templates"
MAX_SIDE = 4000  # pixels; a poster at print-ish resolution, not a billboard
MAX_HTML_CHARS = 200_000
DEFAULT_SIZE = (1080, 1080)
BROWSER_NAMES = ("chromium-headless-shell", "chrome-headless-shell", "headless_shell")
PLAYWRIGHT_GLOBS = (  # a Playwright download: newer builds, then older ones' name
    "~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell",
    "~/.cache/ms-playwright/chromium_headless_shell-*/*/headless_shell",
)
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:"


class RenderError(ValueError):
    """The template couldn't be filled in or the page couldn't be screenshotted — the message says why."""


class RenderUnavailable(RenderError):
    """No headless Chromium on this server."""


# ── Templates ────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def templates() -> dict:
    """The built-in templates: slug → {label, description, width, height, fields: {name: {label, required}},
    images: {name: {label, required}}} (render_templates/manifest.json)."""
    return json.loads((TEMPLATES_DIR / "manifest.json").read_text(encoding="utf-8"))


def template_html(slug: str) -> str:
    if slug not in templates():
        raise RenderError(f"no render template “{slug}” (templates: {', '.join(sorted(templates()))})")
    return (TEMPLATES_DIR / f"{slug}.html").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _jinja():
    from jinja2 import StrictUndefined
    from jinja2.sandbox import SandboxedEnvironment

    # Strict: a field the template uses but the step didn't fill fails loudly instead of rendering a blank card.
    return SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)


def fill(source_html: str, *, fields: dict, images: dict, width: int, height: int, paged: bool = False) -> str:
    """The template filled in, wrapped in the locked-down document Chromium screenshots (or, ``paged``, prints)."""
    from jinja2 import TemplateError

    if len(source_html) > MAX_HTML_CHARS:
        raise RenderError(f"the template is over {MAX_HTML_CHARS:,} characters")
    try:
        body = _jinja().from_string(source_html).render(fields=fields, images=images, width=width, height=height)
    except TemplateError as e:
        raise RenderError(f"the template couldn't be filled in: {e}") from e
    page = (
        f"@page{{size:{width}px {height}px;margin:0}}html,body{{margin:0;padding:0;width:{width}px}}"
        if paged
        else f"html,body{{margin:0;padding:0;width:{width}px;height:{height}px;overflow:hidden}}"
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        f"<style>{page}</style>"
        f"</head><body>{body}</body></html>"
    )


def data_uri(data: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


# ── The browser ──────────────────────────────────────────────────────────────
def browser_path() -> str | None:
    """The headless Chromium to use: the setting, else one on PATH, else a Playwright download (local dev)."""
    from marvin.core.config import get_app_settings

    configured = get_app_settings().MEDIA_RENDER_BROWSER
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    for name in BROWSER_NAMES:
        if found := shutil.which(name):
            return found
    for pattern in PLAYWRIGHT_GLOBS:
        if cached := sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            return cached[0]
    return None


def screenshot(document: str, width: int, height: int) -> bytes:
    """A PNG of ``document`` at exactly ``width`` × ``height``."""
    return _browser(document, width, height, "out.png", f"--window-size={width},{height}", "--screenshot={out}")


def print_pdf(document: str, width: int, height: int) -> bytes:
    """``document`` printed to a PDF whose pages are ``width`` × ``height`` CSS px (A4 is 794 × 1123)."""
    return _browser(document, width, height, "out.pdf", "--no-pdf-header-footer", "--print-to-pdf={out}")


def _browser(document: str, width: int, height: int, out_name: str, *flags: str) -> bytes:
    from marvin.core.config import get_app_settings

    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        raise RenderError(f"a render is 1–{MAX_SIDE} px on each side")
    browser = browser_path()
    if browser is None:
        raise RenderUnavailable("rendering needs headless Chromium (chromium-headless-shell), which this server doesn't have")
    timeout = get_app_settings().MEDIA_RENDER_TIMEOUT_SECONDS
    with tempfile.TemporaryDirectory(prefix="marvin-render-") as tmp:
        page, out = Path(tmp) / "page.html", Path(tmp) / out_name
        page.write_text(document, encoding="utf-8")
        args = [
            browser,
            "--no-sandbox",  # the container's unprivileged user can't use Chromium's sandbox; the CSP keeps the page inert
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--mute-audio",
            "--force-device-scale-factor=1",
            f"--user-data-dir={tmp}/profile",
            *(flag.format(out=out) for flag in flags),
            page.as_uri(),
        ]
        env = {**os.environ, "HOME": tmp}  # an unprivileged container user may have no writable home
        try:
            done = subprocess.run(args, capture_output=True, timeout=timeout, env=env, check=False)  # noqa: S603 — fixed argv
        except subprocess.TimeoutExpired as e:
            raise RenderError(f"the render took longer than {timeout} s") from e
        if not out.exists():
            detail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
            raise RenderError(f"the browser made no image ({detail[0][:200]})")
        return out.read_bytes()


def render(source_html: str, *, fields: dict, images: dict, width: int, height: int, paged: bool = False) -> bytes:
    """Fill in a template and screenshot it (PNG bytes) — or, ``paged``, print it (PDF bytes)."""
    document = fill(source_html, fields=fields, images=images, width=width, height=height, paged=paged)
    return print_pdf(document, width, height) if paged else screenshot(document, width, height)
