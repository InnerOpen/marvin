"""Reads or renders a PDF in a process of its own — documents.py starts it, with a time limit — so a damaged or hostile
file can crash, hang or bloat only this process, never the server. Standalone on purpose: it imports nothing of
Marvin's, and runs with ``python -I`` (no environment, no script directory on the path).

``pdf_worker.py read|render <folder>``: ``<folder>/input.pdf`` and ``<folder>/spec.json`` in; ``<folder>/out.json``
out (``{"error": …}`` when the PDF can't be read), and for ``render`` one ``page-<n>.png`` per page made.
"""

import json
import sys
from pathlib import Path


def _cap_memory(limit: int | None) -> None:
    """The address space this process may use: a PDF that asks for gigabytes fails here, not on the server."""
    if not limit:
        return
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # not on Linux, or not allowed: the time limit still holds
        pass


def read(folder: Path, spec: dict) -> dict:
    """Each page's text layer (empty for a scan), the first ``max_pages`` — stopping early past ``max_chars``."""
    from pypdf import PdfReader

    reader = PdfReader(str(folder / "input.pdf"))
    if reader.is_encrypted:
        return {"error": "the PDF is password-protected"}
    texts, size = [], 0
    for page in reader.pages[: spec["max_pages"]]:
        text = (page.extract_text() or "").strip()
        texts.append(text)
        size += len(text)
        if spec.get("max_chars") and size > spec["max_chars"]:
            break
    return {"pages": len(reader.pages), "texts": texts}


def render(folder: Path, spec: dict) -> dict:
    """The asked-for pages (1-based) as PNGs ``width`` pixels wide, never wider or taller than ``max_side``."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(folder / "input.pdf"))
    total, made = len(doc), []
    for number in spec["pages"]:
        if not 1 <= number <= total:
            continue
        page = doc[number - 1]
        width, height = page.get_size()  # points
        scale = min(spec["width"] / width, spec["max_side"] / width, spec["max_side"] / height)
        page.render(scale=scale).to_pil().convert("RGB").save(folder / f"page-{number}.png")
        made.append(number)
    return {"pages": total, "made": made}


def main(op: str, folder: Path) -> None:
    spec = json.loads((folder / "spec.json").read_text())
    _cap_memory(spec.get("max_memory"))
    try:
        result = {"read": read, "render": render}[op](folder, spec)
    except Exception as e:  # noqa: BLE001 — whatever the file did, the parent gets a reason
        result = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    (folder / "out.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
