"""Execute a single Flavor B action against a workspace.

v1 supports one action kind: ``operation`` — run an AI operation (e.g. ``generate-summary``) on an
entry and optionally apply its write-back. Runs under the ``"automation"`` invocation source, so the
same gate that protects the MCP/agent surfaces protects automations.

This reuses the already-factored primitives (ContextBuilder, provider factory,
``provider.execute_operation``, the entries repo). It deliberately does NOT import the operations
*controller* — unifying the controller's ``execute_operation`` onto a shared runner is a follow-up
(same debt as the scheduled-agent tool-builder extraction).
"""

import time
from datetime import UTC, datetime

from marvin.services.ai.operations import get_operation

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
        from marvin.core.config import get_app_settings

        app = get_app_settings()
        provider_type = settings.provider or getattr(app, "AI_DEFAULT_PROVIDER", "openai")
        return getattr(app, f"{provider_type.upper()}_MODEL", None)
    return None


def run_operation_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    """Run one ``operation`` action; return its output_json (so ``$previous`` can reference it).

    ``action`` = ``{"kind": "operation", "op": <slug>, "input": {...}, "entity_type": "entry",
    "entity_id": "$event.entry_id", "write_back": true}``. entity_type/entity_id default to an entry
    resolved from ``$event.entry_id``. Raises :class:`AutomationActionError` on any failure — the
    engine logs and moves on; automations never break event dispatch.
    """
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.context import ContextBuilder, resolve_prompt_messages
    from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider

    slug = action.get("op")
    if not slug:
        raise AutomationActionError("action is missing 'op'")
    try:
        operation = get_operation(slug)
    except KeyError as e:
        raise AutomationActionError(f"unknown operation '{slug}'") from e

    _gate_source(session, group_id, operation)
    # Definer's rights: the op runs under the automation author's authority, so enforce the op's own
    # min_role against the author's *current* role (fail-closed if they were demoted/removed). None =
    # a direct caller that didn't thread authz (tests) → treated as OWNER.
    from .authz import ROLE_OWNER, require_role

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, operation.min_role, f"operation '{operation.slug}'")

    # Resolve entity (slice: entries). entity_id may be a $event/$previous template. An action may
    # instead target an entry by SLUG (`entity_slug`) — humans reference entries by slug, not UUID,
    # so a webhook payload that carries `entry_slug` is far more usable than an opaque id.
    entity_type = action.get("entity_type", "entry")
    op_input = interpolate(action.get("input", {}) or {}, context)

    entity_slug = interpolate(action.get("entity_slug"), context) if action.get("entity_slug") else None
    if entity_type == "entry" and entity_slug:
        entity_id = _resolve_entry_id_by_slug(session, group_id, str(entity_slug))
    else:
        entity_id = interpolate(action.get("entity_id", "$event.entry_id"), context)

    if dry_run:
        # Preview: the op is authorized and its inputs/target resolve — but don't call the provider,
        # create an AIExecution row, or write back. (An AI call is the expensive, side-effectful part.)
        return {
            "dry_run": True,
            "kind": "operation",
            "op": slug,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "input": op_input,
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

    builder = ContextBuilder(session, group_id).with_site_settings().with_variables()
    if entity_type == "entry" and entity_id:
        builder.with_entry(entity_id).with_assets(entity_id).with_resources(entity_id)
    ctx = builder.build()

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
        parsed, completion = provider.execute_operation(messages, model, operation.output_schema, opts)

        from marvin.services.ai.pricing import estimate_cost

        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        execution.output_json = parsed
        execution.prompt_tokens = completion.prompt_tokens
        execution.completion_tokens = completion.completion_tokens
        execution.total_tokens = completion.total_tokens
        execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, completion.prompt_tokens, completion.completion_tokens)
        session.commit()
    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)
        execution.completed_at = datetime.now(UTC)
        session.commit()
        raise AutomationActionError(f"operation '{slug}' failed: {e}") from e
    if crossing := budget.crossing_after(session, group_id, execution.estimated_cost_usd):
        budget.emit_crossing(group_id, crossing, user_id=user_id, source=AUTOMATION_SOURCE)

    # Optional write-back of the operation's own writeback map — gated by the workspace approval mode
    # like every other AI write-back: applied when the mode allows it for this entry, else staged as a
    # suggestion for a person to accept. The step output says which (`_write_back`).
    if action.get("write_back") and entity_type == "entry" and entity_id and isinstance(parsed, dict):
        writeback = getattr(operation, "writeback", None) or {}
        proposed = {target: parsed[out] for out, target in writeback.items() if out in parsed}
        if proposed:
            outcome = _write_back(session, group_id, entity_id, proposed, user_id, int(context.get("depth", 0)), slug, execution.id)
            return {**parsed, "_write_back": outcome}

    return parsed if isinstance(parsed, dict) else {}


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
