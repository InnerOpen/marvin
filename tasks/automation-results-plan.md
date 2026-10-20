# Automation results: what happened to the work Marvin handed off (2026-10-20)

Jared: "lets not code to tech (n8n) but rather to 'automation results'"; "now lets get the N8N out of collection and in to
whatever it need". n8n is the first source; the shape is any connection's.

## Today (n8n plugin v0.3.0)
- The hand-off recipe's `trigger_workflow` step starts an n8n workflow, then a `set_metadata` step writes `n8n_status: sent`,
  `n8n_workflow`, `n8n_execution_id` on the entry.
- n8n reports back on the `n8n` incoming webhook; the `n8n-record-result` workflow writes `n8n_status` (success | error |
  waiting), `n8n_finished_at`, `n8n_message` on the entry.
- Two private smart collections read that metadata: **n8n: failed** (`error`) and **n8n: in flight** (`sent` | `waiting`).
- Problems: results are content collections (they sit in Collections with the content); one entry keeps only its last
  hand-off; the keys are n8n's; a failure is noticed only by opening the collection.

## The model (core)
- **One record per hand-off**, table `automation_results`: workspace, entry (nullable: a hand-off needn't be about an entry),
  integration (the connection), workflow (the Marvin workflow that sent it, nullable), `target` (what was asked, e.g. the n8n
  workflow path, as the provider names it), `remote_id` and `remote_url` (the run on the other side), `status`
  (`in_flight` | `succeeded` | `failed`), `message`, `sent_at`, `finished_at`, `attempt`.
  - Words are Marvin's, not n8n's: n8n's `waiting` is in flight, `success` succeeded, `error` failed (the provider maps).
- **Recording is automatic, not a recipe step.** An integration action that hands work off declares it (an SDK
  `ActionSpec` flag, e.g. `hands_off=True`, with the output keys for the remote id and URL); the engine then writes an
  `in_flight` record when the step succeeds and a `failed` one when the call itself fails. No `set_metadata` step to remember.
- **Reporting back is one core step:** `{"kind": "automation_result", "remote_id" | "entry_id", "status", "message",
  "finished_at"}`, used by n8n's record-result workflow. It finds the record (by the remote id, else the newest in-flight one
  for that entry and connection) and settles it. Unknown → recorded as a fresh result rather than dropped.
- **Stale:** a record in flight past a timeout (default 24h, per connection later if needed) shows as **No reply**
  (still `in_flight`, flagged), so a lost callback is visible. No automatic failure.
- **Retention:** succeeded results kept 30 days, failed and in flight until handled or 180 days (as Social).

## Where it shows
- **Settings › Automation › Results** (`/automation/results`), next to Approvals, Events and Metrics: compact rows (entry,
  connection with its logo, target, status badge, when, message), filters (status: in flight · no reply · failed ·
  succeeded; connection; search), detail with "Open entry", "Open the run" (remote URL) and **Retry** (re-runs the Marvin
  workflow's hand-off step for that entry; ADMIN), and **Dismiss** for a failure that's been dealt with.
  - Drawn only once a hand-off has happened (the "features appear when used" rule); the Automation hub gets the tab then.
- **Dashboard attention:** "Hand-offs failed (N)" and "No reply (N)" lines linking to the filtered Results page. In flight
  is routine, not a to-do.
- **The entry editor:** a small line under the status for an entry with a recent hand-off ("Sent to n8n · in flight",
  "n8n failed: …" with Open the run), so the person editing sees it.
- Not in the sidebar: Automation isn't there today, and the dashboard plus the editor line cover attention.

## n8n plugin (release v0.4.0)
- `trigger_workflow` declares `hands_off` (remote id `execution_id`, URL `execution_url`); the map n8n status → Marvin status.
- The hand-off recipe drops its `set_metadata` step; `n8n-record-result` uses the `automation_result` step.
- Stops shipping the two collections. README and guide updated.

## Core cleanup (migration)
- Remove `n8n-failed` and `n8n-in-flight` where they are still exactly the plugin's (the Buttondown pattern: smart, private,
  the plugin's rules, no other provenance).
- Turn each entry's `n8n_*` metadata into one result record (status mapped), then remove those keys. Small and makes the
  switch lossless. Workflows a workspace installed from the old blueprints are updated by the plugin's re-apply, not by
  the migration.

## Decisions (my recommendations; Jared to confirm)
1. **Scope now:** n8n only, on the generic model. Later sources each a small change: social posts (`social.post` already
   records per network), Buttondown sends, Cloudflare builds.
2. **The n8n collections:** removed where untouched, as Buttondown's were. A renamed or edited one stays (it's yours).
3. **Where:** Settings › Automation › Results plus the dashboard and the editor line; no sidebar item.

## Phases
1. Core: table, the engine hook and SDK flag, the `automation_result` step, the Results page, dashboard, editor line,
   migration. SDK release (integration SDK for the flag; the TS SDK for the API).
2. n8n v0.4.0, pinned. Ship.

## Tests
Engine records in flight / failed for a `hands_off` action and nothing for others; the step settles by remote id and by
entry; unknown results recorded; No reply after the timeout; retry and dismiss (roles); retention; the page's API filters;
dashboard counts; the migration (collections untouched/edited, metadata import) on both engines; n8n recipe and blueprints
validate against the new core.

## Review: phase 1 (core) built 2026-10-25

### What was built
- **Table and migration** `d3b9f27a6c14` (after `c4e8a2d19f57`): `automation_results` (group, entry, integration, workflow, `action`, `target`, `remote_id`, `remote_url`,
  `status`, `message`, `sent_at`, `finished_at`, `attempt`, `dismissed_at`/`dismissed_by`). Deleted with the workspace, the connection and the entry; the workflow
  is `SET NULL`. The same migration removes `n8n-failed` / `n8n-in-flight` only where each is still exactly the plugin's (name, smart, private, the plugin's rules,
  `source_blueprint` empty or its own slug), imports each entry's `n8n_*` metadata as one result (`sent`/`waiting` in flight, `success` succeeded, `error` failed;
  attached to the workspace's `n8n` connection when there is exactly one) and removes those keys. Downgrade drops the table and puts nothing back.
- **SDK 0.13.0** (`~/code/MarvinIntegrationSDK`): `ProviderAction.hands_off = HandsOff(remote_id, remote_url, target, statuses)`, the `RESULT_*` words, `hands_off_problems`
  (checked at `@register_provider`; the conformance kit asserts it), and the hook `IntegrationProvider.result_status(word, action=None)` (default: the declared map,
  plus Marvin's own three).
- **Engine hook** (`services/automation/actions/integration.py` → `services/automation_results.py: track`): in flight when a hands-off step succeeds, failed (with the
  redacted provider message) when the call fails. A dry run, an idempotency-skipped step and an action with no `hands_off` record nothing. Runs in a savepoint and never
  breaks the step. A retry run (the error policy's) or a person's Retry reuses the failed row and counts up `attempt`.
- **`automation_result` step**: model + union in `automation_definition.py`, executor, `AUTOMATION_RESULT_MIN_ROLE` (AUTHOR), authoring note, editor labels (both copies),
  workflow editor form. Settles by `remote_id`, else the newest in-flight row for the entry and connection; a report that matches nothing is kept as a new row.
- **No reply**: computed from `sent_at` (24 h), never a status. **Retention**: `prune_automation_results` (daily; 30 days settled or dismissed, 180 unhandled), listed in the
  database report.
- **API** `/api/groups/automation-results` (EDITOR+ reads, ADMIN retries and dismisses), the dashboard attention fields `resultsFailed` / `resultsNoReply`.
- **Frontend**: `/automation/results` (tiles as tabs, connection filter, search, compact rows, detail dialog), the Results card in Settings › Automation (only once a result
  exists), two dashboard lines, the entry editor line, the step form. No sidebar item.
- **Docs**: the manual page `whats-new/automation-results.md`, the step reference in `workflows.md`, the SDK's `hands_off` in `integrations.md` and the SDK README.

### What differs from the plan, and why
- **The step takes an `integration` argument** (optional). The plan's step shape had none, but the plan also says "the newest in-flight record for that entry *and connection*",
  and the provider's words can only be mapped by knowing the connection. Without it only Marvin's own words are understood, unless the report finds a result (its connection
  then reads the word). Also `target` (kept on a record the report creates).
- **An unknown status word** (the plan only said an unknown *result* is recorded): the row stays in flight with the word in its message, so nothing is guessed to have
  succeeded or failed.
- **Retry** is the full version, not the simpler one: it re-runs only the one hand-off step (`engine.run_step_once`), refuses with the reason when that is not safe
  (workflow gone or off; step gone or ambiguous; entry gone or no longer matching the conditions; the step reads `event` / `steps` / `previous`, which belong to the run that is over).
  A repeat does not schedule the provider's own retries behind the person's back (connection-level notify only) and leaves no workflow run in the history.
- **Dismiss and `action`** need two columns the plan's list did not name (`dismissed_at`/`dismissed_by`; `action`, to find the step again).
- **The workflow authoring guide's `SECTION_BUDGET` goes from 16,000 to 16,500 characters**: the `actions` section had 37 characters of room, so any new step kind overflowed it. The
  step is documented in the guide's `records` section (like `metric` and `snapshot`), keeping its entry in `actions` to one line.
- **The SDK has no RELEASE_PROCESS.md or CHANGELOG** (the brief names both). Its convention is the version in `pyproject.toml` and `__init__.py`, plus a README note; that is what
  0.13.0 does.
- **An imported result's time**: n8n never recorded when a hand-off was sent, so an old "sent" with no report is dated by when the entry last changed and reads No reply.

### Open points
- Marvin still pins the SDK at `v0.12.0` (pyproject lines 23 and 120, and `uv.lock`); tests need 0.13.0. Switch the pin when the tag exists.
- Phase 2 (n8n 0.4.0): `trigger_workflow` declares `HandsOff(remote_id="execution_id", remote_url="execution_url", target="path", statuses={"success": "succeeded", "error": "failed",
  "waiting": "in_flight"})`; the recipe drops its `set_metadata` step; `n8n-record-result` becomes an `automation_result` step (pass `integration`, `remote_id`, `entry_id`, `target`);
  stop shipping the two collections. Workflows installed from the old blueprints keep writing the metadata until the plugin's re-apply.
- The OpenAPI spec changed (new paths and schemas, two fields on `AttentionCounts`): regenerate the TS SDK.
- Not built, by design: a per-connection No reply timeout; automatic failure of a silent hand-off; hand-offs from social posts, Buttondown and Cloudflare builds.
