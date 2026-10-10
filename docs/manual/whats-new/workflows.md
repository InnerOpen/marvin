# Workflows

A workflow (an "automation" in the API) is a trigger, optional conditions and up to ten ordered steps that run against your workspace content without code.

## What it does

- **Triggers** decide when the workflow runs. **Conditions** gate it. **Steps** (`actions`) run in order; each step's output becomes `$previous` and `$steps.<id>.output`, and a failing step stops the rest — then the workflow's **on-failure steps** (`on_failure`), if it has any, run on the same entry (see [When a step fails](#when-a-step-fails)).
- Runs are recorded (status `success`, `partial` or `failed`, per-step timing and output) and every run emits `automation_ran` or `automation_failed`, which `chained` and `on_error` triggers react to. These events and `automation_started` are about the workflow (`entity_type: automation`). They also name the triggering event's subject in `trigger_entity_type`, `trigger_entity_id` and `trigger_entity_label`: the entry, the incoming webhook, or the workflow a chained run follows. A manual or scheduled run has none. `automation_ran`'s message names each step and its outcome, for example "Automation 'send-issue' ran — webhook 'Buttondown: send issue' → 201". It lists three steps and counts the rest, and a query run's repeats collapse to one line with a count (`×12`). `automation_failed`'s message names the failing step and its error. Both carry the steps in `steps`. `automation_started` fires when a run begins (manual, scheduled, event-, webhook- or agent-started, query runs included) with the run's `execution_id`, which `automation_ran` / `automation_failed` repeat, so the admin's "is running…" toast becomes the result in place; it is deliberately not offered as a trigger, since reacting to runs starting would loop. Chains are bounded: an event at reaction depth 3 or more triggers nothing. A workflow never reacts to an event its own run caused (its entry step's `entry_updated`, its own `automation_ran`), or one a reaction to its run caused; other workflows still react to it, and a later, independent event triggers it as usual.
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

Event triggers accept only the curated catalog: Entries (`entry_created`, `entry_updated`, `entry_published`, `entry_unpublished`, `entry_archived`, `entry_trashed`, `entry_restored`, `entry_deleted`, resource/tag/asset attach and detach), Collections, Assets, Resources, Forms (`form_submission_received`, `submission_surge_detected`, `form_*`), Entry types and Site (`site_deployment_started`, `_completed`, `_failed`; a trigger naming the old `site_build_*` names is saved as its `site_deployment_*` counterpart). Site events come from an **Emit event** step (usually a workflow on a host's deploy-notification webhook), so a second workflow can react to them — for example, tell someone when a deploy fails; reaction depth keeps such chains bounded.

### Conditions and context

Operators: `eq`, `neq`, `contains`, `in` (a comma-separated string is accepted), `starts_with`, `exists` (`value: false` inverts), `changed`, `changed_from`, `changed_to`. A top-level list is AND; `{"all": […]}`, `{"any": […]}` and `{"not": …}` nest. An unknown operator never matches. The `changed*` operators read `event.changed_fields`, `event.before` and `event.after` from an `entry_updated` event.

The builder sends every value as text. `eq` and `neq` convert it to the type of the value being compared: `true`/`false` (also `yes`/`no`, `on`/`off`, `1`/`0`) against a checkbox, a number against a number field.

| Namespace | Contents |
|---|---|
| `event.*` | Every field of the event's data, plus `event_type`, `entry_id`, `entity_type`, `entity_id` (what the event is about), `webhook_slug`, `payload`, `changed_fields`, `before`, `after`, `user_id`. `entry_id` is set only when the event is about an entry. Forms: `event.submission_data.<field>`. |
| `entry.*` | `id`, `entry_type`, `status`, `title`, `slug`, `summary`, `data.<field>` (the entry type's fields), `metadata.<key>`, `image` (the featured image's public URL, or empty). Present for entry events and for every row of a query run. |
| `asset.*` | `id`, `slug`, `name`, `asset_type`, `mime_type`, `filename`, `file_size`, `description`, `tags`, `metadata.<key>`, `url` (its public URL, or empty), `trashed`. Present for `asset_*` events and for every row of an asset query run. |
| `resource.*` | `id`, `slug`, `name`, `resource_type`, `description`, `tags`, `metadata.<key>`, `url` (its link), `external_id`, `trashed`. Present for `resource_*` events and for every row of a resource query run. |
| `previous.*`, `steps.<id or index>.output.*` | Step outputs; usable in step inputs only, never in conditions. |

A numeric path segment indexes a list: `event.payload.items.0.id`.

Templates in step inputs: `$event.entry_id` or `${event.count}` alone keeps the value's type; `Summary: ${previous.summary}` embeds as text, so `${entry.image}` or `${entry.data.<field>}` can be handed to a webhook or integration. `${entry.url}` is the entry's page on the site (absolute when the Canonical URL is set, otherwise the site path; empty when its type has no page URL pattern). `${site.url}` is the workspace's Canonical URL (Settings → General), or empty when it isn't set — e.g. the base a newsletter integration makes an issue's relative links absolute against. `{{SLUG}}` secret refs resolve only in a configured webhook's headers, in a webhook step's `secret_ref`, and in a Run integration step's `args` (see below).

### Run on a query {#run-on-a-query-of-entries}

Tick **Run on a query** and pick what it runs over — **Entries**, **Assets** or **Resources** — to run the steps once per match instead of on the triggering item. The rest of this section is about entries; [assets and resources](#run-on-assets-or-resources) follow it.

For entries, the steps run the steps once per matching entry instead of on the triggering entry. This is how to bulk update entries: with a **Set fields** step (`set_data`) it changes the same fields on every entry the query matches. Each row gets the full `entry.*` context above, so a condition on `entry.data.<field>` works per row; conditions act as the query's WHERE clause. A run acts on at most **250** entries (`MAX_TARGET_ENTITIES`). **Preview matches** shows the true count and says when it is capped, so narrow the query itself (for example with **Fields equal**) rather than relying on conditions to filter a larger set.

The form fills a `target`, `{"entity": "entry", "query": {…}}`, using the same entry query as the agent's `find_entries` tool and bulk agent actions. Form labels map to keys: **Entry type** → `entry_type`, **Status** → `status`, **Title contains** → `text`, **In collection** → `collection`, **has images** / **has assets** / **has resources** → `has_images` / `has_assets` / `has_resources`, **Metadata equals** → `metadata`, **Fields equal** → `data`. **Edit as JSON** accepts every key:

| Key | Meaning |
|---|---|
| `entry_type` / `entry_types` | type slug(s); `-` and `_` spellings both match |
| `status` / `statuses` | the publish status (`inbox`, `draft`, `needs_review`, `approved`, `published`, `archived`, `trashed`). Any other value matches nothing; filter a type's own `status` field with `fields` or `where`. Entries in the [Trash](trash.md) match only a query that asks for `trashed`. |
| `text` (alias `query`) | title or slug contains (case-insensitive) |
| `tags`, `collection` / `collections` | any of these, by slug or name |
| `fields` (alias `data`), `metadata` | exact match, `{field_key: value}`; typed text matches checkbox and number values; an empty value matches nothing |
| `where` | `[{"field": key, "op": op, "value": v}]`, where `field` is a field key or `metadata.<key>`; ops `eq`, `neq`, `in`, `contains`, `exists`, `missing`, `gt`, `gte`, `lt`, `lte`. Comparisons read number-like text (`"$1,170"` → 1170). An unknown op makes the query match nothing (with a note), so a typo never widens the target. |
| `created_after` / `created_before`, `updated_…`, `published_…` | ISO dates or datetimes (UTC) |
| `sort` | `{"by": <key>, "direction": "asc"}` (or `"desc"`); `by` is `title`, `created_at`, `updated_at`, `published_at` or a field key. A field sorts numerically when its values are number-like, empty values last. Default: newest created first. |

In `where` and `sort` a bare key is always the entry type's own field. `where` and sorting by a field read at most 5,000 entries. Query values may be `${event…}` templates, so a webhook payload can carry the query.

#### Run on assets or resources

With **Assets** or **Resources**, the target is `{"entity": "asset", "query": {…}}` (or `"resource"`) and each row gets `asset.*` / `resource.*` (see the context table above), so a condition on `asset.mime_type` or `resource.tags` works per row. The same 250-row cap applies. The steps that act on an item are **Move to Trash** and **Restore** (with **Acts on** left at *The current item*, a bare `trash` or `restore` step acts on each row); webhook and integration steps can read the row through templates such as `${asset.url}`. Other entry ops act on entries only, and `entity_query` always finds entries. Items in the Trash match only a query that asks for them (**in the Trash**, `trashed: true`), which makes "restore everything in the Trash" one query.

| Key | Meaning |
|---|---|
| `text` (alias `query`) | name or slug contains; an asset also by filename (**Name contains**) |
| `tags` | has any of these tags, by slug or name (**Tagged**, comma-separated) |
| `collection` / `collections` | in this collection / any of these (**In collection**) |
| `unattached` | `true`: used by no entry; `false`: used by at least one (**Used by an entry**) |
| `trashed` | `true`: only items in the Trash (**in the Trash**) |
| `created_after` / `created_before` | ISO dates or datetimes (UTC) |
| `asset_type` / `asset_types` | assets only: `image`, `svg`, `document`, `video`, `audio`, `archive`, `other` (**Asset type**) |
| `mime_type` / `mime_types` | assets only: exact MIME type, e.g. `image/svg+xml` (**MIME type**) |
| `resource_type` / `resource_types` | resources only: the resource's type, e.g. `supplier` (**Resource type**) |

An asset or resource query takes only these keys: no `where`, `sort`, `status`, `fields` or `metadata`. Saving a workflow whose target, or whose entry step's `entity_query`, has an unknown key or the wrong shape is refused with the path of each problem (`POST /api/automations/validate` lists them too). The [Workflow Library](https://github.com/InnerOpen/marvin/blob/develop/docs/workflow-library/catalogue.md) has worked examples: *Trash every unattached image*, *Restore all resources in the Trash* and *Post new uploads to a chat channel*.

### Step kinds

| `kind` (builder label) | Fields | Behaviour |
|---|---|---|
| `entry` (Entry action) | `op` (`publish`, `unpublish`, `archive`, `trash`, `restore`, `add_to_collection`, `remove_from_collection`, `set_metadata`, `set_data`, `request_review`), `entity_id` (default `$event.entry_id`), `entity_slug`, `entity_query` (the query above; must match exactly one entry — with `if_none: skip`, no match ends the step quietly with output `{skipped: true, reason: "no matching entry"}` instead of failing it; more than one match still fails; in the builder, **By query (find exactly one)** with **If no entry matches, skip this step instead of failing the run**), `collection_slug`/`collection_id`, `metadata`, `data`, `reason` | Status ops emit the matching lifecycle event (`unpublish` returns the entry to `draft`; `restore` returns an archived entry to `draft` and a trashed one to the status it had, a published one as a draft). **Move to Trash** (`trash`) sends `entry_updated` and `entry_trashed`; an entry already in the Trash is skipped (`{skipped: true}`), so a target of "all entries" + `trash` can be run again safely. `trash` and `restore` also act on an asset or a resource: with no `entity_type` (**Acts on**: *The current item*) they act on each row of an asset or resource target, or on the asset/resource an `asset_*` / `resource_*` event is about; with `entity_type: "asset"` / `"resource"` they act on one named by `entity_slug` or `entity_id` (default `$event.asset_id` / `$event.resource_id`); they send only `asset_trashed` / `asset_restored` (or the resource events), and one already where the op would put it is skipped. No other op takes an `entity_type`. There is no op to delete forever or empty the Trash — see [Trash](trash.md). A publish the publish gate refuses (a missing required field, a placeholder link, a passed expiration date) fails the step with that reason. **Set metadata** (`set_metadata`) merges templated keys into the entry's metadata. **Set fields** (`set_data`) merges into the entry type's own fields, converts typed text to the field's type (true/false for a checkbox, a number for a number field) and validates against the schema, so an unknown select option fails the step. Both drop values that resolve empty and fail if nothing is left. **Send to review** (`request_review`) moves the entry to Needs review; its optional templated `reason` is added to the entry's `metadata.review_reasons` (once — a repeat isn't listed twice), and the review queue's entry cards show it beside a flagged submission's own reasons. |
| `webhook` (Call webhook) | `webhook_id` or raw `url`; `method` (raw URL only; default `POST`), `body`, `secret_ref`, `auth_scheme` (`Bearer` default, or `Token`) | A configured webhook's URL, method, `{{SLUG}}` headers and custom payload are used, with `${event…}` templates resolved. Timeout 15 s. A non-2xx response fails the step. Output: `status_code`, `ok`, `webhook_id`, `body` (parsed JSON or text). Deliveries appear in the webhook log. |
| `integration` (Run integration) | `integration` (the connection's slug from its card, not the provider's), `action` (the provider action key) — or `capability` instead: `notify` with `args` `title` and `body` sends through whatever message action that integration has (Slack's `send_message`, Apprise's `notify`), so one workflow works with either — `args` (templated) | Runs one action of an enabled [integration](integrations.md) with its stored credentials; the provider's result is the step output. An action that requires approval is refused, since nobody is there to approve it. A top-level arg whose whole value is `{{SLUG}}` is replaced by that workspace secret for the call only (the stored workflow keeps the reference); a secret that does not exist fails the step. A provider may give its error a stable code (Buttondown: `blocked`, `suppressed`, `spammy`, `unknown`), which on-failure steps read as `${error.code}`. An input the provider links to one of its read actions gets a searchable picker above the arguments (see [Pick a value from the service](integrations.md#pick-a-value-from-the-service)). |
| `operation` (AI operation) | `op` (AI operation slug), `input`, `entity_type`, `entity_id`/`entity_slug`, `write_back` | Offered only when AI is enabled and the **Workflows** invocation source is on. **Write the result back to the entry** (`write_back: true`) follows the workspace approval mode: the result is applied or staged as a suggestion, and the output's `_write_back` says which (`applied` or `staged`). The workspace's AI limits apply: over the daily request or monthly cost limit the step fails, and the per-request token cap bounds the call (see [Agents and Ask → Usage and limits](agents-and-ask.md#usage-and-limits)). |
| `handler` (Run task) | `task`, `config` | Allowlist: `request_site_rebuild`, `publish_scheduled_entries`, `unpublish_expired_entries`, `ai_reindex_embeddings`, `resync_smart_collections`, `media_enrich`. `request_site_rebuild` queues a coalesced rebuild (see [Operations → Site rebuilds](../operations.md#site-rebuilds)). |
| `emit_event` (Emit event) | `event`, `entity_id` (default `$event.entry_id`); for site events `message`, `error`, `site_url`, `deployment_id` (templated) | An entry event (`entry_*`) is re-emitted for the entry in context, at depth + 1. A site event (`site_deployment_started` / `_completed` / `_failed`; the old names `site_build_*` emit the same events) needs no entry: it records the build or deploy with the given message (default "Site deploy failed" and so on), failure reason and site URL, and shows as an activity toast. For a site event the builder adds message, failure-reason and site-URL inputs; `deployment_id` is set through **Edit as JSON**. Other events are refused. |

Only the first 10 steps run; the validator warns when there are more.

### When a step fails

`on_failure` is a second list of steps, run when any step of `actions` fails: in the same run, on the same entry (each row's own entry in a query run), after the failed step. They read the failure as `${error.message}` (the step's error), `${error.code}` (the provider's code; `unknown` when it gave none), `${error.step}` (the failed step's `id`, else its position from 0), `${error.kind}` and `${error.at}` (when it failed, ISO 8601). A typical pair records the reason and sends the entry to review, so a refused signup doesn't sit in the inbox looking like a pending one:

```json
"on_failure": [
  {"kind": "entry", "op": "set_metadata",
   "metadata": {"subscribe_error": {"code": "${error.code}", "message": "${error.message}", "at": "${error.at}"}}},
  {"kind": "entry", "op": "request_review", "reason": "${error.message}"}
]
```

- The run is still recorded `failed` and still emits `automation_failed` (so `on_error` workflows and the toast still fire): the workflow's own work didn't happen. Its message ends "(on-failure steps ran)", or "(an on-failure step failed too)". **Runs** lists the on-failure steps after the workflow's own, labelled "on failure: …"; the run's step counts are the workflow's own steps.
- They run once. A failing on-failure step stops the rest and has no handler of its own, so a broken handler can't loop. A successful run skips them.
- An integration step's failure may already be handled by the integration's own error policy: review, retry, an admin alert (see [When an integration fails](integrations.md#when-an-integration-fails)). A workflow with on-failure steps runs those **instead of** the policy (only the connection's alert still fires), and `"integration_errors": "fail"` at the top of a definition opts a workflow out of policies without on-failure steps. The default, `"policy"`, applies them. When a policy handled the failure, `automation_failed` carries `handled: true` and `handling` (for example `["handled by Square: sent to review"]`); a retry run's `automation_ran` / `automation_failed` carries `retry_attempt`, and a retry chain announces only its first failure and how it ends.
- The guided builder has no fields for them: it says when a workflow has them and keeps them on save. Edit them in **Edit as JSON**. They're validated like `actions`, and up to 10 run.

## Where

**Workspace Settings → Automation → Workflows** (`/automation/workflows`). Each card offers **Run**, **Dry run**, **Runs** (the last 15 executions), **Enable**/**Disable**, **Edit**, **Copy JSON** and **Delete**. Trigger labels in the builder: Event, Manual (Run button), Schedule, After another workflow, When a workflow fails, Incoming webhook (external POST), MCP tool (external hosts).

## How to use

1. **New workflow**, or **Start from a recipe…** to begin from one of the [Workflow Library](#workflow-library)'s recipes. Then pick a **Trigger** and add conditions under **Only if** with the guided field picker (fields depend on the trigger; `entry.*` is offered only where an entry exists).
2. Add steps under **Then do**. To read a step's output later, give the step an `id` in **Edit as JSON** (`$steps.subscribe.output.body.id`).
3. **Save workflow**. Structural errors (unknown kind, missing field) block the save with `422`; advisory warnings (a condition that can never match) do not.
4. **Dry run** to see the resolved plan without executing, then tick **Enabled** and **Run**.

**Edit as JSON** takes the bare definition (`{"trigger": …, "conditions": […], "actions": […]}`) or a whole workflow, `{"name": "…", "slug": "…", "definition": {…}}`, which is what **Copy JSON** on a card copies (name, slug and definition, no ids). The slug travels because it is the workflow's identity: an "after workflow …" trigger names its workflow by slug, and a renamed workflow keeps its old one, so the copy keeps chains working in another workspace. Pasting a whole workflow fills **Name** (and, for a new workflow, the slug) and leaves the definition in the box; a slug this workspace already uses becomes the next free number (`archive-old-2`), and the paste says so. If the pasted trigger runs after a workflow this workspace doesn't have, the editor warns: copy that one over too. `enabled` in pasted JSON is ignored: a new workflow is saved disabled until you tick **Enabled**. Switching back to the guided builder carries the JSON over; if it doesn't parse, or holds something the builder can't show (a cron schedule, a non-text condition value, a condition group), the editor stays in JSON and lists the parts, or asks before dropping them. A refused save lists each invalid field (`actions.0.entry.op: Field required`).

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

### Workflow Library

**Settings → Automation → Workflow Library** (`/automation/library`) lists ready-made workflows. Each card says when it runs, what it changes (your content, another service, paid calls, notifications, email) and whether this workspace can use it: **Ready here**, **Needs setup** (with what is missing, such as a connected Buttondown integration), **Set up elsewhere** (it is not a workflow: the card lists the parts and links to the page each is set up on, such as Notifications or Email settings) or **Not possible yet** (an idea Marvin can't run, naming what it waits on). The page shows the first two by default. **Use in editor** opens the recipe in the workflow editor.

In the editor, **Start from a recipe…** opens the same recipes. Choose one to read what it does, then set it up: each setting is a picker of this workspace's own names (an entry type and its fields, a connected integration of the right kind, an outgoing webhook, a collection, a status), or a box for a number or text. **Use recipe** fills the builder with the workflow; nothing is saved until you press **Save workflow**, and it saves switched off, so dry-run it before you enable it. A note above the builder names the recipe and lists anything to check, such as a webhook this workspace doesn't have. A recipe the guided builder can't show in full opens in **Edit as JSON**. An event's page (**Subscribe → From the Library**) and a connected integration's card list the recipes for that event or provider.

A workflow saved from a recipe (in the editor, or drafted by the agent with `draft_workflow(recipe=…)`) remembers which recipe and which version of it it came from (`sourceRecipe`, `sourceRecipeVersion` on the workflow). The recipe's card then says **In use:** with a link to each such workflow ("(off)" when it is switched off) and **recipe updated since** when the recipe has been improved after that workflow was made; **Start from a recipe…** shows the same under **Already in use here**, so a second copy is a choice. The notification recipes take any connected integration that can send notifications — Slack or Apprise.

## API

All routes need workspace ADMIN or OWNER. See [API reference](../api/index.md).

| Method and path | Purpose |
|---|---|
| `GET /api/automations` · `POST /api/automations` | List, create (`name`, `slug?`, `enabled`, `definition`). |
| `GET` / `PATCH` / `DELETE /api/automations/{id}` | Read, update, delete (also removes the backing scheduled task). |
| `GET /api/automations/library` | Every Library recipe with `missing` (what this workspace lacks; empty: ready), the `capabilities` ideas wait on, and `refs` for the setup pickers. |
| `POST /api/automations/library/{id}/configure` | `{"vars": {…}}` → `{name, definition, issues}`, the recipe filled in for this workspace. Saves nothing. `404` unknown, `409` not usable here, `422` a bad setup value. |
| `GET /api/automations/options` | Trigger types, event catalog, operators, condition fields per trigger, step kinds, AI operations, webhooks, incoming webhooks, other workflows, and the definition JSON Schema. |
| `POST /api/automations/validate` | `issues[]` with `level` `error` or `warning`, `where`, `index`. |
| `POST /api/automations/preview` | Resolve a `target` query with an optional test `payload`; returns `matches` (capped, after conditions), `total`, `capped`. |
| `POST /api/automations/{id}/run` | Manual run; responds when the run finishes (`409` when disabled). With `?dry_run=true` it returns `plan` and records nothing. For an event-triggered workflow the dry run also takes `entry_id` or `event_id` (an event log row) and returns `sample`, `trigger_matched`, `conditions` (each with `field`, `op`, `value`, `actual`, `expected`, `pass`, or a nested `group`), `conditions_pass` and `would_fire`. |
| `GET /api/automations/{id}/samples?limit=` | The dry run's candidate samples: recent logged events the trigger fires on, then uncovered entries (default 10, at most 25), each with `kind`, `id`, `label`, `occurred_at`, `synthesized`, `conditions_pass`. Empty for a workflow no event triggers. |
| `GET /api/automations/{id}/executions?limit=` · `GET …/executions/{execution_id}` | Run history (default 25, at most 100); detail includes per-step records and the definition snapshot. |

## Settings

A workflow is `enabled: false` when created. A disabled workflow does not run from events, the scheduler or **Run**, but can be dry-run. A workflow with the `mcp` trigger is exposed by the Marvin MCP server as a tool named `marvin_wf_<slug>` (non-alphanumerics in the slug become `_`; needs a user token, see [Marvin as an MCP server](marvin-as-mcp-server.md)). Separately, the agent's `run_workflow` tool runs any enabled workflow by slug, name or id, skipping its trigger and conditions as **Run** does, and the run is recorded under **Runs**. Like **Run**, it needs workspace ADMIN or OWNER (as does `list_workflows`).

**Agents can draft workflows.** Asked to create, build or set up a workflow, an agent reads the format from `workflow_authoring_guide` and saves it with `draft_workflow`. The workflow is created switched off, through the same save as **New workflow** (the same slug from the name, the same checks, recorded as created by you, so its steps run with your role), and the agent answers with a link that opens it in the editor (`/automation/workflows?workflow=<id>&edit=1`). Review the trigger and steps, dry-run it to see which entries it would act on, then tick **Enabled**. An agent never enables or runs a workflow it drafted. A draft also has to pass checks the editor doesn't make: every key must be one the format has (a `steps` list or a step's `type` is refused rather than ignored), and every name must exist (a triggerable event, an entry query key, an entry type, a collection, an AI operation, an allowed job, an integration action that can run unattended, an outgoing or incoming webhook, another workflow); template values (`${…}`) are left to run time. The agent gets each problem with its path, such as `actions[0].op`, and tries again. `update_workflow_draft` revises a workflow only while it is switched off. See [Agents and Ask](agents-and-ask.md#what-it-does).

## Since

`form_submission_received` as a trigger: v1.0.0-rc.51 (`8f1443d1`). `auth_scheme`: rc.50 (`a65ba7d0`). `entry.summary` and `entry.data.*`: rc.52 (`433e949e`). Response `body`, `set_metadata` and metadata targeting: rc.59 (`1380e92e`). `entity_query`: rc.60 (`65ffb648`). Raw-URL `method` and templated stored URLs: rc.61 (`b88e4035`). Builder fixes: rc.63 (`57956e71`). `set_data`, the integration step, `entry.metadata` and list indexes in paths: rc.111. `entry.image`: rc.119. Full entry context per query row and **Fields equal**: rc.129. Typed values for checkbox and number fields: rc.131. The shared entry query (`where`, `sort`, date filters): rc.138. Unknown `where` ops match nothing, and `run_workflow` runs appear under **Runs**: rc.139. Site build and deploy events from `emit_event`: rc.144. `{{SLUG}}` in integration step args: rc.145. AI limits on operation steps: rc.146. Site events as notification subscriptions: rc.151; as workflow triggers: rc.152. `automation_started` and the shared `execution_id`: rc.165. Dry run against a sample event, with the condition checklist and `GET …/samples`: rc.173. A refused publish fails the entry step with the reason: rc.175. `${site.url}`: rc.177. Each event's subject, a run's trigger (`trigger_entity_*`) and step summaries in `automation_ran` / `automation_failed`, `$event.entity_type` / `$event.entity_id`: rc.178. `if_none: skip` and `${entry.url}`: rc.179. `on_failure`, `request_review` and an integration error's `${error.code}`: rc.193. Integration error policies (`integration_errors`, `handled` / `handling` / `retry_attempt` on run events), a workflow never re-triggering itself, and option pickers in the **Run integration** step: rc.197.

## Related

- [Incoming webhooks](incoming-webhooks.md) · [Outgoing webhooks](outgoing-webhooks.md) · [Forms and submission protection](forms-and-submission-protection.md) · [Integrations](integrations.md)
- [Glossary](../glossary.md)
