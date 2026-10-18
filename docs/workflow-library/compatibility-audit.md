# Workflow Library — compatibility audit

Facts derived from the code (paths under `src/marvin/`), against what the starter brief assumed. Status key:
**exists** · **exists-with-caveat** · **needs-adapter** · **needs-engine-capability**.

Written 2026-10-08 and refreshed 2026-10-17: rows marked *(2026-10-17)* were re-checked against the code then; the gaps that
remain are in [`roadmap.md`](roadmap.md).

## Definition and validation

| Feature | Status | Where |
|---|---|---|
| Discriminated definition model (triggers on `type`, actions on `kind`, recursive conditions, target) | exists | `schemas/group/automation_definition.py` |
| Kind tags: operation, entry, emit_event, handler, webhook, integration, approval, media, collect, fetch, schema_check, email, wait, repeat, parallel *(2026-10-18)* | exists | `automation_definition.py:194-201`; `ai` / `http` do not exist |
| Structural gate on save (422 with paths) | exists | `services/automation/validation.py:276` `structural_issues`; `workflows.py:44` |
| Unknown-key and workspace-reference checks (agent drafts) | exists | `validation.py:304` `unknown_key_issues`; `authoring.py` `reference_issues` / `draft_issues` |
| Advisory coherence warnings (`entry.*` under a trigger without an entry…) | exists | `validation.py:100` `validate_definition`, `POST /api/automations/validate` |
| `extra="allow"` on models | exists-with-caveat | unknown keys save via REST and are ignored; only `draft_issues` rejects them |
| JSON Schema of the definition for the builder/SDK | exists | `/api/automations/options` → `definition_schema` |

## Triggers

| Trigger | Status | Notes |
|---|---|---|
| `event` (58 triggerable events, 2026-10-18) | exists | `services/events/event_catalog.py` `triggerable=True`; listener gate `event_bus_listener.py:1139-1146` |
| `manual`, `mcp` | exists | `engine.py:697` `run_automation_now` (skips trigger/condition gates unless a `target`) |
| `schedule` | exists-with-caveat | creates its own backing `run_automation` scheduled task (`workflows.py:101` `sync_schedule`, slug `wf-<id>`); interval, once and cron all fire (cron since 2026-10-08: `services/cron.py`, five numeric fields in an IANA timezone; an expression that can't run is refused on save — before, cron computed no next run and never fired) |
| `chained` / `on_error` | exists | match `automation_ran` / `automation_failed` (`engine.py:391-394`); the failed run's entry is `event.trigger_entity_type/id` (`summary.py:153`) |
| `incoming_webhook` | exists | body → `${event.payload.*}` (`routes/hooks/hooks_controller.py:77-148`); headers/query not carried; no dedup store; signature presets incl. HMAC |
| Custom emitted events | exists (2026-10-18) | a workspace registers `custom.<name>` events with typed fields (`services/events/custom_events.py`, `group_preferences.custom_events_json`); `emit_event` sends one with a templated `payload`; triggerable and subscribable; depth-bounded like every emitted event |
| Operational events as triggers (`ai_budget_threshold_reached` / `_exceeded`, `integration_attention_needed` / `_resolved`, `webhook_delivery_failed`, `scheduled_task_failed`) | exists (2026-10-18) | triggerable under the editor's **Operations** heading (`event_catalog.OPERATIONS`), payload fields as `${event.<field>}` (`operational_fields`; `describe_event`, authoring guide). Origin: `engine._running` keeps a workflow out of what its own run does, and `engine._own_chain_workflows` out of a failure announced in the chain of an event it sent (the publisher gives a failed delivery the delivered event's correlation id and reaction depth). Scheduled tasks: the workspace's own only — a system task has no workspace (its failure is dispatched without a group). Fallback: Automation → Notifications needs no workflow |
| Operational events still not triggers (`webhook_triggered`, `approval_*`, `api_client_*`, `ai_provider_quota_exceeded`, `ai_model_unpriced`; `member_added` / `member_role_changed` became triggers 2026-10-13) | needs-engine-capability (by design) | not triggerable; reach subscriptions (email / integration / outgoing webhook) and Automation → Notifications instead |

**Scheduled dispatch path**: tick → `scheduled_task_triggered` → `ScheduledTaskListener` → `run_automation`
handler → `run_automation_now(trigger_kind="schedule")` with `event = {event_type: "manual"}` (no `$event.*`
facts). `scheduled_task_triggered` fires on every due tick *and* on Run-now; `scheduled_task_completed` only
when the handler returned something, it was run by hand, or it recovered. Timezone is ignored; no backfill; no
overlap (serial in the leader tick).

## Targets and conditions

| Question | Answer |
|---|---|
| Target scope vs triggering entry | Without `target`, steps act on the trigger's entry (`$event.entry_id`). With `target`, the query **replaces** it: each row is bound as `entry` and `event.entry_id` (`engine.py:248-252`); conditions become the WHERE over the set, always applied, even on manual runs. Entity: `entry`, `asset` or `resource` (2026-10-17; was entry only), cap 250 |
| Condition operand typing | `_like` (`matcher.py:45`) reads typed-in text as the actual's type (bool/number); `in` accepts a list or CSV; `exists` checks `is not None` (`""` exists); `contains` is substring or membership; unknown op fails closed |
| before/after paths | `event.before.<f>` / `event.after.<f>` hold **only changed fields** among `status`, `title`, `slug` (`entry_service.py:40` `_TRACKED_FIELDS`); `changed`, `changed_from`, `changed_to` key on the field's last segment. **Data-field changes are not detectable** |
| Event payload propagation | `document_data` is flattened into `event.*` (`context.py:11-57`); curated keys override; `entry.*` loads only when the subject is an entry; `user_id` is the actor (a UUID object) |
| Action ordering | strictly sequential, default 10 (`engine.py` `MAX_ACTIONS`), a workspace may raise it to 25 (Settings → General → Workflows, 2026-10-14); a failure stops the rest and runs `on_failure` once |
| Step output availability | `${previous.*}`, `${steps.<id|index>.output.*}` in later **steps only**; never in conditions (evaluated before any step) |
| Update conflict behaviour | `set_metadata`/`set_data` are read-merge-write with no version check (`actions/entry.py:223`, `:246`); `set_data` is schema-validated; empty/None template values are dropped, an all-empty patch fails |
| Recursion protection | `_running` ContextVar: a workflow sits out events its own run caused (`engine.py:33-51`); other workflows react at depth+1 up to `MAX_REACTION_DEPTH = 3`; one correlation id per cascade |
| Self-trigger via set_metadata | cannot re-enter the same workflow; **does** fire other `entry_updated` workflows (e.g. content-refresh) |

## Actions

| Action | Status | Notes |
|---|---|---|
| `entry`: publish / unpublish / archive / trash / restore / add_to_collection / remove_from_collection / set_metadata / set_data / request_review | exists | `actions/entry.py`; publish honours the completeness gate (`entry_service.py:205-236`) — the brief's "validate required content" |
| `entry` on assets/resources | exists-with-caveat | only `trash` / `restore` with `entity_type` (an asset or resource target does bind `asset.*` / `resource.*`) |
| Create entry | exists *(2026-10-11)* | `op: "create"` makes a schema-validated draft/inbox entry once per event (`actions/entry.py`) |
| `operation` (AI) | exists-with-caveat | built-in ops all allow the `automation` source (`services/ai/operations/system.py`), plus `op: "custom"` (own prompt and answer schema, 2026-10-11); context for entries, and for assets (the image is seen) and resources *(2026-10-17)*, but **form_submission targets still run blind**; write-back is a `write_back` field map, gated by approval mode (default suggest-only → staged in `suggestion_json`); budget-gated |
| `handler` | exists-with-caveat | allowlist of 6 (`actions/handler.py:24`); `resync_smart_collections` is admin-only and **no-ops from a workflow** (`handlers/maintenance.py:409`) |
| `webhook` | exists | configured webhook (`webhook_id`, type `workflow`) or raw `url`; one attempt, 15 s, no retry; response JSON → `${steps.<id>.output.body}`; delivery logged |
| `integration` | exists | provider action with `args`; `requires_approval` actions refused (`actions/integration.py`) unless an earlier `approval` step approved the run (2026-10-11); `instagram.send_private_reply` / `instagram.auto_reply` stay out of reach; error policy (review/retry/notify/succeed) from SDK ≥0.5 providers; retries resume at the failed step with idempotency seed |
| `emit_event` | exists-with-caveat | entry_* (from the context entry) and site_deployment_* only (`EMITTABLE_EVENT_TYPES`) |
| Branches, approvals, waits, collect, repeat *(2026-10-17)* | exists | `when` on any step (skipped ≠ failed); `approval` parks the run (`approvals.py`); `wait` parks it until a date or span (`waits.py`); `collect` gathers a query into rows; `repeat` runs 1–5 steps per item (≤ 25; no wait/approval inside) |
| Parallel branches / joins *(2026-10-18)* | exists | `parallel` runs 2–5 named branches (1–5 steps; no wait/approval/repeat/parallel inside) in written order inside the run, each independent of its siblings; `join` all/any, `on_branch_failure` fail/continue; merged by name (`actions/parallel.py`). Branches run in-process, not concurrently |

Installed-plugin actions (origin/main of each MarvinIntegration* repo): Buttondown `subscribe`,
`lookup_subscriber`, `create_issue_email`, `connect_webhooks`; Apprise `notify`; Slack `send_message`; n8n
`trigger_workflow`, `list_workflows`, `list_webhooks`, `get_execution`; Cloudflare Pages `list_deployments`,
`build_log`, `connect_notifications`, `deploy`; Square `list_locations`, `create_listing`, `close_listing`;
Instagram `list_recent_comments`, `refresh_token` (+2 approval-only); OpenAI Images `generate` (approval-only).
No TTS or social-publishing adapters exist. (2026-10-12→14: image processing, OCR/PDF, zip, rendering and watermarks are the `media` step, background removal and picture edits go through an `image.edit` integration action, `image.*` output is kept as assets, and a `fetch` step checks web addresses; TTS and social publishing still don't exist.)

## Supporting objects

| Object | Status | Where |
|---|---|---|
| Outgoing webhook (`url, method, headers_json` with `{{SECRET}}`, `custom_payload`, `webhook_type` generic/user/entries/event_driven/workflow, `subscribed_events`) | exists | `db/models/groups/webhooks.py`; `POST /api/groups/webhooks`; event-driven delivery retries 3× then `webhook_delivery_failed` |
| Incoming webhook (slug, token, signature scheme/secret ref) | exists | `routes/hooks/incoming_webhooks_controller.py`; `POST /api/hooks/{token}` |
| Scheduled task for a schedule trigger | exists (automatic) | nothing to provision |
| "Notification set" | exists as three things | Automation → Notifications (`services/alerting.py`, `workspace_alerts.py`: six alert kinds — workflow_failed, scheduled_task_failed, integration_attention, ai_operation_failed, webhook_delivery_failed, trash_auto_empty_soon — with email/push/integration routes, incidents and recovery notices); email event subscriptions for any workspace event (`/api/groups/email-event-subscriptions`); integration event subscriptions (`/api/groups/integrations/subscriptions`) |
| Per-workflow success/failure notification | needs-engine-capability | only the workspace-wide `workflow_failed` kind (incident per workflow id), `on_failure` steps, `on_error` triggers, and subscriptions to `automation_ran/failed` |

## Dry run, history, provenance

- Dry run: `POST /api/automations/{id}/run?dry_run=true` (plan with resolved inputs, no side effects), with a
  sample event (`event_id` / `entry_id`) → trigger match, per-condition verdicts, `would_fire`
  (`engine.py:754` `dry_run_for_event`); `POST /preview` resolves a target.
- History: `automation_executions` + per-step rows with outputs, `correlation_id`, `retry_of_id`, retry chains
  (`GET /api/automations/{id}/executions[/{run}]`).
- Provenance: `correlation_id` threads event → runs → re-emitted events; `reaction_depth` bounds chains.
- Idempotency: integration retries carry an idempotency seed and partial progress; **no per-step idempotency
  key** for webhook/integration steps on duplicate events.

## Syntax collisions to design around

Three things use `{{…}}`: the Library's setup placeholders (lower_case, substituted before save), Marvin's
workspace secret references in headers/args (UPPER_CASE by convention, resolved at run time), and the
`{{field}}` templating of integration event subscriptions / outgoing-webhook `custom_payload` (resolved on
delivery). `library.configure` only touches lower_case names declared in the recipe's vars; the configuration
recipes avoid `{{field}}` templating so an installer can't confuse them.

## Engine fixes made by this audit

- `actions/entry.py`: `set_metadata` / `set_data` patches are passed through `jsonable_encoder` before merging.
  A whole-value template keeps its type, and the event context carries UUIDs (`${event.user_id}`) and datetimes
  that a JSON column cannot store — the publication-ledger recipe crashed the step with
  `Object of type UUID is not JSON serializable`.

## Brief assumptions that do not hold

- `webhook_triggered`, `approval_*`, `api_client_*` and the provider-quota events are not workflow triggers →
  `host-rebuild-dispatch`, the approval and token recipes are **configuration**, not workflows. The AI budget, watchdog
  and recovery recipes stay configuration too (native alerts do what they ask); `integration_attention_*`,
  `webhook_delivery_failed`, `scheduled_task_failed` and `ai_budget_*` *are* triggers since 2026-10-18, and
  integration-health-companion and webhook-repair-desk are workflows (a repair task per connection / webhook).
- "Body changes" cannot gate a workflow (`_TRACKED_FIELDS`).
- `classify-form-submission` from a workflow classifies `{}`: the runner loads no submission context and
  new submissions are entries, not `FormSubmissions` rows.
- Custom completion events (`newsletter_issue_processed`) cannot be emitted; `automation_ran` + `chained` is
  the completion signal.
- Image generation is `requires_approval` and therefore unreachable from workflows; every image recipe waits on
  approvals-in-workflows plus asset targets/adapters. (Resolved: approval steps 2026-10-11, generated images kept as
  assets 2026-10-12.)
- `member_added` carries no email address, so a subscription cannot address the member. (Partly resolved 2026-10-13: a workflow on a member event reads `${member.email}`; an `email` step now writes to a workspace member, 2026-10-18; subscriptions still can't address one.)
