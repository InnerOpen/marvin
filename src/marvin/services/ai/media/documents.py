"""PDFs for the media step and Ask's files: a document's text layer, page by page (pypdf), and its pages as pictures
(pypdfium2 — Google's PDFium). Both run in a separate, time-limited, memory-capped process (pdf_worker.py), the way
renders run Chromium: a damaged or hostile PDF fails one step with a reason — it can't crash, hang or bloat the server.
Each call starts one process (about a third of a second), so callers batch: one read, one render of all the pages.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

PDF_MIME = "application/pdf"
MAX_PAGES = 200  # a document read for text (its pages beyond this are left out, and the output says so)
MAX_RENDER_SIDE = 4000  # pixels: a page picture, as a render's cap
MIN_TEXT_CHARS = 20  # a page with less text than this is treated as scanned: it needs reading off its picture
MAX_WORKER_MEMORY = 2 * 1024**3  # bytes of address space the reader may use
WORKER = Path(__file__).with_name("pdf_worker.py")


class NotADocument(ValueError):
    """Not a PDF Marvin can open (damaged, encrypted, too big, too slow, or another type)."""


def is_pdf(mime_type: str | None, data: bytes | None = None) -> bool:
    return (mime_type or "").lower() == PDF_MIME or (data or b"")[:5] == b"%PDF-"


def read(data: bytes, max_pages: int = MAX_PAGES, max_chars: int | None = None) -> tuple[int, list[str]]:
    """(page count, each page's text layer — empty for a scanned page) for the first ``max_pages``, stopping early once
    more than ``max_chars`` is read."""
    result = _isolated("read", data, {"max_pages": max_pages, "max_chars": max_chars})
    return result["pages"], result["texts"]


def render_pages(data: bytes, pages: list[int], *, width: int = 1200) -> tuple[int, dict[int, Image.Image]]:
    """(page count, {page: picture ``width`` pixels wide}) for the asked-for pages (1-based) the PDF has."""
    images: dict[int, Image.Image] = {}
    result = _isolated("render", data, {"pages": list(pages), "width": width, "max_side": MAX_RENDER_SIDE}, images=images)
    return result["pages"], images


def needs_reading(text: str) -> bool:
    """A page whose text layer is (nearly) empty: a scan or a photo of text."""
    return len(text.strip()) < MIN_TEXT_CHARS


def _isolated(op: str, data: bytes, spec: dict, *, images: dict | None = None) -> dict:
    """Run pdf_worker.py on ``data``; its out.json (and, for a render, its pictures loaded into ``images``)."""
    from marvin.core.config import get_app_settings

    timeout = get_app_settings().MEDIA_PDF_TIMEOUT_SECONDS
    with tempfile.TemporaryDirectory(prefix="marvin-pdf-") as tmp:
        folder = Path(tmp)
        (folder / "input.pdf").write_bytes(data)
        (folder / "spec.json").write_text(json.dumps({**spec, "max_memory": MAX_WORKER_MEMORY}))
        try:
            subprocess.run([sys.executable, "-I", str(WORKER), op, tmp], capture_output=True, timeout=timeout, check=False)  # noqa: S603 — fixed argv
        except subprocess.TimeoutExpired as e:
            raise NotADocument(f"reading the PDF took longer than {timeout} s") from e
        out = folder / "out.json"
        if not out.exists():  # killed: out of memory, or the reader crashed on the file
            raise NotADocument("the PDF stopped the reader (damaged, or too big to open)")
        result = json.loads(out.read_text())
        if result.get("error"):
            raise NotADocument(f"not a PDF Marvin can read ({result['error']})")
        if images is not None:
            for number in result.get("made") or []:
                with Image.open(folder / f"page-{number}.png") as picture:
                    images[number] = picture.convert("RGB")  # loaded now: the folder goes when this returns
        return result
