# Workflow Library — compatibility audit

Facts derived from the code (paths under `src/marvin/`), against what the starter brief assumed. Status key:
**exists** · **exists-with-caveat** · **needs-adapter** · **needs-engine-capability**.

## Definition and validation

| Feature | Status | Where |
|---|---|---|
| Discriminated definition model (triggers on `type`, actions on `kind`, recursive conditions, target) | exists | `schemas/group/automation_definition.py` |
| Kind tags: operation, entry, emit_event, handler, webhook, integration | exists | `automation_definition.py:194-201`; `ai` / `http` do not exist |
| Structural gate on save (422 with paths) | exists | `services/automation/validation.py:276` `structural_issues`; `workflows.py:44` |
| Unknown-key and workspace-reference checks (agent drafts) | exists | `validation.py:304` `unknown_key_issues`; `authoring.py` `reference_issues` / `draft_issues` |
| Advisory coherence warnings (`entry.*` under a trigger without an entry…) | exists | `validation.py:100` `validate_definition`, `POST /api/automations/validate` |
| `extra="allow"` on models | exists-with-caveat | unknown keys save via REST and are ignored; only `draft_issues` rejects them |
| JSON Schema of the definition for the builder/SDK | exists | `/api/automations/options` → `definition_schema` |

## Triggers

| Trigger | Status | Notes |
|---|---|---|
| `event` (43 triggerable events) | exists | `services/events/event_catalog.py` `triggerable=True`; listener gate `event_bus_listener.py:1139-1146` |
| `manual`, `mcp` | exists | `engine.py:697` `run_automation_now` (skips trigger/condition gates unless a `target`) |
| `schedule` | exists-with-caveat | creates its own backing `run_automation` scheduled task (`workflows.py:101` `sync_schedule`, slug `wf-<id>`); interval, once and cron all fire (cron since 2026-10-08: `services/cron.py`, five numeric fields in an IANA timezone; an expression that can't run is refused on save — before, cron computed no next run and never fired) |
| `chained` / `on_error` | exists | match `automation_ran` / `automation_failed` (`engine.py:391-394`); the failed run's entry is `event.trigger_entity_type/id` (`summary.py:153`) |
| `incoming_webhook` | exists | body → `${event.payload.*}` (`routes/hooks/hooks_controller.py:77-148`); headers/query not carried; no dedup store; signature presets incl. HMAC |
| Custom emitted events | needs-engine-capability | `emit_event` sends only `entry_*` and `site_deployment_*` (`EMITTABLE_EVENT_TYPES`); no registration of new names |
| Operational events as triggers (`webhook_triggered`, `integration_attention_*`, `webhook_delivery_failed`, `scheduled_task_*`, `ai_budget_*`, `approval_*`, `member_added`, `api_client_*`) | needs-engine-capability (by design) | not triggerable; reach subscriptions (email / integration / outgoing webhook) and Automation → Notifications instead. 46 of the brief's 85 events are **not** workflow triggers |

**Scheduled dispatch path**: tick → `scheduled_task_triggered` → `ScheduledTaskListener` → `run_automation`
handler → `run_automation_now(trigger_kind="schedule")` with `event = {event_type: "manual"}` (no `$event.*`
facts). `scheduled_task_triggered` fires on every due tick *and* on Run-now; `scheduled_task_completed` only
when the handler returned something, it was run by hand, or it recovered. Timezone is ignored; no backfill; no
overlap (serial in the leader tick).

## Targets and conditions

| Question | Answer |
|---|---|
| Target scope vs triggering entry | Without `target`, steps act on the trigger's entry (`$event.entry_id`). With `target`, the query **replaces** it: each row is bound as `entry` and `event.entry_id` (`engine.py:248-252`); conditions become the WHERE over the set, always applied, even on manual runs. Entity: `entry` only (`selector.py:34`), cap 250 |
| Condition operand typing | `_like` (`matcher.py:45`) reads typed-in text as the actual's type (bool/number); `in` accepts a list or CSV; `exists` checks `is not None` (`""` exists); `contains` is substring or membership; unknown op fails closed |
| before/after paths | `event.before.<f>` / `event.after.<f>` hold **only changed fields** among `status`, `title`, `slug` (`entry_service.py:40` `_TRACKED_FIELDS`); `changed`, `changed_from`, `changed_to` key on the field's last segment. **Data-field changes are not detectable** |
| Event payload propagation | `document_data` is flattened into `event.*` (`context.py:11-57`); curated keys override; `entry.*` loads only when the subject is an entry; `user_id` is the actor (a UUID object) |
| Action ordering | strictly sequential, max 10 (`engine.py:30` `MAX_ACTIONS`); a failure stops the rest and runs `on_failure` once |
| Step output availability | `${previous.*}`, `${steps.<id|index>.output.*}` in later **steps only**; never in conditions (evaluated before any step) |
| Update conflict behaviour | `set_metadata`/`set_data` are read-merge-write with no version check (`actions/entry.py:223`, `:246`); `set_data` is schema-validated; empty/None template values are dropped, an all-empty patch fails |
| Recursion protection | `_running` ContextVar: a workflow sits out events its own run caused (`engine.py:33-51`); other workflows react at depth+1 up to `MAX_REACTION_DEPTH = 3`; one correlation id per cascade |
| Self-trigger via set_metadata | cannot re-enter the same workflow; **does** fire other `entry_updated` workflows (e.g. content-refresh) |

## Actions

| Action | Status | Notes |
|---|---|---|
| `entry`: publish / unpublish / archive / trash / restore / add_to_collection / remove_from_collection / set_metadata / set_data / request_review | exists | `actions/entry.py`; publish honours the completeness gate (`entry_service.py:205-236`) — the brief's "validate required content" |
| `entry` on assets/resources | exists-with-caveat | only `trash` / `restore` with `entity_type` |
| Create entry | needs-engine-capability | no op creates an entry |
| `operation` (AI) | exists-with-caveat | 8 ops, all allow the `automation` source (`services/ai/operations/system.py`); **context is built only for entries** (`runner.py:133-136`): asset/resource/form_submission targets run blind; write-back only for `generate-summary` → summary and `generate-tags` → tags, gated by approval mode (default suggest-only → staged in `suggestion_json`); budget-gated |
| `handler` | exists-with-caveat | allowlist of 6 (`actions/handler.py:24`); `resync_smart_collections` is admin-only and **no-ops from a workflow** (`handlers/maintenance.py:409`) |
| `webhook` | exists | configured webhook (`webhook_id`, type `workflow`) or raw `url`; one attempt, 15 s, no retry; response JSON → `${steps.<id>.output.body}`; delivery logged |
| `integration` | exists | provider action with `args`; `requires_approval` actions refused (`actions/integration.py:58`) → `openai_images.generate`, `instagram.send_private_reply`, `instagram.auto_reply` can never run from a workflow; error policy (review/retry/notify/succeed) from SDK ≥0.5 providers; retries resume at the failed step with idempotency seed |
| `emit_event` | exists-with-caveat | entry_* (from the context entry) and site_deployment_* only |
| Branches / waits / approvals / iterate / parallel | needs-engine-capability | none exist; `request_review` is the fire-and-forget substitute for an approval |

Installed-plugin actions (origin/main of each MarvinIntegration* repo): Buttondown `subscribe`,
`lookup_subscriber`, `create_issue_email`, `connect_webhooks`; Apprise `notify`; Slack `send_message`; n8n
`trigger_workflow`, `list_workflows`, `list_webhooks`, `get_execution`; Cloudflare Pages `list_deployments`,
`build_log`, `connect_notifications`, `deploy`; Square `list_locations`, `create_listing`, `close_listing`;
Instagram `list_recent_comments`, `refresh_token` (+2 approval-only); OpenAI Images `generate` (approval-only).
No image-processing, TTS, OCR, social-publishing or HTTP-fetch adapters exist.

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

- `webhook_triggered` and the other operational events are not workflow triggers → `host-rebuild-dispatch`,
  the AI budget, integration-health, watchdog, approval, member and token recipes are **configuration**, not
  workflows.
- "Body changes" cannot gate a workflow (`_TRACKED_FIELDS`).
- `classify-form-submission` from a workflow classifies `{}`: the runner loads no submission context and
  new submissions are entries, not `FormSubmissions` rows.
- Custom completion events (`newsletter_issue_processed`) cannot be emitted; `automation_ran` + `chained` is
  the completion signal.
- Image generation is `requires_approval` and therefore unreachable from workflows; every image recipe waits on
  approvals-in-workflows plus asset targets/adapters.
- `member_added` carries no email address; the member cannot be addressed.
