# Scheduled tasks

Run a handler on an interval or once, from a workspace or platform-wide, with an execution log, manual runs and a new handler that polls an integration.

## What it does

A scheduled task is a row with a schedule and a handler:

| Field | Meaning |
|---|---|
| `name`, `slug`, `description`, `enabled` | slug is generated from the name; `enabled` defaults to `true` on the API, but a task applied from a blueprint is created disabled (`847631de`) |
| `schedule_type` | `interval` or `once`. The schema also accepts `cron`, but `ScheduledTasksRepository._compute_next_run` returns `None` for it, so a cron task never becomes due |
| `schedule_config` | `interval`: `{"interval_seconds": 120}` · `once`: `{"run_at": "2026-10-01T09:00:00Z"}` |
| `task_type` | a registered handler name (table below) |
| `task_config` | handler-specific JSON; the handler's `config_schema` (from `task-types?detailed=true`) describes it, but it is not validated on save |
| `retry_policy` | stored and exported with the workspace; not consulted by the runner (not verified beyond that) |
| `last_run_at`, `last_status`, `last_duration_ms`, `failure_count`, `next_run_at` | runtime state |

**Runner.** Every `SCHEDULER_INTERVAL_SECONDS` the scheduler leader runs `check_scheduled_tasks`, which selects enabled tasks with `next_run_at <= now` and emits `scheduled_task_triggered`. The listener runs the handler, writes an execution row, updates state, recomputes `next_run_at` (a `once` task has it cleared) and emits `scheduled_task_completed` or `scheduled_task_failed`. A failure increments `failure_count` and still reschedules, so the task retries on its normal cadence. A task can fire up to one interval late.

**Execution log.** A handler returns a one-line summary, or `None` for "nothing happened". Since `c34e516f` a routine run that returns `None` writes no row, so a frequent poller does not bury real runs under "nothing happened" rows; `last_run_at` and `last_status` still update. A run you trigger by hand arrives with a different `integration_id` and is always logged, as `Nothing to do.` when the handler had nothing to say. The `prune_scheduled_task_executions` system task keeps the table bounded (`ce6b4c5f`).

**Handlers** (`task_type` → purpose, `task_config`):

| `task_type` | Purpose | Config (defaults) |
|---|---|---|
| `publish_scheduled_entries` | publish entries whose `publish_at` has arrived | `dry_run` (false) |
| `unpublish_expired_entries` | archive entries whose `expire_at` has passed | `dry_run` (false) |
| `request_site_rebuild` | queue a static-site rebuild; the scheduler sends one `webhook_triggered` per workspace once requests go quiet ([Operations → Site rebuilds](../operations.md#site-rebuilds)) | `reason` (`scheduled`) |
| `ai_reindex_embeddings` | rebuild the search index: published entries, resources and assets, in batches, skipping unchanged items (all workspaces for a system task) | `{}` |
| `run_automation` | run a workspace automation (the schedule trigger for Workflows) | `automation_id` (required) |
| `media_enrich` | run the entry type's recipe media derivations on one entry | `entry_id` (required) |
| `run_integration_action` | call one provider action on one integration | see below |
| `prune_expired_invitations` | delete invitations older than N days | `age_days` (30) |
| `remove_orphaned_assets` | report or delete assets linked to no entry | `age_days` (30), `auto_delete` (false) |
| `prune_expired_sessions` | no-op (JWTs are stateless) | none |
| `cleanup_temp_files` (admin) | delete old temporary uploads | `age_hours` (24), `dry_run` (false) |
| `prune_event_logs` (admin) | delete audit events past retention | `retention_days` (`EVENT_LOG_RETENTION_DAYS`) |
| `prune_ai_executions` (admin) | delete AI executions past retention | `retention_days` (per-workspace `logging_config.retention_days`, else `AI_EXECUTION_RETENTION_DAYS`) |
| `prune_scheduled_task_executions` (admin) | delete execution rows past retention | `retention_days` (30; `<= 0` disables) |
| `resync_smart_collections` (admin) | reconcile smart-collection membership from rules | none |

Admin-only handlers run as system tasks (`group_id = NULL`) and are hidden from the workspace task-type list. Automations may only call `request_site_rebuild`, `publish_scheduled_entries`, `unpublish_expired_entries`, `ai_reindex_embeddings`, `resync_smart_collections` and `media_enrich` (`AUTOMATION_ALLOWED_HANDLERS`); `run_integration_action` is deliberately excluded because an action may have side effects.

**System tasks** seeded at every startup (idempotent by slug, daily interval): `prune_event_logs`, `prune_ai_executions`, `prune_scheduled_task_executions` (`retention_days: 30`) and `resync_smart_collections`.

### `run_integration_action`

Calls `provider.run_action(action, args, ctx)` for one workspace integration, feeding entries in and persisting returned records as entries. `task_config`:

```json
{
  "integration": "<integration slug>",
  "action": "<action key>",
  "args": {},
  "inputs": {
    "rules": {"entry_type": "rule", "status": "published", "as": "records"},
    "seen_ids": {"entry_type": "action-log", "as": "field", "field": "external_id"}
  },
  "outputs": {
    "records_entry_type": "action-log",
    "slug_prefix": "log-",
    "slug_field": "external_id",
    "title_template": "Handled {external_id}",
    "status": "draft"
  }
}
```

- `integration` (the integration's slug in this workspace), `action` (the provider action key): required; the task is skipped with a message if the integration is missing, disabled, or its provider is not installed.
- `inputs`: each key becomes an argument. `as: "records"` passes each entry's `data_json` plus `slug` and `title`; `as: "field"` passes a list of one field's values (`field`, default `comment_id`). Entries are loaded oldest-first so "first rule wins" is stable.
- `outputs`: each record in the result's `records` becomes an entry of `records_entry_type` with slug `slug_prefix + record[slug_field]` (`slug_field` also defaults to `comment_id`); an existing slug is skipped (that is the dedupe). `title_template` is formatted from the record plus `slug` (default `{slug}`); `status` defaults to `draft`.
- A `secret_update` in the result rotates the integration's credential in the secret backend (`secret_ref`, else `INTEGRATION_<SLUG>`) and is never logged.
- The run is logged only when something happened: records created, a rotation, `sent` or `matched` counts, a failed skip reason, or a dry run that `would_send`.

## Where

- Workspace: **Settings → Automation → Scheduler** (`/workspace/scheduled-tasks`), with `/new`, `/{id}` (edit, **Run Now**) and `/log` (**Activity Log**).
- Platform-wide (system tasks): **Admin Settings → Scheduler** (`/admin/scheduled-tasks`) with the same sub-pages.

!!! note "`task_config` is not editable in the UI"
    The create form sends `task_config: {}` and the edit form has no field for it. Set it with `PATCH /api/scheduled-tasks/{id_or_slug}` (or the admin route), or apply a blueprint or seed script.

## How to use

1. `GET /api/scheduled-tasks/task-types?detailed=true` to see handlers and their `config_schema`.
2. Create the task in the UI or with `POST /api/scheduled-tasks` (`interval_seconds` or `run_at`). Keep it disabled while you fill in `task_config` by PATCH.
3. **Run Now**, or `POST /api/scheduled-tasks/{id_or_slug}/execute`, to run it now (202; the run is always logged), then check `.../history`.
4. Enable it. Watch `GET /api/scheduled-tasks/log` for the workspace-wide log.

## API

Workspace routes take an id or a slug; admin routes (`/api/admin/scheduled-tasks`) take an id. Reference: [`../api/`](../api/index.md).

| Method and path | Purpose |
|---|---|
| `GET /api/scheduled-tasks/task-types?detailed=` | handlers available to the workspace (admin-only ones excluded) |
| `GET` / `POST /api/scheduled-tasks` | list / create |
| `GET` / `PATCH` / `DELETE /api/scheduled-tasks/{id_or_slug}` | read / update (slug and workspace cannot change; a schedule change recomputes `next_run_at`) / delete |
| `POST /api/scheduled-tasks/{id_or_slug}/execute` | manual run, returns 202 and emits `scheduled_task_triggered` |
| `GET /api/scheduled-tasks/{id_or_slug}/history?limit=50` | that task's execution rows (`executed_at`, `status`, `duration_ms`, `output`, `error_message`, `retry_attempt`) |
| `GET /api/scheduled-tasks/log?limit=100` | all executions in the workspace |

Agents and MCP clients read the same data through the `list_scheduled_tasks` and `get_scheduled_task_history` tools.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `SCHEDULER_ENABLED` | `true` | whether this process joins the scheduler at all; safe to leave on across replicas |
| `SCHEDULER_INTERVAL_SECONDS` | `60` (min 10) | cadence of the tick that fires due tasks, delivers webhooks and renews the lease |
| `SCHEDULER_LEASE_TTL_SECONDS` | `150` | lease lifetime; validated to be at least 2× the interval or leadership flaps |

**Leader election.** Every replica starts the scheduler, but a tick runs only in the process holding a lease on a single `scheduler_lock` row. The claim is a conditional `UPDATE` (renew if mine, or take it if expired), so the database picks the winner on SQLite and Postgres alike; a dead leader is replaced within the TTL, and a clean shutdown releases the lease immediately. If the database cannot be reached the process treats itself as not the leader and skips the tick.

## Since

`run_integration_action`: rc.78 (`49490df8`). Quiet no-op runs, manual runs always logged, prune handler: rc.96 (`c34e516f`). Prune shipped as a system task: rc.97 (`ce6b4c5f`). Coalesced `request_site_rebuild`: rc.121; leader election and the `SCHEDULER_*` settings predate these.

## Related

- [Agents and Ask](agents-and-ask.md) — the `automation_read` category exposes task history to agents.
- [Marvin as an MCP server](marvin-as-mcp-server.md) — `marvin_list_scheduled_tasks`, `marvin_get_scheduled_task_history`.
- [Glossary](../glossary.md) · [API reference](../api/index.md)
