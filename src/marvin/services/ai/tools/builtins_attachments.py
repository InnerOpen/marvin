"""
Attachment tool: read the text of a document asset — read-only.

The bubble and the Ask page let the user attach files to a question. Images the model looks at with
`view_image`; this tool covers documents: plain text (txt, md, csv, json, …), PDF and Word (.docx). It
returns the text, capped, and writes nothing.
"""

from __future__ import annotations

import io
import json
import uuid

from marvin.services.ai.operations.base import ROLE_VIEWER

from .base import ToolContext, register_tool

DEFAULT_MAX_CHARS = 20_000
MAX_FILE_BYTES = 25 * 1024 * 1024  # larger files aren't opened: the cap on returned text would throw most of it away

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT_MIMES = {"application/json", "application/xml", "application/yaml", "application/x-yaml", "application/csv", "application/x-ndjson"}
_TEXT_EXTENSIONS = {"txt", "md", "markdown", "csv", "tsv", "json", "ndjson", "yaml", "yml", "xml", "html", "htm", "log", "ini", "toml"}


def document_kind(mime_type: str | None, extension: str | None) -> str | None:
    """'text' | 'pdf' | 'docx' for a file this tool can read, else None."""
    mime = (mime_type or "").split(";")[0].strip().lower()
    ext = (extension or "").lstrip(".").lower()
    if mime == "application/pdf" or ext == "pdf":
        return "pdf"
    if mime == DOCX_MIME or ext == "docx":
        return "docx"
    if mime.startswith("text/") or mime in _TEXT_MIMES or ext in _TEXT_EXTENSIONS:
        return "text"
    return None


def extract_text(kind: str, data: bytes, max_chars: int) -> str:
    """The document's text, stopping once a little more than `max_chars` has been read."""
    if kind == "text":
        return data.decode("utf-8", errors="replace")
    if kind == "pdf":
        from pypdf import PdfReader

        parts, size = [], 0
        for page in PdfReader(io.BytesIO(data)).pages:
            text = page.extract_text() or ""
            parts.append(text)
            size += len(text)
            if size > max_chars:
                break
        return "\n\n".join(parts)
    if kind == "docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            paragraphs.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
        return "\n".join(paragraphs)
    raise ValueError(f"unknown document kind {kind!r}")


@register_tool(
    name="read_attachment",
    description=(
        "Read the text of a document asset — plain text, Markdown, CSV, JSON, PDF or Word (.docx) — without "
        "changing anything. Use when the user attaches a document (or points at one) and asks about its "
        "contents. Images: use view_image instead. Long documents are cut at `max_chars` (default 20000); "
        "the result says when."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "asset": {"type": "string", "description": "asset id or slug"},
            "max_chars": {"type": "integer", "description": f"most characters to return (default and maximum {DEFAULT_MAX_CHARS})"},
        },
        "required": ["asset"],
    },
    min_role=ROLE_VIEWER,
    read_only=True,
)
def read_attachment(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.entity_resolve import resolve_entity_id
    from marvin.services.storage.provider_factory import provider_for

    ref = str(args.get("asset") or "").strip()
    if not ref:
        return json.dumps({"error": "asset is required (id or slug)"})
    try:
        # An unknown slug comes back unchanged, and isn't a valid id: same answer as a missing asset.
        asset = ctx.session.get(Assets, uuid.UUID(str(resolve_entity_id(ctx.session, ctx.group_id, "asset", ref))))
    except (TypeError, ValueError):
        asset = None
    except Exception as e:  # noqa: BLE001 — surface to the model
        return json.dumps({"error": f"could not resolve asset '{ref}': {e}"})
    if asset is None or str(asset.group_id) != str(ctx.group_id):
        return json.dumps({"error": f"no asset '{ref}' in this workspace (try list_assets)"})

    about = {"id": str(asset.id), "name": asset.name, "mimeType": asset.mime_type}
    kind = document_kind(asset.mime_type, asset.extension)
    if kind is None:
        hint = " Use view_image for an image." if (asset.mime_type or "").startswith("image/") else ""
        return json.dumps({"error": f"can't read this kind of file ({asset.mime_type}).{hint}", "asset": about})
    if (asset.file_size or 0) > MAX_FILE_BYTES:
        return json.dumps({"error": f"the file is too large to read ({asset.file_size // (1024 * 1024)} MB)", "asset": about})

    try:
        max_chars = max(1, min(int(args.get("max_chars") or DEFAULT_MAX_CHARS), DEFAULT_MAX_CHARS))
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS
    try:
        with provider_for(asset.storage_provider).get(asset.storage_key) as fh:
            data = fh.read()
        text = extract_text(kind, data, max_chars).strip()
    except Exception as e:  # noqa: BLE001 — an unreadable file is data for the model, never an exception in the loop
        return json.dumps({"error": f"could not read the file: {e}", "asset": about})

    if not text:
        note = "no text found — a scanned PDF holds only images of its pages" if kind == "pdf" else "the document is empty"
        return json.dumps({"asset": about, "text": "", "note": note})
    if len(text) > max_chars:
        return json.dumps({"asset": about, "text": text[:max_chars], "truncated": True, "note": f"cut at {max_chars} characters"})
    return json.dumps({"asset": about, "text": text, "truncated": False})
