# The assistant can work out what went wrong (diagnostics tools)

Status: **approved — building** (2026-10-24; Jared: "yes plan it, push when done")

## Why

Asked "why did X fail?", the bubble / Ask could see only a workflow's **last** run summary, event titles, AI executions and
scheduled-task history. It couldn't open a run's steps, an earlier run, an event's data, Automation Results, the webhook
logs, connection health or the Social engine's report — so this week's failures (Bluesky's HTTP 501 engine runs, the
Instagram webhook's 401 signature refusals, the double DM reply) needed the server log or a person.

## Rules every new tool follows

- **Read-only**, category `automation_read` / `insights` (agents get them under Allow; nothing asks).
- **Never more than the page shows:** each tool requires the role the matching admin route requires, and scopes the same way.
- **Untrusted, bounded output:** lists default to 10–25 rows (max 50); every free-text field is capped; payloads and
  response bodies come back as a short excerpt plus their length, never whole. Secrets redacted as the code already does.
- Few tools with filters rather than many tools (the registry is ~60 already).
- They reach the claude.ai connector automatically (`services/mcp_remote`), so they're testable there after deploy.

## Tools

1. `list_workflow_runs` — runs of one workflow or all: `workflow`, `status` (failed…), `since`, `limit`. Each: id,
   workflow, trigger, status, started, duration, steps ok/failed, error (capped), retry_of, handled.
2. `get_workflow_run` — one run by id: the run, then each step: index, kind, label, status, error, duration, a capped
   excerpt of its output, its error handling.
3. `get_event` — one logged event by id: type, time, entity, message, and its **data** (capped values; no secrets — the
   event payloads never carry them). `list_events` gains `id` per row so it can be followed.
4. `list_automation_results` — hand-off results: status (in_flight / succeeded / failed), integration, workflow, entry,
   message (capped), sent / finished.
5. `list_webhook_deliveries` — outgoing webhook attempts: webhook, status, HTTP code, error (capped), attempt, time,
   request/response excerpts.
6. `connection_health` — every integration: status, last error (redacted, capped), last success, last checked; and every
   incoming webhook: enabled, received count, last received, **last refused** (time, reason) and refused count.
7. `get_scheduled_task_history` gains each run's **output** (capped) — the Social engine's report ("matched 2, replied 2,
   bluesky failed: …").

## Refused incoming deliveries (the one write path)

Refusals were only in the server log. Three columns on `workspace_incoming_webhooks` (migration): `refused_count`,
`last_refused_at`, `last_refused_reason` ("signature rejected", "verification refused", "disabled"). Written **only when the
URL's token matched a webhook** (a scanner with a wrong token writes nothing), never the payload, best-effort (a failed write
never changes the response). The incoming webhooks card shows "last refused …"; `IncomingWebhookRead` gains the three
fields (SDK regenerated).

## Verification

Unit tests per tool: roles, scoping, caps/redaction, the refusal record (written on a bad signature with a good token; not on
a bad token). After deploy, call the tools through the connector on this week's real cases.
