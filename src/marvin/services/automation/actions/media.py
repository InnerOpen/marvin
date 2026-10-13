"""`media` step — make an image from an image, or read facts from one. Pillow, local, free; no provider.

`{"kind": "media", "id": "square", "op": "crop", "source": "${asset.id}", "aspect": "1:1", "focus": "subject",
"attach_as": "square"}`

* **source** — an asset id or slug; default the run's asset (`${asset.id}`). `${steps.<id>.output.asset.id}` chains
  from an earlier step; `role:<role>` takes the run's entry's asset in that role (`role:hero`).
* **ops** — `resize` (width/height, fit inside|cover, never upscales), `crop` (aspect, focus center|subject),
  `convert` (format), `grade` (a preset) each make a NEW asset; `format` / `quality` re-encode any of them.
  `inspect` (size, orientation, aspect, sharpness, type, bytes) and `palette` (main colours) only read.
* **originals are never modified.** A new asset carries its lineage in metadata (`derived_from`, `derivation`, the
  workflow, step and correlation id) and is named after its source, op and arguments (`<src>--<op>-<hash8>`), so the
  same derivation of the same picture is made once: a retry or a re-run reuses it (`reused: true`).
* **attach_as** links the new asset to the run's entry in that role (EntryService: `asset_attached_to_entry`).
* A derivative sends no `asset_uploaded`, so an "image added → resize" workflow can't trigger itself; conditions read
  `asset.derived_from` to tell a derivative from an original.

Integration steps whose action returns images (an `image.*` capability) keep them the same way — see
:func:`keep_generated_images`, called by the integration executor before the output reaches the run.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid

from marvin.schemas.group.automation_definition import MEDIA_OP_ARGS

from ..matcher import interpolate
from .base import AutomationActionError, register_action

DERIVE_OPS = ("resize", "crop", "convert", "grade")
READ_OPS = ("inspect", "palette")
RENDER = "render"  # a template filled with fields and pictures, screenshotted (services/ai/media/render.py)
# PDFs, OCR, privacy blur, ZIP and watermarks (media_documents.py)
DOC_OPS = ("extract_text", "pages", "find_sensitive", "redact", "zip", "watermark")
OPS = (*DERIVE_OPS, *READ_OPS, RENDER, *DOC_OPS)
# What each op takes beside source / attach_as / id / when: format and quality re-encode anything an op makes.
OP_ARGS = MEDIA_OP_ARGS
DEFAULT_SOURCE = "${asset.id}"
ROLE_PREFIX = "role:"
ASPECT = re.compile(r"^\s*([1-9]\d{0,2})\s*[:x/]\s*([1-9]\d{0,2})\s*$")
DEFAULT_PALETTE_COLORS = 5
SLUG_SOURCE_CHARS = 120  # the source's slug inside a derivative's, so the whole stays well under 200
PROMPT_KEPT_CHARS = 2000  # a generated image's prompt, as its lineage keeps it
DETECT_OPERATION = "detect-subject"  # the AI execution log's name for a subject-focus crop's vision call
# Where a run keeps what subject detection found per source asset (its box, or None: no subject), so a run's square,
# portrait and landscape crops of one picture make one vision call between them, not three.
SUBJECTS = "_media_subjects"


def parse_aspect(value) -> tuple[int, int] | None:
    """``"4:5"`` / ``"4x5"`` / ``"4/5"`` → (4, 5); None when it isn't one."""
    m = ASPECT.match(str(value or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


@register_action("media")
def run_media_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services.ai.media import transforms

    from ..authz import ENTRY_ACTION_MIN_ROLE, ROLE_OWNER, require_role

    op = action.get("op")
    if op not in OPS:
        raise AutomationActionError(f"unknown media op '{op}' (expected: {', '.join(OPS)})")
    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, ENTRY_ACTION_MIN_ROLE, f"media step '{op}'")
    if op == RENDER:
        return _render(session, group_id, action, context, user_id=user_id, dry_run=dry_run)
    if op in DOC_OPS:
        from .media_documents import run_document_op

        return run_document_op(session, group_id, op, action, context, user_id=user_id, dry_run=dry_run)
    src = resolve_source(session, group_id, action.get("source"), context)
    if not transforms.can_transform(src.mime_type):
        raise AutomationActionError(f"“{src.name}” ({src.mime_type or 'unknown type'}) is not an image Marvin can process (jpeg, png or webp)")

    if op in READ_OPS:
        return _read(session, group_id, op, action, src)
    args = derive_args(session, group_id, op, action, context)
    attach_as = _attach_role(action, context)
    entry_id = attach_target(session, group_id, action, context, attach_as, dry_run=dry_run)
    return _derive(
        session,
        group_id,
        op,
        args,
        src,
        context,
        user_id=user_id,
        attach_as=attach_as,
        entry_id=entry_id,
        dry_run=dry_run,
        action_tags=action.get("tags"),
    )


# ── Reading the source ───────────────────────────────────────────────────────
def resolve_source(session, group_id, ref, context: dict):
    """The asset a step works on: an id or slug (templates allowed; default the run's asset), the URL it is served at
    (`${entry.image}`, `${asset.url}`), or `role:<role>` — the run's entry's asset in that role, first by position. Not
    one in the Trash."""
    from marvin.db.models.platform.assets import Assets

    raw = interpolate(ref or DEFAULT_SOURCE, context)
    value = str(raw).strip() if raw not in (None, "") else ""
    if not value:
        raise AutomationActionError(
            "no image to work on — set source (an asset id or slug, ${steps.<id>.output.asset.id}, or role:<role>), or run it on an asset"
        )
    if value.startswith(ROLE_PREFIX):
        row = _asset_in_role(session, group_id, value[len(ROLE_PREFIX) :].strip(), context)
    elif "://" in value or value.startswith("/"):
        row = _asset_by_url(session, group_id, value)
    else:
        row = None
        try:
            row = session.get(Assets, uuid.UUID(value))
        except ValueError:
            row = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == value).first()
        if row is None or row.group_id != group_id:
            raise AutomationActionError(f"no asset “{value}” in this workspace")
    if row.trashed_at is not None:
        raise AutomationActionError(f"“{row.name}” is in the Trash")
    return row


def _asset_by_url(session, group_id, url: str):
    """One of this workspace's assets by the URL it is served at — what `${entry.image}` and `${asset.url}` give. The
    URL ends in the asset's storage key (behind the storage's public domain, or the local `/assets/` path); any other
    URL is refused: a media step works on the workspace's own files and never fetches the web."""
    from urllib.parse import urlparse

    from marvin.db.models.platform.assets import Assets

    parts = [p for p in urlparse(url).path.split("/") if p]
    keys = ["/".join(parts[i:]) for i in range(len(parts))]  # the key, behind however many path prefixes
    rows = session.query(Assets).filter(Assets.group_id == group_id, (Assets.public_url == url) | Assets.storage_key.in_(keys or [""])).all()
    if not rows:
        raise AutomationActionError(
            f"“{url}” isn't one of this workspace's assets — a media step only works on the workspace's own files "
            "(an asset id or slug, ${entry.image}, ${asset.url}, ${steps.<id>.output.asset.id} or role:<role>)"
        )

    def closeness(row) -> tuple:  # its own public URL first, then the longest key the URL ends in
        return (row.public_url != url, keys.index(row.storage_key) if row.storage_key in keys else len(keys))

    return min(rows, key=closeness)


def _asset_in_role(session, group_id, role: str, context: dict):
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets

    entry_id = subject_entry_id(context)
    if entry_id is None:
        raise AutomationActionError(f"source role:{role} needs an entry: run this workflow on an entry")
    links = (
        session.query(EntryAssets)
        .join(Assets, Assets.id == EntryAssets.asset_id)
        .filter(EntryAssets.entry_id == entry_id, EntryAssets.role == role, Assets.group_id == group_id, Assets.trashed_at.is_(None))
        .order_by(EntryAssets.position)
        .all()
    )
    link = next((ea for ea in links if not (ea.metadata_json or {}).get("suggested")), None)  # not a pending AI suggestion
    if link is None:
        raise AutomationActionError(f"the entry has no asset in the role “{role}”")
    return session.get(Assets, link.asset_id)


def attach_target(session, group_id, action: dict, context: dict, attach_as, *, dry_run: bool = False) -> uuid.UUID | None:
    """The entry a made asset is linked to in role ``attach_as``: ``attach_to`` (an entry id or slug — e.g. one this
    run created, ${steps.draft.output.entry_id}), else the run's entry. None when nothing is attached, or in a dry
    run naming an entry an earlier step only previewed."""
    if not attach_as:
        return None
    named = interpolate(action.get("attach_to"), context)
    if named in (None, ""):
        entry_id = subject_entry_id(context)
        if entry_id is None:
            raise AutomationActionError(
                "attach_as needs an entry: run this workflow on an entry (an entry event or an entry target), or name one with attach_to"
            )
        return entry_id
    entry_id = _entry_named(session, group_id, str(named))
    if entry_id is None and not dry_run:
        raise AutomationActionError(f"attach_to: no entry “{named}” in this workspace")
    return entry_id


def _entry_named(session, group_id, ref: str) -> uuid.UUID | None:
    from marvin.db.models.platform.entries import Entries

    q = session.query(Entries.id).filter(Entries.group_id == group_id)
    try:
        row = q.filter(Entries.id == uuid.UUID(ref)).first()
    except ValueError:
        row = q.filter(Entries.slug == ref).first()
    return row[0] if row else None


def subject_entry_id(context: dict) -> uuid.UUID | None:
    """The entry the run acts on (an entry event's, or each entry-target match), if any."""
    raw = (context.get("entry") or {}).get("id") or (context.get("event") or {}).get("entry_id")
    try:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _read_bytes(session, group_id, src) -> bytes:
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.provider_factory import get_storage_provider

    try:
        return AssetStorageService(get_repositories(session, group_id=group_id), get_storage_provider()).read_bytes(src)
    except Exception as e:  # noqa: BLE001 — a missing file is the step's failure, said plainly
        raise AutomationActionError(f"could not read “{src.name}”: {e}") from e


def _read(session, group_id, op: str, action: dict, src) -> dict:
    """`inspect` / `palette`: facts about the picture, nothing written (so a dry run runs them too)."""
    from marvin.services.ai.media import ops

    data = _read_bytes(session, group_id, src)
    try:
        if op == "inspect":
            return {"source_id": str(src.id), **ops.inspect(data)}
        return {"source_id": str(src.id), "colors": ops.palette(data, int(action.get("colors") or DEFAULT_PALETTE_COLORS))}
    except ops.NotAnImage as e:
        raise AutomationActionError(f"“{src.name}”: {e}") from e


# ── Making a derivative ──────────────────────────────────────────────────────
def derive_args(session, group_id, op: str, action: dict, context: dict) -> dict:
    """The op's arguments, checked and in canonical form (what the derivative's name and lineage are made from)."""
    from marvin.services.ai.media import ops

    args = {k: action[k] for k in OP_ARGS[op] if action.get(k) not in (None, "")}
    for key in ("width", "height", "quality", "colors"):  # the editor may store numbers as text
        if key in args:
            try:
                args[key] = int(args[key])
            except (TypeError, ValueError) as e:
                raise AutomationActionError(f"{key} must be a whole number") from e
    if args.get("format") is not None and args["format"] not in ops.FORMATS:
        raise AutomationActionError(f"format must be one of {', '.join(ops.FORMATS)}")
    if op == "resize":
        if not (args.get("width") or args.get("height")):
            raise AutomationActionError("resize needs a width or a height")
        args["fit"] = args.get("fit") or "inside"
        if args["fit"] == "cover" and not (args.get("width") and args.get("height")):
            raise AutomationActionError("fit cover needs both a width and a height")
    elif op == "crop":
        aspect = parse_aspect(args.get("aspect"))
        if aspect is None:
            raise AutomationActionError("crop needs an aspect like 1:1, 4:5 or 16:9")
        args["aspect"] = f"{aspect[0]}:{aspect[1]}"  # 4x5 and 4:5 are one derivative
        args["focus"] = args.get("focus") or "center"
    elif op == "convert" and not args.get("format"):
        raise AutomationActionError("convert needs a format (jpeg, png or webp)")
    elif op == "grade":
        preset = str(interpolate(args.get("preset") or "", context) or "").strip()
        if not preset:
            raise AutomationActionError("grade needs a preset")
        from marvin.services.ai.media.enrichment import grade_presets

        if preset not in grade_presets(session, group_id):
            raise AutomationActionError(f"no grade preset “{preset}” (presets: {', '.join(sorted(grade_presets(session, group_id)))})")
        args["preset"] = preset
    return args


def _attach_role(action: dict, context: dict) -> str | None:
    if not action.get("attach_as"):
        return None
    role = interpolate(action["attach_as"], context)
    return str(role).strip() if role not in (None, "") and str(role).strip() else None


def derivative_slug(src, op: str, args: dict) -> str:
    """`<source slug>--<op>-<hash8>`: the same op with the same arguments on the same picture names the same asset."""
    canon = _canonical(args)
    digest = hashlib.sha256(f"{op}|{canon}|{src.checksum or src.id}".encode()).hexdigest()[:8]
    return f"{src.slug[:SLUG_SOURCE_CHARS]}--{op}-{digest}"


def _canonical(args: dict) -> str:
    return ",".join(f"{k}={args[k]}" for k in sorted(args) if args[k] is not None)


def _derive(session, group_id, op: str, args: dict, src, context: dict, *, user_id, attach_as, entry_id, dry_run: bool, action_tags=None) -> dict:
    from marvin.db.models.platform.assets import Assets

    if op == "crop" and args["focus"] == "subject":
        known = context.get(SUBJECTS) or {}
        if str(src.id) in known and known[str(src.id)] is None:  # an earlier step found no subject in this picture
            detector, why_not = None, "no subject found; cropped from the centre"
        else:
            detector, why_not = _subject_detector(session, group_id)
        planned = {**args, "focus": "subject" if detector else "center"}
    else:
        detector, why_not, planned = None, None, args
    slug = derivative_slug(src, op, planned)
    existing = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == slug).first()
    if dry_run:
        plan = {"dry_run": True, "kind": "media", "op": op, "source": src.slug, "args": planned}
        return {**plan, ("would_reuse" if existing else "would_create"): slug, **({"attach_as": attach_as} if attach_as else {})}
    out: dict = {"source_id": str(src.id)}
    produced = b""
    if op == "crop":
        out["focus_used"] = planned["focus"]
        if why_not and args["focus"] == "subject":
            out["focus_note"] = why_not
    if existing is None:
        data = _read_bytes(session, group_id, src)
        produced, box = _produce(session, group_id, op, args, src, data, detector, context, user_id=user_id)
        if op == "crop" and planned["focus"] == "subject" and box is None:  # the model found no subject: centre it
            out.update(focus_used="center", focus_note="no subject found; cropped from the centre")
            planned = {**args, "focus": "center"}
            slug = derivative_slug(src, op, planned)
            existing = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == slug).first()
    if existing is not None:
        if existing.trashed_at is not None:
            raise AutomationActionError(
                f"this {op} of “{src.name}” was made before and is in the Trash ({slug}): restore it, or delete it to make it again"
            )
        asset, reused = existing, True
    else:
        asset, reused = _store(session, group_id, op, planned, src, produced, slug, context, user_id=user_id), False
    return _deliver(session, group_id, out, asset, reused, context, tags=action_tags, attach_as=attach_as, entry_id=entry_id, user_id=user_id)


def _deliver(session, group_id, out: dict, asset, reused: bool, context: dict, *, tags, attach_as, entry_id, user_id) -> dict:
    """A made (or reused) asset as the step's output: tagged and attached as the step says."""
    out.update(asset=asset_ref(asset), reused=reused)
    if names := tag_names(tags, context):
        out["tags"] = tag_asset(session, group_id, asset, names)
    if attach_as:
        out["attached"] = attach(session, group_id, entry_id, asset, attach_as, context, user_id=user_id)
    return out


def _produce(session, group_id, op: str, args: dict, src, data: bytes, detector, context: dict, *, user_id) -> tuple[bytes, list | None]:
    """The new image's bytes (and the subject box a subject crop used, None when it centred)."""
    from marvin.services.ai.media import ops, transforms

    fmt, quality = args.get("format"), args.get("quality")
    box = None
    try:
        if op == "resize":
            produced = ops.resize(data, width=args.get("width"), height=args.get("height"), fit=args["fit"], fmt=fmt, quality=quality)
        elif op == "convert":
            produced = ops.convert(data, fmt, quality=quality)
        elif op == "crop":
            focus = (0.5, 0.5)
            if detector is not None:
                known = context.setdefault(SUBJECTS, {})
                if str(src.id) not in known:
                    known[str(src.id)] = _detect_subject(session, group_id, detector, src, data, user_id=user_id)
                box = known[str(src.id)]
                if box:
                    focus = (box[0] + box[2] / 2, box[1] + box[3] / 2)
            produced = ops.reencode(transforms.crop_to_aspect(data, parse_aspect(args["aspect"]), focus=focus), fmt, quality)
        else:  # grade
            from marvin.services.ai.media.enrichment import grade_presets

            graded = transforms.color_grade_params(data, grade_presets(session, group_id)[args["preset"]])
            if graded is None:
                raise AutomationActionError(f"grade preset “{args['preset']}” has no settings")
            produced = ops.reencode(graded, fmt, quality)
    except ops.NotAnImage as e:
        raise AutomationActionError(f"“{src.name}”: {e}") from e
    except AutomationActionError:
        raise
    except Exception as e:  # noqa: BLE001 — a corrupt or exotic file fails the step with the reason
        raise AutomationActionError(f"could not {op} “{src.name}”: {e}") from e
    return produced, box


def _store(session, group_id, op: str, args: dict, src, data: bytes, slug: str, context: dict, *, user_id):
    """Keep the new image as an asset with its lineage; the source is left as it was."""
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media import ops
    from marvin.services.assets.asset_storage_service import AssetRejected

    fmt = ops.format_of(data)
    name = f"{src.name or src.filename} ({_describe(op, args)})"
    lineage = {"derivation": f"media:{op}:{_canonical(args)}", "media_op": op, **run_lineage(context)}
    try:
        read = _storage(session, group_id).create_derivative(
            source=src,
            data=data,
            group_id=group_id,
            derivation=lineage.pop("derivation"),
            slug=slug,
            name=name,
            user_id=user_id,
            extra_metadata=lineage,
            extension=ops.FORMATS[fmt][2],
        )
    except AssetRejected as e:
        raise AutomationActionError(f"the {op} of “{src.name}” can't be kept: {e}") from e
    return session.get(Assets, read.id)


def _describe(op: str, args: dict) -> str:
    """A derivative's name tag: "resize 800×600", "crop 1:1", "webp", "grade warm" (+ its format when it changes one)."""
    if op == "resize":
        what = f"resize {args.get('width') or 'auto'}×{args.get('height') or 'auto'}"
    elif op == "crop":
        what = f"crop {args['aspect']}" + (" subject" if args.get("focus") == "subject" else "")
    elif op == "grade":
        what = f"grade {args['preset']}"
    else:
        return str(args["format"])
    return f"{what} {args['format']}" if args.get("format") else what


def _storage(session, group_id):
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.provider_factory import get_storage_provider

    return AssetStorageService(get_repositories(session, group_id=group_id), get_storage_provider())


def asset_ref(row) -> dict:
    """An asset as a step output carries it — small, so a run's snapshot never holds image data."""
    from marvin.services.storage.provider_factory import asset_public_url

    try:
        url = asset_public_url(row)
    except Exception:  # noqa: BLE001 — a URL that can't be built never fails the step
        url = None
    return {"id": str(row.id), "slug": row.slug, "name": row.name, "url": url, "width": row.width, "height": row.height, "mime_type": row.mime_type}


def uploader(session, context: dict, user_id):
    """Who a made-from-nothing image is uploaded by: the run's user, else the workflow's author, else the creator of
    the entry it was made for."""
    owner = user_id or (context.get("_step") or {}).get("author_id")
    if owner is None and (entry_id := subject_entry_id(context)) is not None:
        from marvin.db.models.platform.entries import Entries

        entry = session.get(Entries, entry_id)
        owner = getattr(entry, "created_by", None) if entry is not None else None
    return owner


def run_lineage(context: dict) -> dict:
    """Which run made an asset: the workflow, the step and the event's correlation id."""
    from marvin.services.event_bus_service.correlation import current_correlation_id

    step = context.get("_step") or {}
    found = {
        "workflow_id": step.get("workflow"),
        "workflow_slug": step.get("workflow_slug"),
        "step": step.get("step_id") or (step.get("index") if step.get("index") is not None else None),
        "correlation_id": (context.get("event") or {}).get("correlation_id") or current_correlation_id.get(),
    }
    return {k: v for k, v in found.items() if v not in (None, "")}


def tag_names(raw, context: dict) -> list[str]:
    """A step's `tags` (templates allowed), blanks dropped."""
    values = interpolate(raw or [], context)
    values = values if isinstance(values, list) else [values]
    return [str(v).strip() for v in values if v not in (None, "") and str(v).strip()]


def tag_asset(session, group_id, asset, tags: list[str]) -> list[str]:
    """Put these tags on an asset (find-or-create by slug, added to what it has) and re-sync its smart collections."""
    from marvin.repos.all_repositories import get_repositories

    repo = get_repositories(session, group_id=group_id).assets
    repo.apply_fields(asset.id, {"tags": tags})
    repo._resync_membership(asset.id)
    session.refresh(asset)
    return sorted(t.slug for t in asset.tags)


def attach(session, group_id, entry_id, asset, role: str, context: dict, *, user_id) -> str:
    """Link the asset to the run's entry in ``role`` (once): "attached" (sends asset_attached_to_entry) or "exists"."""
    from marvin.services.entries import EntryService

    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    result = svc.attach_asset(entry_id, asset.id, role=role, reaction_depth=int(context.get("depth", 0)) + 1)
    if result is None:
        raise AutomationActionError(f"could not attach “{asset.name}”: the entry is not in this workspace")
    return result


# ── Rendering a template ─────────────────────────────────────────────────────
def _render(session, group_id, action: dict, context: dict, *, user_id, dry_run: bool) -> dict:
    """`render`: a built-in template (or the step's own `html`) filled with `fields` (text, templates allowed) and
    `images` (each a source: an asset id/slug, ${steps.<id>.output.asset.id}, role:<role>), screenshotted at
    width × height into a new asset. Its first picture is the asset it was made from; the same template, text and
    pictures make the same asset once."""
    from marvin.services.ai.media import render

    template, html = action.get("template"), action.get("html")
    if bool(template) == bool(html):
        raise AutomationActionError("render needs a template (a built-in one) or its own html — one of them")
    manifest = render.templates().get(template) if template else {}
    if template and not manifest:
        raise AutomationActionError(f"no render template “{template}” (templates: {', '.join(sorted(render.templates()))})")
    width = int(action.get("width") or manifest.get("width") or render.DEFAULT_SIZE[0])
    height = int(action.get("height") or manifest.get("height") or render.DEFAULT_SIZE[1])
    fields = _render_fields(action, context, manifest)
    pictures = _render_pictures(session, group_id, action, context, manifest)
    source_html = render.template_html(template) if template else str(html)
    fmt, quality = action.get("format"), action.get("quality")
    if fmt is None and manifest.get("paged"):
        fmt = "pdf"  # a printable template is a PDF unless the step asks for a picture of its first page
    primary = _unwrap(next(iter(_flat(pictures)), None))
    attach_as = _attach_role(action, context)
    entry_id = attach_target(session, group_id, action, context, attach_as, dry_run=dry_run)
    slug = _render_slug(template or "custom", source_html, fields, pictures, (width, height, fmt, quality), primary)
    existing = _by_slug(session, group_id, slug)
    if dry_run:
        try:  # fill it in (a missing field shows now), but don't start a browser
            slots = dict.fromkeys(manifest.get("images") or {})
            slots |= {k: [{"src": "data:,", "label": r.label} for r in v] if isinstance(v, list) else "data:," for k, v in pictures.items()}
            render.fill(source_html, fields=fields, images=slots, width=width, height=height, paged=fmt == "pdf")
        except render.RenderError as e:
            raise AutomationActionError(str(e)) from e
        plan = {"dry_run": True, "kind": "media", "op": RENDER, "template": template or "custom", "size": f"{width}×{height}"}
        return {**plan, ("would_reuse" if existing else "would_create"): slug, **({"attach_as": attach_as} if attach_as else {})}
    if existing is not None and existing.trashed_at is not None:
        raise AutomationActionError(f"this render was made before and is in the Trash ({slug}): restore it, or delete it to make it again")
    if existing is None:
        existing = _store_render(
            session, group_id, template, source_html, fields, pictures, (width, height), (fmt, quality), slug, context, user_id=user_id
        )
        reused = False
    else:
        reused = True
    out = {"template": template or "custom", "sources": _ids(pictures)}
    return _deliver(
        session, group_id, out, existing, reused, context, tags=action.get("tags"), attach_as=attach_as, entry_id=entry_id, user_id=user_id
    )


def _render_fields(action: dict, context: dict, manifest: dict) -> dict:
    """The step's text, filled in; a built-in template's own fields default to blank, a field it doesn't have fails."""
    raw = interpolate(action.get("fields") or {}, context)
    if not isinstance(raw, dict):
        raise AutomationActionError("render `fields` is an object of text values")
    fields = {str(k): "" if v is None else str(v) for k, v in raw.items()}
    known = manifest.get("fields") or {}
    if known:
        if unknown := sorted(set(fields) - set(known)):
            label = manifest.get("label")
            raise AutomationActionError(f"the {label} template has no field {', '.join(unknown)} (fields: {', '.join(known)})")
        if missing := [k for k, spec in known.items() if spec.get("required") and not fields.get(k, "").strip()]:
            raise AutomationActionError(f"the {manifest.get('label')} template needs {', '.join(missing)} (it resolved to empty)")
        fields = dict.fromkeys(known, "") | fields
    return fields


def _render_pictures(session, group_id, action: dict, context: dict, manifest: dict) -> dict:
    """name → asset row for each picture the step names (a source ref each); a required one that resolves to nothing
    fails the step, an optional one is left out."""
    refs = action.get("images") or {}
    if not isinstance(refs, dict):
        raise AutomationActionError("render `images` is an object of picture names to assets")
    known = manifest.get("images") or {}
    if known and (unknown := sorted(set(refs) - set(known))):
        label = manifest.get("label")
        raise AutomationActionError(f"the {label} template has no picture {', '.join(unknown)} (pictures: {', '.join(known)})")
    rows = {}
    for name in [*known, *(k for k in refs if k not in known)]:
        ref = refs.get(name)
        resolved = interpolate(ref, context) if ref else None
        if resolved in (None, ""):
            if (known.get(name) or {}).get("required"):
                raise AutomationActionError(f"the {manifest.get('label')} template needs the picture {name}")
            continue
        required = (known.get(name) or {}).get("required")
        if isinstance(resolved, list) or (known.get(name) or {}).get("list"):
            rows[name] = _picture_list(session, group_id, resolved if isinstance(resolved, list) else [resolved], context)
            if required and not rows[name]:
                raise AutomationActionError(f"the {manifest.get('label')} template needs at least one picture in {name}")
            continue
        try:
            row = resolve_source(session, group_id, str(resolved), context)
        except AutomationActionError:
            if required or not str(resolved).startswith(ROLE_PREFIX):
                raise
            continue  # an optional picture by role the entry doesn't have: the template does without it
        if not str(row.mime_type or "").startswith("image/"):
            raise AutomationActionError(f"“{row.name}” isn't a picture ({row.mime_type})")
        rows[name] = row
    return rows


MAX_LIST_PICTURES = 48  # a contact sheet's worth; each is inlined as a thumbnail
LIST_THUMB_SIDE = 800


def _picture_list(session, group_id, items: list, context: dict) -> list:
    """A list of pictures — a collect step's rows or asset refs — as labelled asset rows (`_Pic`), pictures only, at most
    MAX_LIST_PICTURES. An asset row is its own picture, labelled by its name; an entry row stands for its main picture
    (`image`), labelled by its title; an item with no picture is left out."""
    pics = []
    for item in items[:MAX_LIST_PICTURES]:
        if isinstance(item, dict):
            is_entry = "entry_type" in item or "title" in item
            ref, label = (item.get("image"), item.get("title")) if is_entry else (item.get("id"), item.get("name"))
        else:
            ref, label = item, None
        if ref in (None, ""):
            continue
        row = resolve_source(session, group_id, str(ref), context)
        if str(row.mime_type or "").startswith("image/"):
            pics.append(_Pic(row, label or row.name))
    return pics


class _Pic:
    """An asset row with the label a list template shows under it (an entry's title, or the asset's name)."""

    def __init__(self, row, label: str):
        self.row, self.label = row, label

    def __getattr__(self, name):
        return getattr(self.row, name)


def _unwrap(row):
    return row.row if isinstance(row, _Pic) else row


def _flat(pictures: dict) -> list:
    """Every picture a render uses, in order (a list's items in place)."""
    return [r for v in pictures.values() for r in (v if isinstance(v, list) else [v])]


def _fingerprint(row) -> str:
    return row.checksum or str(row.id)


def _ids(pictures: dict) -> dict:
    return {k: [str(r.id) for r in v] if isinstance(v, list) else str(v.id) for k, v in pictures.items()}


def _render_slug(template: str, source_html: str, fields: dict, pictures: dict, shape: tuple, primary) -> str:
    """`<first picture's slug or the template>--render-<hash8>`, from everything that changes the image."""
    from slugify import slugify

    key = json.dumps(
        {
            "html": hashlib.sha256(source_html.encode()).hexdigest(),
            "fields": fields,
            "pictures": {k: [_fingerprint(r) for r in v] if isinstance(v, list) else _fingerprint(v) for k, v in sorted(pictures.items())},
            "shape": [str(x) for x in shape],
        },
        sort_keys=True,
    )
    base = primary.slug[:SLUG_SOURCE_CHARS] if primary is not None else (slugify(f"{template} {next(iter(fields.values()), '')}") or template)[:60]
    return f"{base}--render-{hashlib.sha256(key.encode()).hexdigest()[:8]}"


def _by_slug(session, group_id, slug: str):
    from marvin.db.models.platform.assets import Assets

    return session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == slug).first()


def _thumbnail(session, group_id, row) -> str:
    from marvin.services.ai.media import ops, render

    data = _read_bytes(session, group_id, row)
    try:
        small = ops.resize(data, width=LIST_THUMB_SIDE, height=LIST_THUMB_SIDE, fmt="jpeg", quality=82)
    except ops.NotAnImage:
        return render.data_uri(data, row.mime_type)  # an svg: inline as it is
    return render.data_uri(small, "image/jpeg")


def _store_render(session, group_id, template, source_html, fields, pictures, size, encoding, slug, context, *, user_id):
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media import ops, render
    from marvin.services.assets.asset_storage_service import AssetRejected

    # Every picture the template declares is there — blank when not given — so `{% if images.x %}` works.
    images = dict.fromkeys((render.templates().get(template) or {}).get("images") or {})
    for name, value in pictures.items():
        if isinstance(value, list):  # a list template-side: [{src, label}], each a thumbnail so the page stays small
            images[name] = [{"src": _thumbnail(session, group_id, pic.row), "label": pic.label} for pic in value]
        else:
            images[name] = render.data_uri(_read_bytes(session, group_id, value), value.mime_type)
    paged = encoding[0] == "pdf"
    try:
        made = render.render(source_html, fields=fields, images=images, width=size[0], height=size[1], paged=paged)
        data = made if paged else ops.reencode(made, encoding[0], encoding[1])
    except render.RenderError as e:
        raise AutomationActionError(f"render: {e}") from e
    extension = "pdf" if paged else ops.FORMATS[ops.format_of(data)][2]
    primary = _unwrap(next(iter(_flat(pictures)), None))
    label = (render.templates().get(template) or {}).get("label") or "Custom render"
    title = next((v for v in fields.values() if v.strip()), "") if fields else ""
    lineage = {"render_template": template or "custom", "rendered_from": _ids(pictures), **run_lineage(context)}
    if primary is None:
        lineage["generated_by"] = f"render:{template or 'custom'}"
    owner = uploader(session, context, user_id)
    try:
        read = _storage(session, group_id).create_derivative(
            source=primary,
            data=data,
            group_id=group_id,
            derivation=f"render:{template or 'custom'}",
            slug=slug,
            name=f"{label}: {title[:80]}" if title else label,
            user_id=owner,
            extra_metadata=lineage,
            extension=extension,
        )
    except (AssetRejected, ValueError) as e:
        raise AutomationActionError(f"the render can't be kept: {e}") from e
    return session.get(Assets, read.id)


# ── Subject focus (a vision model, or an integration that detects subjects) ──
def _subject_detector(session, group_id):
    """The handler that finds a picture's main subject, or (None, why not) — then a subject crop centres instead."""
    from marvin.services.ai.media import capability

    handler, why_not = vision_handler(session, group_id, capability.KIND_DETECT_SUBJECT)
    return handler, None if handler else f"{why_not}; cropped from the centre"


def vision_handler(session, group_id, kind: str):
    """The handler for an image-in capability (`kind`: detect a subject, read text, find what to blur) — an integration
    that offers it, else the workspace's vision model — or (None, why not). A vision model is used only where the
    workspace lets workflows use AI, within its budget."""
    from marvin.services.ai.media import capability

    handlers = capability._integrations_providing(kind, group_id)
    if handlers:
        return handlers[0], None
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai import budget
    from marvin.services.ai.factory import get_workspace_ai_provider

    from ..runner import AUTOMATION_SOURCE, _model_sees_images, _resolve_model

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    policy = settings.invocation_sources if settings else None
    if not (settings and settings.enabled) or (isinstance(policy, dict) and policy.get(AUTOMATION_SOURCE, True) is False):
        return None, "AI is off for workflows here"
    if reason := budget.blocked_reason(session, group_id):
        return None, f"AI budget: {reason}"
    model = _resolve_model(session, group_id, settings)
    try:
        provider = get_workspace_ai_provider(session, group_id)
    except Exception:  # noqa: BLE001 — no provider is the same as no vision model
        provider = None
    if not (provider and model and _model_sees_images(session, group_id, model)):
        return None, "no AI model that can see images"
    handler = capability.resolve_capability(kind, session=session, group_id=group_id, provider=provider, model=model)
    return (handler, None) if handler else (None, "no AI model that can see images")


def _detect_subject(session, group_id, handler, src, data: bytes, *, user_id) -> list | None:
    """The subject's normalized box [x, y, w, h], or None. A vision model's call is logged and costed like any
    workflow AI call (AI usage, the monthly budget)."""
    started = now()
    result = handler.invoke({"asset_id": src.id, "image_bytes": data, "image_b64": base64.b64encode(data).decode("ascii")}) or {}
    box = result.get("box")
    usage = getattr(handler, "last_usage", None)
    if usage is not None:
        log_vision_call(session, group_id, handler, src, {"box": box}, usage, started, user_id=user_id)
    return list(box) if box else None


def log_vision_call(session, group_id, handler, src, output: dict, usage, started, *, user_id, operation: str = DETECT_OPERATION) -> None:
    """A media step's vision call in AI Executions, costed against the monthly budget like any workflow AI call."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai import budget
    from marvin.services.ai.pricing import estimate_cost

    from ..runner import AUTOMATION_SOURCE

    provider_type = getattr(handler.provider, "provider_type", None)
    prompt, completion = usage.prompt_tokens or 0, usage.completion_tokens or 0
    row = AIExecutionModel(
        session=session,
        group_id=group_id,
        operation_slug=operation,
        provider_type=provider_type,
        model_id=handler.model,
        status="completed",
        triggered_by=user_id,
        trigger_type=AUTOMATION_SOURCE,
        entity_type="asset",
        entity_id=src.id,
        input_json={},
        output_json=output,
        started_at=started,
        completed_at=now(),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=usage.total_tokens or prompt + completion,
        estimated_cost_usd=estimate_cost(provider_type, handler.model, prompt, completion),
    )
    session.add(row)
    session.commit()
    if crossing := budget.crossing_after(session, group_id, row.estimated_cost_usd):
        budget.emit_crossing(group_id, crossing, user_id=user_id, source=AUTOMATION_SOURCE)


def now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


# ── Images an integration returns ────────────────────────────────────────────
IMAGE_KEYS = ("image_b64", "url")


def returns_images(declared) -> bool:
    """Whether a provider action's output is images to keep: it declares an `image.*` capability. Other actions'
    `url` fields (a checkout link, a post) are left alone."""
    return str(getattr(declared, "capability", None) or "").startswith("image.")


def keep_generated_images(
    session, group_id, result: dict, *, generated_by: str, args: dict, context: dict, user_id, attach_as=None, tags=None, source=None
) -> dict:
    """Save each image in an `image.*` action's result as an asset and put a reference in its place, before the output
    reaches the run (so a run's snapshot holds ids, not megabytes of base64). The canonical shapes:
    `images: [{image_b64 | url}]` (image.generate) and a top-level `image_b64 | url` (image.edit, image.upscale).
    Each asset records how it was made (generated_by, prompt, model, the run). `attach_as` links them to the run's
    entry in that role. With a `source` (the picture an image.edit worked on) each is kept as a version of it."""
    images = result.get("images") if isinstance(result.get("images"), list) else []
    count = sum(1 for item in images if _has_image(item)) + (1 if _has_image(result) else 0)
    if not count:
        return result
    role = _attach_role({"attach_as": attach_as}, context)
    entry_id = subject_entry_id(context)
    if role and entry_id is None:
        raise AutomationActionError("attach_as needs an entry: run this workflow on an entry (an entry event or an entry target)")
    keep = _GeneratedKeeper(
        session, group_id, result, generated_by=generated_by, args=args, context=context, user_id=user_id, count=count, source=source
    )
    out = dict(result)
    if images:
        out["images"] = [{**_without_image(item), "asset": keep.one(item)} if _has_image(item) else item for item in images]
    if _has_image(result):
        out = {**_without_image(out), "asset": keep.one(result)}
    for ref in keep.kept:
        if names := tag_names(tags, context):
            ref["tags"] = tag_asset(session, group_id, keep.rows[ref["id"]], names)
        if role:
            ref["attached"] = attach(session, group_id, entry_id, keep.rows[ref["id"]], role, context, user_id=user_id)
    return out


def _has_image(item) -> bool:
    return isinstance(item, dict) and any(isinstance(item.get(k), str) and item.get(k) for k in IMAGE_KEYS)


def _without_image(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in IMAGE_KEYS}


class _GeneratedKeeper:
    """Stores one action's images: named after the step's `name` arg (else the workflow and what it ran on), once per
    event — the same step of the same run handling an event twice finds the asset it made."""

    def __init__(self, session, group_id, result: dict, *, generated_by: str, args: dict, context: dict, user_id, count: int, source=None):
        self.session, self.group_id, self.context, self.count, self.source = session, group_id, context, count, source
        self.generated_by = generated_by
        step = context.get("_step") or {}
        self.uploader = uploader(session, context, user_id)
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        prompt = str(args.get("prompt") or "")[:PROMPT_KEPT_CHARS]
        entry = context.get("entry") or {}
        self.lineage = {
            "generated_by": generated_by,
            **({"prompt": prompt} if prompt else {}),
            **({"model": usage["model"]} if usage.get("model") else {}),
            **({"made_for_entry": entry["id"]} if entry.get("id") else {}),
            **run_lineage(context),
        }
        subject = entry.get("title") or (context.get("asset") or {}).get("name")
        workflow = step.get("workflow_name") or step.get("workflow_slug") or "Generated image"
        default = f"{source.name} (edited)" if source is not None else f"{workflow} — {subject}" if subject else workflow
        self.name = str(args.get("name") or "").strip() or default
        self.key = _run_step_key(context)
        self.kept: list[dict] = []
        self.rows: dict[str, object] = {}

    def one(self, item: dict) -> dict:
        from marvin.db.models.platform.assets import Assets

        index = len(self.kept)
        slug = self._slug(index)
        row = self.session.query(Assets).filter(Assets.group_id == self.group_id, Assets.slug == slug).first()
        if row is None:
            row = self._store(item, slug, index)
        ref = asset_ref(row)
        self.kept.append(ref)
        self.rows[ref["id"]] = row
        return ref

    def _slug(self, index: int) -> str:
        from slugify import slugify

        base = (slugify(self.name) or "generated")[:SLUG_SOURCE_CHARS]
        seed = f"{self.key}:{index}" if self.key else uuid.uuid4().hex
        return f"{base}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"

    def _store(self, item: dict, slug: str, index: int):
        from marvin.db.models.platform.assets import Assets
        from marvin.services.ai.media import ops
        from marvin.services.assets.asset_storage_service import AssetRejected

        try:
            data = _image_bytes(item)
            fmt = ops.format_of(data)
            name = self.name if self.count == 1 else f"{self.name} ({index + 1})"
            read = _storage(self.session, self.group_id).create_derivative(
                source=self.source,
                data=data,
                group_id=self.group_id,
                derivation=f"{'edited' if self.source is not None else 'generated'}:{self.generated_by}",
                slug=slug,
                name=name,
                user_id=self.uploader,
                extra_metadata=dict(self.lineage),
                extension=ops.FORMATS[fmt][2],
            )
        except (ValueError, AssetRejected) as e:  # NotAnImage, a bad fetch, the upload limits, no uploader
            raise AutomationActionError(f"{self.generated_by} made an image, but it can't be kept: {e}") from e
        return self.session.get(Assets, read.id)


def _image_bytes(item: dict) -> bytes:
    """An image's bytes from base64 (a data: URL's too) or a URL fetched through the SSRF-guarded client."""
    from marvin.services.ai.media.fetch import MAX_IMAGE_BYTES, fetch_image

    b64 = item.get("image_b64")
    if b64:
        b64 = b64.split(",", 1)[1] if b64.startswith("data:") else b64
        if len(b64) * 3 // 4 > MAX_IMAGE_BYTES:
            raise ValueError(f"the image is over {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        try:
            return base64.b64decode(b64, validate=False)
        except (ValueError, TypeError) as e:
            raise ValueError("the image data isn't valid base64") from e
    return fetch_image(item["url"])


def _run_step_key(context: dict) -> str | None:
    """This step of this run (correlation id, workflow, target row, step) — None without a correlation id."""
    from marvin.services.event_bus_service.correlation import current_correlation_id

    correlation = (context.get("event") or {}).get("correlation_id") or current_correlation_id.get()
    step = context.get("_step") or {}
    if not correlation or not step:
        return None
    return f"{correlation}:{step.get('workflow')}:{step.get('target')}:{step.get('index')}"
