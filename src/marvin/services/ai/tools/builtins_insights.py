"""Built-in insights tools — workspace introspection (AI executions, settings, events, tasks).

These read/query surfaces used to be hand-written a second time in MarvinMCP's `insights` capability
(TypeScript over REST). They now live in the core tool registry — one definition the internal agent
binds in-process AND MarvinMCP projects outward via `GET /api/ai/tools`, so a change here reaches both
with zero MCP code. Read-only. AI executions and the event log are gated at VIEWER, like their routes.
Scheduled tasks and the workspace AI policy are workspace settings, so those tools need ADMIN, matching
the scheduled-task routes (a VIEWER asking the agent must not see what the settings pages refuse them).

Handlers reuse the same repos the platform controllers use, so the shapes match what the REST endpoints
return. Return a JSON string (fed to the model verbatim / parsed by the invoke endpoint).
"""

import json

from marvin.repos.all_repositories import get_repositories

from ..operations.base import ROLE_ADMIN, ROLE_VIEWER
from .base import ToolContext, register_tool


def _repos(ctx: ToolContext):
    return get_repositories(ctx.session, group_id=ctx.group_id)


def _dump(value) -> str:
    return json.dumps(value, default=str)


@register_tool(
    name="list_ai_executions",
    description="List recent AI operation executions in this workspace (operation, status, model, tokens, cost, timing). Optionally filter by status, operation slug, or entity_type. Use to see what AI has run and how much it cost.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "filter by status (e.g. completed, failed, running)"},
            "operation": {"type": "string", "description": "filter by operation slug (e.g. generate-summary)"},
            "entity_type": {"type": "string", "description": "filter by entity type (entry, asset, …)"},
            "limit": {"type": "integer", "description": "max rows (default 25)"},
        },
    },
    min_role=ROLE_VIEWER,
)
def list_ai_executions(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai.agents import agent_names, operation_label

    q = ctx.session.query(AIExecutionModel).filter(AIExecutionModel.group_id == ctx.group_id)
    if args.get("status"):
        q = q.filter(AIExecutionModel.status == args["status"])
    if args.get("operation"):
        q = q.filter(AIExecutionModel.operation_slug == args["operation"])
    if args.get("entity_type"):
        q = q.filter(AIExecutionModel.entity_type == args["entity_type"])
    limit = min(int(args.get("limit", 25) or 25), 100)
    rows = q.order_by(AIExecutionModel.started_at.desc()).limit(limit).all()
    names = agent_names(ctx.session, ctx.group_id)
    out = [
        {
            "id": str(r.id),
            "operation": r.operation_slug,
            "operationLabel": operation_label(r.operation_slug, names),
            "status": r.status,
            "provider": r.provider_type,
            "model": r.model_id,
            "triggerType": r.trigger_type,
            "entityType": r.entity_type,
            "entityId": str(r.entity_id) if r.entity_id else None,
            "totalTokens": r.total_tokens,
            "estimatedCostUsd": r.estimated_cost_usd,
            "durationMs": r.duration_ms,
            "error": r.error_message,
            "startedAt": r.started_at,
        }
        for r in rows
    ]
    return _dump({"executions": out, "count": len(out)})


@register_tool(
    name="get_ai_execution",
    description="Get one AI execution by id, including its input and output JSON (the full record). Use after list_ai_executions to inspect what a run produced or why it failed.",  # noqa: E501
    input_schema={"type": "object", "properties": {"id": {"type": "string", "description": "the execution id"}}, "required": ["id"]},
    min_role=ROLE_VIEWER,
)
def get_ai_execution(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai.agents import agent_names, operation_label

    r = ctx.session.get(AIExecutionModel, args.get("id"))
    if not r or r.group_id != ctx.group_id:
        return _dump({"error": "AI execution not found in this workspace"})
    return _dump(
        {
            "id": str(r.id),
            "operation": r.operation_slug,
            "operationLabel": operation_label(r.operation_slug, agent_names(ctx.session, ctx.group_id)),
            "status": r.status,
            "provider": r.provider_type,
            "model": r.model_id,
            "triggerType": r.trigger_type,
            "entityType": r.entity_type,
            "entityId": str(r.entity_id) if r.entity_id else None,
            "input": r.input_json,
            "output": r.output_json,
            "promptTokens": r.prompt_tokens,
            "completionTokens": r.completion_tokens,
            "totalTokens": r.total_tokens,
            "estimatedCostUsd": r.estimated_cost_usd,
            "durationMs": r.duration_ms,
            "error": r.error_message,
            "startedAt": r.started_at,
            "completedAt": r.completed_at,
        }
    )


@register_tool(
    name="get_ai_settings",
    description="Get this workspace's AI policy (enabled, credential mode, approval mode, provider/model, invocation sources). Use to explain why AI is on/off or a source is blocked. Never returns secrets.",  # noqa: E501
    input_schema={"type": "object", "properties": {}},
    min_role=ROLE_ADMIN,
)
def get_ai_settings(ctx: ToolContext, _args: dict) -> str:
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    row = ctx.session.query(WorkspaceAISettingsModel).filter_by(group_id=ctx.group_id).first()
    if not row:
        return _dump({"enabled": True, "credentialMode": "platform", "note": "defaults (no settings row yet)"})
    return _dump(
        {
            "enabled": row.enabled,
            "credentialMode": row.credential_mode,
            "approvalMode": row.approval_mode,
            "provider": row.provider,
            "model": row.model,
            "invocationSources": row.invocation_sources,
            "externalMcpEnabled": row.external_mcp_enabled,
        }
    )


@register_tool(
    name="list_events",
    description="List recent events from the workspace audit log (entry/asset/collection lifecycle, automations, …). Optionally filter by event_type, entity_type, or correlation_id (to follow one causal chain). Use for 'what happened recently' or to trace a cascade.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "event_type": {"type": "string", "description": "e.g. entry_published"},
            "entity_type": {"type": "string", "description": "entry | asset | collection | …"},
            "correlation_id": {"type": "string", "description": "follow one causal chain across events"},
            "limit": {"type": "integer", "description": "max rows (default 25)"},
        },
    },
    min_role=ROLE_VIEWER,
)
def list_events(ctx: ToolContext, args: dict) -> str:
    events = _repos(ctx).event_log.get_by_workspace(
        workspace_id=ctx.group_id,
        event_type=args.get("event_type"),
        entity_type=args.get("entity_type"),
        correlation_id=args.get("correlation_id"),
        limit=min(int(args.get("limit", 25) or 25), 100),
    )
    out = [
        {
            "eventType": e.event_type,
            "occurredAt": e.occurred_at,
            "entityType": e.entity_type,
            "entityId": str(e.entity_id) if e.entity_id else None,
            "correlationId": e.correlation_id,
            "title": e.message_title,
        }
        for e in events
    ]
    return _dump({"events": out, "count": len(out)})


@register_tool(
    name="get_entity_history",
    description="Get the full event history for one entity (entry, asset, …) by id — every lifecycle event, newest first. Use to answer 'what happened to this entry'.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "the entity's id"},
            "entity_type": {"type": "string", "description": "optional filter (entry, asset, …)"},
            "limit": {"type": "integer", "description": "max rows (default 50)"},
        },
        "required": ["entity_id"],
    },
    min_role=ROLE_VIEWER,
)
def get_entity_history(ctx: ToolContext, args: dict) -> str:
    events = _repos(ctx).event_log.get_by_entity(
        entity_id=args.get("entity_id"),
        entity_type=args.get("entity_type"),
        limit=min(int(args.get("limit", 50) or 50), 100),
    )
    events = [e for e in events if str(e.workspace_id) == str(ctx.group_id)]
    out = [
        {
            "eventType": e.event_type,
            "occurredAt": e.occurred_at,
            "correlationId": e.correlation_id,
            "title": e.message_title,
        }
        for e in events
    ]
    return _dump({"entityId": str(args.get("entity_id")), "events": out, "count": len(out)})


@register_tool(
    name="list_scheduled_tasks",
    description="List the workspace's scheduled tasks (name, slug, schedule, enabled, last run + status, next run). Use for 'what's scheduled' or 'is task X enabled'.",  # noqa: E501
    input_schema={"type": "object", "properties": {}},
    min_role=ROLE_ADMIN,
)
def list_scheduled_tasks(ctx: ToolContext, _args: dict) -> str:
    tasks = _repos(ctx).scheduled_tasks.get_all(order_by="name")
    out = [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "taskType": t.task_type,
            "enabled": t.enabled,
            "scheduleType": t.schedule_type,
            "lastRunAt": t.last_run_at,
            "lastStatus": t.last_status,
            "nextRunAt": t.next_run_at,
            "failureCount": t.failure_count,
        }
        for t in tasks
    ]
    return _dump({"tasks": out, "count": len(out)})


@register_tool(
    name="get_scheduled_task_history",
    description="Get recent execution history for one scheduled task by id or slug (each run's status, duration, error). Use to see whether a task is succeeding.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "task id or slug"},
            "limit": {"type": "integer", "description": "max runs (default 25)"},
        },
        "required": ["task"],
    },
    min_role=ROLE_ADMIN,
)
def get_scheduled_task_history(ctx: ToolContext, args: dict) -> str:
    repos = _repos(ctx)
    ref = str(args.get("task") or "")
    task = None
    try:
        import uuid as _uuid

        task = repos.scheduled_tasks.get_one(_uuid.UUID(ref))
    except (ValueError, TypeError):
        pass
    if task is None:
        task = repos.scheduled_tasks.get_by_slug(ref)
    if not task:
        return _dump({"error": f"scheduled task '{ref}' not found — pass its id or slug"})
    runs = repos.scheduled_task_executions.get_task_history(task.id, limit=min(int(args.get("limit", 25) or 25), 100))
    out = [
        {
            "executedAt": r.executed_at,
            "status": r.status,
            "durationMs": r.duration_ms,
            "error": r.error_message,
            "retryAttempt": r.retry_attempt,
        }
        for r in runs
    ]
    return _dump({"task": task.slug, "runs": out, "count": len(out)})
