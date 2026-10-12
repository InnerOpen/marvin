"""PDFs for the media step: a document's text layer, page by page (pypdf), and its pages as pictures (pypdfium2 —
Google's PDFium, in-process). Pure functions on bytes; the step owns assets, vision calls and costs.
"""

from __future__ import annotations

import io

from PIL import Image

PDF_MIME = "application/pdf"
MAX_PAGES = 200  # a document read for text (its pages beyond this are left out, and the output says so)
MAX_RENDER_SIDE = 4000  # pixels: a page picture, as a render's cap
MIN_TEXT_CHARS = 20  # a page with less text than this is treated as scanned: it needs reading off its picture


class NotADocument(ValueError):
    """Not a PDF Marvin can open (damaged, encrypted, or another type)."""


def is_pdf(mime_type: str | None, data: bytes | None = None) -> bool:
    return (mime_type or "").lower() == PDF_MIME or (data or b"")[:5] == b"%PDF-"


def page_count(data: bytes) -> int:
    return len(_document(data))


def page_texts(data: bytes, max_pages: int = MAX_PAGES) -> list[str]:
    """Each page's text layer (empty for a scanned page), the first ``max_pages``."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise NotADocument("the PDF is password-protected")
        return [(page.extract_text() or "").strip() for page in reader.pages[:max_pages]]
    except PdfReadError as e:
        raise NotADocument(f"not a PDF Marvin can read ({e})") from e


def needs_reading(text: str) -> bool:
    """A page whose text layer is (nearly) empty: a scan or a photo of text."""
    return len(text.strip()) < MIN_TEXT_CHARS


def render_page(data: bytes, page: int, *, width: int = 1200) -> Image.Image:
    """Page ``page`` (1-based) as a picture ``width`` pixels wide (never wider than MAX_RENDER_SIDE either way)."""
    doc = _document(data)
    if not 1 <= page <= len(doc):
        raise NotADocument(f"the PDF has {len(doc)} page{'s' if len(doc) != 1 else ''}, not a page {page}")
    pdf_page = doc[page - 1]
    page_width, page_height = pdf_page.get_size()  # points
    scale = min(width / page_width, MAX_RENDER_SIDE / page_width, MAX_RENDER_SIDE / page_height)
    return pdf_page.render(scale=scale).to_pil().convert("RGB")


def _document(data: bytes):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise NotADocument(f"not a PDF Marvin can open ({e})") from e
