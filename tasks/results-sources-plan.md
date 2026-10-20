# Automation results: Cloudflare Pages builds and Buttondown sends (2026-10-20)

Jared: "what about the others Like Buttondown and Cloudflare pages" → "do the plan, don't worry about the issue-type".
Builds on `tasks/automation-results-plan.md` (n8n first; live 2026-10-20).

## Core + integration SDK (phase 1)
- **Hand-offs core runs itself are recorded too.** Today only the workflow `integration` step records a `hands_off` action.
  The site rebuild runs the deploy target's integration action from the `webhook_triggered` event subscription (event
  connections), not a workflow step: record it there with the same hook (workflow none; target and remote id from the
  declaration; failure recorded with the redacted message).
- **SDK 0.14.0: `HandsOff.record_if`** — an output key that must be truthy for the hand-off to be recorded (empty = always).
  For an action that sometimes hands off and sometimes doesn't (Buttondown: draft vs send). Checked at registration
  against the output schema like the other keys.
- Tests, docs (`whats-new/automation-results.md`, `integrations.md` hands_off section, SDK README).

## Cloudflare Pages v0.3.0 (phase 2)
- `deploy` declares `HandsOff(remote_id="deployment_id", remote_url="url", statuses={...Cloudflare's words → Marvin's})`.
- The three notification workflows (started / succeeded / failed) each add an `automation_result` step (remote_id = the
  notification's deployment id; failure message = the build log tail, as the toast shows). They keep emitting the
  site_deployment_* events and toasts.
- Blueprint parameter `integration` stays only where the build-log step needs it; the result step infers the connection from
  the webhook.

## Buttondown v0.9.0 (phase 2)
- `create_issue_email` declares `HandsOff(remote_id="email_id", remote_url="url", record_if=<true only when it sent>)`.
  Draft and off are not hand-offs.
- Webhooks: add `email.sent` to the events `connect_webhooks` subscribes; a new workflow `buttondown-email-sent` settles
  the result (`automation_result`, remote_id = the payload's email id, status succeeded).
- **Must not change `buttondown-issue-on-publish`'s definition** (Mash & Burn edited it to send Bench Notes; Update would
  overwrite the edit). No send-failure event exists: a send that never completes shows as No reply.

## Release
Integration SDK v0.14.0 tag → Marvin pin; plugins tagged and pinned; TS SDK if the API changes; existing workspaces click
Update on each card once (the new/changed workflows).

## Review: built 2026-10-26 (core `wl/sources`, SDK 0.14.0, Cloudflare Pages 0.3.0, Buttondown 0.9.0)

### What was built
- **Core: hand-offs core runs itself are recorded.** `IntegrationEventListener.publish_to_subscribers` (what runs an action subscribed to an event through event
  connections, so the site rebuild's `webhook_triggered` → Cloudflare `deploy`) now calls `automation_results.track_direct` after the provider call: in flight with the
  declared remote id and URL, or failed with the redacted message. `track_direct` is the same `track` the integration step uses, in a session of its own (the
  caller's transaction is never touched, as `connection_succeeded` already does in that loop) with no workflow and an entry only when the event is about one
  (`entity_type == "entry"` or an `entry_id` in its data). Delivering an alert never records (the loop guard). Nothing duplicated: one hook, two callers.
- **Core: `HandsOff.record_if`** is honoured in `track`: a successful call records only when that key is truthy in the result; a failed call records nothing (see below).
  An older SDK's declaration (no `record_if`) always records.
- **Core: `settle` never reopens an ended hand-off.** A report that says "in flight" (Cloudflare's *started*) for a result that already succeeded or failed is ignored:
  deliveries are not ordered, and *started* is one of the three notifications that now report.
- **SDK 0.14.0** (`~/code/MarvinIntegrationSDK`): `HandsOff.record_if`; `hands_off_problems` checks it against the `output_schema` (and refuses a `record_if` on an action
  that declares no output properties, since a typo could never be caught); the conformance kit's hands-off check already runs `hands_off_problems`. README section.
- **Cloudflare Pages 0.3.0**: `deploy` declares `HandsOff(remote_id="deployment_id", remote_url="link", statuses=BUILD_STATUSES)`; the three notification workflows each end with
  an `automation_result` step (`status` = the notification's own `event` word, `remote_id` = its deployment id, `target` = the project; no `integration`: core infers the
  connection from the webhook), after their `emit_event` step; the failed one carries `message: ${steps.log.output.reason}`, the build log tail the toast shows (the workflow
  already fetched it).
- **Buttondown 0.9.0**: `create_issue_email` declares `HandsOff(remote_id="email_id", remote_url="url", record_if="sent")` and returns `sent` (true only when this call created the
  email with delivery `send`; draft, off and an already-created email are false); `connect_webhooks` subscribes `email.sent` too; a new required workflow
  `buttondown-email-sent` and a new action `resolve_email_id`. `buttondown-issue-on-publish` is byte-for-byte what 0.8.0 shipped (the other 0.8.0 workflows and the webhook too),
  pinned by a test against a snapshot of the 0.8.0 blueprint taken from git `aef2cb1` (`tests/fixtures/issue_on_publish_v0_8_0.json`).
- **Docs**: `whats-new/automation-results.md`, `whats-new/integrations.md` (`record_if` and event connections), SDK and both plugin READMEs, the Buttondown guide.

### Cloudflare's status words (read from the plugin, not guessed)
The notifications say `data.event` = `EVENT_DEPLOYMENT_STARTED` | `EVENT_DEPLOYMENT_SUCCESS` | `EVENT_DEPLOYMENT_FAILED` (the three the plugin's workflows and its
`connect_notifications` policy filter on): In flight, Succeeded, Failed. The Pages API's deployment stage `status` (what `list_deployments` returns) is `idle` | `active` |
`success` | `failure` | `canceled` | `skipped`: mapped `idle`/`active` In flight, `success` Succeeded, `failure`/`canceled` Failed; `skipped` is deliberately unmapped (a build
Cloudflare chose not to run is neither, so it stays in flight with the word shown). The stage words are from Cloudflare's API documentation, not from this repo.

### What differs from the plan, and why
- **A failed call with `record_if` records nothing.** A failure has no output to read, so Marvin cannot tell a failed send from a failed draft; recording it would put a "Failed"
  hand-off in Results for something that was never one. The failure still fails the step and goes through the error policy (retry, then notify admins), and a retry that gets
  through records in flight as usual. (A hand-off without `record_if` records its failures as before.)
- **`deploy`'s `remote_url` is a new output `link`, not `url`.** `url` is the deployment's own address (`<hash>.<project>.pages.dev`), which is dead until the build ends and
  stays dead if it fails. `link` is the build's page in the Cloudflare dashboard (its log), the same link `build_log` already makes. `url` is still returned.
- **Buttondown: a new `resolve_email_id` action and a step in front of `automation_result`.** The plan sets `remote_id` to the payload's email id. Buttondown's OpenAPI documents the
  webhook body only as `{id, event_type, data: object}`, with no per-event shape, so the payload's `data.email` is **not verified**. For subscribers the API returns `sub_…` while
  webhooks carry a UUID (the plugin already works around it with `lookup_subscriber`); an email almost certainly has the same two ids. A TypeID is its prefix plus the UUID in base32
  (checked against the TypeID spec's own test vector), so `resolve_email_id` turns either form into the `em_…` id the hand-off was recorded under, without a call. Without it a
  UUID would never match, and every send would sit In flight and then show No reply, with a stray Succeeded result beside it.
- **The step also has a condition `event.payload.data.email exists`**, as the subscriber workflows do for `data.subscriber`, so a payload without it does nothing rather than
  recording a result with no id.
- **Scheduled "Run Integration Action" tasks are not recorded.** The brief says "outside a workflow step"; the event connection is the case the plan names, and the task handler
  polls (an Instagram matcher, a feed) with its own long-lived session, where writing from a second session risks a lock on SQLite. No hands-off action is known to be scheduled. It is
  a few lines with `track_direct` (or `track` on its own session) if one ever is. A test-fire from the card records nothing, by intent.
- **Existing workspaces:** the new webhook event needs one re-run of the card's **Connect Buttondown webhooks** (it updates the webhook already there), plus **Apply** and switching on
  `buttondown-email-sent`; the three Cloudflare workflows' cards offer **Update**.
- The review of the first phase said Marvin still pinned the SDK at v0.12.0; it already pins v0.13.0 (pyproject and `uv.lock`).

### Open points
- **Verify one real `email.sent` delivery** (Buttondown's webhook *deliveries* panel shows the body): the key name `data.email` and the id form are assumptions. If the key is something
  else (`data.email_id`?) change the workflow's condition and argument; the rest holds.
- **Any email sent from Buttondown's own dashboard, and any Cloudflare build that Marvin did not start (a git push), becomes a Succeeded result** (a report that matches nothing is kept as
  a new one, by design). Pruned after 30 days. If that is noise, the step could grow an "only settle, never create" option.
- A send that never completes shows as No reply after a day (Buttondown has no failure event), as planned.
- Release: SDK tag v0.14.0, then Marvin's pins (`marvin-integration-sdk` in `pyproject.toml` twice, `uv.lock`; the `plugins` group: Cloudflare Pages `@v0.3.0`, Buttondown `@v0.9.0`).
  The plugins need SDK 0.13+ (Cloudflare) and 0.14+ (Buttondown). The TS SDK is unaffected: the OpenAPI spec is unchanged.

### Verification
- ruff check and format: clean on core, the SDK, and both plugins.
- Core, SQLite (`-n auto`): 5993 passed, 78 skipped. Core, Postgres (`marvin_test_sources`, `-n auto`): 6064 passed, 7 skipped, run twice (cold and warm databases), both green.
  New: 20 end-to-end tests (`tests/test_results_sources.py`) and 13 in `tests/test_automation_results.py` (`record_if`, event subscriptions, a late *started*).
- SDK 184 passed, 5 skipped; Cloudflare Pages 37; Buttondown 210. The OpenAPI spec is identical before and after (`app.openapi()` of `a5ded4ac` against this tree).
- Local wiring: SDK, Cloudflare Pages and Buttondown installed editable into `.venv` (see the report); core run with `uv run --no-sync`.
