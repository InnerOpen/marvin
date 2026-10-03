# Blueprints

A blueprint describes something a workspace could have (a collection, an entry type, fields on an entry type, a scheduled task, an event subscription, an incoming webhook or a workflow) and creates nothing until you apply it.

## What it does

A **blueprint** is a declarative description of one piece of workspace structure. Core ships a small catalog of them; an installed [integration](integrations.md) contributes its own through the SDK's `ContentBlueprint`, because a provider may only ever declare content, never create it. One schema (`src/marvin/schemas/platform/blueprints.py`) serves both the core catalog and what an integration brings.

Each blueprint has a `kind`, a `slug`, `name`, one-line `description`, a `category`, a `source` (`core` or a provider slug), optional `requires`, optional `parameters`, and a `payload` in the shape the creating code expects. A payload that carries `group_id` or `id` is rejected: scoping is the core's job.

| `kind` | Creates | Payload |
| --- | --- | --- |
| `collection` | A collection (smart collections are materialised at once) | A collection body |
| `entry_type` | An entry type | An entry-type body |
| `entry_fields` | Fields on an existing entry type | `{"entry_type": "<slug>", "fields": [<schema field>, …]}`; only fields whose `key` is missing are appended, existing fields are never changed |
| `scheduled_task` | A scheduled task, switched off | A scheduled-task body |
| `event_subscription` | An event → integration action wiring, switched off | `event_type`, `action`, `args` |
| `incoming_webhook` | An [incoming webhook](incoming-webhooks.md), switched off and without a token | `name`, `description`, `signature_scheme`, `signature_header`, `signing_secret_ref`, `signature_url`, `signature_config`; a `token` is refused |
| `workflow` | A [workflow](workflows.md), switched off, authored by whoever applies it | `{"name": …, "definition": {trigger, conditions, actions}}`; the definition must pass structural validation |

**Required vs suggested.** `required` defaults to `False` and is meant to be set sparingly: `True` only when the source cannot work without it, such as an entry type an action reads or writes. Everything else is a suggestion. Core blueprints are never required.

**Parameters.** Core names nobody's content. Where a blueprint needs a slug from the workspace, it asks for it: a `BlueprintParameter` has a `key`, a `label`, a `kind`, `required`, `default` and `help`. `entry_type`, `collection` and `integration` render as dropdowns of what the workspace has and are validated against it; `text` and `number` are free input. An `integration` parameter lists the workspace's connections of the declaring provider and defaults to the connection whose card you are on (through the API: the workspace's only connection of that provider). `{{key}}` placeholders are substituted through slug, name, description and payload, so `all-{{entry_type}}` applies once per type. A lone `{{key}}` yields the value itself rather than a string.

**Core catalog** (`src/marvin/services/blueprints/catalog.py`), collections only, all smart:

| Slug | Category | Rule it demonstrates |
| --- | --- | --- |
| `recently-published` | Editorial | `statuses: [published]`, `published_within_days: 30` |
| `new-this-week` | Editorial | `created_within_days: 7` |
| `all-{{entry_type}}` | Editorial | `entry_types` (asks which type) |
| `published-{{entry_type}}` | Editorial | `entry_types` + `statuses` (asks which type) |
| `all-images` | Media | `target_type: asset`, `asset_types: [image]` |
| `vector-artwork` | Media | `target_type: asset`, `mime_types: [image/svg+xml]` |

Status buckets are deliberately absent: every workspace already gets the locked inbox/drafts/needs-review/approved/archive collections.

## Where

- **Integrations page** (`/workspace/settings/integrations`): each connected integration's card lists that provider's blueprints under **Content**, split into **Needed to work** and **Optional — set these up if you want them**. This is the only admin UI for blueprints.
- **API**: `/api/groups/blueprints`, which also serves the core catalog.

## How to use

### Apply from an integration card

1. Connect the integration. Its card opens the **Content** section automatically if anything needed is missing.
2. Fill a row's parameters if it has any. They are dropdowns of your entry types, collections or connections, prefilled with the blueprint's defaults.
3. Click **Add** on a row, or **Add N missing items** to apply everything needed that is missing (parameters are read from each row).
4. Read the result. A toast reports what was added and, for anything skipped, why; "already exists — left as it is" is information, not an error.
5. Review what arrived switched off (scheduled tasks, event subscriptions, incoming webhooks, workflows) and turn it on. An incoming webhook also needs a token, created on its page.

### Update an applied workflow

When an integration ships a newer version of a workflow you applied, its row shows ↑ and an **Update** button. Update replaces the workflow's definition with the integration's current one, discarding any edits you made to it, and keeps whether it is switched on. Only workflows can be updated; everything else stays as you have it.

### Apply semantics

- **Create what is missing, never overwrite what exists.** The upsert is keyed on the resolved slug within the workspace. A customised copy survives a repeat apply and a provider upgrade. For `entry_fields`, "applied" means every declared field is already on the type.
- **Dependency order.** Bulk apply sorts entry types, then added fields, collections, scheduled tasks, incoming webhooks and workflows, and flushes after each, so a collection that `requires: entry_type:<slug>` sees the type created moments earlier and a workflow finds the webhook it triggers on.
- **Requirements gate.** An unmet `requires` entry makes the blueprint `available: false`; applying it returns `created: false` with `detail: "needs entry_type:<slug>"` rather than half-creating.
- **Event subscriptions need a connection.** They reference an integration instance: `POST /{slug}/apply` takes `integration_id`, otherwise the workspace's only connection of that provider is used; with two or more, apply refuses rather than guess. They have no database slug, so the upsert dedupes on (integration, event type, action).
- **Created switched off.** Anything that acts once enabled (`scheduled_task`, `event_subscription`, `incoming_webhook`, `workflow`) is created with `enabled: false`. Turning it on is a deliberate second act.
- **Collections are materialised on create**, so a smart collection does not sit empty until the next entry event. Scheduled tasks go through the repository so `next_run_at` is computed.

## API

Workspace-scoped, under `/api/groups/blueprints`. Apply and update need workspace ADMIN or OWNER.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `` | Catalog annotated per workspace: `applied`, `outdated`, `available`, `missing_requirements`. Filters `?kind=`, `?category=`, `?source=core|<provider>`, `?integration_id=` |
| GET | `/categories` | Category names in catalog order, core first then each provider |
| GET | `/{slug}?source=` | One blueprint with its payload |
| POST | `/{slug}/apply?source=&integration_id=` | Body: the `params` dict, e.g. `{"entry_type": "post"}`. Returns `BlueprintApplyResult` |
| POST | `/apply?source=` | Body: `slugs` list and `params` keyed by slug. Returns a list of results, applied in dependency order |
| POST | `/{slug}/update?source=` | Workflows only: replace the applied workflow's definition with the declared one. Returns `BlueprintApplyResult` with `updated` |

A parameterised blueprint is judged `applied` by its default parameter values; one with a required parameter that has no default reads as not applied. `outdated` is true when an applied workflow's definition differs from what the provider declares now. Slugs are unique per source; pass `source` to disambiguate.

```json
{"slug": "recently-published", "kind": "collection", "created": true, "updated": false, "detail": "", "name": "Recently published"}
```

Full reference: [API reference](../api/index.md).

## Settings

None.

## Since

Blueprints and the core catalog: 1.0.0-rc.84 to rc.97. `entry_fields`, `incoming_webhook` and `workflow` kinds, and admin-only apply: rc.111. Parameters from dropdowns: rc.116. An `integration` parameter defaults to the workspace's own connection: rc.117. Updating an applied workflow: rc.118.

## Related

- [Integrations](integrations.md) — where provider blueprints are offered and applied.
- [Collections](collections.md) — the smart rules the core catalog demonstrates.
- SDK contract: [marvin-integration-sdk](https://github.com/InnerOpen/marvin-integration-sdk) `ContentBlueprint`.
- [Glossary](../glossary.md)
