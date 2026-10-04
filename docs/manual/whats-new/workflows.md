# Workflows

A workflow (an "automation" in the API) is a trigger, optional conditions and up to ten ordered steps that run against your workspace content without code.

## What it does

- **Triggers** decide when the workflow runs. **Conditions** gate it. **Steps** (`actions`) run in order; each step's output becomes `$previous` and `$steps.<id>.output`, and a failing step stops the rest.
- Runs are recorded (status `success`, `partial` or `failed`, per-step timing and output) and every run emits `automation_ran` or `automation_failed`, which `chained` and `on_error` triggers react to. Chains are bounded: an event at reaction depth 3 or more triggers nothing.
- Steps run with the author's current workspace role (definer's rights): entry and emit-event steps need AUTHOR; task, webhook and integration steps need ADMIN; an AI operation needs its own minimum role. If the author is demoted or removed, steps above their new role fail.

### Trigger types

| `trigger.type` | Fires when | Extra keys |
|---|---|---|
| `event` | A listed workspace event occurs | `event` (name) |
| `manual` | You press **Run** or call `POST …/run` | |
| `schedule` | A scheduler task fires; saving upserts a `run_automation` task (`wf-<id>`), deleted again when the trigger changes | `schedule_type: "interval"`, `schedule_config: {"interval_seconds": n}` |
| `chained` | Another workflow finishes (`automation_ran`) | `automation`: slug/id, or `any` |
| `on_error` | Another workflow fails (`automation_failed`) | `automation` |
| `incoming_webhook` | An [incoming webhook](incoming-webhooks.md) receives a POST | `webhook`: slug, or `any` |
| `mcp` | An external MCP host calls the workflow's own tool, `marvin_wf_<slug>` (see [Settings](#settings)); **Run** also works | |

Event triggers accept only the curated catalog: Entries (`entry_created`, `entry_updated`, `entry_published`, `entry_unpublished`, `entry_archived`, `entry_restored`, `entry_deleted`, resource/tag/asset attach and detach), Collections, Assets, Resources, Forms (`form_submission_received`, `submission_surge_detected`, `form_*`), Entry types and Site (`site_build_*` and `site_deployment_*`: `started`, `completed`, `failed`). Site events come from an **Emit event** step (usually a workflow on a host's deploy-notification webhook), so a second workflow can react to them — for example, tell someone when a deploy fails; reaction depth keeps such chains bounded.

### Conditions and context

Operators: `eq`, `neq`, `contains`, `in` (a comma-separated string is accepted), `starts_with`, `exists` (`value: false` inverts), `changed`, `changed_from`, `changed_to`. A top-level list is AND; `{"all": […]}`, `{"any": […]}` and `{"not": …}` nest. An unknown operator never matches. The `changed*` operators read `event.changed_fields`, `event.before` and `event.after` from an `entry_updated` event.

The builder sends every value as text. `eq` and `neq` convert it to the type of the value being compared: `true`/`false` (also `yes`/`no`, `on`/`off`, `1`/`0`) against a checkbox, a number against a number field.

| Namespace | Contents |
|---|---|
| `event.*` | Every field of the event's data, plus `event_type`, `entry_id`, `webhook_slug`, `payload`, `changed_fields`, `before`, `after`, `user_id`. Forms: `event.submission_data.<field>`. |
| `entry.*` | `id`, `entry_type`, `status`, `title`, `slug`, `summary`, `data.<field>` (the entry type's fields), `metadata.<key>`, `image` (the featured image's public URL, or empty). Present for entry events and for every row of a query run. |
| `previous.*`, `steps.<id or index>.output.*` | Step outputs; usable in step inputs only, never in conditions. |

A numeric path segment indexes a list: `event.payload.items.0.id`.

Templates in step inputs: `$event.entry_id` or `${event.count}` alone keeps the value's type; `Summary: ${previous.summary}` embeds as text, so `${entry.image}` or `${entry.data.<field>}` can be handed to a webhook or integration. `{{SLUG}}` secret refs resolve only in a configured webhook's headers, in a webhook step's `secret_ref`, and in a Run integration step's `args` (see below).

### Run on a query of entries

Tick **Run on a query of entries** to run the steps once per matching entry instead of on the triggering entry. This is how to bulk update entries: with a **Set fields** step (`set_data`) it changes the same fields on every entry the query matches. Each row gets the full `entry.*` context above, so a condition on `entry.data.<field>` works per row; conditions act as the query's WHERE clause. A run acts on at most **250** entries (`MAX_TARGET_ENTITIES`). **Preview matches** shows the true count and says when it is capped, so narrow the query itself (for example with **Fields equal**) rather than relying on conditions to filter a larger set.

The form fills a `target`, `{"entity": "entry", "query": {…}}`, using the same entry query as the agent's `find_entries` tool and bulk agent actions. Form labels map to keys: **Entry type** → `entry_type`, **Status** → `status`, **Title contains** → `text`, **In collection** → `collection`, **has images** / **has assets** / **has resources** → `has_images` / `has_assets` / `has_resources`, **Metadata equals** → `metadata`, **Fields equal** → `data`. **Edit as JSON** accepts every key:

| Key | Meaning |
|---|---|
| `entry_type` / `entry_types` | type slug(s); `-` and `_` spellings both match |
| `status` / `statuses` | the publish status (`inbox`, `draft`, `needs_review`, `approved`, `published`, `archived`). Any other value matches nothing; filter a type's own `status` field with `fields` or `where`. |
| `text` (alias `query`) | title or slug contains (case-insensitive) |
| `tags`, `collection` / `collections` | any of these, by slug or name |
| `fields` (alias `data`), `metadata` | exact match, `{field_key: value}`; typed text matches checkbox and number values; an empty value matches nothing |
| `where` | `[{"field": key, "op": op, "value": v}]`, where `field` is a field key or `metadata.<key>`; ops `eq`, `neq`, `in`, `contains`, `exists`, `missing`, `gt`, `gte`, `lt`, `lte`. Comparisons read number-like text (`"$1,170"` → 1170). An unknown op makes the query match nothing (with a note), so a typo never widens the target. |
| `created_after` / `created_before`, `updated_…`, `published_…` | ISO dates or datetimes (UTC) |
| `sort` | `{"by": <key>, "direction": "asc"}` (or `"desc"`); `by` is `title`, `created_at`, `updated_at`, `published_at` or a field key. A field sorts numerically when its values are number-like, empty values last. Default: newest created first. |

In `where` and `sort` a bare key is always the entry type's own field. `where` and sorting by a field read at most 5,000 entries. Query values may be `${event…}` templates, so a webhook payload can carry the query.

### Step kinds

| `kind` (builder label) | Fields | Behaviour |
|---|---|---|
| `entry` (Entry action) | `op` (`publish`, `unpublish`, `archive`, `restore`, `add_to_collection`, `remove_from_collection`, `set_metadata`, `set_data`), `entity_id` (default `$event.entry_id`), `entity_slug`, `entity_query` (the query above; must match exactly one entry), `collection_slug`/`collection_id`, `metadata`, `data` | Status ops emit the matching lifecycle event (`unpublish` and `restore` return the entry to `draft`). **Set metadata** (`set_metadata`) merges templated keys into the entry's metadata. **Set fields** (`set_data`) merges into the entry type's own fields, converts typed text to the field's type (true/false for a checkbox, a number for a number field) and validates against the schema, so an unknown select option fails the step. Both drop values that resolve empty and fail if nothing is left. |
| `webhook` (Call webhook) | `webhook_id` or raw `url`; `method` (raw URL only; default `POST`), `body`, `secret_ref`, `auth_scheme` (`Bearer` default, or `Token`) | A configured webhook's URL, method, `{{SLUG}}` headers and custom payload are used, with `${event…}` templates resolved. Timeout 15 s. A non-2xx response fails the step. Output: `status_code`, `ok`, `webhook_id`, `body` (parsed JSON or text). Deliveries appear in the webhook log. |
| `integration` (Run integration) | `integration` (the workspace integration's slug), `action` (the provider action key), `args` (templated) | Runs one action of an enabled [integration](integrations.md) with its stored credentials; the provider's result is the step output. An action that requires approval is refused, since nobody is there to approve it. A top-level arg whose whole value is `{{SLUG}}` is replaced by that workspace secret for the call only (the stored workflow keeps the reference); a secret that does not exist fails the step. |
| `operation` (AI operation) | `op` (AI operation slug), `input`, `entity_type`, `entity_id`/`entity_slug`, `write_back` | Offered only when AI is enabled and the **Workflows** invocation source is on. **Write the result back to the entry** (`write_back: true`) follows the workspace approval mode: the result is applied or staged as a suggestion, and the output's `_write_back` says which (`applied` or `staged`). The workspace's AI limits apply: over the daily request or monthly cost limit the step fails, and the per-request token cap bounds the call (see [Agents and Ask → Usage and limits](agents-and-ask.md#usage-and-limits)). |
| `handler` (Run task) | `task`, `config` | Allowlist: `request_site_rebuild`, `publish_scheduled_entries`, `unpublish_expired_entries`, `ai_reindex_embeddings`, `resync_smart_collections`, `media_enrich`. `request_site_rebuild` queues a coalesced rebuild (see [Operations → Site rebuilds](../operations.md#site-rebuilds)). |
| `emit_event` (Emit event) | `event`, `entity_id` (default `$event.entry_id`); for site events `message`, `error`, `site_url`, `deployment_id` (templated) | An entry event (`entry_*`) is re-emitted for the entry in context, at depth + 1. A site event (`site_build_started` / `_completed` / `_failed`, `site_deployment_started` / `_completed` / `_failed`) needs no entry: it records the build or deploy with the given message (default "Site build failed" and so on), failure reason and site URL, and shows as an activity toast. For a site event the builder adds message, failure-reason and site-URL inputs; `deployment_id` is set through **Edit as JSON**. Other events are refused. |

Only the first 10 steps run; the validator warns when there are more.

## Where

**Workspace Settings → Automation → Workflows** (`/automation/workflows`). Each card offers **Run**, **Dry run**, **Runs** (the last 15 executions), **Edit** and **Delete**. Trigger labels in the builder: Event, Manual (Run button), Schedule, After another workflow, When a workflow fails, Incoming webhook (external POST), MCP tool (external hosts).

## How to use

1. **New workflow**, then pick a **Trigger** and add conditions under **Only if** with the guided field picker (fields depend on the trigger; `entry.*` is offered only where an entry exists).
2. Add steps under **Then do**. To read a step's output later, give the step an `id` in **Edit as JSON** (`$steps.subscribe.output.body.id`).
3. **Save workflow**. Structural errors (unknown kind, missing field) block the save with `422`; advisory warnings (a condition that can never match) do not.
4. **Dry run** to see the resolved plan without executing, then tick **Enabled** and **Run**.

A dry run of an event-triggered workflow (Event, Incoming webhook, After another workflow, When a workflow fails) runs against a sample event, so `${entry.title}` and `$event.*` resolve as they would on a real run. **Testing with** picks the sample: recent events of the trigger's type from the event log, then (for entry lifecycle triggers) recent entries with no logged event, built into the event the entry would emit. The default is the newest event whose conditions pass, else the newest event (marked "conditions fail"), else the newest matching entry. The panel shows whether the trigger fires on that event, a ✓/✗ line per condition with the value it got, **Would fire** or **Would not fire**, and the resolved steps (a webhook step shows its URL, headers and body; `{{SLUG}}` references stay unresolved and a credential typed into a header shows as `••••••`). Steps are resolved even when a condition fails. The entry is read as it is now, not as it was when the event was logged. Manual and scheduled workflows dry-run as before.

**Run** executes the whole workflow inside the request and waits for it, so a query run over many entries (especially with AI steps) can take minutes. Behind a proxy with a request timeout (Cloudflare gives up after about 100 seconds) the browser may report an error while the server carries on. Don't press **Run** again; check **Runs** for the result.

```json
{
  "trigger": {"type": "event", "event": "form_submission_received"},
  "conditions": [{"field": "event.flagged", "op": "eq", "value": false}],
  "actions": [
    {"kind": "webhook", "id": "subscribe", "webhook_id": "<webhook uuid>"},
    {"kind": "entry", "op": "set_metadata",
     "metadata": {"subscriber_id": "$steps.subscribe.output.body.id"}}
  ]
}
```

## API

All routes need workspace ADMIN or OWNER. See [API reference](../api/index.md).

| Method and path | Purpose |
|---|---|
| `GET /api/automations` · `POST /api/automations` | List, create (`name`, `slug?`, `enabled`, `definition`). |
| `GET` / `PATCH` / `DELETE /api/automations/{id}` | Read, update, delete (also removes the backing scheduled task). |
| `GET /api/automations/options` | Trigger types, event catalog, operators, condition fields per trigger, step kinds, AI operations, webhooks, incoming webhooks, other workflows, and the definition JSON Schema. |
| `POST /api/automations/validate` | `issues[]` with `level` `error` or `warning`, `where`, `index`. |
| `POST /api/automations/preview` | Resolve a `target` query with an optional test `payload`; returns `matches` (capped, after conditions), `total`, `capped`. |
| `POST /api/automations/{id}/run` | Manual run; responds when the run finishes (`409` when disabled). With `?dry_run=true` it returns `plan` and records nothing. For an event-triggered workflow the dry run also takes `entry_id` or `event_id` (an event log row) and returns `sample`, `trigger_matched`, `conditions` (each with `field`, `op`, `value`, `actual`, `expected`, `pass`, or a nested `group`), `conditions_pass` and `would_fire`. |
| `GET /api/automations/{id}/samples?limit=` | The dry run's candidate samples: recent logged events the trigger fires on, then uncovered entries (default 10, at most 25), each with `kind`, `id`, `label`, `occurred_at`, `synthesized`, `conditions_pass`. Empty for a workflow no event triggers. |
| `GET /api/automations/{id}/executions?limit=` · `GET …/executions/{execution_id}` | Run history (default 25, at most 100); detail includes per-step records and the definition snapshot. |

## Settings

A workflow is `enabled: false` when created. A disabled workflow does not run from events, the scheduler or **Run**, but can be dry-run. A workflow with the `mcp` trigger is exposed by the Marvin MCP server as a tool named `marvin_wf_<slug>` (non-alphanumerics in the slug become `_`; needs a user token, see [Marvin as an MCP server](marvin-as-mcp-server.md)). Separately, the agent's `run_workflow` tool runs any enabled workflow by slug, name or id, skipping its trigger and conditions as **Run** does, and the run is recorded under **Runs**.

## Since

`form_submission_received` as a trigger: v1.0.0-rc.51 (`8f1443d1`). `auth_scheme`: rc.50 (`a65ba7d0`). `entry.summary` and `entry.data.*`: rc.52 (`433e949e`). Response `body`, `set_metadata` and metadata targeting: rc.59 (`1380e92e`). `entity_query`: rc.60 (`65ffb648`). Raw-URL `method` and templated stored URLs: rc.61 (`b88e4035`). Builder fixes: rc.63 (`57956e71`). `set_data`, the integration step, `entry.metadata` and list indexes in paths: rc.111. `entry.image`: rc.119. Full entry context per query row and **Fields equal**: rc.129. Typed values for checkbox and number fields: rc.131. The shared entry query (`where`, `sort`, date filters): rc.138. Unknown `where` ops match nothing, and `run_workflow` runs appear under **Runs**: rc.139. Site build and deploy events from `emit_event`: rc.144. `{{SLUG}}` in integration step args: rc.145. AI limits on operation steps: rc.146. Site events as notification subscriptions: rc.151; as workflow triggers: rc.152.

## Related

- [Incoming webhooks](incoming-webhooks.md) · [Outgoing webhooks](outgoing-webhooks.md) · [Forms and submission protection](forms-and-submission-protection.md) · [Integrations](integrations.md)
- [Glossary](../glossary.md)
