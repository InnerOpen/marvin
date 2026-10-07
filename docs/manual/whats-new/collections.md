# Collections

A collection groups entries by hand or by rule; smart collections now support rolling date windows and field conditions, are edited in a visual builder or as JSON, and can be previewed with **Run Query** before saving. New workspaces no longer inherit a "Recent" collection.

## What it does

A **manual collection** is curated: you add, remove and reorder entries yourself. A **smart collection** (`is_smart: true`) fills itself from a `smart_rules` object and you do not add members by hand. Both kinds are read the same way: membership is **materialised** into junction rows, so the admin UI, renderers and the [publishing API](publishing-api.md) never special-case smart collections at read time.

A collection has a `target_type` of `entry` (default), `asset` or `resource`. Manual collections are entry-only; a smart collection can group any one of the three.

Every workspace also gets six locked **system** collections (`inbox`, `drafts`, `needs-review`, `approved`, `archive`, `trash`): smart, status-driven, non-public, and not editable. A trashed entry belongs to the [Trash](trash.md) alone: no other collection lists or counts it, smart or manual (a manual collection keeps its membership for when it is restored). The only editorial default a new workspace receives is `featured`.

**Visible to sites.** A collection's `is_public` flag (default on) decides whether the [publishing API](publishing-api.md) serves it. The create and edit forms show it as **Visible to sites**. Off, sites can't list the collection, open it, or filter entries by it (`GET /entries?collection=` ignores a private collection, as the collection endpoints do). Its entries stay published and can still appear through other collections, entry lists and their own pages. A private collection carries a **Private** pill in the collections list and on its page. System collections are always private, so their toggle is shown disabled with that explanation.

### Rule format

`smart_rules` is JSON. Every dimension is optional, but an **empty rule set matches nothing**, so a misconfigured smart collection cannot sweep in the whole workspace.

| Field | Applies to | Meaning |
| --- | --- | --- |
| `entry_types` | entry | entry-type slugs |
| `statuses` | entry | entry status values |
| `published_within_days` | entry | `published_at` within the last N days |
| `where` | entry | field conditions, `[{"field": key, "op": op, "value": v}]`; each condition is one dimension |
| `asset_types` | asset | asset type bucket, e.g. `image` |
| `mime_types` | asset | exact MIME type, e.g. `image/svg+xml` |
| `resource_types` | resource | resource type |
| `created_within_days` | any | `created_at` within the last N days |
| `tags` | any | tag slugs; matches when the item carries at least one |
| `match` | — | `all` (default) or `any` across the dimensions given |

`published_within_days` and `created_within_days` are the new **rolling windows**. They fail closed: a missing date, a non-numeric window, or a window of zero or less matches nothing rather than dropping the constraint. Naive timestamps are read as UTC. Because membership is materialised, an item that has aged out leaves on the next reconcile pass, not on read; a rolling collection is accurate to within one run of `resync_smart_collections`.

```json
{"statuses": ["published"], "published_within_days": 30, "match": "all"}
```

`where` is the same condition a workflow's entry query uses (see [Workflows](workflows.md#run-on-a-query-of-entries)), evaluated by the same code: `field` is a field key of the entry type or `metadata.<key>`, and `op` is `eq`, `neq`, `in`, `contains`, `exists`, `missing`, `gt`, `gte`, `lt` or `lte`; comparisons read number-like text (`"$1,170"` → 1170). An unknown op never matches. The rest of the two shapes differ: smart rules use plural keys (`entry_types`, `statuses`), rolling windows and `match`, while a workflow query uses `entry_type`/`status`, `text`, `collection`, date ranges and `sort`, which smart rules do not read. **Run Query** names any key it ignores.

### Materialisation

- `SmartCollectionReactionListener` re-evaluates an entry against every smart collection on `entry_created`, `entry_updated`, `entry_published`, `entry_unpublished`, `entry_archived`, `entry_trashed` and `entry_restored`. Deletion needs no reaction; the junction cascades.
- Tagging an entry, asset or resource re-syncs that item; asset and resource writes re-sync through their repositories.
- Changing a collection's rules re-materialises that collection (`sync_collection`).
- Applying a collection [blueprint](blueprints.md) materialises it immediately.
- The system task **Resync Smart Collections** (`resync_smart_collections`, admin-only, daily interval) re-materialises every smart collection in every workspace. It is the safety net for missed events, bulk imports and rolling windows.

## Where

- Create: `/workspace/collections/new`. Edit: `/workspace/collections/{id}/edit`. Both have the **Visible to sites** toggle and render `SmartCollectionFields`: a **Smart Collection** toggle, the rules under two tabs, **Builder** and **JSON**, and a **Run Query** button.
- Admin: the platform scheduled-tasks list, for `resync_smart_collections`.

## How to use

1. Create a collection and switch on **Smart Collection**, then choose what it collects (entries, assets or resources).
2. Build the rules on the **Builder** tab: **Match** all or any, entry types and statuses (or asset types and MIME types, or resource types), tags, the published and created windows, and **Field conditions** (field, operator, value; `is one of` takes a comma-separated list). Or write them on the **JSON** tab. Both tabs edit the same rules: a builder change rewrites the JSON, and valid JSON redraws the builder. Invalid JSON shows the parse error under the editor, leaves the builder on the last valid rules, and blocks saving. Keys the builder has no control for stay in the JSON untouched.
3. Press **Run Query** to evaluate the unsaved rules: it shows how many items would be in the collection and links the first 10, newest first. Empty rules say they match nothing. The preview uses the same matching code as saving, so the count is the membership you get.
4. Save. Membership is computed on save and kept current by the reactions above.
5. Treat the entry list as read-only; pins on a smart collection are not preserved (smart XOR manual in this release).

Want the old "Recent" behaviour? Create a smart collection with `published_within_days: 30` and `statuses: ["published"]`, or apply the core `recently-published` blueprint. Since 921047ad the bootstrap no longer creates one: it was a manual collection described as "recently published content", so nothing could fill it, and it sat empty in every workspace on the instance. Existing workspaces keep whatever they already have.

## API

Workspace collections live under `/api/platform/collections`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `` | List / create. Body includes `is_smart`, `smart_rules`, `target_type`, `is_public` |
| GET / PATCH / DELETE | `/{id}` | Read / update (a rules change re-materialises) / delete |
| PATCH | `/order` | Reorder collections |
| GET | `/{id}/members` | Members of any target type |
| POST | `/preview` | Evaluate unsaved rules: body `{"targetType", "smartRules", "limit"}` (limit 0–50, default 10); returns `total`, `items` (`id`, `label`, `slug`, `type`, newest first), `ignoredKeys` and `note`. Saves nothing; scoped to your workspace |
| GET | `/{id}/entries` | Entries, with junction data |
| PATCH | `/{id}/entries/order`, `/{id}/entries/{entry_id}` | Manual ordering and junction metadata |

SDK: `sdk.collections.createSmart(name, rules)` on `@inneropen/marvin-sdk/platform`, or `create({ isSmart: true, smartRules })`. `SmartCollectionRules` is exported for typing. Full reference: [`../api/`](../api/index.md).

## Settings

None. The resync cadence is the system task's interval (daily); an admin can adjust it in the scheduled-tasks UI.

## Since

Builder, **Run Query**, `where` and `POST /preview`: rc.169. A scheduled publish joins matching smart collections at once (it fires the usual entry events): rc.171. **Visible to sites**, and private collections ignored by the entries `collection` filter: rc.186. Rolling windows: rc.82 (`142eb6e9`). No default "Recent": rc.83 (`921047ad`). Asset/resource targets, `mime_types` and `tags` predate this release.

## Related

- [Blueprints](blueprints.md) — the core catalog is six worked smart-rule examples.
- [Publishing API](publishing-api.md) — how public collections are served.
- [Integrations](integrations.md) — an integration can declare the smart collections it needs as blueprints.
- Design: [smart-collections-explained.md](https://github.com/InnerOpen/marvin/blob/develop/docs/smart-collections-explained.md), `frontend/docs/smart-collections.md`.
- [Glossary](../glossary.md)
