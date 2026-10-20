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
