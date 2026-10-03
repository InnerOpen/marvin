"""Capability-routed media enrichment — pick the best available handler for an image capability.

A *capability* is a verb the media pipeline needs performed on an image — describe it, detect its
subject, grade it, crop it, generate/edit/search/upscale one. Each is a `kind` string (below). The
same verb can be served by several *backends*, in a fixed precedence:

  1. **Integrations** — a workspace integration advertising the capability (highest priority wins).
     Owned by the integrations team; pre-authorized handlers come from ``integrations_providing``.
  2. **Vision model** — the default path for VISION-IN kinds (``image.describe`` /
     ``image.detect_subject``) when the workspace has a vision-capable provider + model.
  3. **Local Pillow** — deterministic PIXEL kinds (``image.grade`` / ``image.crop``), no model/cost.

``resolve_capability`` returns the first backend that can serve a kind, or ``None`` (the caller
logs and skips — media enrichment is best-effort and never raises into compose/publish).
``image.generate`` / ``image.edit`` / ``image.search`` / ``image.upscale`` have NO model/local
fallback: they resolve to ``None`` until an integration provides them (expected/correct).

Handlers are uniform: ``.invoke(inputs: dict) -> dict`` plus metadata (``kind``/``priority``/
``cost_hint``/``requires_approval``) mirroring the integration-side ``ProviderAction`` contract.
Integration handlers are DB-free pure functions — the RESOLVER (here / the enrichment service)
owns all asset I/O and passes base64 bytes in ``inputs``; those handlers return bytes or a URL.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from marvin.services.ai.media import transforms

logger = logging.getLogger(__name__)

# ── Shared capability-kind vocabulary ──────────────────────────────────────────────────────
# Standardize on these string constants across the media pipeline and the integrations side.
KIND_DESCRIBE = "image.describe"
KIND_GENERATE = "image.generate"
KIND_EDIT = "image.edit"
KIND_SEARCH = "image.search"
KIND_UPSCALE = "image.upscale"
# Internal kinds (not user-facing integrations vocabulary, but routed the same way):
KIND_DETECT_SUBJECT = "image.detect_subject"
KIND_GRADE = "image.grade"
KIND_CROP = "image.crop"

# Kinds that feed an image IN and get text/structured data OUT — servable by a vision model.
_VISION_IN_KINDS = frozenset({KIND_DESCRIBE, KIND_DETECT_SUBJECT})
# Kinds that are pure, local, deterministic pixel transforms — servable by Pillow.
_PIXEL_KINDS = frozenset({KIND_GRADE, KIND_CROP})

# Inline output schema + prompt for image.detect_subject. Kept here (not a registered AIOperation)
# because it's an internal, media-only structured call — no need for a catalog entry / min_role.
_DETECT_SUBJECT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "box": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 4,
            "maxItems": 4,
            "description": "Normalized bounding box [x, y, w, h] of the main subject, values 0..1 "
            "where (x, y) is the top-left corner and (w, h) the width/height fraction.",
        },
    },
    "required": ["box"],
}


@runtime_checkable
class CapabilityHandler(Protocol):
    """A resolved, pre-authorized backend for one capability ``kind``.

    Metadata mirrors the integration-side ``ProviderAction`` fields so integration handlers and
    the built-in (vision/local) handlers are interchangeable to the caller.
    """

    kind: str
    priority: int
    cost_hint: float
    requires_approval: bool

    def invoke(self, inputs: dict) -> dict:  # pragma: no cover - protocol
        ...


class LocalPixelHandler:
    """Serves PIXEL kinds (``image.grade`` / ``image.crop``) with local Pillow transforms.

    ``invoke({image_bytes, op, arg})`` → ``{image_bytes}``. ``arg`` is a preset name for ``grade``;
    for ``crop`` it's either an aspect string (``"4x5"``) → center aspect-crop, or a normalized
    4-tuple/list ``[x, y, w, h]`` → box-crop. Returns ``{}`` (skip) on an unknown/degenerate arg.

    For ``grade``, the caller may pass resolved ``params`` (the workspace-effective preset dict).
    When present those win — the service layer merges workspace overrides over the built-ins — and
    only fall back to the built-in preset lookup by ``arg`` when no params are supplied.
    """

    def __init__(self, kind: str, *, priority: int = 0, cost_hint: float = 0.0) -> None:
        self.kind = kind
        self.priority = priority
        self.cost_hint = cost_hint
        self.requires_approval = False

    def invoke(self, inputs: dict) -> dict:
        data = inputs.get("image_bytes")
        op = inputs.get("op") or (self.kind.split(".", 1)[-1])
        arg = inputs.get("arg")
        if not data:
            return {}
        out: bytes | None = None
        if op == "grade":
            params = inputs.get("params")
            if isinstance(params, dict) and params:
                out = transforms.color_grade_params(data, params)
            else:
                out = transforms.color_grade(data, str(arg))
        elif op == "crop":
            if isinstance(arg, list | tuple) and len(arg) == 4:
                out = transforms.crop_to_box(data, tuple(arg))
            elif arg:
                aspect = transforms._parse_aspect(str(arg))
                out = transforms.crop_to_aspect(data, aspect) if aspect else None
        return {"image_bytes": out} if out else {}


class VisionModelHandler:
    """Serves VISION-IN kinds via the workspace's vision provider (the default path).

    Mirrors the proven vision call in ``authoring._run_alt_text_enrichment``: ContextBuilder →
    ``with_asset_images`` → ``op.build_prompt`` → ``provider.execute_operation``.

      - ``image.describe`` reuses the registered ``describe-image`` operation.
      - ``image.detect_subject`` uses a small inline schema/prompt, returning a normalized
        ``{box: [x, y, w, h]}`` (values 0..1).

    ``invoke({asset_id})`` (the resolver reads the image via ContextBuilder). Returns ``{}`` when
    no vision provider/model is configured or the asset is unreadable/not an image.
    """

    def __init__(
        self,
        kind: str,
        *,
        session,
        group_id,
        provider,
        model,
        priority: int = 0,
        cost_hint: float = 0.5,
    ) -> None:
        self.kind = kind
        self.session = session
        self.group_id = group_id
        self.provider = provider
        self.model = model
        self.priority = priority
        self.cost_hint = cost_hint
        self.requires_approval = False

    def invoke(self, inputs: dict) -> dict:
        if not (self.provider and getattr(self.provider, "supports_vision", False) and self.model):
            return {}
        asset_id = inputs.get("asset_id")
        if not asset_id:
            return {}

        from marvin.services.ai.base import CompletionOptions, ImagePart, Message
        from marvin.services.ai.context import ContextBuilder, resolve_prompt_messages

        try:
            ctx = ContextBuilder(self.session, self.group_id).with_site_settings().with_variables().with_asset(asset_id).with_asset_images().build()
            if not (ctx.assets and ctx.assets[0].get("image_data")):
                return {}  # unreadable / not actually an image

            if self.kind == KIND_DESCRIBE:
                from marvin.services.ai.operations.base import get_operation

                op = get_operation("describe-image")
                messages = resolve_prompt_messages(op.build_prompt({}, ctx), self.group_id, ctx.variables)
                opts = CompletionOptions(max_tokens=400)
                parsed, _ = self.provider.execute_operation(messages, self.model, op.output_schema, opts)
                return parsed or {}

            if self.kind == KIND_DETECT_SUBJECT:
                asset = ctx.assets[0]
                instruction = (
                    "Locate the single main subject of this image. Return its bounding box as "
                    "normalized coordinates in [0, 1]: [x, y, w, h] where (x, y) is the top-left "
                    "corner and (w, h) the width and height as fractions of the image.\n\n"
                    'Return JSON: {"box": [x, y, w, h]}'
                )
                messages = [
                    Message(role="system", content="You are a vision assistant that locates the main subject of an image."),
                    Message(
                        role="user",
                        content=[
                            instruction,
                            ImagePart(data=asset["image_data"], mime_type=asset.get("mime_type") or "image/png"),
                        ],
                    ),
                ]
                opts = CompletionOptions(max_tokens=200)
                parsed, _ = self.provider.execute_operation(messages, self.model, _DETECT_SUBJECT_SCHEMA, opts)
                box = _normalize_box((parsed or {}).get("box"))
                return {"box": box} if box else {}
        except Exception as e:  # noqa: BLE001 — best-effort; a vision failure just yields no result
            logger.warning("media: vision %s failed: %s", self.kind, e)
        return {}


def _normalize_box(box) -> list[float] | None:
    """Coerce a model's box output into a clamped normalized [x, y, w, h] (0..1), or None."""
    if not isinstance(box, list | tuple) or len(box) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    clamp = lambda v: min(max(v, 0.0), 1.0)  # noqa: E731
    return [clamp(x), clamp(y), clamp(w), clamp(h)]


def _integrations_providing(kind: str, group_id) -> list[CapabilityHandler]:
    """Defensive seam over the integrations-team-owned ``integrations_providing(kind, group_id)``.

    That function returns enabled integrations advertising ``kind`` as pre-authorized
    ``CapabilityHandler``s, highest-priority first (disabled/orphaned filtered out). It does not
    exist yet — until it lands this returns ``[]`` so routing runs today and lights up when theirs
    ships. This is the ONE place the media pipeline touches the integrations side.
    """
    try:
        from marvin.services.integrations import integrations_providing  # type: ignore
    except ImportError:
        return []
    try:
        # Cross-module seam: integrations' CapabilityHandler structurally satisfies this module's
        # Protocol; list invariance is the only mismatch, so the ignore is safe.
        return list(integrations_providing(kind, group_id) or [])  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001 — never let an integrations error break resolution
        logger.debug("media: integrations_providing(%s) failed: %s", kind, e)
        return []


def resolve_capability(
    kind: str,
    *,
    session,
    group_id,
    provider=None,
    model=None,
) -> CapabilityHandler | None:
    """Return the best available handler for ``kind`` (or ``None``), by fixed precedence:

    1. Integrations (top-priority advertised handler), then
    2. Vision model — VISION-IN kinds only, when a vision-capable provider + model exist, then
    3. Local Pillow — PIXEL kinds, then
    4. ``None`` (caller logs + skips).
    """
    handlers = _integrations_providing(kind, group_id)
    if handlers:
        return handlers[0]

    if kind in _VISION_IN_KINDS:
        if provider is not None and getattr(provider, "supports_vision", False) and model:
            return VisionModelHandler(
                kind,
                session=session,
                group_id=group_id,
                provider=provider,
                model=model,
            )
        return None

    if kind in _PIXEL_KINDS:
        return LocalPixelHandler(kind)

    return None
