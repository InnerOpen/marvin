"""Execute a single Flavor B action against a workspace.

v1 supports one action kind: ``operation`` — run an AI operation (e.g. ``generate-summary``) on an
entry and optionally apply its write-back. Runs under the ``"automation"`` invocation source, so the
same gate that protects the MCP/agent surfaces protects automations.

This reuses the already-factored primitives (ContextBuilder, provider factory,
``provider.execute_operation``, the entries repo). It deliberately does NOT import the operations
*controller* — unifying the controller's ``execute_operation`` onto a shared runner is a follow-up
(same debt as the scheduled-agent tool-builder extraction).
"""

import json
import time
from datetime import UTC, datetime

from marvin.schemas.group.automation_definition import writeback_field_ok
from marvin.services.ai.base import Message
from marvin.services.ai.operations import get_operation
from marvin.services.ai.operations.custom import CUSTOM_OP, CustomOperation, output_problems, workspace_voice

from .actions.base import AutomationActionError  # re-exported for callers importing from runner
from .matcher import interpolate

# Invocation source every automation-driven op call is stamped with.
AUTOMATION_SOURCE = "automation"

__all__ = ["AUTOMATION_SOURCE", "AutomationActionError", "run_operation_action"]


def _gate_source(session, group_id, operation) -> None:
    """Enforce the operation's declared sources ∩ workspace policy for ``"automation"``."""
    if AUTOMATION_SOURCE not in operation.invocation_sources:
        raise AutomationActionError(f"operation '{operation.slug}' cannot be invoked from the automation source")
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    policy = settings.invocation_sources if settings else None
    if isinstance(policy, dict) and policy.get(AUTOMATION_SOURCE, True) is False:
        raise AutomationActionError("this workspace has disabled AI from the automation source")


def _resolve_model(session, group_id, settings) -> str | None:
    """Default model for the workspace — mirrors the operations controller's `_default_model`.

    settings.model → default provider's default model → (platform credential mode) the
    admin-configured AppSettings model (e.g. OPENAI_MODEL), so platform-mode workspaces with no
    per-workspace model still resolve.
    """
    if settings and settings.model:
        return settings.model
    from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel

    provider = session.query(AIProviderModel).filter_by(group_id=group_id, is_default=True, enabled=True).first()
    if provider:
        model = session.query(AIModelModel).filter_by(provider_id=provider.id, is_default=True, enabled=True).first()
        if model:
            return model.model_id
    if settings and settings.credential_mode == "platform":
        from marvin.services.ai.factory import platform_model

        return platform_model(settings.provider)
    return None


def run_operation_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    """Run one ``operation`` action; return its output_json (so ``$previous`` can reference it).

    ``action`` = ``{"kind": "operation", "op": <slug>, "input": {...}, "entity_type": "entry",
    "entity_id": "$event.entry_id", "write_back": true}``. entity_type/entity_id default to an entry
    resolved from ``$event.entry_id``. Raises :class:`AutomationActionError` on any failure — the
    engine logs and moves on; automations never break event dispatch.
    """
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.context import resolve_prompt_messages
    from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider

    slug = action.get("op")
    if not slug:
        raise AutomationActionError("action is missing 'op'")
    operation = _operation_for(session, group_id, action, context)
    custom = getattr(operation, "slug", None) == CUSTOM_OP
    _gate_source(session, group_id, operation)
    # Definer's rights: the op runs under the automation author's authority, so enforce the op's own
    # min_role against the author's *current* role (fail-closed if they were demoted/removed). None =
    # a direct caller that didn't thread authz (tests) → treated as OWNER.
    from .authz import ROLE_OWNER, require_role

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, operation.min_role, f"operation '{operation.slug}'")

    # Resolve entity. Without an entity_type the step acts on the run's subject — an asset/resource event's
    # item or an asset/resource target's row, else an entry. entity_id may be a $event/$previous template and
    # defaults to the current item of that kind. An action may instead target an entry by SLUG (`entity_slug`)
    # — humans reference entries by slug, not UUID, so a webhook payload that carries `entry_slug` is far more
    # usable than an opaque id.
    from .actions.entry import subject_kind

    entity_type = action.get("entity_type") or subject_kind(context) or "entry"
    supported = getattr(operation, "entity_types", None) or ()  # empty: the op needs no entity (a workspace question)
    if supported and entity_type not in supported:
        raise AutomationActionError(f"operation '{slug}' does not run on an {entity_type} (it runs on: {', '.join(supported)})")
    op_input = interpolate(action.get("input", {}) or {}, context)

    entity_slug = interpolate(action.get("entity_slug"), context) if action.get("entity_slug") else None
    if entity_type == "entry" and entity_slug:
        entity_id = _resolve_entry_id_by_slug(session, group_id, str(entity_slug))
    else:
        entity_id = interpolate(action.get("entity_id", f"$event.{entity_type}_id"), context)

    if dry_run:
        # Preview: the op is authorized and its inputs/target resolve — but don't call the provider,
        # create an AIExecution row, or write back. (An AI call is the expensive, side-effectful part.)
        return {
            **(_stand_ins(action.get("output_schema")) if custom else {}),
            "dry_run": True,
            "kind": "operation",
            "op": slug,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "input": op_input,
            **({"prompt": operation.prompt[:2000], "see": list(operation.see)} if custom else {}),
            "would_write_back": bool(action.get("write_back")),
        }

    from marvin.services.ai import budget

    # Workflows spend from the same monthly budget as every other AI run.
    if reason := budget.blocked_reason(session, group_id):
        raise AutomationActionError(f"AI budget: {reason}")

    try:
        provider = get_workspace_ai_provider(session, group_id)
    except AIDisabledError as e:
        raise AutomationActionError(f"AI disabled: {e}") from e
    except Exception as e:
        raise AutomationActionError(f"provider error: {e}") from e

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    model = _resolve_model(session, group_id, settings)
    if not model:
        raise AutomationActionError("no default model configured for this workspace")

    ctx = _operation_context(session, group_id, operation, entity_type, entity_id, model)

    from marvin.db.models.groups.ai_executions import AIExecutionModel

    execution = AIExecutionModel(
        session=session,
        group_id=group_id,
        operation_slug=slug,
        provider_type=provider.provider_type,
        model_id=model,
        status="running",
        triggered_by=user_id,
        trigger_type=AUTOMATION_SOURCE,
        entity_type=entity_type,
        entity_id=entity_id,
        input_json=op_input,
        started_at=datetime.now(UTC),
    )
    session.add(execution)
    session.commit()

    start = time.monotonic()
    try:
        from marvin.core.config import get_app_settings
        from marvin.services.ai.base import CompletionOptions

        _app = get_app_settings()
        opts = CompletionOptions(
            temperature=_app.AI_DEFAULT_TEMPERATURE,
            max_tokens=budget.max_output_tokens(session, group_id),
        )
        messages = operation.build_prompt(op_input, ctx)
        messages = resolve_prompt_messages(messages, group_id, ctx.variables)
        parsed, usage = _complete(provider, operation, messages, model, opts, check=custom)

        from marvin.services.ai.pricing import estimate_cost

        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        execution.output_json = parsed
        prompt_tokens = sum(c.prompt_tokens or 0 for c in usage)  # a retried custom answer costs both calls
        completion_tokens = sum(c.completion_tokens or 0 for c in usage)
        execution.prompt_tokens = prompt_tokens
        execution.completion_tokens = completion_tokens
        execution.total_tokens = sum(c.total_tokens or 0 for c in usage)
        execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, prompt_tokens, completion_tokens)
        session.commit()
    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)
        execution.completed_at = datetime.now(UTC)
        session.commit()
        raise AutomationActionError(f"operation '{slug}' failed: {e}") from e
    if crossing := budget.crossing_after(session, group_id, execution.estimated_cost_usd):
        budget.emit_crossing(group_id, crossing, user_id=user_id, source=AUTOMATION_SOURCE)

    return _apply_write_back(session, group_id, action, operation, parsed, entity_type, entity_id, context, user_id, authorizer_role, execution.id)


def _stand_ins(output_schema) -> dict:
    """A dry run's stand-in for a custom step's answer: each text field of its output schema as ‹AI answer: key›, so the
    steps after it (a create's title, a render's text) preview as they will run instead of failing on an empty value."""
    properties = (output_schema or {}).get("properties") if isinstance(output_schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    return {key: f"‹AI answer: {key}›" for key, spec in properties.items() if isinstance(spec, dict) and spec.get("type") == "string"}


def _operation_for(session, group_id, action: dict, context: dict):
    """The step's operation: a registered one by slug, or (`op: "custom"`) one built from the step's own prompt (its
    ${…} templates filled in now), output schema and `see` — the schema was checked when the workflow was saved."""
    slug = action["op"]
    if slug == CUSTOM_OP:
        see = tuple(action["see"]) if action.get("see") is not None else None  # [] = the prompt alone; unset = the item
        return CustomOperation(
            prompt=str(interpolate(action.get("prompt") or "", context) or ""),
            output_schema=action.get("output_schema") or {},
            see=see,
            voice=workspace_voice(session, group_id) if "persona" in (see or ()) else "",
        )
    try:
        return get_operation(slug)
    except KeyError as e:
        raise AutomationActionError(f"unknown operation '{slug}'") from e


def _operation_context(session, group_id, operation, entity_type: str, entity_id, model: str):
    """What the operation's prompt is built from: the site, the variables, and the item the step runs on — with its
    pictures when the operation looks at images (a vision op, a custom step that asks to `see` them)."""
    from marvin.services.ai.context import ContextBuilder

    if operation.requires_vision and not _model_sees_images(session, group_id, model):
        raise AutomationActionError(f"operation '{operation.slug}' needs a model that can see images; {model} can't")
    builder = ContextBuilder(session, group_id).with_site_settings().with_variables()
    if entity_type == "entry" and entity_id:
        builder.with_entry(entity_id).with_assets(entity_id).with_resources(entity_id)
        if operation.requires_vision:  # the entry's attached pictures
            builder.with_asset_images()
    elif entity_type == "asset" and entity_id:
        builder.with_asset(entity_id)
        # As in the interactive route: a vision op needs the image; one that merely benefits sees it if the model can.
        if operation.requires_vision or (getattr(operation, "sees_asset_image", False) and _model_sees_images(session, group_id, model)):
            builder.with_asset_images()
    elif entity_type == "resource" and entity_id:
        builder.with_resource(entity_id)
    return builder.build()


def _complete(provider, operation, messages: list, model: str, opts, *, check: bool) -> tuple[dict, list]:
    """The provider's structured answer and the usage of every call. With `check` (a custom step) the answer must match
    the output schema: one more try, told what was wrong, then a ValueError (the step fails, logged as failed)."""
    parsed, completion = provider.execute_operation(messages, model, operation.output_schema, opts)
    usage = [completion]
    if check and (problems := output_problems(operation.output_schema, parsed)):
        retry = [
            *messages,
            Message(role="assistant", content=json.dumps(parsed)[:4000]),
            Message(role="user", content=f"That answer doesn't match the schema: {'; '.join(problems)}. Answer again with only the JSON object."),
        ]
        parsed, completion = provider.execute_operation(retry, model, operation.output_schema, opts)
        usage.append(completion)
        if problems := output_problems(operation.output_schema, parsed):
            raise ValueError(f"the answer doesn't match output_schema: {'; '.join(problems)}")
    return parsed, usage


def _apply_write_back(session, group_id, action, operation, parsed, entity_type, entity_id, context, user_id, authorizer_role, execution_id) -> dict:
    """The step's output, after its optional write-back — gated by the workspace approval mode like every other AI
    write-back (applied, or staged as a suggestion for a person to accept); `_write_back` in the output says which.
    `write_back: true` writes a built-in op's own fields on an entry; a map {output key: field} names them."""
    if not isinstance(parsed, dict):
        return {}
    write_back = action.get("write_back")
    depth = int(context.get("depth", 0))
    if isinstance(write_back, dict) and write_back:
        if not entity_id:
            raise AutomationActionError(f"write_back: no {entity_type} to write onto")
        proposed = {field: parsed[out] for out, field in write_back.items() if out in parsed}
        if bad := sorted(f for f in proposed if not writeback_field_ok(entity_type, f)):
            raise AutomationActionError(f"write_back can't write {', '.join(bad)} on an {entity_type}")
        if not proposed:
            return parsed
        if entity_type == "entry":
            fields = {f"metadata_json.{f.split('.', 1)[1]}" if f.startswith("metadata.") else f: v for f, v in proposed.items()}
            outcome = _write_back(session, group_id, entity_id, fields, user_id, depth, operation.slug, execution_id)
        else:
            outcome = _write_back_item(session, group_id, entity_type, entity_id, proposed, authorizer_role, operation.slug, execution_id)
        return {**parsed, "_write_back": outcome}
    if write_back and entity_type == "entry" and entity_id:
        proposed = {target: parsed[out] for out, target in (getattr(operation, "writeback", None) or {}).items() if out in parsed}
        if proposed:
            outcome = _write_back(session, group_id, entity_id, proposed, user_id, depth, operation.slug, execution_id)
            return {**parsed, "_write_back": outcome}
    return parsed


def _write_back(session, group_id, entity_id, proposed: dict, user_id, depth: int, slug: str, execution_id) -> str:
    """Apply or stage per the workspace approval mode. Returns "applied" | "staged"."""
    from marvin.db.models.platform.entries import Entries
    from marvin.repos.repository_factory import AllRepositories
    from marvin.services.ai.approval import may_apply, workspace_approval_mode

    entry = session.get(Entries, entity_id)
    if may_apply(workspace_approval_mode(session, group_id), "entry", getattr(entry, "status", None)):
        _apply_writeback(session, group_id, entity_id, proposed, user_id, depth)
        return "applied"
    AllRepositories(session, group_id=group_id).entries.stage_suggestion(
        entity_id, {**proposed, "_meta": {"operation": slug, "executionId": str(execution_id), "source": "automation"}}
    )
    return "staged"


def _write_back_item(session, group_id, kind: str, item_id, proposed: dict, authorizer_role, slug: str, execution_id) -> str:
    """An operation's output onto an asset or resource, under the same rules as the interactive route: an EDITOR+
    author (definer's rights) may change it, and the approval mode decides whether it is applied or staged as a
    suggestion. Returns "applied" | "staged" | "not_permitted"."""
    from marvin.db.models.platform import Assets, Resources
    from marvin.repos.repository_factory import AllRepositories
    from marvin.services.ai.approval import may_apply, workspace_approval_mode

    from .authz import ROLE_EDITOR, ROLE_OWNER

    if (ROLE_OWNER if authorizer_role is None else authorizer_role) < ROLE_EDITOR:
        return "not_permitted"
    model, repos = (
        (Assets, AllRepositories(session, group_id=group_id).assets)
        if kind == "asset"
        else (Resources, AllRepositories(session, group_id=group_id).resources)
    )
    item = session.get(model, item_id)
    if item is None or str(item.group_id) != str(group_id):
        raise AutomationActionError(f"write_back: no such {kind} in this workspace")
    fields = {f"metadata_json.{f.split('.', 1)[1]}" if f.startswith("metadata.") else f: v for f, v in proposed.items()}
    if may_apply(workspace_approval_mode(session, group_id), kind, None):
        repos.apply_fields(item_id, fields)
        return "applied"
    repos.stage_suggestion(item_id, {**fields, "_meta": {"operation": slug, "executionId": str(execution_id), "source": AUTOMATION_SOURCE}})
    session.commit()
    return "staged"


def _model_sees_images(session, group_id, model: str) -> bool:
    """False only when the model's `ai_models` row says it has no vision; no row → assume it can (as the route)."""
    from marvin.db.models.groups.ai_providers import AIModelModel

    row = session.query(AIModelModel).filter_by(group_id=group_id, model_id=model).first()
    return not (row and not row.supports_vision)


def _resolve_entry_id_by_slug(session, group_id, slug: str):
    """Resolve an entry SLUG to its id within the workspace. Raises if there's no such entry."""
    from marvin.db.models.platform.entries import Entries

    entry = session.query(Entries).filter_by(group_id=group_id, slug=slug).first()
    if not entry:
        raise AutomationActionError(f"no entry with slug '{slug}' in this workspace")
    return entry.id


def _apply_writeback(session, group_id, entity_id, proposed: dict, user_id, depth: int = 0) -> None:
    """Apply an op's write-back to an entry via the entry domain service.

    Routing through EntryService (instead of mutating + hand-dispatching here) means a write-back
    that changes status now emits the *right* events — entry_published / entry_unpublished /
    entry_archived / entry_restored — not just a bare entry_updated. So chained automations that key
    on publish fire reliably. The events carry ``reaction_depth = depth + 1`` so the loop-guard still
    bounds any chain, and ``integration_id="automation"`` tags them as automation-sourced.
    """
    from marvin.services.entries import EntryService

    EntryService(session, group_id, actor_id=user_id, integration_id="automation").apply_fields(entity_id, proposed, reaction_depth=depth + 1)
