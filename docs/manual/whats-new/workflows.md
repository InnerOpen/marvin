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

Operators: `eq`, `neq`, `contains`, `in` (a comma-separated string is accepted), `starts_with`, `exists` (`value: false` inverts), `changed`, `changed_from`, `changed_to`, and the number comparisons `gt`, `gte`, `lt`, `lte` (**is more than**, **is at least**, **is less than**, **is at most**: both sides read as numbers, typed-in text too; anything that isn't a number never matches). A top-level list is AND; `{"all": […]}`, `{"any": […]}` and `{"not": …}` nest. An unknown operator never matches. The `changed*` operators read `event.changed_fields`, `event.before` and `event.after` from an `entry_updated` event.

The builder sends every value as text. `eq` and `neq` convert it to the type of the value being compared: `true`/`false` (also `yes`/`no`, `on`/`off`, `1`/`0`) against a checkbox, a number against a number field.

| Namespace | Contents |
|---|---|
| `event.*` | Every field of the event's data, plus `event_type`, `entry_id`, `entity_type`, `entity_id` (what the event is about), `webhook_slug`, `payload`, `changed_fields`, `before`, `after`, `user_id`. `entry_id` is set only when the event is about an entry. Forms: `event.submission_data.<field>`. |
| `entry.*` | `id`, `entry_type`, `status`, `title`, `slug`, `summary`, `data.<field>` (the entry type's fields), `metadata.<key>`, `image` (the featured image's public URL, or empty). Present for entry events and for every row of a query run. |
| `asset.*` | `id`, `slug`, `name`, `asset_type`, `mime_type`, `filename`, `file_size`, `description`, `tags`, `metadata.<key>`, `url` (its public URL, or empty), `trashed`, `derived_from` (the id of the asset it was made from — a [Process an image](#process-an-image) step's or an entry type's media derivative; empty for an original), `origin` (`upload`, `derived` or `generated`). Present for `asset_*` events and for every row of an asset query run. |
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
| `versions` | assets only: `false` leaves out versions of an original still in the library; `true` keeps only versions; `all` keeps both (**Versions**). A workflow's asset target runs on **originals only** unless it sets `versions`, `source` or `origin: derived` — so a bulk job never makes copies of copies |
| `source` | assets only: the versions made from this asset (id or slug) |
| `resource_type` / `resource_types` | resources only: the resource's type, e.g. `supplier` (**Resource type**) |

An asset or resource query takes only these keys: no `where`, `sort`, `status`, `fields` or `metadata`. Saving a workflow whose target, or whose entry step's `entity_query`, has an unknown key or the wrong shape is refused with the path of each problem (`POST /api/automations/validate` lists them too). The [Workflow Library](https://github.com/InnerOpen/marvin/blob/develop/docs/workflow-library/catalogue.md) has worked examples: *Trash every unattached image*, *Restore all resources in the Trash* and *Post new uploads to a chat channel*.

### Step kinds

| `kind` (builder label) | Fields | Behaviour |
|---|---|---|
| `entry` (Entry action) | `op` (`publish`, `unpublish`, `archive`, `trash`, `restore`, `add_to_collection`, `remove_from_collection`, `set_metadata`, `set_data`, `request_review`, `create`), `entity_id` (default `$event.entry_id`), `entity_slug`, `entity_query` (the query above; must match exactly one entry — with `if_none: skip`, no match ends the step quietly with output `{skipped: true, reason: "no matching entry"}` instead of failing it; more than one match still fails; in the builder, **By query (find exactly one)** with **If no entry matches, skip this step instead of failing the run**), `collection_slug`/`collection_id`, `metadata`, `data`, `reason` | Status ops emit the matching lifecycle event (`unpublish` returns the entry to `draft`; `restore` returns an archived entry to `draft` and a trashed one to the status it had, a published one as a draft). **Move to Trash** (`trash`) sends `entry_updated` and `entry_trashed`; an entry already in the Trash is skipped (`{skipped: true}`), so a target of "all entries" + `trash` can be run again safely. `trash` and `restore` also act on an asset or a resource: with no `entity_type` (**Acts on**: *The current item*) they act on each row of an asset or resource target, or on the asset/resource an `asset_*` / `resource_*` event is about; with `entity_type: "asset"` / `"resource"` they act on one named by `entity_slug` or `entity_id` (default `$event.asset_id` / `$event.resource_id`); they send only `asset_trashed` / `asset_restored` (or the resource events), and one already where the op would put it is skipped. No other op takes an `entity_type`. There is no op to delete forever or empty the Trash — see [Trash](trash.md). A publish the publish gate refuses (a missing required field, a placeholder link, a passed expiration date) fails the step with that reason. **Set metadata** (`set_metadata`) merges templated keys into the entry's metadata. **Set fields** (`set_data`) merges into the entry type's own fields, converts typed text to the field's type (true/false for a checkbox, a number for a number field) and validates against the schema, so an unknown select option fails the step. Both drop values that resolve empty and fail if nothing is left. **Send to review** (`request_review`) moves the entry to Needs review; its optional templated `reason` is added to the entry's `metadata.review_reasons` (once — a repeat isn't listed twice), and the review queue's entry cards show it beside a flagged submission's own reasons. **Create an entry** (`create`) makes a new one: `entry_type` (a slug), `title`, optional `data` (that type's fields, typed and validated as **Set fields** does) and `metadata`, `status` `draft` (default) or `inbox` — publishing is a following **Publish** step with `entity_id: ${steps.<id>.output.entry_id}`, which checks the type's publish rules. Templates work in every value. Its output is `{entry_id, slug, created}`; it sends `entry_created`, and the same event handled twice (same correlation id, workflow and step) finds the entry it made instead of making a second (`created: false`; the key is kept in the new entry's `metadata.automation_created`). |
| `webhook` (Call webhook) | `webhook_id` or raw `url`; `method` (raw URL only; default `POST`), `body`, `secret_ref`, `auth_scheme` (`Bearer` default, or `Token`) | A configured webhook's URL, method, `{{SLUG}}` headers and custom payload are used, with `${event…}` templates resolved. Timeout 15 s. A non-2xx response fails the step. Output: `status_code`, `ok`, `webhook_id`, `body` (parsed JSON or text). Deliveries appear in the webhook log. |
| `integration` (Run integration) | `integration` (the connection's slug from its card, not the provider's), `action` (the provider action key) — or `capability` instead: `notify` with `args` `title` and `body` sends through whatever message action that integration has (Slack's `send_message`, Apprise's `notify`), so one workflow works with either — `args` (templated) | Runs one action of an enabled [integration](integrations.md) with its stored credentials; the provider's result is the step output. An action that requires approval runs only after a [Wait for approval](#wait-for-approval) step, and only when it was approved. An action that makes images (an `image.*` capability, such as OpenAI Images' **Generate image**) keeps each one as an asset — see [Generated images are kept](#generated-images-are-kept). A top-level arg whose whole value is `{{SLUG}}` is replaced by that workspace secret for the call only (the stored workflow keeps the reference); a secret that does not exist fails the step. A provider may give its error a stable code (Buttondown: `blocked`, `suppressed`, `spammy`, `unknown`), which on-failure steps read as `${error.code}`. An input the provider links to one of its read actions gets a searchable picker above the arguments (see [Pick a value from the service](integrations.md#pick-a-value-from-the-service)). |
| `approval` (Wait for approval) | `message` (what is asked; templates allowed), `approvers` (`editor`, the default, or `admin`), `expires_in_hours` (1–720, default 72) | The run waits here for a person — see [Wait for approval](#wait-for-approval). |
| `collect` (Gather items) | `entity` (`entry`, `asset`, `resource`), `query` (a target's keys), `fields`, `limit` (default 25, at most 250) | Gathers a set into one output so the steps after it see them all — see [Gather items](#gather-items-many-one). |
| `fetch` (Check a web address) | `url` (+ `method` `GET`/`HEAD`, `find`) or `links` (a text, + `base`) | Reads a public web address, or checks the links in a text. A dead link is output, not a failure — see [Check a web address](#check-a-web-address). |
| `media` (Process an image) | `op` (`resize`, `crop`, `convert`, `grade`, `inspect`, `palette`), `source`, the op's own fields, `attach_as` | Makes a new image from an image, or reads one — no AI or provider needed. See [Process an image](#process-an-image). |
| `operation` (AI operation) | `op` (AI operation slug), `input`, `entity_type`, `entity_id`/`entity_slug`, `write_back` | Offered only when AI is enabled and the **Workflows** invocation source is on. **Write the result back to the entry** (`write_back: true`) follows the workspace approval mode: the result is applied or staged as a suggestion, and the output's `_write_back` says which (`applied` or `staged`). On an asset or resource the step sees the item (an image asset's picture, for an operation that looks at images) and `write_back` is a map of output keys to the item's fields, for example `{"alt_text": "alt_text"}`: an asset takes `alt_text`, `description`, `name`, `tags` or `metadata.<key>`, a resource `description`, `name`, `tags` or `metadata.<key>`. It follows the same approval mode, and needs a workflow author who is an EDITOR or above (else `_write_back` is `not_permitted`). The workspace's AI limits apply: over the daily request or monthly cost limit the step fails, and the per-request token cap bounds the call (see [Agents and Ask → Usage and limits](agents-and-ask.md#usage-and-limits)). |
| `handler` (Run task) | `task`, `config` | Allowlist: `request_site_rebuild`, `publish_scheduled_entries`, `unpublish_expired_entries`, `ai_reindex_embeddings`, `resync_smart_collections`, `media_enrich`. `request_site_rebuild` queues a coalesced rebuild (see [Operations → Site rebuilds](../operations.md#site-rebuilds)). |
| `emit_event` (Emit event) | `event`, `entity_id` (default `$event.entry_id`); for site events `message`, `error`, `site_url`, `deployment_id` (templated) | An entry event (`entry_*`) is re-emitted for the entry in context, at depth + 1. A site event (`site_deployment_started` / `_completed` / `_failed`; the old names `site_build_*` emit the same events) needs no entry: it records the build or deploy with the given message (default "Site deploy failed" and so on), failure reason and site URL, and shows as an activity toast. For a site event the builder adds message, failure-reason and site-URL inputs; `deployment_id` is set through **Edit as JSON**. Other events are refused. |

Only the first 10 steps run; the validator warns when there are more.

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
  carries the `role`). It needs a run about an entry — an entry event, `asset_attached_to_entry`, or an entry query.
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
(`<provider>.<action>`), the `prompt`, the `model`, the entry it was made for, and the run. A picture returned as a
link is fetched through Marvin's guarded client (public hosts only, 20 MB at most); the upload size and type limits
apply. **Attach as** (`attach_as`) on the step links the pictures to the run's entry in that role, and `tags` tags them. Because the run now
carries references instead of image data, it can wait for approval *after* generating ("use this cover?") and be
retried. The same event handled twice keeps one set of pictures.

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
| `POST /api/automations/{id}/run` | Manual run; responds when the run finishes (`409` when disabled) — or, with `?background=true`, at once with `{"status": "started"}` while the run goes on (what the **Run** button does). With `?dry_run=true` it returns `plan` and records nothing. For an event-triggered workflow the dry run also takes `entry_id` or `event_id` (an event log row) and returns `sample`, `trigger_matched`, `conditions` (each with `field`, `op`, `value`, `actual`, `expected`, `pass`, or a nested `group`), `conditions_pass` and `would_fire`. |
| `GET /api/automations/{id}/samples?limit=` | The dry run's candidate samples: recent logged events the trigger fires on, then uncovered entries (default 10, at most 25), each with `kind`, `id`, `label`, `occurred_at`, `synthesized`, `conditions_pass`. Empty for a workflow no event triggers. |
| `GET /api/automations/{id}/executions?limit=` · `GET …/executions/{execution_id}` | Run history (default 25, at most 100); detail includes per-step records and the definition snapshot. |

## Settings

A workflow is `enabled: false` when created. A disabled workflow does not run from events, the scheduler or **Run**, but can be dry-run. A workflow with the `mcp` trigger is exposed by the Marvin MCP server as a tool named `marvin_wf_<slug>` (non-alphanumerics in the slug become `_`; needs a user token, see [Marvin as an MCP server](marvin-as-mcp-server.md)). Separately, the agent's `run_workflow` tool runs any enabled workflow by slug, name or id, skipping its trigger and conditions as **Run** does, and the run is recorded under **Runs**. Like **Run**, it needs workspace ADMIN or OWNER (as does `list_workflows`).

**Agents can draft workflows.** Asked to create, build or set up a workflow, an agent reads the format from `workflow_authoring_guide` and saves it with `draft_workflow`. The workflow is created switched off, through the same save as **New workflow** (the same slug from the name, the same checks, recorded as created by you, so its steps run with your role), and the agent answers with a link that opens it in the editor (`/automation/workflows?workflow=<id>&edit=1`). Review the trigger and steps, dry-run it to see which entries it would act on, then tick **Enabled**. An agent never enables or runs a workflow it drafted. A draft also has to pass checks the editor doesn't make: every key must be one the format has (a `steps` list or a step's `type` is refused rather than ignored), and every name must exist (a triggerable event, an entry query key, an entry type, a collection, an AI operation, an allowed job, an integration action that can run unattended, an outgoing or incoming webhook, another workflow); template values (`${…}`) are left to run time. The agent gets each problem with its path, such as `actions[0].op`, and tries again. `update_workflow_draft` revises a workflow only while it is switched off. See [Agents and Ask](agents-and-ask.md#what-it-does).

## Since

`form_submission_received` as a trigger: v1.0.0-rc.51 (`8f1443d1`). `auth_scheme`: rc.50 (`a65ba7d0`). `entry.summary` and `entry.data.*`: rc.52 (`433e949e`). Response `body`, `set_metadata` and metadata targeting: rc.59 (`1380e92e`). `entity_query`: rc.60 (`65ffb648`). Raw-URL `method` and templated stored URLs: rc.61 (`b88e4035`). Builder fixes: rc.63 (`57956e71`). `set_data`, the integration step, `entry.metadata` and list indexes in paths: rc.111. `entry.image`: rc.119. Full entry context per query row and **Fields equal**: rc.129. Typed values for checkbox and number fields: rc.131. The shared entry query (`where`, `sort`, date filters): rc.138. Unknown `where` ops match nothing, and `run_workflow` runs appear under **Runs**: rc.139. Site build and deploy events from `emit_event`: rc.144. `{{SLUG}}` in integration step args: rc.145. AI limits on operation steps: rc.146. Site events as notification subscriptions: rc.151; as workflow triggers: rc.152. `automation_started` and the shared `execution_id`: rc.165. Dry run against a sample event, with the condition checklist and `GET …/samples`: rc.173. A refused publish fails the entry step with the reason: rc.175. `${site.url}`: rc.177. Each event's subject, a run's trigger (`trigger_entity_*`) and step summaries in `automation_ran` / `automation_failed`, `$event.entity_type` / `$event.entity_id`: rc.178. `if_none: skip` and `${entry.url}`: rc.179. `on_failure`, `request_review` and an integration error's `${error.code}`: rc.193. Integration error policies (`integration_errors`, `handled` / `handling` / `retry_attempt` on run events), a workflow never re-triggering itself, and option pickers in the **Run integration** step: rc.197. A step's `when` (if/else), an operation step's `write_back` field map, custom AI steps (`op: "custom"`), **Create an entry** (`create`) and **Wait for approval** (`approval`, migration `5c2e8a91d4f7`): unreleased (2026-10-11). **Process an image** (`media`), generated images kept as assets, `attach_as`, `asset.derived_from`, the `role` on `asset_attached_to_entry`, and `gt` / `gte` / `lt` / `lte`: unreleased (2026-10-12). **Render a template** (`render`): unreleased (2026-10-12). **Gather items** (`collect`), relative query dates, lists of pictures in a render, and local times across the admin: unreleased (2026-10-12). Linked items in queries (`entries`, `asset`, `resource`, `entry`, `role`, `exclude`, `checksum`, sort `position`), `only_invalid`, `asset.checksum` and **Check a web address** (`fetch`): unreleased (2026-10-12). Step ids and the result key in the editor, dry-run stand-ins for AI answers, and unchanged Set metadata / Set fields saving nothing: unreleased (2026-10-12).

## Related

- [Incoming webhooks](incoming-webhooks.md) · [Outgoing webhooks](outgoing-webhooks.md) · [Forms and submission protection](forms-and-submission-protection.md) · [Integrations](integrations.md)
- [Glossary](../glossary.md)
