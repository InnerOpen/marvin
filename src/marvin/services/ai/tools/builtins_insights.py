"""Built-in insights tools — workspace introspection (AI executions, settings, events, tasks).

These read/query surfaces used to be hand-written a second time in MarvinMCP's `insights` capability
(TypeScript over REST). They now live in the core tool registry — one definition the internal agent
binds in-process AND MarvinMCP projects outward via `GET /api/ai/tools`, so a change here reaches both
with zero MCP code. Read-only. AI executions and the event log are gated at VIEWER, like their routes.
Scheduled tasks and the workspace AI policy are workspace settings, so those tools need ADMIN, matching
the scheduled-task routes (a VIEWER asking the agent must not see what the settings pages refuse them).
`describe_event` (what sends an event and what reacts to it, from services/events/connections.py) needs ADMIN too,
like the Events pages: it names the workspace's workflows, webhooks, emails and integrations.

Handlers reuse the same repos the platform controllers use, so the shapes match what the REST endpoints
return. Return a JSON string (fed to the model verbatim / parsed by the invoke endpoint).

AI executions follow the execution log's rule: OWNERs/ADMINs see every run, other members only the runs
they triggered (services/ai/executions.py). The event tools apply it to AI-run events the same way.
"""

import json

from marvin.repos.all_repositories import get_repositories

from ..operations.base import ROLE_ADMIN, ROLE_VIEWER
from .base import ToolContext, caller_role, register_tool


def _repos(ctx: ToolContext):
    return get_repositories(ctx.session, group_id=ctx.group_id)


def _dump(value) -> str:
    return json.dumps(value, default=str)


@register_tool(
    name="list_ai_executions",
    description="List recent AI operation executions in this workspace (operation, status, model, tokens, cost, timing); workspace admins see every run, other members only their own. Optionally filter by status, operation slug, or entity_type. Use to see what AI has run and how much it cost.",  # noqa: E501
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
    from marvin.services.ai.executions import sees_every_run, visible_runs

    q = ctx.session.query(AIExecutionModel).filter(AIExecutionModel.group_id == ctx.group_id)
    q = visible_runs(q, sees_all=sees_every_run(ctx.user, caller_role(ctx)), user_id=getattr(ctx.user, "id", None))
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
    from marvin.services.ai.executions import may_see_run, sees_every_run

    r = ctx.session.get(AIExecutionModel, args.get("id"))
    sees_all = sees_every_run(ctx.user, caller_role(ctx))
    if not r or r.group_id != ctx.group_id or not may_see_run(r, sees_all=sees_all, user_id=getattr(ctx.user, "id", None)):
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


def _visible_events(ctx: ToolContext):
    """Other members' AI-run events are admin-only, as in the event log routes."""
    from marvin.services.ai.executions import sees_every_run, visible_events_clause

    return visible_events_clause(sees_all=sees_every_run(ctx.user, caller_role(ctx)), user_id=getattr(ctx.user, "id", None))


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
        visible=_visible_events(ctx),
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
        visible=_visible_events(ctx),
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


_HINT_STOPWORDS = frozenset(
    "a an and are does do event events fire fires happen happens i if is it my of on someone something the to what when who".split()
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    import re

    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())} - _HINT_STOPWORDS


def _as_type(hint: str) -> str:
    return hint.strip().lower().replace(" ", "_").replace("-", "_")


def _resolve_event(hint: str, allowed: list) -> tuple[object | None, list]:
    """The catalog entry `hint` names: an event type (an old name counts as its counterpart), else the entry whose
    name and type share the most words with it ("publish" → entry_published), catalog order breaking ties. Returns
    (entry or None, the other close matches)."""
    from marvin.services.events.event_catalog import canonical_event_type

    by_type = {e.event_type: e for e in allowed}
    exact = by_type.get(canonical_event_type(_as_type(hint)))
    if exact is not None:
        return exact, []
    wanted = _words(hint)
    if not wanted:
        return None, []

    def hits(entry) -> int:
        have = _words(entry.event_type.replace("_", " ")) | _words(entry.name)
        return sum(1 for w in wanted if any(h.startswith(w) or (len(h) > 3 and w.startswith(h)) for h in have))

    scored = sorted(((hits(e), -i, e) for i, e in enumerate(allowed)), key=lambda t: (t[0], t[1]), reverse=True)
    best = [e for n, _, e in scored if n == scored[0][0] and n > 0] if scored else []
    if not best:
        return None, []
    return best[0], best[1:6]


def _ref(entry) -> dict:
    return {"eventType": entry.event_type, "name": entry.name}


def _rows(items) -> list[dict]:
    return [i.model_dump(by_alias=True, mode="json", exclude_none=True, exclude={"managed_at"}) for i in items]


@register_tool(
    name="describe_event",
    description="Explain what happens when an event fires in this workspace — 'what happens when I publish?'. Give an event type (entry_published) or a plain-language hint (publish, site rebuild, form submission). Returns what sends it (Marvin itself, workflows, incoming webhooks, scheduled tasks), everything that reacts to it (workflows, integration actions, emails, webhooks — switched-off ones marked, and what an integration installed — then Marvin's built-in reactions), the events it leads to and is caused by, and when it last happened. Read-only.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "event": {"type": "string", "description": "an event type (e.g. entry_published) or a hint (e.g. 'publish')"},
        },
        "required": ["event"],
    },
    min_role=ROLE_ADMIN,
)
def describe_event(ctx: ToolContext, args: dict) -> str:
    """Workspace OWNER/ADMIN, like the Events pages: it names the workspace's workflows, webhooks, emails and
    integrations. Workspace-scope events only, plus platform events for a super admin (their reactions across
    workspaces, as on the admin Events page)."""
    from marvin.db.models.users.roles import PlatformRole
    from marvin.services.events import connections
    from marvin.services.events.event_catalog import CATALOG, canonical_event_type, get_catalog_entry

    user = ctx.user
    super_admin = getattr(user, "platform_role", None) == PlatformRole.SUPER_ADMIN or bool(getattr(user, "is_superuser", False))
    allowed = [e for e in CATALOG if not e.hidden and (e.scope == "workspace" or super_admin)]
    asked = str(args.get("event") or "")
    named = get_catalog_entry(canonical_event_type(_as_type(asked)))
    if named is not None and named not in allowed:  # a real type this caller can't ask about: say why, don't guess
        why = "nothing sends it" if named.hidden else "it's a platform event (super admins only)"
        return _dump({"found": False, "error": f"{named.event_type} isn't described here: {why}.", "eventTypes": [_ref(e) for e in allowed]})
    entry, others = _resolve_event(asked, allowed)
    if entry is None:
        return _dump({"found": False, "error": f"No event matches {args.get('event')!r}.", "eventTypes": [_ref(e) for e in allowed]})

    out: dict = {
        "found": True,
        "eventType": entry.event_type,
        "name": entry.name,
        "description": entry.description,
        "category": entry.category,
        "scope": entry.scope,
    }
    if entry.scope == "workspace":
        detail = connections.detail(ctx.session, ctx.group_id, entry, limit=1, visible=_visible_events(ctx))
        out |= {
            "sentBy": _rows(detail.senders),
            "reactions": _rows(detail.reactions),
            "recorded": detail.audited,  # False: the Event Log leaves it out, so no lastOccurredAt is "not recorded"
            "lastOccurredAt": detail.recent[0].occurred_at if detail.recent else None,
        }
    else:
        senders, reactions, workspaces = connections.platform_detail(ctx.session, entry)
        rows, _ = _repos(ctx).event_log.page_platform_events(event_type=entry.event_type, page=1, per_page=1)
        out |= {
            "sentBy": _rows(senders),
            "reactions": _rows(reactions),
            "workspaceReactions": [{"workspace": w.workspace_name, "reactions": _rows(w.reactions)} for w in workspaces],
            "lastOccurredAt": rows[0].occurred_at if rows else None,
        }
    out["leadsTo"] = [_ref(get_catalog_entry(t)) for t in entry.leads_to if get_catalog_entry(t)]
    shown = {e.event_type for e in allowed}
    out["causedBy"] = [_ref(e) for e in CATALOG if entry.event_type in e.leads_to and e.event_type in shown]
    if others:
        out["otherMatches"] = [_ref(e) for e in others]
    return _dump(out)


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
