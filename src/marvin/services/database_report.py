"""Admin → Database & cleanup: how big the database is, which tables are the bulk of it, and what keeps each one in
check — the system task that trims it, the retention it trims to, and when it last and next runs. A table nothing
trims says so, which is the point: it's the one that grows forever.

Postgres only (the only engine since 2026-10-13). Row counts are the planner's live-tuple estimates
(pg_stat_user_tables), good to a few percent and free to read; sizes include indexes and TOAST.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa

from marvin.schemas.admin.maintenance import CleanupTaskRead, DatabaseReport, DatabaseTableRead

TABLES_SHOWN = 12


@dataclass(frozen=True)
class Kept:
    """What trims a table: the system task's slug, and how its retention is described (``days`` is resolved live)."""

    task: str
    setting: str | None = None  # the app setting a task's retention_days defaults to
    default_days: int | None = None  # the handler's own default when there is no setting
    rule: str | None = None  # a rule that isn't "older than N days"


# What each table holds, in words, and what (if anything) trims it. A table not trimmed is either content (kept on
# purpose: entries, assets…) or a log that only grows — LOGS says which, so the page warns only about the latter.
LOGS = {
    "ai_embeddings",
    "automation_executions",
    "automation_action_executions",
    "integration_retries",
    "ai_thread_messages",
    "webhook_execution_logs",
    "backup_runs",
    "media_embed_cache",
    "workflow_waits",
    "workflow_approvals",
}
TABLES: dict[str, tuple[str, Kept | None]] = {
    "event_log": ("Event log (every event, with its data)", Kept("prune_event_logs", setting="EVENT_LOG_RETENTION_DAYS")),
    "ai_executions": ("AI runs (tokens, cost, output)", Kept("prune_ai_executions", setting="AI_EXECUTION_RETENTION_DAYS")),
    "scheduled_task_execution_log": ("Scheduled task history", Kept("prune_scheduled_task_executions", default_days=30)),
    "long_live_tokens": ("API tokens", Kept("prune_revoked_tokens", rule="revoked over 30 days ago")),
    "api_clients": ("Site clients", Kept("prune_revoked_tokens", rule="revoked over 30 days ago")),
    "ai_embeddings": ("Search embeddings (RAG)", None),
    "automation_executions": ("Workflow runs", Kept("prune_workflow_runs", setting="WORKFLOW_RUN_RETENTION_DAYS")),
    "automation_action_executions": ("Workflow run steps", Kept("prune_workflow_runs", setting="WORKFLOW_RUN_RETENTION_DAYS")),
    "integration_retries": ("Integration retries", None),
    "ai_thread_messages": ("Ask conversation turns", None),
    "ai_threads": ("Ask conversations", None),
    "webhook_execution_logs": ("Outgoing webhook deliveries", None),
    "form_submissions": ("Form submissions", None),
    "entries": ("Entries", None),
    "assets": ("Assets (rows; files are in storage)", None),
    "backup_runs": ("Backup run history", None),
    "media_embed_cache": ("Media embed cache", None),
    "scheduled_tasks": ("Scheduled tasks", None),
    "entry_types": ("Entry types", None),
    "entry_assets": ("Entry ↔ asset links", None),
    "entry_collections": ("Entry ↔ collection links", None),
    "collections": ("Collections", None),
    "resources": ("Resources", None),
    "users": ("Users", None),
    "workflow_waits": ("Workflow waits", None),
    "workflow_approvals": ("Workflow approvals", None),
}

# System tasks that clean something other than a table above (files, the planner), listed on their own.
OTHER_CLEANUP = ("cleanup_temp_files", "optimize_database")


def _days(kept: Kept, task) -> str | None:
    from marvin.core.config import get_app_settings

    if kept.rule:
        return kept.rule
    default = getattr(get_app_settings(), kept.setting, None) if kept.setting else kept.default_days
    config = (task.task_config or {}) if task is not None else {}
    days = config.get("retention_days", default) if config.get("retention_days") is not None else default  # 0 = off, not unset
    if days is None:
        return None
    return "kept forever (retention off)" if int(days) <= 0 else f"older than {int(days)} days"


def _task_read(task, retention: str | None = None) -> CleanupTaskRead:
    return CleanupTaskRead(
        id=task.id,
        slug=task.slug,
        name=task.name,
        enabled=task.enabled,
        retention=retention,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        last_status=task.last_status,
    )


def database_report(session) -> DatabaseReport:
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    size = int(session.execute(sa.text("SELECT pg_database_size(current_database())")).scalar() or 0)
    rows = session.execute(
        sa.text(
            "SELECT relname, pg_total_relation_size(relid) AS bytes, n_live_tup FROM pg_stat_user_tables "
            "ORDER BY pg_total_relation_size(relid) DESC LIMIT :n"
        ),
        {"n": TABLES_SHOWN},
    ).all()
    tasks = {t.slug: t for t in session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id.is_(None)).all()}

    tables = []
    for name, nbytes, live in rows:
        label, kept = TABLES.get(name, (None, None))
        task = tasks.get(kept.task) if kept else None
        tables.append(
            DatabaseTableRead(
                name=name,
                label=label,
                size_bytes=int(nbytes or 0),
                rows=max(int(live or 0), 0),
                share=round(int(nbytes or 0) / size, 4) if size else 0.0,
                kept_by=_task_read(task, _days(kept, task)) if task is not None else None,
                kind="log" if name in LOGS or kept is not None else "content",
            )
        )
    other = [_task_read(tasks[slug]) for slug in OTHER_CLEANUP if slug in tasks]
    return DatabaseReport(size_bytes=size, tables=tables, other_cleanup=other)
