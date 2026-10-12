"""The media step's document and privacy ops: `extract_text`, `pages`, `find_sensitive`, `redact`.

* **extract_text** — a PDF's text layer, page by page (free, local); a scanned page or a picture is read by the vision
  model (`image.read_text`, one AI call each, under the workflow AI gates and budget, logged in AI Executions). `ocr:
  never` keeps it to the text layer. Output `text` (pages marked), `pages` [{page, text, method}], `page_count`.
* **pages** — PDF pages as pictures (pypdfium2): `page` (first, default 1), `count` (default 1), `width` (default
  1200 px), `format`. Each is a derived asset with lineage, made once (the same page, size and format is reused).
* **find_sensitive** — the regions a person would blur before publishing (faces, plates, personal text), by the vision
  model: `regions` [{kind, box}], `count`. Reading only.
* **redact** — a copy with those regions pixelated (`boxes` given, or found as find_sensitive does): a derived asset;
  none when there is nothing to blur (`count: 0`).
"""

from __future__ import annotations

import hashlib
import io
import json

from ..matcher import interpolate
from .base import AutomationActionError

MAX_OCR_PAGES = 20  # scanned pages read by the vision model in one step (each is an AI call)
OCR_PAGE_WIDTH = 1600  # px: a scanned page as the vision model sees it
TEXT_CHARS = 20_000  # the whole text in the step's output (the run snapshot has a size cap)
PAGE_TEXT_CHARS = 2_000  # each page's text in `pages`
PAGES_LISTED = 50
DEFAULT_PAGE_WIDTH = 1200
DEFAULT_PAGE_FORMAT = "webp"
READ_OPERATION = "read-text"  # AI Executions' name for a vision text read
SENSITIVE_OPERATION = "find-sensitive"
SENSITIVE = "_media_sensitive"  # per run: what find_sensitive found per picture, so a redact after it doesn't ask again
BLOCKS_ACROSS = 6  # pixelation blocks across a region's short side
BOX_PADDING = 0.08  # each side of a region, as a share of its size: a blur that just misses an ear is no blur


def run_document_op(session, group_id, op: str, action: dict, context: dict, *, user_id, dry_run: bool) -> dict:
    from .media import resolve_source

    src = resolve_source(session, group_id, action.get("source"), context)
    if op == "extract_text":
        return _extract_text(session, group_id, action, src, context, user_id=user_id, dry_run=dry_run)
    if op == "pages":
        return _pages(session, group_id, action, src, context, user_id=user_id, dry_run=dry_run)
    _require_picture(src)
    if op == "find_sensitive":
        if dry_run:
            return {"dry_run": True, "kind": "media", "op": op, "source": src.slug, "would_ask": "the vision model", "regions": [], "count": 0}
        regions = _sensitive(session, group_id, action, src, context, user_id=user_id)
        return {"source_id": str(src.id), "regions": regions, "count": len(regions)}
    return _redact(session, group_id, action, src, context, user_id=user_id, dry_run=dry_run)


# ── extract_text ─────────────────────────────────────────────────────────────
def _extract_text(session, group_id, action: dict, src, context: dict, *, user_id, dry_run: bool) -> dict:
    from marvin.services.ai.media import documents, transforms

    from .media import _read_bytes

    is_pdf = documents.is_pdf(src.mime_type)
    if not (is_pdf or transforms.can_transform(src.mime_type)):
        raise AutomationActionError(f"“{src.name}” ({src.mime_type or 'unknown type'}) isn't a PDF or a picture to read text from")
    if dry_run:  # no AI call: later steps preview against a stand-in
        return {"dry_run": True, "kind": "media", "op": "extract_text", "source": src.slug, "text": f"‹the text of {src.name}›", "pages": []}
    data = _read_bytes(session, group_id, src)
    ocr = (action.get("ocr") or "auto") == "auto"
    if not is_pdf:
        text = _read_picture(session, group_id, src, data, src.mime_type, user_id=user_id, required=True)
        return _text_output(src, [{"page": 1, "text": text, "method": "vision"}], page_count=1)
    try:
        texts = documents.page_texts(data)
        total = documents.page_count(data)
    except documents.NotADocument as e:
        raise AutomationActionError(f"“{src.name}”: {e}") from e
    pages = [{"page": i + 1, "text": text, "method": "pdf"} for i, text in enumerate(texts)]
    scanned = [p for p in pages if documents.needs_reading(p["text"])]
    note = None
    if scanned and ocr:
        for p in scanned[:MAX_OCR_PAGES]:
            image = documents.render_page(data, p["page"], width=OCR_PAGE_WIDTH)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            read = _read_picture(session, group_id, src, buf.getvalue(), "image/png", user_id=user_id, required=False)
            if read is None:
                note = "some pages are scanned and no AI model that can see images is available to read them"
                break
            p.update(text=read, method="vision")
        if len(scanned) > MAX_OCR_PAGES:
            note = f"only the first {MAX_OCR_PAGES} scanned pages were read"
    elif scanned:
        note = "scanned pages weren't read (ocr: never)"
    return _text_output(src, pages, page_count=total, note=note)


def _read_picture(session, group_id, src, data: bytes, mime_type: str | None, *, user_id, required: bool) -> str | None:
    """The text in a picture, by the vision model (one logged AI call); None (or a failed step when required) without one."""
    from marvin.services.ai.media import capability

    from .media import log_vision_call, now, vision_handler

    handler, why_not = vision_handler(session, group_id, capability.KIND_READ_TEXT)
    if handler is None:
        if required:
            raise AutomationActionError(f"reading text from a picture needs an AI model that can see images ({why_not})")
        return None
    started = now()
    result = handler.invoke({"image_bytes": data, "mime_type": mime_type or "image/png"}) or {}
    if (usage := getattr(handler, "last_usage", None)) is not None:
        log_vision_call(
            session, group_id, handler, src, {"chars": len(result.get("text") or "")}, usage, started, user_id=user_id, operation=READ_OPERATION
        )
    return str(result.get("text") or "")


def _text_output(src, pages: list[dict], *, page_count: int, note: str | None = None) -> dict:
    joined = "\n\n".join(f"[page {p['page']}]\n{p['text']}" for p in pages if p["text"])
    out = {
        "source_id": str(src.id),
        "page_count": page_count,
        "text": joined[:TEXT_CHARS] + ("…" if len(joined) > TEXT_CHARS else ""),
        "pages": [{**p, "text": p["text"][:PAGE_TEXT_CHARS]} for p in pages[:PAGES_LISTED]],
        "read_with_ai": sum(p["method"] == "vision" for p in pages),
    }
    if len(pages) < page_count:
        note = (note + "; " if note else "") + f"only the first {len(pages)} of {page_count} pages were read"
    return {**out, **({"note": note} if note else {})}


# ── pages ────────────────────────────────────────────────────────────────────
def _pages(session, group_id, action: dict, src, context: dict, *, user_id, dry_run: bool) -> dict:
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media import documents

    from .media import _attach_role, _deliver, _read_bytes, derivative_slug, subject_entry_id

    if not documents.is_pdf(src.mime_type):
        raise AutomationActionError(f"“{src.name}” isn't a PDF (pages saves a PDF's pages as pictures)")
    first, count = int(action.get("page") or 1), int(action.get("count") or 1)
    args = {
        "width": int(action.get("width") or DEFAULT_PAGE_WIDTH),
        "format": action.get("format") or DEFAULT_PAGE_FORMAT,
        "quality": action.get("quality"),
    }
    attach_as = _attach_role(action, context)
    entry_id = subject_entry_id(context) if attach_as else None
    if attach_as and entry_id is None:
        raise AutomationActionError("attach_as needs an entry: run this workflow on an entry (an entry event or an entry target)")
    wanted = [(page, derivative_slug(src, "page", {**args, "page": page})) for page in range(first, first + count)]
    existing = {a.slug: a for a in session.query(Assets).filter(Assets.group_id == group_id, Assets.slug.in_([s for _, s in wanted]))}
    if dry_run:
        made = [{"page": p, ("would_reuse" if slug in existing else "would_create"): slug} for p, slug in wanted]
        return {"dry_run": True, "kind": "media", "op": "pages", "source": src.slug, "pages": made, **({"attach_as": attach_as} if attach_as else {})}
    data = _read_bytes(session, group_id, src) if len(existing) < len(wanted) else b""
    total = documents.page_count(data) if data else None
    outputs = []
    for page, slug in wanted:
        if total is not None and page > total:
            if page == first:
                raise AutomationActionError(f"“{src.name}” has {total} page{'s' if total != 1 else ''}, not a page {page}")
            break  # fewer pages than asked: the ones there are
        asset, reused = existing.get(slug), slug in existing
        if asset is None:
            asset = _store_page(session, group_id, src, data, page, args, slug, context, user_id=user_id)
        elif asset.trashed_at is not None:
            raise AutomationActionError(
                f"page {page} of “{src.name}” was made before and is in the Trash ({slug}): restore it, or delete it to make it again"
            )
        out = _deliver(
            session,
            group_id,
            {"page": page},
            asset,
            reused,
            context,
            tags=action.get("tags"),
            attach_as=attach_as,
            entry_id=entry_id,
            user_id=user_id,
        )
        outputs.append(out)
    return {
        "source_id": str(src.id),
        "page_count": total,
        "asset": outputs[0]["asset"],
        "assets": [{"page": o["page"], **o["asset"]} for o in outputs],
        "reused": all(o["reused"] for o in outputs),
    }


def _store_page(session, group_id, src, data: bytes, page: int, args: dict, slug: str, context: dict, *, user_id):
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media import documents, ops
    from marvin.services.assets.asset_storage_service import AssetRejected

    from .media import _canonical, _storage, run_lineage

    try:
        image = documents.render_page(data, page, width=args["width"])
        encoded = ops._encode(image, args["format"], args.get("quality"))
    except documents.NotADocument as e:
        raise AutomationActionError(f"“{src.name}”: {e}") from e
    try:
        read = _storage(session, group_id).create_derivative(
            source=src,
            data=encoded,
            group_id=group_id,
            derivation=f"media:page:{_canonical({**args, 'page': page})}",
            slug=slug,
            name=f"{src.name or src.filename} (page {page})",
            user_id=user_id,
            extra_metadata={"media_op": "pages", "page": page, **run_lineage(context)},
            extension=ops.FORMATS[args["format"]][2],
        )
    except AssetRejected as e:
        raise AutomationActionError(f"page {page} of “{src.name}” can't be kept: {e}") from e
    return session.get(Assets, read.id)


# ── find_sensitive / redact ──────────────────────────────────────────────────
def _require_picture(src) -> None:
    from marvin.services.ai.media import transforms

    if not transforms.can_transform(src.mime_type):
        raise AutomationActionError(f"“{src.name}” ({src.mime_type or 'unknown type'}) is not an image Marvin can process (jpeg, png or webp)")


def _sensitive(session, group_id, action: dict, src, context: dict, *, user_id) -> list[dict]:
    """The regions to blur in a picture, of the kinds `find` asks for (default all) — asked once per picture per run."""
    from marvin.services.ai.media import capability

    from .media import _read_bytes, log_vision_call, now, vision_handler

    known = context.setdefault(SENSITIVE, {})
    if str(src.id) not in known:
        handler, why_not = vision_handler(session, group_id, capability.KIND_DETECT_SENSITIVE)
        if handler is None:
            raise AutomationActionError(f"finding what to blur needs an AI model that can see images ({why_not})")
        data = _read_bytes(session, group_id, src)
        started = now()
        result = handler.invoke({"image_bytes": data, "mime_type": src.mime_type}) or {}
        regions = list(result.get("regions") or [])
        if (usage := getattr(handler, "last_usage", None)) is not None:
            log_vision_call(session, group_id, handler, src, {"regions": regions}, usage, started, user_id=user_id, operation=SENSITIVE_OPERATION)
        known[str(src.id)] = regions
    kinds = set(action.get("find") or capability.SENSITIVE_KINDS)
    return [r for r in known[str(src.id)] if r.get("kind") in kinds]


def _boxes(given) -> list[list[float]]:
    """`boxes` as given: regions [{box}] (find_sensitive's output) or bare [x, y, w, h] lists, normalized 0..1."""
    from marvin.services.ai.media.capability import _normalize_box

    items = given if isinstance(given, list) else []
    boxes = [_normalize_box(item.get("box") if isinstance(item, dict) else item) for item in items]
    return [b for b in boxes if b]


def _redact(session, group_id, action: dict, src, context: dict, *, user_id, dry_run: bool) -> dict:
    from marvin.db.models.platform.assets import Assets

    from .media import _attach_role, _deliver, _read_bytes, derivative_slug, subject_entry_id

    attach_as = _attach_role(action, context)
    entry_id = subject_entry_id(context) if attach_as else None
    if attach_as and entry_id is None:
        raise AutomationActionError("attach_as needs an entry: run this workflow on an entry (an entry event or an entry target)")
    given = interpolate(action.get("boxes"), context) if action.get("boxes") is not None else None
    if given is None and dry_run:
        return {"dry_run": True, "kind": "media", "op": "redact", "source": src.slug, "would_ask": "the vision model what to blur"}
    boxes = _boxes(given) if given is not None else [r["box"] for r in _sensitive(session, group_id, action, src, context, user_id=user_id)]
    if not boxes:
        return {"source_id": str(src.id), "count": 0, "regions": []}
    args = {
        "boxes": hashlib.sha256(json.dumps([[round(v, 4) for v in b] for b in boxes]).encode()).hexdigest()[:12],
        "format": action.get("format"),
        "quality": action.get("quality"),
    }
    slug = derivative_slug(src, "redact", args)
    existing = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == slug).first()
    if dry_run:
        return {
            "dry_run": True,
            "kind": "media",
            "op": "redact",
            "source": src.slug,
            "count": len(boxes),
            ("would_reuse" if existing else "would_create"): slug,
        }
    if existing is not None and existing.trashed_at is not None:
        raise AutomationActionError(
            f"this blurred copy of “{src.name}” was made before and is in the Trash ({slug}): restore it, or delete it to make it again"
        )
    asset, reused = existing, existing is not None
    if asset is None:
        asset = _store_redacted(session, group_id, src, _read_bytes(session, group_id, src), boxes, args, slug, context, user_id=user_id)
    out = {"source_id": str(src.id), "count": len(boxes), "regions": [{"box": b} for b in boxes]}
    return _deliver(session, group_id, out, asset, reused, context, tags=action.get("tags"), attach_as=attach_as, entry_id=entry_id, user_id=user_id)


def pixelate(data: bytes, boxes: list[list[float]], fmt: str | None = None, quality=None) -> bytes:
    """The picture with each box (padded a little) pixelated into large blocks, then softened — no detail survives."""
    from PIL import Image, ImageFilter

    from marvin.services.ai.media import ops, transforms

    fmt = fmt or ops.format_of(data)
    img = transforms._load(data)[0].convert("RGB")
    width, height = img.size
    for x, y, w, h in boxes:
        pad_x, pad_y = w * BOX_PADDING, h * BOX_PADDING
        left, top = max(0, int((x - pad_x) * width)), max(0, int((y - pad_y) * height))
        right, bottom = min(width, int((x + w + pad_x) * width + 0.5)), min(height, int((y + h + pad_y) * height + 0.5))
        if right - left < 2 or bottom - top < 2:
            continue
        region = img.crop((left, top, right, bottom))
        block = max(8, min(region.size) // BLOCKS_ACROSS)  # a face or a plate is a handful of blocks across: unreadable
        tiny = region.resize((max(1, region.width // block), max(1, region.height // block)), Image.Resampling.BILINEAR)
        coarse = tiny.resize(region.size, Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(radius=block // 3))
        img.paste(coarse, (left, top))
    return ops._encode(img, fmt, quality)


def _store_redacted(session, group_id, src, data: bytes, boxes, args: dict, slug: str, context: dict, *, user_id):
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media import ops
    from marvin.services.assets.asset_storage_service import AssetRejected

    from .media import _canonical, _storage, run_lineage

    try:
        produced = pixelate(data, boxes, args.get("format"), args.get("quality"))
    except ops.NotAnImage as e:
        raise AutomationActionError(f"“{src.name}”: {e}") from e
    try:
        read = _storage(session, group_id).create_derivative(
            source=src,
            data=produced,
            group_id=group_id,
            derivation=f"media:redact:{_canonical(args)}",
            slug=slug,
            name=f"{src.name or src.filename} (blurred)",
            user_id=user_id,
            extra_metadata={"media_op": "redact", "regions": len(boxes), **run_lineage(context)},
            extension=ops.FORMATS[ops.format_of(produced)][2],
        )
    except AssetRejected as e:
        raise AutomationActionError(f"the blurred copy of “{src.name}” can't be kept: {e}") from e
    return session.get(Assets, read.id)
