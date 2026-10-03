# Collections

A collection groups entries by hand or by rule; smart collections now support rolling date windows, and new workspaces no longer inherit a "Recent" collection.

## What it does

A **manual collection** is curated: you add, remove and reorder entries yourself. A **smart collection** (`is_smart: true`) fills itself from a `smart_rules` object and you do not add members by hand. Both kinds are read the same way: membership is **materialised** into junction rows, so the admin UI, renderers and the [publishing API](publishing-api.md) never special-case smart collections at read time.

A collection has a `target_type` of `entry` (default), `asset` or `resource`. Manual collections are entry-only; a smart collection can group any one of the three.

Every workspace also gets five locked **system** collections (`inbox`, `drafts`, `needs-review`, `approved`, `archive`): smart, status-driven, non-public, and not editable. The only editorial default a new workspace receives is `featured`.

### Rule format

`smart_rules` is JSON. Every dimension is optional, but an **empty rule set matches nothing**, so a misconfigured smart collection cannot sweep in the whole workspace.

| Field | Applies to | Meaning |
| --- | --- | --- |
| `entry_types` | entry | entry-type slugs |
| `statuses` | entry | entry status values |
| `published_within_days` | entry | `published_at` within the last N days |
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

### Materialisation

- `SmartCollectionReactionListener` re-evaluates an entry against every smart collection on `entry_created`, `entry_updated`, `entry_published`, `entry_unpublished`, `entry_archived` and `entry_restored`. Deletion needs no reaction; the junction cascades.
- Tagging an entry, asset or resource re-syncs that item; asset and resource writes re-sync through their repositories.
- Changing a collection's rules re-materialises that collection (`sync_collection`).
- Applying a collection [blueprint](blueprints.md) materialises it immediately.
- The system task **Resync Smart Collections** (`resync_smart_collections`, admin-only, daily interval) re-materialises every smart collection in every workspace. It is the safety net for missed events, bulk imports and rolling windows.

## Where

- Create: `/workspace/collections/new`. Edit: `/workspace/collections/{id}`. Both render `SmartCollectionFields`: a **Smart Collection** toggle and a **Rules (JSON)** editor with an inline reference.
- Admin: the platform scheduled-tasks list, for `resync_smart_collections`.

## How to use

1. Create a collection and switch on **Smart Collection**.
2. Paste a rules object. Keys are `snake_case` and stored as opaque JSON; the server evaluates exactly these keys.
3. Save. Membership is computed on save and kept current by the reactions above.
4. Treat the entry list as read-only; pins on a smart collection are not preserved (smart XOR manual in this release).

Want the old "Recent" behaviour? Create a smart collection with `published_within_days: 30` and `statuses: ["published"]`, or apply the core `recently-published` blueprint. Since 921047ad the bootstrap no longer creates one: it was a manual collection described as "recently published content", so nothing could fill it, and it sat empty in every workspace on the instance. Existing workspaces keep whatever they already have.

## API

Workspace collections live under `/api/platform/collections`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `` | List / create. Body includes `is_smart`, `smart_rules`, `target_type`, `is_public` |
| GET / PATCH / DELETE | `/{id}` | Read / update (a rules change re-materialises) / delete |
| PATCH | `/order` | Reorder collections |
| GET | `/{id}/members` | Members of any target type |
| GET | `/{id}/entries` | Entries, with junction data |
| PATCH | `/{id}/entries/order`, `/{id}/entries/{entry_id}` | Manual ordering and junction metadata |

SDK: `sdk.collections.createSmart(name, rules)` on `@inneropen/marvin-sdk/platform`, or `create({ isSmart: true, smartRules })`. `SmartCollectionRules` is exported for typing. Full reference: [`../api/`](../api/index.md).

## Settings

None. The resync cadence is the system task's interval (daily); an admin can adjust it in the scheduled-tasks UI.

## Since

Rolling windows: rc.82 (`142eb6e9`). No default "Recent": rc.83 (`921047ad`). Asset/resource targets, `mime_types` and `tags` predate this release.

## Related

- [Blueprints](blueprints.md) — the core catalog is six worked smart-rule examples.
- [Publishing API](publishing-api.md) — how public collections are served.
- [Integrations](integrations.md) — an integration can declare the smart collections it needs as blueprints.
- Design: [smart-collections-explained.md](https://github.com/InnerOpen/marvin/blob/develop/docs/smart-collections-explained.md), `frontend/docs/smart-collections.md`.
- [Glossary](../glossary.md)
