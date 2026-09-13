"""
Vision tool: look at an image asset and say what it shows — read-only.

`describe-image` (an AI operation) writes its description back to the asset, which is a write and so
is off-limits to read-only agents. Chat needs the *looking* without the writing: a user attaches a
photo and asks "what is this?". This tool answers from the pixels and persists nothing except the
execution row (so the vision tokens still show up in AI executions with their cost).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from marvin.services.ai.operations.base import ROLE_VIEWER

from .base import ToolContext, register_tool

_SYSTEM = "You are a vision assistant. Describe images accurately from what you can actually see; do not guess at what is not visible."


@register_tool(
    name="view_image",
    description=(
        "Look at an image asset and describe what it shows — objects, text, colours, setting — without "
        "changing anything. Use when the user attaches or points at an image and asks what it is or what's "
        "in it. Pass an optional `question` to focus the look (e.g. 'what fabric is this?')."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "asset": {"type": "string", "description": "asset id or slug"},
            "question": {"type": "string", "description": "optional focus for the description"},
        },
        "required": ["asset"],
    },
    min_role=ROLE_VIEWER,
    read_only=True,
)
def view_image(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.groups.ai_providers import AIModelModel
    from marvin.services.ai.base import CompletionOptions, ImagePart, Message
    from marvin.services.ai.context import ContextBuilder
    from marvin.services.ai.entity_resolve import resolve_entity_id
    from marvin.services.ai.pricing import estimate_cost

    from .builtins_agents import _default_model

    ref = str(args.get("asset") or "").strip()
    if not ref:
        return json.dumps({"error": "asset is required (id or slug)"})
    try:
        asset_id = resolve_entity_id(ctx.session, ctx.group_id, "asset", ref)
    except Exception as e:  # noqa: BLE001 — surface to the model
        return json.dumps({"error": f"could not resolve asset '{ref}': {e}"})
    if not asset_id:
        return json.dumps({"error": f"no asset '{ref}' in this workspace (try list_assets)"})

    built = ContextBuilder(ctx.session, ctx.group_id).with_asset(asset_id).with_asset_images(limit=1).build()
    asset = (getattr(built, "assets", None) or [None])[0]
    if not asset:
        return json.dumps({"error": f"no asset '{ref}' in this workspace (try list_assets)"})
    if not asset.get("image_data"):
        return json.dumps(
            {
                "error": "that asset is not an image, or its file is unavailable",
                "asset": {"id": str(asset_id), "name": asset.get("name"), "mimeType": asset.get("mime_type")},
            }
        )

    provider = ctx.provider
    if provider is None:
        return json.dumps({"error": "no AI provider configured for this workspace"})
    model = _default_model(ctx)
    if not model:
        return json.dumps({"error": "no model configured — set a default model on the provider"})
    row = ctx.session.query(AIModelModel).filter_by(group_id=ctx.group_id, model_id=model).first()
    if row is not None and not getattr(row, "supports_vision", True):
        return json.dumps({"error": f"the workspace model '{model}' cannot see images; configure a vision-capable model"})

    question = str(args.get("question") or "").strip()
    instruction = f"Describe the image '{asset.get('name') or 'this image'}' in detail: the main objects, any text, colours, and setting." + (
        f" Focus on: {question}" if question else ""
    )
    messages = [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=[instruction, ImagePart(data=asset["image_data"], mime_type=asset.get("mime_type") or "image/png")]),
    ]

    execution = AIExecutionModel(
        session=ctx.session,
        group_id=ctx.group_id,
        operation_slug="tool:view_image",
        provider_type=provider.provider_type,
        model_id=model,
        status="running",
        triggered_by=getattr(ctx.user, "id", None),
        trigger_type="agent",
        entity_type="asset",
        entity_id=asset_id,
        input_json={"asset": str(asset_id), "question": question or None},
    )
    execution.started_at = datetime.now(UTC)
    ctx.session.add(execution)
    ctx.session.commit()
    start = time.monotonic()
    try:
        res = provider.complete(messages, model, CompletionOptions(temperature=0.2, max_tokens=None))
    except Exception as e:  # noqa: BLE001 — a vision failure is data for the model, never an exception in the loop
        execution.status = "failed"
        execution.error_message = str(e)[:2000]
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        ctx.session.commit()
        return json.dumps({"error": f"vision call failed: {e}"})

    execution.status = "completed"
    execution.completed_at = datetime.now(UTC)
    execution.duration_ms = int((time.monotonic() - start) * 1000)
    execution.prompt_tokens = getattr(res, "prompt_tokens", 0)
    execution.completion_tokens = getattr(res, "completion_tokens", 0)
    execution.total_tokens = getattr(res, "total_tokens", 0)
    execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, execution.prompt_tokens, execution.completion_tokens)
    execution.output_json = {"description": res.content}
    ctx.session.commit()
    return json.dumps(
        {
            "asset": {"id": str(asset_id), "name": asset.get("name"), "slug": asset.get("slug"), "mimeType": asset.get("mime_type")},
            "description": res.content,
            "model": model,
            "executionId": str(execution.id),
        }
    )
