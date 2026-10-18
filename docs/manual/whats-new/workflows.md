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
| `manual` | You press **Run** or call `POST …/run` | It can ask for inputs when it runs — see [Run inputs](#run-inputs) |
| `schedule` | A scheduler task fires; saving upserts a `run_automation` task (`wf-<id>`), deleted again when the trigger changes | `schedule_type: "interval"`, `schedule_config: {"interval_seconds": n}` |
| `chained` | Another workflow finishes (`automation_ran`) | `automation`: slug/id, or `any` |
| `on_error` | Another workflow fails (`automation_failed`) | `automation` |
| `incoming_webhook` | An [incoming webhook](incoming-webhooks.md) receives a POST | `webhook`: slug, or `any` |
| `mcp` | An external MCP host calls the workflow's own tool, `marvin_wf_<slug>` (see [Settings](#settings)); **Run** also works | |

Event triggers accept only the curated catalog: Members (`member_added`, `member_role_changed` — the run reads the person as `${member.*}`: `id`, `username`, `name`, `email`, `role`; the event's `user_id` is the admin who did it), Entries (`entry_created`, `entry_updated`, `entry_published`, `entry_unpublished`, `entry_archived`, `entry_trashed`, `entry_restored`, `entry_deleted`, resource/tag/asset attach and detach), Collections, Assets, Resources, Forms (`form_submission_received`, `submission_surge_detected`, `form_*`), Entry types and Site (`site_deployment_started`, `_completed`, `_failed`; a trigger naming the old `site_build_*` names is saved as its `site_deployment_*` counterpart). Site events come from an **Emit event** step (usually a workflow on a host's deploy-notification webhook), so a second workflow can react to them — for example, tell someone when a deploy fails; reaction depth keeps such chains bounded. Your own [custom events](#custom-events) (`custom.<name>`) are offered under a **Custom** heading once registered. Under **Operations**: the platform reporting a failure or a shortfall — see [Answer a failure](#operational-events).

### Custom events {#custom-events}

Marvin's catalog lists what Marvin itself sends. A workspace can add events of its own, named `custom.<name>`: a "milestone reached", a "kit shipped". Nothing in Marvin sends one but a workflow's **Emit event** step; everything else treats it like any other event.

**Register one** under **Settings → Automation → Custom events** (`/automation/custom-events`, workspace OWNER/ADMIN), or `PUT /api/groups/custom-events/{name}`. A name is `custom.` and a slug: it starts with a letter and uses lowercase letters, digits and underscores (40 characters at most). Give it an optional title and description and up to 12 **fields**, each a key and a simple type: `string`, `number`, `boolean` or `date`. A workspace can register 50. Registering an existing name replaces it. An event a workflow still starts on or sends can't be removed (the page says which workflows); what the Event Log recorded stays.

**Send it** with an Emit event step: `{"kind": "emit_event", "event": "custom.milestone", "payload": {"milestone": "Shipped", "badge": "First ${entry.title}"}, "message": "${entry.title} shipped"}`. The payload may name only the event's fields (a key it doesn't have fails the step, and the validator and the AI authoring guide say so first); each value is a template, then held to its field's type: `"12"` becomes the number 12 for a `number`, `"yes"` the boolean true, an ISO date or date and time the date; a value that doesn't fit fails the step, and an empty one is left out. The event is about the run's entry when there is one (`entity_id`, default `$event.entry_id`) and carries the workflow's reaction depth + 1. A dry run shows the resolved payload and sends nothing. An unregistered name is never sent.

**React to it.** A workflow can start on it: the editor's trigger list has a **Custom** heading, and the run reads `${event.payload.<field>}` (and `${entry.*}` when the event is about an entry). A workflow never wakes for an event its own run sent; another one does, which is how one workflow hands work to the next. Chains stop where every emitted event does: at reaction depth 3 the event is recorded but nothing reacts to it. Webhook, email and integration subscriptions name a custom event like any other (the pickers list it, with its fields): a webhook receives `eventType: "custom.milestone"` and `documentData: {eventName, payload, workspaceId}`, and an email template reads each field as `{{ field }}`. The Events pages show it under **Custom** with what sends and reacts to it, and `describe_event` explains it with its fields. Custom events are always recorded in the Event Log.

### Answer a failure (operational events) {#operational-events}

A workflow can start on the events that say something is failing or running short. They are listed under **Operations** in the trigger list:

| Event | Fields (`${event.<field>}`) |
|---|---|
| `webhook_delivery_failed` | `webhook_id`, `webhook_name`, `delivered_event_type`, `status_code`, `error_message`, `attempts` |
| `integration_attention_needed` / `integration_attention_resolved` | `integration_slug`, `integration_name`, `provider`, `provider_name`, `alert_id`, `code`, `error`, `count`, `reminder`, `title`, `summary` |
| `scheduled_task_failed` | `task_id`, `task_name`, `task_slug`, `task_type`, `error_message`, `consecutive_failures`, `transient` |
| `ai_budget_threshold_reached` / `ai_budget_exceeded` | `current_value`, `limit_value`, `percent`, `detail` |

`describe_event` and the AI authoring guide list the same fields. **Whose failure it is.** A workflow is never woken by a failure its own run caused: its Emit event step that a down webhook can't deliver, its AI call that crosses the budget, its integration step that makes a connection fail. That failure goes to the other workflows and to the usual alerts, but not back to the one that made it, so answering a failure can't start a loop. This also holds when the delivery runs after the workflow's run ended: the failed delivery is announced with the workflows that sent the event it carried, and those sit it out (a workflow that merely ran earlier in the same chain, without sending the event, still answers it). A failure nothing a workflow did caused wakes every workflow that answers it.

**Whose workspace.** A workflow runs in the workspace the event belongs to. A scheduled task that is the platform's own (the system tasks in Admin) has no workspace, so no workflow hears its failure (it shows under **Admin → Scheduled Tasks**). A workspace's own scheduled tasks do.

**A backup channel.** These events still reach **Settings → Automation → Notifications** (email to owners and admins, push, a chat connection) with no workflow involved, and a workflow that answers one and fails itself is reported there as a failed workflow. So a workflow is an addition to the alerts, never the only way to hear. A workflow runs on every event: for one that should act once per incident, look for an open task first (the Library's *Integration health companion* and *Webhook repair desk* do), or gate it with a condition such as `event.consecutive_failures` ≥ 2.

### Conditions and context

Operators: `eq`, `neq`, `contains`, `in` (a comma-separated string is accepted), `starts_with`, `exists` (`value: false` inverts), `changed`, `changed_from`, `changed_to`, and the number comparisons `gt`, `gte`, `lt`, `lte` (**is more than**, **is at least**, **is less than**, **is at most**: both sides read as numbers, typed-in text too; anything that isn't a number never matches). `longer_than` and `shorter_than` (**is longer than**, **is shorter than**, in characters) compare a text's length — or a list's item count — with a number; nothing there counts as length 0. A top-level list is AND; `{"all": […]}`, `{"any": […]}` and `{"not": …}` nest. An unknown operator never matches. The `changed*` operators read `event.changed_fields`, `event.before` and `event.after` from an `entry_updated` event (and the publish, unpublish, archive, trash and restore events, which carry the same diff).

**A type's own field changing.** The diff covers `status`, `title` and `slug` and every changed field of the entry's type, as `data.<field>`: `entry.data.price` with `changed` is true when the price changed, `changed_from` / `changed_to` compare the old and new value, and `event.changed_fields` `contains` `data.price` says the same. The values are `${event.before.data.price}` and `${event.after.data.price}`. They are kept small, because an event outlives the edit (it goes to the Event Log and to webhooks): a number, yes/no or a short text (up to 160 characters) is carried as it is; a longer text such as a body, a list, an object, or a field whose name reads as a secret (`password`, `token`, `api_key`…) shows `‹elided›` — the field is still named in `changed_fields`, so “the body changed” works, but not what it said. An event names up to 100 changed fields and carries values for the first 25. The field picker offers `event.after.data.`, `event.before.data.` and `entry.data.`, and `describe_event` lists the diff fields.

The builder sends every value as text. `eq` and `neq` convert it to the type of the value being compared: `true`/`false` (also `yes`/`no`, `on`/`off`, `1`/`0`) against a checkbox, a number against a number field.

| Namespace | Contents |
|---|---|
| `event.*` | Every field of the event's data, plus `event_type`, `entry_id`, `entity_type`, `entity_id` (what the event is about), `webhook_slug`, `payload`, `changed_fields`, `before`, `after`, `user_id`. `entry_id` is set only when the event is about an entry. Forms: `event.submission_data.<field>`. |
| `entry.*` | `id`, `entry_type`, `status`, `title`, `slug`, `summary`, `data.<field>` (the entry type's fields), `metadata.<key>`, `image` (the featured image's public URL, or empty). Present for entry events and for every row of a query run. |
| `asset.*` | `id`, `slug`, `name`, `asset_type`, `mime_type`, `filename`, `file_size`, `description`, `tags`, `metadata.<key>`, `url` (its public URL, or empty), `trashed`, `derived_from` (the id of the asset it was made from — a [Process an image](#process-an-image) step's or an entry type's media derivative; empty for an original), `origin` (`upload`, `derived` or `generated`). Present for `asset_*` events and for every row of an asset query run. |
| `resource.*` | `id`, `slug`, `name`, `resource_type`, `description`, `tags`, `metadata.<key>`, `url` (its link), `external_id`, `trashed`. Present for `resource_*` events and for every row of a resource query run. |
| `form_submission.*` | `id`, `form` (the form's name), `form_slug`, `data.<field>`, `status`, `submitted_at`, `flagged` (submission protection held it), `review_reasons`. Present for `form_submission_received` and for any run on an entry of a form (a submittable entry type) — see [Classify a form submission](#classify-a-form-submission). |
| `previous.*`, `steps.<id or index>.output.*` | Step outputs; usable in step inputs only, never in conditions. |

A numeric path segment indexes a list: `event.payload.items.0.id`.

Templates in step inputs: `$event.entry_id` or `${event.count}` alone keeps the value's type; `Summary: ${previous.summary}` embeds as text, so `${entry.image}` or `${entry.data.<field>}` can be handed to a webhook or integration. `${entry.url}` is the entry's page on the site (absolute when the Canonical URL is set, otherwise the site path; empty when its type has no page URL pattern). `${site.url}` is the workspace's Canonical URL (Settings → General), or empty when it isn't set — e.g. the base a newsletter integration makes an issue's relative links absolute against. `${path|url}` URL-encodes the value, for a share link's text or a query string (`https://bsky.app/intent/compose?text=${steps.post.output.text|url}`). A member event's run reads the person as `${member.name}`, `${member.email}` and so on. An entry also carries the dates every entry has, whatever its type's fields: `${entry.published_at}`, `${entry.publish_at}` (scheduled), `${entry.expire_at}`, `${entry.created_at}` and `${entry.updated_at}` (UTC). `{{SLUG}}` secret refs resolve only in a configured webhook's headers, in a webhook step's `secret_ref`, and in a Run integration step's `args` (see below).

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
| `entries` | exactly these entries, by id or slug (one or a list) — the entry a field names: `{"entries": "${entry.data.project}"}`. The other way round, the entries whose field names this one, is `{"data": {"project": "${entry.slug}"}}` |
| `asset` / `resource` | linked to this asset / resource (id or slug): the entries that use a picture, or a supplier |
| `fields` (alias `data`), `metadata` | exact match, `{field_key: value}`; typed text matches checkbox and number values; an empty value matches nothing |
| `where` | `[{"field": key, "op": op, "value": v}]`, where `field` is a field key or `metadata.<key>`; ops `eq`, `neq`, `in`, `contains`, `exists`, `missing`, `gt`, `gte`, `lt`, `lte`. Comparisons read number-like text (`"$1,170"` → 1170). An unknown op makes the query match nothing (with a note), so a typo never widens the target. |
| `created_after` / `created_before`, `updated_…`, `published_…` | ISO dates or datetimes (UTC), or relative to the moment the run reads them: `-7d`, `-12h`, `-2w` (ago; `+3d` is ahead), `now`, `today` (midnight UTC). A date it can't read stops the query with a note instead of being ignored |
| `sort` | `{"by": <key>, "direction": "asc"}` (or `"desc"`); `by` is `title`, `created_at`, `updated_at`, `published_at`, `position` or a field key. A field sorts numerically when its values are number-like, empty values last. `position` is the order of the one `collection` the query names, as the site shows it (its order, then newest published). Default: newest created first. |

In `where` and `sort` a bare key is always the entry type's own field. `where` and sorting by a field read at most 5,000 entries. Query values may be `${event…}` templates, so a webhook payload can carry the query.

#### Run on assets or resources

With **Assets** or **Resources**, the target is `{"entity": "asset", "query": {…}}` (or `"resource"`) and each row gets `asset.*` / `resource.*` (see the context table above), so a condition on `asset.mime_type` or `resource.tags` works per row. The same 250-row cap applies. The steps that act on an item are **Move to Trash** and **Restore** (with **Acts on** left at *The current item*, a bare `trash` or `restore` step acts on each row); webhook and integration steps can read the row through templates such as `${asset.url}`. Other entry ops act on entries only, and `entity_query` always finds entries. Items in the Trash match only a query that asks for them (**in the Trash**, `trashed: true`), which makes "restore everything in the Trash" one query.

| Key | Meaning |
|---|---|
| `text` (alias `query`) | name or slug contains; an asset also by filename (**Name contains**) |
| `tags` | has any of these tags, by slug or name (**Tagged**, comma-separated) |
| `collection` / `collections` | in this collection / any of these (**In collection**) |
| `unattached` | `true`: used by no entry; `false`: used by at least one (**Used by an entry**). A version made from an original still in the library doesn't count as unattached (it goes with its original) unless the query asks for versions (`versions: true` or `source`) |
| `trashed` | `true`: only items in the Trash (**in the Trash**) |
| `entry` | attached to this entry (id or slug), in the entry's own order — a project's pictures or materials: `{"entry": "${entry.id}"}` |
| `role` | assets only: attached in this role (`hero`), to `entry` or, without it, to any entry |
| `exclude` | leave this one out (id or slug): "the others", e.g. `${asset.id}` in a run about that asset |
| `checksum` | assets only: exactly this file (its sha256) — `${asset.checksum}` finds an earlier upload of the same file |
| `created_after` / `created_before` | ISO dates or datetimes (UTC), or relative: `-7d`, `-12h`, `-2w`, `now`, `today` |
| `asset_type` / `asset_types` | assets only: `image`, `svg`, `document`, `video`, `audio`, `archive`, `other` (**Asset type**) |
| `mime_type` / `mime_types` | assets only: exact MIME type, e.g. `image/svg+xml` (**MIME type**) |
| `origin` / `origins` | assets only: `upload`, `derived` (made from another asset by a media step or recipe), `generated` (an image an integration made) |
| `decision` | assets only: what the person said when an approval step showed the picture — `approved`, `denied`, `expired`, `stale`, or `none` (never asked). See [A picture's decision stays with it](#a-pictures-decision-stays-with-it). |
| `versions` | assets only: `false` leaves out versions of an original still in the library; `true` keeps only versions; `all` keeps both (**Versions**). A workflow's asset target runs on **originals only** unless it sets `versions`, `source` or `origin: derived` — so a bulk job never makes copies of copies |
| `source` | assets only: the versions made from this asset (id or slug) |
| `resource_type` / `resource_types` | resources only: the resource's type, e.g. `supplier` (**Resource type**) |

An asset or resource query takes only these keys: no `where`, `sort`, `status`, `fields` or `metadata`. Saving a workflow whose target, or whose entry step's `entity_query`, has an unknown key or the wrong shape is refused with the path of each problem (`POST /api/automations/validate` lists them too). The [Workflow Library](https://github.com/InnerOpen/marvin/blob/develop/docs/workflow-library/catalogue.md) has worked examples: *Trash every unattached image*, *Restore all resources in the Trash* and *Post new uploads to a chat channel*.

### Make a call once (idempotency keys) {#idempotency}

A **webhook** or **integration** step can carry an `idempotency_key`, a template that names what makes this call the same call again: `handoff-${entry.id}`, `subscribe-${entry.data.email}`. The first call goes out and its output is kept. The same key at the same webhook (or integration action), in the same workflow, within the window calls nothing: the step is recorded as a success and its output is the first call's, so `${steps.<id>.output…}` reads what it read the first time, plus `idempotency: {key, duplicate: true, recorded_at}`.

- **The window** is `idempotency_window_hours`, 1 to 720, 24 by default. When it ends the next call goes out and a new window starts. The editor has both fields under the step ("Make this call once", "For how many hours").
- **A failed call doesn't count.** The step gives its key back, so a retry (an integration's retry resumes at the failed step with its own seed) or the next event makes the call. A call still in flight holds the key, so two duplicates racing deliver once; one a crashed worker never finished is open again after five minutes.
- **Different keys are different calls**, and so is the same key at another destination or in another workflow. An entry saved ten times with `handoff-${entry.id}` is handed off once a day, not once per save: put what changed into the key if a later change should go out.
- **A key that reads nothing** (`${entry.data.missing}`) fails the step instead of treating every call as one.
- **A dry run** shows `would: call` or `would: skip (duplicate)` with the key, and claims nothing; after a skip it hands the next step the output a real run would.
- Marvin keeps a hash of the key, the workflow, the destination and the output (up to 100,000 characters; a larger one is dropped, the call still counts). The scheduled **Prune Workflow Runs** task deletes keys whose window ended.

### Step kinds

| `kind` (builder label) | Fields | Behaviour |
|---|---|---|
| `entry` (Entry action) | `op` (`publish`, `unpublish`, `archive`, `trash`, `restore`, `add_to_collection`, `remove_from_collection`, `set_metadata`, `set_data`, `request_review`, `create`, `attach_asset`), `entity_id` (default `$event.entry_id`), `entity_slug`, `entity_query` (the query above; must match exactly one entry — with `if_none: skip`, no match ends the step quietly with output `{skipped: true, reason: "no matching entry"}` instead of failing it; more than one match still fails; in the builder, **By query (find exactly one)** with **If no entry matches, skip this step instead of failing the run**), `collection_slug`/`collection_id`, `metadata`, `data`, `reason` | Status ops emit the matching lifecycle event (`unpublish` returns the entry to `draft`; `restore` returns an archived entry to `draft` and a trashed one to the status it had, a published one as a draft). **Move to Trash** (`trash`) sends `entry_updated` and `entry_trashed`; an entry already in the Trash is skipped (`{skipped: true}`), so a target of "all entries" + `trash` can be run again safely. `trash` and `restore` also act on an asset or a resource: with no `entity_type` (**Acts on**: *The current item*) they act on each row of an asset or resource target, or on the asset/resource an `asset_*` / `resource_*` event is about; with `entity_type: "asset"` / `"resource"` they act on one named by `entity_slug` or `entity_id` (default `$event.asset_id` / `$event.resource_id`); they send only `asset_trashed` / `asset_restored` (or the resource events), and one already where the op would put it is skipped. No other op takes an `entity_type`. There is no op to delete forever or empty the Trash — see [Trash](trash.md). A publish the publish gate refuses (a missing required field, a placeholder link, a passed expiration date) fails the step with that reason. **Set metadata** (`set_metadata`) merges templated keys into the entry's metadata. **Set fields** (`set_data`) merges into the entry type's own fields, converts typed text to the field's type (true/false for a checkbox, a number for a number field) and validates against the schema, so an unknown select option fails the step. Both drop values that resolve empty and fail if nothing is left. **Send to review** (`request_review`) moves the entry to Needs review; its optional templated `reason` is added to the entry's `metadata.review_reasons` (once — a repeat isn't listed twice), and the review queue's entry cards show it beside a flagged submission's own reasons. **Create an entry** (`create`) makes a new one: `entry_type` (a slug), `title`, optional `data` (that type's fields, typed and validated as **Set fields** does) and `metadata`, `status` `draft` (default) or `inbox` — publishing is a following **Publish** step with `entity_id: ${steps.<id>.output.entry_id}`, which checks the type's publish rules. Templates work in every value. Its output is `{entry_id, slug, created}`; it sends `entry_created`, and the same event handled twice (same correlation id, workflow and step) finds the entry it made instead of making a second (`created: false`; the key is kept in the new entry's `metadata.automation_created`). |
| `webhook` (Call webhook) | `webhook_id` or raw `url`; `method` (raw URL only; default `POST`), `body`, `secret_ref`, `auth_scheme` (`Bearer` default, or `Token`) | A configured webhook's URL, method, `{{SLUG}}` headers and custom payload are used, with `${event…}` templates resolved. Timeout 15 s. A non-2xx response fails the step. Output: `status_code`, `ok`, `webhook_id`, `body` (parsed JSON or text). Deliveries appear in the webhook log. |
| `integration` (Run integration) | `integration` (the connection's slug from its card, not the provider's), `action` (the provider action key) — or `capability` instead: `notify` with `args` `title` and `body` sends through whatever message action that integration has (Slack's `send_message`, Apprise's `notify`), so one workflow works with either — `args` (templated) | Runs one action of an enabled [integration](integrations.md) with its stored credentials; the provider's result is the step output. An action that requires approval runs only after a [Wait for approval](#wait-for-approval) step, and only when it was approved. An action that makes images (an `image.*` capability, such as OpenAI Images' **Generate image**) keeps each one as an asset — see [Generated images are kept](#generated-images-are-kept). A top-level arg whose whole value is `{{SLUG}}` is replaced by that workspace secret for the call only (the stored workflow keeps the reference); a secret that does not exist fails the step. A provider may give its error a stable code (Buttondown: `blocked`, `suppressed`, `spammy`, `unknown`), which on-failure steps read as `${error.code}`. An input the provider links to one of its read actions gets a searchable picker above the arguments (see [Pick a value from the service](integrations.md#pick-a-value-from-the-service)). |
| `approval` (Wait for approval) | `message` (what is asked; templates allowed), `approvers` (`editor`, the default, or `admin`), `expires_in_hours` (1–720; default the workspace's **Approvals wait**, else 72) | The run waits here for a person — see [Wait for approval](#wait-for-approval). |
| `collect` (Gather items) | `entity` (`entry`, `asset`, `resource`), `query` (a target's keys), `fields`, `limit` (default 25, at most 250) | Gathers a set into one output so the steps after it see them all — see [Gather items](#gather-items-many-one). |
| `wait` (Wait) | `for` (a span) or `until` (a date) with `offset` and `at` | Keeps the run and goes on later — see [Wait](#wait). |
| `repeat` (Repeat for each) | `for_each` (a list), `as` (the item's name), `steps` (1–5), `limit`, `on_item_error` | Runs its steps once for each item — see [Repeat for each](#repeat-for-each). |
| `parallel` (Parallel branches) | `branches` (2–5, each a `name` and `steps` 1–5), `join` (`all`, the default, or `any`), `on_branch_failure` (`fail`, the default, or `continue`) | Runs independent branches of steps and joins them — see [Parallel branches](#parallel-branches). |
| `fetch` (Check a web address) | `url` (+ `method` `GET`/`HEAD`, `find`) or `links` (a text, + `base`) | Reads a public web address, or checks the links in a text. A dead link is output, not a failure — see [Check a web address](#check-a-web-address). |
| `schema_check` (Check against a schema) | `document`, `schema` or `schema_resource`; `fail_on_invalid`, `max_errors` | Holds a JSON document up against a JSON Schema and reports what doesn't fit. An invalid document is output, not a failure, unless `fail_on_invalid` — see [Check against a schema](#check-against-a-schema). |
| `email` (Email a member) | `to` (a member's id or email), `subject`, `body` (markdown), `heading`, `button_text` + `button_link`, `once_per` | Writes to a member of the workspace — never an outside address — in the workspace's email layout; sent once per event. See [Email a member](#email-a-member). |
| `metric` (Record a metric) | `op` (`record`, the default, `add` or `read`), `metric`, `value`, `variant`, `subject`, `window` (`day`/`week`/`month` or `2026-10-18` / `2026-W42` / `2026-10`), `at`; for a read `window_from`, `window_to`, `limit` | Records a number as an observation for a metric, variant and window — or adds to a count, or reads observations back. Recording again replaces the number; adding raises it, once for each event; a dry run writes nothing. Observations, not conclusions — see [Record a metric](#record-a-metric). |
| `snapshot` (Save or restore a version) | `op` (`capture`, the default, or `restore`), `label`, `snapshot` (an id), `parts`, `entity_id`/`entity_slug` | Keeps a version of an entry and puts it back — see [Save and restore a version](#save-and-restore-a-version). |
| `media` (Process an image) | `op` (`resize`, `crop`, `convert`, `grade`, `inspect`, `palette`), `source`, the op's own fields, `attach_as` | Makes a new image from an image, or reads one — no AI or provider needed. See [Process an image](#process-an-image). |
| `operation` (AI operation) | `op` (AI operation slug), `input`, `entity_type`, `entity_id`/`entity_slug`, `write_back` | Offered only when AI is enabled and the **Workflows** invocation source is on. **Write the result back to the entry** (`write_back: true`) follows the workspace approval mode: the result is applied or staged as a suggestion, and the output's `_write_back` says which (`applied` or `staged`). On an asset or resource the step sees the item (an image asset's picture, for an operation that looks at images) and `write_back` is a map of output keys to the item's fields, for example `{"alt_text": "alt_text"}`: an asset takes `alt_text`, `description`, `name`, `tags` or `metadata.<key>`, a resource `description`, `name`, `tags` or `metadata.<key>`. It follows the same approval mode, and needs a workflow author who is an EDITOR or above (else `_write_back` is `not_permitted`). The workspace's AI limits apply: over the daily request or monthly cost limit the step fails, and the per-request token cap bounds the call (see [Agents and Ask → Usage and limits](agents-and-ask.md#usage-and-limits)). |
| `handler` (Run task) | `task`, `config` | Allowlist: `request_site_rebuild`, `publish_scheduled_entries`, `unpublish_expired_entries`, `ai_reindex_embeddings`, `resync_smart_collections`, `media_enrich`. `request_site_rebuild` queues a coalesced rebuild (see [Operations → Site rebuilds](../operations.md#site-rebuilds)). |
| `emit_event` (Emit event) | `event`, `entity_id` (default `$event.entry_id`); for custom events `payload`, `message`; for site events `message`, `error`, `site_url`, `deployment_id` (templated) | An entry event (`entry_*`) is re-emitted for the entry in context, at depth + 1. A site event (`site_deployment_started` / `_completed` / `_failed`; the old names `site_build_*` emit the same events) needs no entry: it records the build or deploy with the given message (default "Site deploy failed" and so on), failure reason and site URL, and shows as an activity toast. For a site event the builder adds message, failure-reason and site-URL inputs; `deployment_id` is set through **Edit as JSON**. A workspace's own `custom.<name>` event (see [Custom events](#custom-events)) takes `payload` (its registered fields, values templated), an optional `message` and an optional `entity_id` (the entry it is about; default `$event.entry_id`, none if the run has no entry). Other events are refused. |

Only the first 10 steps run — or the workspace's **Steps per workflow** (Settings → General, 1–25) — and the validator warns when there are more.

### Run a step only when… (if/else)

Any step can carry `when`: conditions in the same shape and with the same operators as the workflow's own
**Conditions**, checked just before that step runs. Besides the event and the entry they can read what earlier steps
returned, `steps.<id>.output.<key>` and `previous.<key>`. When they don't hold, the step is **skipped**: shown with a
`–` in the run's steps (not a failure), the run goes on, and a later reference to that step's output reads as nothing.
Two steps with opposite `when`s make an if/else:

```json
{"kind": "webhook", "id": "stock", "webhook_id": "<stock checker webhook uuid>"},
{"kind": "entry", "op": "set_metadata", "metadata": {"availability": "in stock"},
 "when": {"field": "steps.stock.output.body.in_stock", "op": "eq", "value": true}},
{"kind": "entry", "op": "request_review", "reason": "Out of stock",
 "when": {"not": {"field": "steps.stock.output.body.in_stock", "op": "eq", "value": true}}}
```

A dry run shows each skipped step with the verdict of its conditions. The editor warns when a `when` reads a step
that hasn't run by then. In the guided editor, open **Only run this step when…** under a step: the same condition rows
as the workflow's own (a grouped condition, `any` or `not`, is edited as JSON there).

### Your own AI instructions (custom AI step)

An **AI operation** step can run **Custom prompt** instead of a built-in operation: your instructions, and the answer
fields you want back. In JSON it is `"op": "custom"` with:

| Key | What it is |
| --- | --- |
| `prompt` | The instructions (up to 8,000 characters). `${entry.title}` and other templates are filled in when it runs. |
| `output_schema` | The answer as a JSON Schema object, for example `{"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}` (1–20 properties). The guided editor builds it from **Answer fields**: a name, a kind (text, number, whole number, yes/no, list of text) and what it's for. |
| `see` | What the AI gets besides the instructions: `item` (the entry, asset or resource it runs on; the default), `attachments` (an entry's attached assets and linked resources), `images` (the pictures: an image asset, or an entry's attached images; needs a model that can see images), `persona` (the workspace persona and tone). |
| `write_back` | Optional, a map from answer field to where it goes: on an entry `summary`, `tags` or `metadata.<key>`; on an asset `alt_text`, `description`, `name`, `tags`, `metadata.<key>`; on a resource `description`, `name`, `tags`, `metadata.<key>`. It follows the approval mode (applied, or staged as a suggestion). An entry's title, status and typed fields are never written this way; to fill a field, add a **Set fields** step reading `${steps.<id>.output.<name>}`. |

The answer is checked against the answer fields. If it doesn't match, the AI is told what was wrong and asked once
more (both calls count against the AI budget); a second miss fails the step. Give the step an `id` and later steps read
the answer as `${steps.<id>.output.<name>}`, including in a `when`. The material the AI is given is marked as data: text
in an entry that reads like instructions is not followed. A dry run shows the instructions with their templates filled
in, and calls nothing.

```json
{"kind": "operation", "id": "ask", "op": "custom",
 "prompt": "Write one open question readers of “${entry.title}” could discuss.",
 "output_schema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
 "write_back": {"question": "metadata.discussion_question"}}
```

Workflow Library recipes that use it: **Community question**, **Marvin margin notes**, **Soundtrack brief**,
**Resource attachment notes** and **Asset attachment social kit**.

### Classify a form submission {#classify-a-form-submission}

A workflow that starts on `form_submission_received` (or runs on an entry of a form) reads the submission as
`${form_submission.*}` — what the visitor sent, as the public form saved it. An **AI operation** step with
`op: "classify-form-submission"` finds that submission itself (no `entity_type` or `entity_id` needed; name
`entity_id` to classify another) and answers `category`, `confidence`, `is_spam`, `sentiment`, `tags` and
`action_required`. Give the step an `id` and read the answer as `${steps.<id>.output.<key>}`, in a `when` or in
later steps. `input.categories` is the list to choose from (default inquiry, support, feedback, other).

```json
{"kind": "operation", "id": "sort", "op": "classify-form-submission", "input": {"categories": ["lead", "support", "press"]}}
```

A dry run asks no AI: the step previews with a stand-in for each text answer (`‹AI answer: category›`) and the steps
after it preview as they will run. The submission's text goes to the workspace's AI provider; submissions that
submission protection already flagged are best left out with a condition on `event.flagged`.

Workflow Library recipe: **Form submission sorter**.

### Save and restore a version {#save-and-restore-a-version}

Entries had a history of *what happened* but no record of *what they looked like*. A **Save or restore a version** step
(`kind: "snapshot"`) keeps one, and puts it back later:

```json
{"kind": "snapshot", "id": "save", "label": "before the rewrite"}
{"kind": "snapshot", "op": "restore", "snapshot": "${steps.save.output.snapshot_id}"}
```

**Capture** (the default) keeps the entry's title, summary, description, fields, metadata, status, its collections and
which assets are attached (references — the files aren't copied). Smart collections, tags and linked resources aren't
kept. Output: `snapshot_id`, `label`, `created`. An entry whose latest version is already identical gets that one back
(`created: false`), so a run repeated for the same entry adds nothing; an entry keeps its **latest 20** versions and the
oldest go first. They are removed with the entry.

**Restore** puts `snapshot` back on its entry; left out, the entry's latest (or the latest with `label`) is used.
`parts` says what comes back: `content` (title, summary, description, fields, metadata — metadata whole, except the
Trash record), `collections` (added to the ones it was in, removed from the others), `assets` (the links it had are made
again in their role, the ones added since are detached; an asset that has been trashed or deleted since is listed as
`missing`). The default is those three. **`status` is only restored when you list it**: restoring content never publishes
or unpublishes an entry by itself, and a status that would publish goes through the same publish checks as any edit. It
never moves an entry into or out of the Trash (an entry in the Trash must be restored from there first). Restoring runs
through the entry service, so the usual events go out at the next reaction depth (`entry_updated`, collection and asset
link events, a status change's own) and other workflows see them. A restore that would change nothing writes nothing;
output: `restored`, `changed`, and what changed by part.

A dry run previews the same difference (`would`: `capture` | `reuse`, or `restore` | `leave`) and writes nothing; when the
snapshot comes from an earlier step that only previewed, there is no id yet and it says so. Both ops need the workflow
author to be at least an AUTHOR, like any entry step. A typical use: capture before an AI rewrite, and restore in an
`on_failure` step.

**API**, for a person: `GET`/`POST /entries/{id}/snapshots` (list; keep one, `{"label": …}`),
`GET …/snapshots/{snapshot_id}/diff?parts=…` (what a restore would change), `POST …/snapshots/{snapshot_id}/restore`
(`{"parts": […]}`) and `DELETE …/snapshots/{snapshot_id}`. AUTHOR and above, on entries the caller may change (an AUTHOR:
their own until approved or published). There is no snapshot list on the entry page yet; use the API or a workflow.

### Run inputs

A manual workflow can ask for what it needs when it runs: **Ask when it runs** under the trigger (`trigger.inputs`).
Each input has a `name` (steps read it as `${input.<name>}`), a `label`, a `type` and whether it's `required`:

| type | The Run form shows | Notes |
|---|---|---|
| `text` | a text box | up to 2,000 characters |
| `number` | a number box | `"3"` arrives as 3 |
| `choice` | a list of `options` | anything else is refused — the list is the only choices |
| `entry` | the entry's slug or id | the run works on that entry: `${entry.*}`, entry steps and a step's `see: ["item"]`, as if the entry had triggered it (one per workflow) |

**Run** opens a small form with them; the API takes them in the body (`POST /api/automations/{id}/run` with
`{"inputs": {"piece": "brass-lantern", "remix": "a haiku"}}`), and the agent's `run_workflow` tool takes `inputs`
(`list_workflows` shows each workflow's). A missing required input, an unknown name or a value that doesn't fit is
refused (400) with what to fix; a default fills an empty one. A dry run fills a missing one with a stand-in
(`‹name›`). The Workflow Library's **Surprise remix button** asks for an entry and one of the remixes you set up.

The schedule trigger can also be set **At set times (cron)** in the editor — an expression (`0 9 * * 1`, Mondays at
9:00) and a time zone; before, the editor only offered "every N minutes/hours/days" and re-saved a cron schedule as daily.

### Using one step's result in another

Give a step an **id** (the box next to its kind) and later steps read its result as `${steps.<id>.output.<key>}`.
Under each step the editor shows the keys it gives, ready to copy — `${steps.week.output.text}` for a Gather items step
with id `week`, `${steps.story.output.headline}` for an AI step whose answer has a `headline`. In **Only run this step
when…** write the same path without `${ }`: `steps.week.output.count`. Steps are numbered in the order they run.

In a dry run an AI step isn't asked, so its answer is a stand-in (`‹AI answer: title›`), and a value read from a step
that only previewed (an image not yet made) shows where it comes from — the steps after them preview as they will run.

**Set metadata** and **Set fields** save nothing when the values are already there: no "last updated" change and no
`entry_updated`, so a weekly check that finds the same answer leaves the entry alone.

### Gather items (many → one)

A workflow runs once per item — the trigger's, or each row of a query run. A **Gather items** step (`collect`) is the
other direction: it runs a query and hands the whole set to the steps after it, under any trigger. That makes a weekly
digest from the week's articles, a contact sheet from a series, a report over a project's notes.

**Linked items.** A query can follow links from the run's entry: `entries` (the entry a field names), `data` (the
entries whose field names this one), `asset` / `resource` (the entries using one), an asset or resource query's `entry`
(what this entry holds, in its order), and `collection` with sort `position` (a series in its own order). A key whose
template resolved to nothing matches nothing, never everything.

- `entity` and `query` are a target's (see [Run on a query](#run-on-a-query-of-entries)); values may be templates and
  dates may be relative (`"published_after": "-7d"`). An asset query leaves versions out unless it asks, as a target
  does. `limit` caps the rows (default 25, at most 250); `total` still counts every match.
- **Output:** `rows` — each the facts a run binds as `${entry.*}` / `${asset.*}` / `${resource.*}` (an entry's id,
  type, status, title, slug, summary, url, image and published_at; an asset's id, name, slug, url, size, alt text,
  tags and origin; a resource's id, name, type, url, description and tags), plus any extra `fields` paths
  (`data.body`, `metadata.price`) — `count`, `total`, and `text`: one line per row (title or name, summary or size,
  link) with each extra field under it, ready for a custom AI step's prompt (`${steps.<id>.output.text}`).
- `only_invalid: true` (entries) keeps only the entries that break their type's current rules, each with its `problem`
  ("Field 'price': Required field is missing or null") — after an entry type's fields change, the ones to fix.
- A **render** step's `images` can take `${steps.<id>.output.rows}` whole: the `grid` (contact sheet) and
  `moodboard` templates draw up to 48 pictures; an entry row stands for its main picture, labelled with its title.
- It only reads, so a dry run runs it too. Put `when` on the steps after it (`steps.<id>.output.count` **is more
  than** 0) to skip an empty week.

```json
{"kind": "collect", "id": "week", "entity": "entry",
 "query": {"entry_type": "article", "status": "published", "published_after": "-7d"}, "fields": ["data.body"]},
{"kind": "operation", "id": "issue", "op": "custom",
 "prompt": "Write this week's newsletter from these articles:\n${steps.week.output.text}",
 "output_schema": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["title", "body"]},
 "when": {"field": "steps.week.output.count", "op": "gt", "value": 0}}
```

### Check a web address

A **Check a web address** step (`fetch`) reads the web for a workflow, through the same guarded client integrations use:
public addresses only (a private or local one is refused, also after a redirect), 10 seconds, 2 MB.

- **`url`** — one address (templates allowed: `${resource.url}`). Output: `status`, `ok` (2xx/3xx), `content_type`,
  `title` (a page's), `text` (the first 20,000 characters) and `json` (an API's answer). `find` takes words to look for
  on the page, ignoring case — `found` lists the ones there (`"find": "sold out"`, then **Only run this step when**
  `steps.<id>.output.found.0` exists). `method: HEAD` asks only whether it answers.
- **`links`** — a text (`${entry.data.body}`): its links (markdown, HTML or bare; relative ones against `base`, default
  the site URL), up to 50, checked a few at a time. Output: `checked`, `broken` (`[{url, status, error}]`),
  `broken_count` and `text` (one line per broken link). Broken means no answer, 404, 410 or a 5xx; 401, 403 and 429 are
  servers refusing robots, so they don't count.
- No answer is `status: 0` with an `error` — output, never a failed step, so a `when` decides what happens. A dry run
  doesn't fetch.

```json
{"kind": "fetch", "id": "links", "links": "${entry.data.body}"},
{"kind": "integration", "integration": "alerts", "capability": "notify",
 "args": {"title": "Broken links in ${entry.title}", "body": "${steps.links.output.text}"},
 "when": {"field": "steps.links.output.broken_count", "op": "gt", "value": 0}}
```

### Check against a schema

A **Check against a schema** step (`schema_check`) holds a JSON document up against a [JSON Schema](https://json-schema.org)
and reports what doesn't fit — an agent's capability document, an API's answer, a story an AI wrote.

- **`document`** — what to check: usually a Check a web address step's parsed answer (`${steps.page.output.json}`), or
  any template (an entry's field, a run input). Text holding a JSON object or array is read as JSON; any other text is
  checked as the text itself. Documents over 100 KB are reported, not checked.
- **`schema`** — the schema, written inline (Draft 2020-12 unless it says otherwise; `format` isn't asserted, so use a
  `pattern`; a `$ref` can point only inside the schema, nothing is fetched) — or **`schema_resource`**: a resource (id or
  slug) whose metadata holds the schema under `schema` (an object or its JSON text), so several workflows share one. A
  malformed inline schema is refused when you write the workflow, in the editor and in the validator; a schema that
  arrives by template or resource and can't be used fails the step.
- Output: `valid`, `errors` (`[{path, message}]`, in path order; `$.agents[0].name` names the place), `error_count`,
  `truncated` and `text` (one line per problem, for a note or an AI prompt). `max_errors` (default 20, at most 50) bounds
  how many are listed; a long message is cut at 300 characters.
- A document that doesn't fit — or that never arrived — is output, never a failed step, so a `when` on `valid` decides
  what happens. Set **Stop the run when the document doesn't fit** (`fail_on_invalid`) to fail the run instead.
- A dry run checks a document it has; when an earlier step didn't really run (a fetch, an AI answer) there is nothing to
  judge and `valid` is empty.

```json
{"kind": "fetch", "id": "page", "url": "${entry.data.capabilities_url}"},
{"kind": "schema_check", "id": "check", "document": "${steps.page.output.json}",
 "schema": {"type": "object", "required": ["name", "url"], "properties": {"name": {"type": "string"}}}},
{"kind": "entry", "op": "request_review", "reason": "Doesn't fit the schema:\n${steps.check.output.text}",
 "when": {"field": "steps.check.output.valid", "op": "eq", "value": false}}
```

It checks the shape of a document, not what the document says: it can't run an agent or follow links between passages.
Two Library recipes use it: **Agent directory intake** (a submitted capability document is fetched and checked) and
**Choose your own adventure** (an AI writes a branching story as nested passages; the schema holds every branch to a
choice or an ending before it is drafted).

### Email a member {#email-a-member}

An **Email a member** step (`email`) writes to one person in the workspace: a welcome, a heads-up that something of theirs
was published, a note to the owner an entry names. It needs an SMTP profile (Settings → Email), the platform's or the
workspace's; with none the step fails and says so.

- **`to`** — the person, by user id or by the email address on their account: `${member.id}` or `${member.email}` on a
  member event, an entry field that holds an address, a Gather items row. They must be a **member of this workspace**: an
  outside address, someone who is only in another workspace, or a typed-in word fails the step and nothing is sent (the
  message is the same for "no such person" and "elsewhere", so a workflow can't be used to learn who has an account). The
  email goes to the address on their account. A fixed outside recipient is still an email subscription's `specific`
  recipient (Settings → Email).
- **`subject`** and **`body`** — templates; the body is markdown (headings, bold, italic, links, bare addresses) and any
  HTML in it is shown as text. It is set in the workspace's email layout (its own template file, else Marvin's), which
  names the workspace; **`heading`** (default the subject) titles the layout, and **`button_text`** + **`button_link`** (an
  `http(s)` address; left out when the link resolves to nothing) add its button. `${site.url}` is the public site and
  `${site.app_url}` where the admin app lives (the configured `FRONTEND_URL`).
- **Links for a role** — give each kind of member its own step with *Only run this step when…* on `member.role` (the New
  member welcome recipe sends writers a button to the workspace and readers one to the site).
- **Sent once.** The step records each send (by event, step and person) before it sends: the same event handled twice, a
  retry of the run or a re-run sends nothing the second time (the output says `sent: false, skipped: true`). **`once_per`**
  (a template such as `welcome:${member.id}`) widens that — this step writes to that person once, whatever the event. A
  send the mail server refuses fails the step and gives the record back, so a retry sends it. A manual run has no event, so
  without `once_per` it sends every time.
- Needs an admin author, like a webhook or integration step; a demoted author's step fails closed. Put an
  [approval](#wait-for-approval) step before it to have a person agree to each send.
- A **dry run** resolves the person, renders the email (`body_html`) and says whether it would go (`would_send`: false when it
  was already sent, or the workspace can't send mail) — it sends nothing and records nothing. Output: `sent`, `to`, `name`,
  `role`, `subject`.

```json
{"kind": "email", "id": "welcome", "to": "${member.id}", "subject": "Welcome to the Studio",
 "body": "Hi ${member.name},\n\nYou joined as **${member.role}**.",
 "button_text": "Open the workspace", "button_link": "${site.app_url}",
 "once_per": "welcome:${member.id}", "when": {"field": "member.role", "op": "neq", "value": "VIEWER"}}
```

The **New member welcome** Library recipe is this step on `member_added`.

### Record a metric

A **Record a metric** step (`metric`) notes a number down against a **metric**, a **variant** and a **window**, so a workflow can keep a plain log of results — clicks on two versions of a post, followers each week — and a person can read it later. It records **observations, not conclusions**: nothing here compares variants, tests significance or says what caused a number. The list says what was recorded, and the reading is yours.

- **`metric`** — a name: lowercase letters, digits, `-` and `_` (up to 64 characters), e.g. `clicks`.
- **`value`** — a number, usually a template (`${input.clicks}`, an earlier step's output). `1,204` is read as 1204. Something that isn't a number fails the step, naming it. With `op: "add"` it is optional and means 1 (see below).
- **`variant`** and **`subject`** — optional labels (up to 100 characters; templates allowed): `a` / `b`, and what the numbers are about (an entry's slug, a campaign). Both are part of the key.
- **`window`** — which stretch of time the number belongs to. **`day`** (the default), **`week`** (Monday to Sunday, ISO weeks: `2026-W42`) or **`month`** mean the one the run falls in, worked out in the **workspace's time zone** (Settings → Site), so a run at 11:30 pm New York time on the 31st is still that month's, whatever UTC says; **`at`** points at another date to take it from (`${entry.published_at}`). Or name it outright: `2026-10-18`, `2026-W42` or `2026-10` (a template may give it).
- **One observation per metric, variant, subject and window.** **`op: "record"`** (the default) **replaces the value** — a run repeated for the same window, a retry, a scheduled check that reads the same number twice never double-counts, and an unchanged number saves nothing. Use it for a total you already have ("clicks so far", "followers today"). To count things as they happen, use **`op: "add"`** (below).
- Output: `recorded`, `created`, `changed`, `metric`, `variant`, `subject`, `window`, `value` and `previous_value` (empty when new). A **dry run** resolves everything and says what it would do (`would`: `create`, `change` or `leave`) and writes nothing; with no number yet (an AI answer that wasn't asked for) it previews without one.

With **`op: "add"`** the step **counts**: it raises the window's number by `value` — 1 when you leave `value` out, a negative number to count down. A workflow that records 1 for each signup shows how many signups there were that week, where `record` would show 1. Same `metric`, `variant`, `subject`, `window` and `at` as a record. **Each event is counted once**: the step claims a key made of the run's event, the workflow and the step (in `metric_contributions`, in the same transaction as the new number), so the same event handled twice — a re-delivery, a retry, a run of the same trigger again — adds nothing the second time, while a different event adds again; inside a repeat each item counts once. A write that fails leaves no claim behind, so a retry can still count. Each manual run is its own event. Clearing a window on the Metrics page starts its count over. Output: `value` (the window's new total), `previous_value` (0 for a new window), `added`, `window`, `changed`, plus `created`, `metric`, `variant`, `subject` and `counted` (`false`, with `skipped`, when the event was already added). A **dry run** says `would: "add"` with the previous and new value and writes and claims nothing (`would: "leave"` when this event is already counted).

With **`op: "read"`** the step lists observations back: `metric`, optionally one `variant` / `subject` and a range `window_from` to `window_to` (any window form; a window counts when it starts inside the range), up to `limit` (default 50, at most 250). Output: `rows` (`[{metric, variant, subject, window, value}]`, newest window first), `count`, `total` and `text` — a plain list headed "Observations, not conclusions:" for a note or a prompt. A filter that resolves to nothing fails the step rather than widening the report. Reading changes nothing, so a dry run runs it.

```json
{"kind": "metric", "id": "a", "metric": "clicks", "value": "${input.a_clicks}", "variant": "a", "subject": "${entry.slug}", "window": "week"},
{"kind": "metric", "id": "report", "op": "read", "metric": "clicks", "subject": "${entry.slug}"}
```

Counting signups, one per member added:

```json
{"kind": "metric", "op": "add", "metric": "signups", "window": "week"}
```

**Where they are listed.** **Settings → Automation → Metrics** (`/automation/metrics`; editors and above) shows each metric as a table of windows by variant — plain numbers — and every observation below it; an owner or admin can remove one (a workflow that records that window again writes it afresh). Through the API: `GET /api/groups/metrics` (the metrics, with how many observations and the first and last window), `GET /api/groups/metrics/observations?metric=&variant=&subject=&window_from=&window_to=&limit=&offset=` (editors and above; `variant=` empty means observations with no variant; `422` for a window that isn't a day, week or month) and `DELETE /api/groups/metrics/observations/{id}` (admins). A workspace keeps at most 50,000 observations. They are a deliberate record: no scheduled task trims them (remove the ones you don't want). The Library's **Social experiment log** recipe uses it.

### Process an image

A **Process an image** step (`media`) works on one picture (JPEG, PNG or WebP; anything else fails the step with "not
an image Marvin can process"). It needs no AI and no integration, and costs nothing — except a subject crop, which asks
the workspace's AI model where the subject is.

**Which picture** (`source`): by default the asset the run is about (`${asset.id}`: an `asset_*` event's, or each row of
an asset query run). It can also be an asset's id or slug, the URL it is served at (`${entry.image}` — the entry's
main picture — or `${asset.url}`), `${steps.<id>.output.asset.id}` to work on what an earlier step made, or
`role:<role>` — the run's entry's picture in that role (`role:hero`). A URL that isn't one of the workspace's own
assets is refused; a media step never fetches the web.

| `op` | Fields | Result |
|---|---|---|
| `resize` | `width` and/or `height`; `fit` `inside` (default: the whole picture within the box) or `cover` (fills `width` × `height` exactly, trimming from the centre) | A new asset. Never scales up: a smaller picture keeps its size. |
| `crop` | `aspect` (`1:1`, `4:5`, `16:9`…), `focus` `center` (default) or `subject` | A new asset: the largest window of that shape. `subject` asks a vision model where the main subject is and centres the window on it; without one (AI off for workflows, no model that sees images, the budget reached) it crops from the centre, and the output's `focus_used` and `focus_note` say so. The vision call is logged and costed in AI usage like any workflow AI step, and made once per picture per run: a run's square, portrait and landscape crops of one picture share it. |
| `convert` | `format` `jpeg`, `png` or `webp` | A new asset in that format (JPEG puts transparency on white). |
| `grade` | `preset`: `rustic-warm`, `warm`, `cool`, `muted`, or one of the workspace's own media presets | A new asset with that colour grade. |
| `inspect` | — | `width`, `height`, `orientation` (`landscape`, `portrait`, `square`), `aspect` (width ÷ height), `sharpness`, `mime_type`, `file_size`. Nothing is written. |
| `palette` | `colors` (1–16, default 5) | `colors`: the main colours as `#rrggbb`, most common first. Nothing is written. |
| `render` | `template` (a built-in one) or `html` (your own), `fields`, `images`, `width` / `height` | A new image drawn from an HTML/CSS template — see [Render a template](#render-a-template). |

`format` and `quality` (1–100, default 90) re-encode the result of any op that makes a picture.

- **Originals are never changed.** The new asset is in the Assets library like any other, with its lineage in its
  metadata: `derived_from` (the source asset), `derivation` (the op and its settings), the workflow, the step and the
  event's correlation id. Its page says **Made from** the source.
- **Made once.** The new asset is named after its source, the op and its settings (`harbour--resize-1a2b3c4d`), so a
  re-run, a retry or the same event twice reuses it (`reused: true`) instead of making a copy. One you moved to the
  Trash isn't brought back: the step fails until it is restored or deleted.
- **Output:** `asset` (`id`, `slug`, `name`, `url`, `width`, `height`, `mime_type`), `source_id`, `reused`.
- **Tag it** (`tags`, templates allowed) tags the new asset — the same picture made again keeps its tags.
- **Attach as** (`attach_as`) links the new asset to the run's entry in that role (`asset_attached_to_entry`, which now
  carries the `role`). It needs a run about an entry — an entry event, `asset_attached_to_entry`, or an entry query —
  or **On entry** (`attach_to`): an entry id or slug, such as one this run just created
  (`${steps.draft.output.entry_id}`), so a scheduled run can attach a card to the post it drafted.
- **No loops:** a new picture made here sends no `asset_uploaded`, so an "image added → resize" workflow doesn't
  trigger itself. A condition `asset.derived_from` **exists** `false` keeps a workflow to originals.
- **Sharpness** is the variance of a Laplacian on a downscaled grey copy: blurry pictures score low (often under
  100), crisp ones in the hundreds or more. Compare it with **is less than** in **Only run this step when…**.
- A dry run reports what each step would make (`would_create` or `would_reuse`) and writes nothing; `inspect` and
  `palette` run, since they only read.

```json
{"kind": "media", "id": "q", "op": "inspect"},
{"kind": "entry", "op": "request_review", "reason": "The picture looks blurry",
 "when": {"field": "steps.q.output.sharpness", "op": "lt", "value": 60}}
```

### Documents and privacy

Four more **Process an image** ops work on PDFs and on what a picture shows. Each new picture is a version of its
source, made once — the same rules as above.

| op | Takes | Gives |
|---|---|---|
| `extract_text` | a PDF or a picture; `ocr` (`auto`, `never`) | `text` (pages marked `[page N]`), `pages` (`page`, `text`, `method`: `pdf` or `vision`), `page_count`, `read_with_ai`, and `note` when pages were skipped. A PDF's own text is read free; a scanned page (one with almost no text) or a picture is read by the workspace's vision model — one AI call each, up to 20 pages, logged in **AI Executions** as `read-text`. `ocr: never` keeps it to the PDF's text. |
| `pages` | a PDF; `page` (default 1), `count` (1–10), `width` (default 1200), `format` (default WebP) | `asset` (the first), `assets` (each with its `page`), `page_count`. Each page is a picture saved as a version of the PDF; `attach_as` attaches every one in that role. An entry links an asset once, so for a cover in another role, make it at another size. |
| `find_sensitive` | a picture; `find` (`face`, `plate`, `text`; default all) | `regions` (`kind`, `box` as fractions of the picture), `count`. One vision call (`find-sensitive`), once per picture per run. Nothing is written. |
| `redact` | a picture; `boxes` (`${steps.<id>.output.regions}`, or `[[x, y, w, h]]`) — or, without them, it asks as `find_sensitive` does; `find` | a copy with each region pixelated in large blocks and softened, so nothing readable survives: `asset`, `count`, `regions`. With nothing to blur it makes nothing (`count: 0`). |

| `zip` | `files` (a gather step's rows — an entry brings the files attached to it — or assets), `name` | a ZIP asset: each entry a folder with its files and `entry.json` (its facts), loose assets under `files/`, and `manifest.json` listing everything. Files in the Trash are left out; past the upload size cap the rest are skipped and listed. The same files and facts make the same ZIP once. |

| `watermark` | a picture; `text` (templates allowed, e.g. `© ${site.url}`) and/or `logo` (an asset — a transparent PNG works best); `position` (`bottom-right` — the default — `bottom-left`, `top-right`, `top-left`, `center`, or `tiled`: repeated diagonally across the picture, so it can't be cropped away); `opacity` (default 60); `size` (the mark's width as a percent of the picture's, default 25) | a watermarked copy as a version of the picture: `asset`. Text is white with a soft shadow, readable on light and dark pictures. Free and local; the same picture and settings make it once. |

A **render** can be printed instead of photographed: `format: "pdf"` turns the page into a PDF whose pages are width ×
height (A4 is 794 × 1123), the content flowing onto as many pages as it needs. The printable **guide** template (title,
intro, a body whose blank lines start paragraphs, `## ` headings, `- ` lists and `1. ` steps, and pictures at the end) is
a PDF by default.

PDFs are read and rendered in a separate, time-limited process (`MEDIA_PDF_TIMEOUT_SECONDS`, default 60, and a memory
cap), as renders run Chromium: a damaged or hostile PDF fails its step with the reason — it can't crash or hang the
server. Ask's **read a file** goes through the same reader.

Without a vision model, reading a picture or finding what to blur fails the step with the reason; a PDF's own text and
its pages need none. The Workflow Library's **OCR notebook**, **Document preview factory**, **Privacy crop desk**, **Archive
packager**, **Workshop field guide**, **Watermark new pictures** and **Watermark a set of pictures** use them.

### Render a template

The `render` op draws a new image from an HTML/CSS template filled with text and pictures — a quote card, a poster,
a trading card — and saves it as an asset like any other made image (lineage, made once, **Attach as**, **Tag it**).

- **Built-in templates** (`template`), each with its own size, text fields and pictures (* needed):

  | Template | Size | Text | Pictures |
  |---|---|---|---|
  | `card` | 1080×1350 | title*, text, footer, accent | image |
  | `quote` | 1080×1080 | quote*, attribution, source, accent | background |
  | `poster` (retro) | 1200×1800 | title*, subtitle, tagline, year, footer | image* |
  | `trading-card` | 750×1050 | title*, subtitle, stats (one `Label: value` per line), text, number, accent | image* |
  | `meme` | 1080×1080 | top, bottom | image* |
  | `side-by-side` | 1600×900 | title, left_label, right_label | left*, right* |
  | `comic-4` | 1200×1400 | title, caption1*–caption4*, footer | panel1–panel4 |
  | `newspaper` | 1200×1600 | masthead*, date, headline*, deck, body* (paragraphs split by a blank line), banner | image |
  | `grid` (contact sheet) | 1600×1600 | title, footer | tiles* (a list) |
  | `moodboard` | 1600×1200 | title, notes, colors (hex codes, comma-separated, or a palette step's list) | tiles* (a list) |

- **Your own** (`html` instead of `template`): HTML and CSS using `{{ fields.<name> }}` for text and
  `{{ images.<name> }}` as an image URL (e.g. `background-image: url('{{ images.photo }}')`), at `width` × `height`
  (1080×1080 by default). It is a sandboxed Jinja template: text is escaped, and a name you use but don't fill fails
  the step. Use `vw` / `vh` units to scale with the size.
- **Text** (`fields`) takes templates (`${entry.title}`, `${steps.<id>.output.<key>}`); a built-in template's
  needed text that resolves to empty fails the step, and a name it doesn't have is refused.
- **Pictures** (`images`) are named like **Which picture**: an asset id or slug, `${steps.<id>.output.asset.id}`, or
  `role:<role>`. An optional picture by role that the entry doesn't have is left out (the template does without
  it); a needed one fails the step. The first picture is the one the new asset is **Made from**; without pictures it
  counts as generated.
- **Locked down:** the page runs no script and loads nothing from the network — not even a font or an image from a
  URL; pictures are inlined from your assets and fonts are the server's (Lato, Open Sans, DejaVu, Liberation, Noto
  Color Emoji). Up to 4000 px a side.
- Rendering takes about half a second and costs nothing. It needs the server's headless Chromium
  (`chromium-headless-shell`, in the Marvin image); without it a render step fails saying so. A dry run fills the
  template in (so a missing field shows) without drawing it.

```json
{"kind": "media", "id": "card", "op": "render", "template": "quote",
 "fields": {"quote": "${steps.pick.output.quote}", "attribution": "Grace Martin Franklin"},
 "images": {"background": "role:hero"}, "attach_as": "quote-card"}
```

### Generated images are kept

A **Run integration** step whose action makes images (an `image.*` capability — OpenAI Images' **Generate image**)
keeps each picture as an asset before the result reaches the run: the output's `images` become
`[{"asset": {"id", "slug", "url", …}}]` (an edit or upscale action's single image becomes `asset`). The asset is named
after the step's `name` argument, else "<workflow> — <entry title>", and records how it was made: `generated_by`
(`<provider>.<action>`), the `prompt`, the `model`, the entry it was made for, and the run. Its page says so in one
line — **Generated by … (model) · for the entry … · by the workflow …** — with the entry and the workflow linked, and
the same ids in its File Metadata link there too. A picture returned as a
link is fetched through Marvin's guarded client (public hosts only, 20 MB at most); the upload size and type limits
apply. **Attach as** (`attach_as`) on the step links the pictures to the run's entry in that role, and `tags` tags them. Because the run now
carries references instead of image data, it can wait for approval *after* generating ("use this cover?") and be
retried. The same event handled twice keeps one set of pictures.

**Editing a picture.** An action that changes a picture it's given (`image.edit` — OpenAI Images' **Edit an image**,
v0.3.0) takes the step's **Picture to edit** (`source`: an asset id or slug, `${asset.id}`, `${entry.image}`,
`role:hero` or an earlier step's `${steps.<id>.output.asset.id}`, as a media step's). Marvin passes the picture as
`image_b64` / `image_mime` for that call only — it's never in the step's output or the image's lineage — and keeps
the result as a *version* of the picture: made from it, `edited:<provider>.<action>`, the prompt recorded. OpenAI Images'
edit takes `prompt`, `background` (`auto`, `transparent`, `opaque`) and `fidelity` (`high` keeps the picture's details).
The Workflow Library's **Background remover**, **Product scene studio** and **Seasonal variation** use it; each asks an
editor first (a paid edit). `source` on an action that doesn't work on pictures is refused.

### Wait

A **Wait** step (`wait`) keeps the run and goes on later, from the next step:

- `for` — a while: `30m`, `12h`, `3d`, `2w`.
- `until` — a moment: a date (`2026-11-08`) or a date and time, usually a template (`${entry.data.event_date}`);
  `offset` moves it (`-7d` a week before, `+1d` a day after) and, for a date, `at` is the time of day (default
  `09:00`). It's read in the workspace's time zone (Settings → Site), and the offset is counted on the calendar: a week
  before 09:00 is 09:00, whatever the clocks did in between.

While it waits the run shows **waiting** under **Runs** (the step says until when). A sweep every minute picks it up
when its time comes and runs the steps after it in a new run, with the entry as it is by then; they read
`${steps.<id>.output.waited_until}` and `resumed_at`. A run's inputs and the earlier steps' outputs are kept. A moment
already past doesn't wait: the run goes on at once and the step's output says `late: true` — put **Only run this step
when…** `steps.<id>.output.late` is not `true` on what shouldn't happen late. If the entry goes to the Trash, or the
workflow is switched off or its steps change while it waits, the run stops there (**cancelled**, with the reason);
switching the workflow off is how to stop a waiting run. A wait is at most a year; a dry run shows `would_wait_until`.
The Workflow Library's **Event countdown** drafts reminders a week and a day before an event.

**Editing while runs wait.** A waiting run goes on with the workflow *as it is then*: a changed prompt, voice or field
applies, and a step added or removed before the Wait step doesn't move it (the step is found by its id). Only
switching the workflow off, removing the Wait step itself, or the entry going to the Trash cancels a waiting run — and
then `automation_failed` says why, so an admin alert or an `on_error` workflow can react.

**Cancelling a wait.** Under **Runs**, a run parked at a Wait step has a **Cancel** button (admins): it stops there —
the steps after the wait never run, what ran before it stays, and the run's status becomes `cancelled`
(`POST …/executions/{id}/cancel`; 409 when the run isn't waiting at a Wait step — one waiting for an approval is
decided on Automation → Approvals).

### Repeat for each

A **Repeat for each** step (`repeat`) runs a few steps once for each item of a list — usually what a
[Gather items](#gather-items-many-one) step found:

```json
{"kind": "repeat", "id": "credit", "for_each": "${steps.people.output.rows}", "as": "person",
 "steps": [
   {"kind": "operation", "id": "note", "op": "custom", "prompt": "Write a short thank-you to ${person.title}…", "output_schema": {…}},
   {"kind": "entry", "op": "create", "entry_type": "article", "title": "Thanks, ${person.title}", "data": {"body": "${steps.note.output.body}"}}
 ]}
```

- **The item** is `${<as>.*}` (`as`, default `item`; it can't take a name a run already reads, such as `entry` or
  `steps`), and its place is `${each.index}` (from 0), `${each.number}` (from 1) and `${each.count}`.
- **`for_each`** is a list (a gathered `rows`, a list in an earlier step's output), one object, or comma-separated
  text (`"a, b, c"`). Nothing there: the step runs no items and succeeds.
- **Inner steps** (1–5) read each other's output for the same item as `${steps.<id>.output}`, and each may have its own
  **Only run this step when…** (`when`, read per item). Nothing of one item carries into the next, and after the
  repeat the item is gone again. A wait, an approval or another repeat can't go inside — put an approval before it.
- **A create inside** makes one entry per item, keyed on the item's id (or its place), so the same event handled twice
  makes none again, in whatever order the list comes.
- **At most `limit` items** (default and maximum 25); past it, the output says how many were `left_out`.
- **A failing item** (`on_item_error`): `stop` (the default) fails the step with which item and step failed, and items
  done before it stay done; `continue` notes it and goes on — the step fails only if every item did.
- **Output:** `count`, `done`, `failed`, `results` (per item, each inner step's output by id), `errors`
  (`{index, step, error}`).
- **In the guided builder**, choose **Repeat for each**: **For each** (the list), **Call each one** (the item's name),
  **At most** and **If one fails**, then the steps to repeat (indented, lettered a, b, c — **+ Add a step to repeat**,
  up to 5). An Entry action inside usually targets the item: **Target entry → By id** with `${person.id}`.

### Parallel branches

A **Parallel branches** step (`parallel`) runs two to five named branches of steps independently and joins them: the
way to run several checks and decide once, or to try one source and fall back to another.

```json
{"kind": "parallel", "id": "checks", "join": "all", "on_branch_failure": "continue",
 "branches": [
   {"name": "text", "steps": [{"kind": "schema_check", "document": "${entry.data}", "schema": {…}, "fail_on_invalid": true}]},
   {"name": "images", "steps": [
     {"kind": "collect", "id": "pictures", "entity": "asset", "query": {"entry": "${entry.id}"}},
     {"kind": "schema_check", "document": "${steps.pictures.output}", "schema": {…}, "fail_on_invalid": true}]}
 ]}
```

- **Branches run one after another, in the order written, inside the run** — not at the same moment. What "parallel"
  means here is independence and a fixed merge: a branch reads what ran before the step (the entry, earlier steps) but
  never a sibling's output, nothing a branch ran leaks into the next one, and the result is merged by name in written
  order, so it can't depend on which branch happened to finish first.
- **Each branch** has a `name` (lower case, letters, digits and `_`; each different) and 1–5 steps, with the same
  step kinds and `when` as a Repeat's. Steps inside a branch read each other as `${steps.<id>.output}`. **A wait, an
  approval, a repeat or another parallel step can't go inside** (a run can't be parked, or nested, in the middle of
  branches): put the wait or approval before the step or after it. A save with one says so.
- **The join.** `all` (the default): every branch must succeed. `any`: the first branch that succeeds satisfies it and the
  branches after it are skipped (not run) — a fallback chain, cheapest first.
- **When a branch fails** (`on_branch_failure`): `fail` (the default) fails the step when the join isn't met — under `all`
  the first failing branch stops the rest, which are skipped; under `any` the step fails only if every branch did. What
  a branch had already done stays done. `continue` never fails the step for a branch: every branch under `all` still
  runs, and the output says how it went for a later step's `when` to act on.
- **Output:** `branches.<name>` (`status` `ok`, `failed` or `skipped`; `error` and `step` for a failure; `steps`, each
  step's output by id; `output`, the last step's), `order`, `count`, `ok`, `failed`, `skipped`, `satisfied` (the join was
  met), `winner` (under `any`), `errors` and `text` (one line per failed branch, for a note or a review reason). Read a
  value as `${steps.checks.output.branches.images.output.count}`.
- **A check that should block must fail its step**: a Check against a schema step with `fail_on_invalid`, say. A gate is
  `continue`, then one step with **Only run this step when** `steps.checks.output.failed` equals 0 (go ahead) and another
  with it greater than 0 (send `${steps.checks.output.text}` to review) — the [Publication release gate](#workflow-library)
  recipe does this.
- **Limits.** At most five branches of five steps; all the branches' steps together count against the workspace's
  **steps per workflow** (Settings → General), so a save warns, and a run fails with the count, when they're over it.
  A create inside a branch is keyed on the branch, so the same event handled twice makes nothing again.
- **A dry run** previews every branch and writes nothing. Under `any`, the branches after the first success show as
  `skipped` with what they would have done.
- **In the guided builder**, choose **Parallel branches**: **Join when** (all / any), **If a branch fails** (stop / carry
  on), then each branch (**+ Add a branch**) with its name and its steps (**+ Add a step to this branch**).

### Wait for approval

A **Wait for approval** step (`approval`) stops the run until a person decides. The members who may decide — editors and
above, or admins and above (`approvers`) — get a push notification ("Waiting for your approval") and find it under
**Automation → Approvals**, with the workflow, the entry and the question (`message`). The app's icon badge counts it.
They **Approve** or **Deny**, optionally with a note, and the run goes on from the next step. The step's output is
`${steps.<id>.output.decision}` (`approved`, `denied`, `expired` or `stale`), `decided_by`, `decided_by_name` and
`note`: give the step an `id` and use **Only run this step when…** on the steps after it.

- **One tap:** on Chrome and Android the notification has **Approve** and **Deny** buttons when every step after the
  approval can be undone in Marvin (trash, restore, archive, add to or remove from a collection, send to review, create
  a draft). Anything else — publishing, setting fields or metadata, an integration, a webhook, an AI step — gets no
  buttons: the tap opens Approvals so the person looks first. Each approver's buttons work once, for 15 minutes, as
  them and at their role now; afterwards the run is decided in Approvals.
- **Expired:** if nobody decides within `expires_in_hours`, the run goes on with `expired` (checked hourly).
- **A picture's decision stays with it:** an approval step that shows a picture (`image`) writes its outcome onto that
  asset's metadata as `approval` — `decision` (`approved`, `denied`, `expired`, `stale`), who (`decided_by`,
  `decided_by_name`), `decided_at`, the `note`, and `approval_id` — when the picture is one of the workspace's assets.
  A denied generated image stays in the library, so this is what tells it from one that was kept: the asset page
  says "Denied by … — note", the library shows a **Denied** badge and filters by **Decision**, and a workflow can
  gather `{"entity": "asset", "query": {"decision": "denied", "created_before": "-30d"}}` to trash them later.
- **Stale:** approving an entry that has changed since the question was asked gives `stale`, not `approved` — what was
  approved is not what would be acted on.
- **Actions that need approval:** an integration action that requires approval (OpenAI image generation, Instagram's
  private reply) can run in a workflow only after an approval step, and only when it was approved; the editor refuses it
  elsewhere.
- The run that waited shows ⏸ and **waiting** in its steps, then **resumed**; what happens after the decision is a new
  run linked to it, starting with the decision.
- A run on a query waits once per matching entry. An approval step can't be an on-failure step. A dry run shows the
  question and the steps after it as if approved, and waits for nobody.

```json
{"kind": "approval", "id": "ok", "message": "Feature “${entry.title}” on the home page?"},
{"kind": "entry", "op": "add_to_collection", "collection_slug": "featured",
 "when": {"field": "steps.ok.output.decision", "op": "eq", "value": "approved"}}
```

API: `GET /api/automations/approvals` (what you may decide, EDITOR+), `POST /api/automations/approvals/{id}/decide`
with `{"decision": "approve" | "deny", "note": …}` (403 below the step's role, 409 already decided or expired). Events:
`workflow_approval_requested`, `workflow_approval_decided`.

**Ask for one of several** — `choices`: 2–8 labels (templates allowed), or one template that resolves to a list
(`${steps.ideas.output.titles}`). The Approvals page shows a button per choice and **None of these**; approving with
one sets `${steps.<id>.output.choice}` (the label) and `.choice_index` (from 0), so a later step can act on the pick
(`"role": "thumbnail-option-${steps.pick.output.choice_index}"`); denying picks none. The API takes `choice` (the
label or its index) on `decide`, and refuses an approval with choices that names none (422). In the builder, **Choices**
on the Wait for approval step.

### One run per entry at a time

A workflow never runs twice on the same entry at the same moment. If a run of it is already working on that entry —
a retry, the same event delivered twice, **Run** pressed again on a query — the next one waits for it (up to two
minutes), then reads the entry again and checks the workflow's conditions again before doing anything. So a listing
that the first run just made isn't made a second time. Different entries, and different workflows, still run side by
side. (A run that crashed holds its entry for at most five minutes.)

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

**Run** starts the workflow and doesn't wait for it: the button says **Started ✓**, the activity toast follows the run and says when it is done, and **Runs** has the result. A run over many entries (re-listing a whole shop, AI steps on a query) can take minutes, longer than a request may (Cloudflare gives up after about 100 seconds).

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

### Example: switch a field on for many entries

"Turn on **Sell online** for every available artwork with a price" is one workflow run once by hand:

1. **New workflow**, name it, **Trigger** → **Manual (Run button)**.
2. Tick **Run on a query** → **Entries**; **Entry type** → your artwork type; **Fields equal** → `availability` = `available` (the field's key and the value exactly as stored). Narrow with **Fields equal** rather than **Only if**: the query is what's capped at 250, conditions only skip rows inside it.
3. If "has a price" isn't an equality, add it under **Only if**: `entry.data.price` **exists**.
4. **Then do** → **Entry action** → **Set fields**: `sell_online` = `true`. Values are typed: a checkbox takes `true`, a number `45`, not `"45"`.
5. **Preview matches** shows how many entries it will touch (and whether the 250 cap applies); **Dry run** shows the resolved plan.
6. **Save workflow**, tick **Enabled**, **Run** once and wait for it (see above); untick **Enabled** afterwards if it was a one-off.

Builder (an agent: ask "how do I…") gives these steps for your own types and fields, in these words, and can draft the workflow switched off for you to check.

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
| `POST /api/automations/{id}/run` | Manual run, with an optional body `{"inputs": {…}}` (its [run inputs](#run-inputs); `400` says which doesn't fit); responds when the run finishes (`409` when disabled) — or, with `?background=true`, at once with `{"status": "started"}` while the run goes on (what the **Run** button does). With `?dry_run=true` it returns `plan` and records nothing. For an event-triggered workflow the dry run also takes `entry_id` or `event_id` (an event log row) and returns `sample`, `trigger_matched`, `conditions` (each with `field`, `op`, `value`, `actual`, `expected`, `pass`, or a nested `group`), `conditions_pass` and `would_fire`. |
| `GET /api/automations/{id}/samples?limit=` | The dry run's candidate samples: recent logged events the trigger fires on, then uncovered entries (default 10, at most 25), each with `kind`, `id`, `label`, `occurred_at`, `synthesized`, `conditions_pass`. Empty for a workflow no event triggers. |
| `GET /api/automations/{id}/executions?limit=` · `GET …/executions/{execution_id}` | Run history (default 25, at most 100); detail includes per-step records and the definition snapshot. |

## Settings

A workflow is `enabled: false` when created. A disabled workflow does not run from events, the scheduler or **Run**, but can be dry-run. A workflow with the `mcp` trigger is exposed by the Marvin MCP server as a tool named `marvin_wf_<slug>` (non-alphanumerics in the slug become `_`; needs a user token, see [Marvin as an MCP server](marvin-as-mcp-server.md)). Separately, the agent's `run_workflow` tool runs any enabled workflow by slug, name or id, skipping its trigger and conditions as **Run** does, and the run is recorded under **Runs**. Like **Run**, it needs workspace ADMIN or OWNER (as does `list_workflows`).

**Agents can draft workflows.** Asked to create, build or set up a workflow, an agent reads the format from `workflow_authoring_guide` — its index first (what each section holds and when to read it, the step kinds in a line each, this workspace's entry types), then only the sections the request needs, several in one call — and saves it with `draft_workflow`. The workflow is created switched off, through the same save as **New workflow** (the same slug from the name, the same checks, recorded as created by you, so its steps run with your role), and the agent answers with a link that opens it in the editor (`/automation/workflows?workflow=<id>&edit=1`). Review the trigger and steps, dry-run it to see which entries it would act on, then tick **Enabled**. An agent never enables or runs a workflow it drafted. A draft also has to pass checks the editor doesn't make: every key must be one the format has (a `steps` list or a step's `type` is refused rather than ignored), and every name must exist (a triggerable event, an entry query key, an entry type, a collection, an AI operation, an allowed job, an integration action that can run unattended, an outgoing or incoming webhook, another workflow); template values (`${…}`) are left to run time. The agent gets each problem with its path, such as `actions[0].op`, and tries again. `update_workflow_draft` revises a workflow only while it is switched off. See [Agents and Ask](agents-and-ask.md#what-it-does).

## Since

Operational events as triggers (**Operations** heading: `webhook_delivery_failed`, `integration_attention_*`, `scheduled_task_failed`, `ai_budget_*`; a workflow never answers a failure its own run caused; Integration health companion and Webhook repair desk recipes): 2026-10-18.
Parallel branches (`parallel`; the Publication release gate recipe): 2026-10-18.

Custom events (`custom.<name>`: registered fields, Emit event `payload`, trigger and subscriptions, Achievement cabinet recipe): 2026-10-18.

Save or restore a version (`snapshot` step, `/entries/{id}/snapshots`, migration `c5b1eb095038`): 2026-10-18.

Classify a form submission (`${form_submission.*}`, the `classify-form-submission` step from a workflow; Form submission sorter recipe): 2026-10-18.

Check against a schema (`schema_check`; Agent directory intake and Choose your own adventure recipes): 2026-10-18.

Email a member (`email`, `site.app_url`; New member welcome recipe): 2026-10-18.
Record a metric (`metric`, migration `c4139a718fc6`, the Metrics page and `/api/groups/metrics`; Social experiment log recipe): 2026-10-18. `op: add` (counts each event once; migration `4d8eabca4995`): 2026-10-18.

`form_submission_received` as a trigger: v1.0.0-rc.51 (`8f1443d1`). `auth_scheme`: rc.50 (`a65ba7d0`). `entry.summary` and `entry.data.*`: rc.52 (`433e949e`). Response `body`, `set_metadata` and metadata targeting: rc.59 (`1380e92e`). `entity_query`: rc.60 (`65ffb648`). Raw-URL `method` and templated stored URLs: rc.61 (`b88e4035`). Builder fixes: rc.63 (`57956e71`). `set_data`, the integration step, `entry.metadata` and list indexes in paths: rc.111. `entry.image`: rc.119. Full entry context per query row and **Fields equal**: rc.129. Typed values for checkbox and number fields: rc.131. The shared entry query (`where`, `sort`, date filters): rc.138. Unknown `where` ops match nothing, and `run_workflow` runs appear under **Runs**: rc.139. Site build and deploy events from `emit_event`: rc.144. `{{SLUG}}` in integration step args: rc.145. AI limits on operation steps: rc.146. Site events as notification subscriptions: rc.151; as workflow triggers: rc.152. `automation_started` and the shared `execution_id`: rc.165. Dry run against a sample event, with the condition checklist and `GET …/samples`: rc.173. A refused publish fails the entry step with the reason: rc.175. `${site.url}`: rc.177. Each event's subject, a run's trigger (`trigger_entity_*`) and step summaries in `automation_ran` / `automation_failed`, `$event.entity_type` / `$event.entity_id`: rc.178. `if_none: skip` and `${entry.url}`: rc.179. `on_failure`, `request_review` and an integration error's `${error.code}`: rc.193. Integration error policies (`integration_errors`, `handled` / `handling` / `retry_attempt` on run events), a workflow never re-triggering itself, and option pickers in the **Run integration** step: rc.197. A step's `when` (if/else), an operation step's `write_back` field map, custom AI steps (`op: "custom"`), **Create an entry** (`create`) and **Wait for approval** (`approval`, migration `5c2e8a91d4f7`): unreleased (2026-10-11). **Process an image** (`media`), generated images kept as assets, `attach_as`, `asset.derived_from`, the `role` on `asset_attached_to_entry`, and `gt` / `gte` / `lt` / `lte`: unreleased (2026-10-12). **Render a template** (`render`): unreleased (2026-10-12). **Gather items** (`collect`), relative query dates, lists of pictures in a render, and local times across the admin: unreleased (2026-10-12). Linked items in queries (`entries`, `asset`, `resource`, `entry`, `role`, `exclude`, `checksum`, sort `position`), `only_invalid`, `asset.checksum` and **Check a web address** (`fetch`): unreleased (2026-10-12). Step ids and the result key in the editor, dry-run stand-ins for AI answers, and unchanged Set metadata / Set fields saving nothing: unreleased (2026-10-12). Run inputs (`trigger.inputs`, `${input.*}`) and cron in the editor's schedule: unreleased (2026-10-12). `extract_text`, `pages`, `find_sensitive`, `redact` (pypdfium2), `zip` and printed renders (`format: pdf`, the guide template): unreleased (2026-10-12). An integration step's `source` (image edits): unreleased (2026-10-12). `watermark`: unreleased (2026-10-12). **Wait** (`wait`, migration `b7e2c4f9a1d3`): unreleased (2026-10-13). Entry dates in `${entry.*}` and the recipe date picker: unreleased (2026-10-13). `${path|url}`, `attach_to`, comma-separated `entries`, and the One-tap share links, On this day, Audience milestone and Collaborator shout-out recipes (with the entry page's **Share** box): unreleased (2026-10-13). **Repeat for each** (`repeat`, `${each.*}`) with its guided form, an Entry action's **By id** target, and **Edit** opening as JSON when the guided builder can't show a workflow in full: unreleased (2026-10-13). Approvals with `choices` (migration `c9d4e7a2b1f8`), `longer_than` / `shorter_than`, **Cancel** on a waiting run, and the Thumbnail audition, Platform preview checker, Time capsule and Intake triage recipes: unreleased (2026-10-13).

## Related

- [Incoming webhooks](incoming-webhooks.md) · [Outgoing webhooks](outgoing-webhooks.md) · [Forms and submission protection](forms-and-submission-protection.md) · [Integrations](integrations.md)
- [Glossary](../glossary.md)

## A picture with the question, and attaching it only once approved

An **Approval** step can show a picture: `image` is a template to a picture URL — a step's generated asset
(`${steps.cover.output.images.0.asset.url}`) or the entry's main picture (`${entry.image}`) — and it appears on the
Approvals page and the dashboard card, so the approver judges the actual picture. A new entry op, **Attach a picture**
(`attach_asset`), links an asset to the entry: `asset` is the asset's id or slug (a template to a step's asset works),
`role` the role to link it in. Together they let a run make a picture, show it, and attach it only on a yes:

```json
{"kind": "approval", "id": "ok", "message": "Make a cover for “${entry.title}”? (one paid image)"},
{"kind": "integration", "id": "cover", "integration": "images", "action": "generate", "args": {"prompt": "…"},
 "when": {"field": "steps.ok.output.decision", "op": "eq", "value": "approved"}},
{"kind": "approval", "id": "keep", "message": "Use this cover?", "image": "${steps.cover.output.images.0.asset.url}",
 "when": {"field": "steps.ok.output.decision", "op": "eq", "value": "approved"}},
{"kind": "entry", "op": "attach_asset", "asset": "${steps.cover.output.images.0.asset.id}", "role": "cover-variant",
 "when": {"field": "steps.keep.output.decision", "op": "eq", "value": "approved"}}
```

Denied at the second step, the picture stays in the library, unattached. The library's **Alternate universe cover**
recipe has this shape.
