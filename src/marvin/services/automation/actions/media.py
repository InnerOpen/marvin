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
import re
import uuid

from marvin.schemas.group.automation_definition import MEDIA_OP_ARGS

from ..matcher import interpolate
from .base import AutomationActionError, register_action

DERIVE_OPS = ("resize", "crop", "convert", "grade")
READ_OPS = ("inspect", "palette")
OPS = (*DERIVE_OPS, *READ_OPS)
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
    src = resolve_source(session, group_id, action.get("source"), context)
    if not transforms.can_transform(src.mime_type):
        raise AutomationActionError(f"“{src.name}” ({src.mime_type or 'unknown type'}) is not an image Marvin can process (jpeg, png or webp)")

    if op in READ_OPS:
        return _read(session, group_id, op, action, src)
    args = derive_args(session, group_id, op, action, context)
    attach_as = _attach_role(action, context)
    entry_id = subject_entry_id(context) if attach_as else None
    if attach_as and entry_id is None:
        raise AutomationActionError("attach_as needs an entry: run this workflow on an entry (an entry event or an entry target)")
    return _derive(session, group_id, op, args, src, context, user_id=user_id, attach_as=attach_as, entry_id=entry_id, dry_run=dry_run)


# ── Reading the source ───────────────────────────────────────────────────────
def resolve_source(session, group_id, ref, context: dict):
    """The asset a step works on: an id or slug (templates allowed; default the run's asset), or `role:<role>` — the
    run's entry's asset in that role, first by position. Not one in the Trash."""
    from marvin.db.models.platform.assets import Assets

    raw = interpolate(ref or DEFAULT_SOURCE, context)
    value = str(raw).strip() if raw not in (None, "") else ""
    if not value:
        raise AutomationActionError(
            "no image to work on — set source (an asset id or slug, ${steps.<id>.output.asset.id}, or role:<role>), or run it on an asset"
        )
    if value.startswith(ROLE_PREFIX):
        row = _asset_in_role(session, group_id, value[len(ROLE_PREFIX) :].strip(), context)
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


def _derive(session, group_id, op: str, args: dict, src, context: dict, *, user_id, attach_as, entry_id, dry_run: bool) -> dict:
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
    out.update(asset=asset_ref(asset), reused=reused)
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


def attach(session, group_id, entry_id, asset, role: str, context: dict, *, user_id) -> str:
    """Link the asset to the run's entry in ``role`` (once): "attached" (sends asset_attached_to_entry) or "exists"."""
    from marvin.services.entries import EntryService

    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    result = svc.attach_asset(entry_id, asset.id, role=role, reaction_depth=int(context.get("depth", 0)) + 1)
    if result is None:
        raise AutomationActionError(f"could not attach “{asset.name}”: the entry is not in this workspace")
    return result


# ── Subject focus (a vision model, or an integration that detects subjects) ──
def _subject_detector(session, group_id):
    """The handler that finds a picture's main subject, or (None, why not) — then a subject crop centres instead. A
    vision model is used only where the workspace lets workflows use AI, within its budget."""
    from marvin.services.ai.media import capability

    handlers = capability._integrations_providing(capability.KIND_DETECT_SUBJECT, group_id)
    if handlers:
        return handlers[0], None
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai import budget
    from marvin.services.ai.factory import get_workspace_ai_provider

    from ..runner import AUTOMATION_SOURCE, _model_sees_images, _resolve_model

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    policy = settings.invocation_sources if settings else None
    if not (settings and settings.enabled) or (isinstance(policy, dict) and policy.get(AUTOMATION_SOURCE, True) is False):
        return None, "AI is off for workflows here; cropped from the centre"
    if reason := budget.blocked_reason(session, group_id):
        return None, f"AI budget: {reason}; cropped from the centre"
    model = _resolve_model(session, group_id, settings)
    try:
        provider = get_workspace_ai_provider(session, group_id)
    except Exception:  # noqa: BLE001 — no provider is the same as no vision model
        provider = None
    if not (provider and model and _model_sees_images(session, group_id, model)):
        return None, "no AI model that can see images; cropped from the centre"
    handler = capability.resolve_capability(capability.KIND_DETECT_SUBJECT, session=session, group_id=group_id, provider=provider, model=model)
    return (handler, None) if handler else (None, "no AI model that can see images; cropped from the centre")


def _detect_subject(session, group_id, handler, src, data: bytes, *, user_id) -> list | None:
    """The subject's normalized box [x, y, w, h], or None. A vision model's call is logged and costed like any
    workflow AI call (AI usage, the monthly budget)."""
    started = _now()
    result = handler.invoke({"asset_id": src.id, "image_bytes": data, "image_b64": base64.b64encode(data).decode("ascii")}) or {}
    box = result.get("box")
    usage = getattr(handler, "last_usage", None)
    if usage is not None:
        _log_vision_call(session, group_id, handler, src, box, usage, started, user_id=user_id)
    return list(box) if box else None


def _log_vision_call(session, group_id, handler, src, box, usage, started, *, user_id) -> None:
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai import budget
    from marvin.services.ai.pricing import estimate_cost

    from ..runner import AUTOMATION_SOURCE

    provider_type = getattr(handler.provider, "provider_type", None)
    prompt, completion = usage.prompt_tokens or 0, usage.completion_tokens or 0
    row = AIExecutionModel(
        session=session,
        group_id=group_id,
        operation_slug=DETECT_OPERATION,
        provider_type=provider_type,
        model_id=handler.model,
        status="completed",
        triggered_by=user_id,
        trigger_type=AUTOMATION_SOURCE,
        entity_type="asset",
        entity_id=src.id,
        input_json={},
        output_json={"box": box},
        started_at=started,
        completed_at=_now(),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=usage.total_tokens or prompt + completion,
        estimated_cost_usd=estimate_cost(provider_type, handler.model, prompt, completion),
    )
    session.add(row)
    session.commit()
    if crossing := budget.crossing_after(session, group_id, row.estimated_cost_usd):
        budget.emit_crossing(group_id, crossing, user_id=user_id, source=AUTOMATION_SOURCE)


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


# ── Images an integration returns ────────────────────────────────────────────
IMAGE_KEYS = ("image_b64", "url")


def returns_images(declared) -> bool:
    """Whether a provider action's output is images to keep: it declares an `image.*` capability. Other actions'
    `url` fields (a checkout link, a post) are left alone."""
    return str(getattr(declared, "capability", None) or "").startswith("image.")


def keep_generated_images(session, group_id, result: dict, *, generated_by: str, args: dict, context: dict, user_id, attach_as=None) -> dict:
    """Save each image in an `image.*` action's result as an asset and put a reference in its place, before the output
    reaches the run (so a run's snapshot holds ids, not megabytes of base64). The canonical shapes:
    `images: [{image_b64 | url}]` (image.generate) and a top-level `image_b64 | url` (image.edit, image.upscale).
    Each asset records how it was made (generated_by, prompt, model, the run). `attach_as` links them to the run's
    entry in that role."""
    images = result.get("images") if isinstance(result.get("images"), list) else []
    count = sum(1 for item in images if _has_image(item)) + (1 if _has_image(result) else 0)
    if not count:
        return result
    role = _attach_role({"attach_as": attach_as}, context)
    entry_id = subject_entry_id(context)
    if role and entry_id is None:
        raise AutomationActionError("attach_as needs an entry: run this workflow on an entry (an entry event or an entry target)")
    keep = _GeneratedKeeper(session, group_id, result, generated_by=generated_by, args=args, context=context, user_id=user_id, count=count)
    out = dict(result)
    if images:
        out["images"] = [{**_without_image(item), "asset": keep.one(item)} if _has_image(item) else item for item in images]
    if _has_image(result):
        out = {**_without_image(out), "asset": keep.one(result)}
    if role:
        for ref in keep.kept:
            ref["attached"] = attach(session, group_id, entry_id, keep.rows[ref["id"]], role, context, user_id=user_id)
    return out


def _has_image(item) -> bool:
    return isinstance(item, dict) and any(isinstance(item.get(k), str) and item.get(k) for k in IMAGE_KEYS)


def _without_image(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in IMAGE_KEYS}


class _GeneratedKeeper:
    """Stores one action's images: named after the step's `name` arg (else the workflow and what it ran on), once per
    event — the same step of the same run handling an event twice finds the asset it made."""

    def __init__(self, session, group_id, result: dict, *, generated_by: str, args: dict, context: dict, user_id, count: int):
        self.session, self.group_id, self.context, self.count = session, group_id, context, count
        self.generated_by = generated_by
        step = context.get("_step") or {}
        self.uploader = user_id or step.get("author_id")
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
        self.name = str(args.get("name") or "").strip() or (f"{workflow} — {subject}" if subject else workflow)
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
                source=None,
                data=data,
                group_id=self.group_id,
                derivation=f"generated:{self.generated_by}",
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
