# Plan: structured search (a filter builder) for entries (2026-10-16)

Jared: "a search style where you can give one condition, then add a second then add a third."

## What exists

- **Entries page** (`frontend/src/pages/workspace/entries.astro`): loads every entry (`GET /api/entries`, no
  parameters) and filters by status and tag in the page. Fine at 443 entries; the list API takes no conditions.
- **Query engine** (`services/entries/query.py`, `run(session, group_id, spec, limit, offset)`; the assistants'
  `find_entries` is a thin wrapper). In SQL: `entry_type(s)`, `status`, `fields` (exact), `where`
  `[{field, op, value}]` with `eq|neq|in|contains|exists|missing|gt|gte|lt|lte` (number-like text compares as
  numbers), `query` (title/slug contains), `tags`, `collection`, `has_images|assets|resources`, `entries`,
  `asset`, `resource`, `created_/updated_/published_ after|before` (ISO or relative: `-7d`), `sort`, `group_by`.
  Returns `rows`, `total`, `groups`, `note` (why a filter can't match), `unknown_ops`. All conditions are ANDed.
- **Smart collections** (`services/collections/smart_collections.py`, builder `SmartCollectionFields.astro`,
  `lib/smartRules.ts`): their own rule shape: `entry_types`, `statuses`, `published_within_days`, `where`, and a
  `match` of all/any, evaluated item by item in Python.

## Approach

**One query language: the engine's spec.** The builder edits a spec, the page sends it, the engine answers.
The assistants already speak it (`find_entries`), so "show me published bench notes tagged denim" in the bubble
can open the page with the same conditions filled in, and what the page shows is what the AI would find.

### The builder (Entries page)

A row of condition chips above the list, plus "+ Add condition":

```
[Type is Bench Note ×] [Status is Published ×] [Tag is denim ×] [readTime contains "2 min" ×]  [+ Add condition]
                                                                         17 entries · Clear · Save as…
```

- **Adding a condition**: pick what to filter on, then the operator, then the value.
  - **Built-in dimensions:** type, status, tag, collection, has images, title contains, created / updated /
    published (before, after, within N days).
  - **The type's own fields:** offered once one type is chosen (or the fields common to the chosen types). Each
    field gets the operators that suit its kind: text `is / is not / contains / is empty / is set`; number and
    date `= ≠ > ≥ < ≤`; choice `is / is one of`; checkbox `is yes / is no`.
- **Each chip** is removable and editable in place. Results update as chips change, with the count shown.
- **The URL holds the spec** (`?q=` holding compact JSON, or readable `?type=…&where=…`), so a search can be
  bookmarked, shared and reloaded. The existing `status` and `tag` parameters become chips.
- **Match:** all conditions (AND) in slice 1; see Q3 for "any".

### The API

`POST /api/entries/query` with body = a spec (the same keys `find_entries` takes), answering
`{entries: EntryRead[], total, note, ignoredOps}` with `limit` / `offset` paging. It is read-only and has the same
role gates as `GET /api/entries` (Trash left out unless asked). An OpenAPI change, so the MarvinSDK types land on
`main` first (additive).

### Save as smart collection (slice 2)

"Save as…" makes a smart collection from the chips. The two rule shapes differ, so a small translator maps a spec
onto smart rules where it can (types, statuses, `where`, published within) and says what it can't carry (tags,
`has_images`, title contains…). The alternative is to give smart collections the engine's spec as a second rule
format (Q2).

### The bubble (slice 3)

`find_entries` results carry an `openInEntries` link (`/workspace/entries?q=<spec>`). The assistant hands it to
the user ("see all 17 in Entries"), and the page opens with the chips set, so you can see and adjust what it
understood.

## Slices

1. **Builder + query API on Entries.**
   - The `POST /api/entries/query` route plus tests over the engine (it is already tested, so the tests cover the
     route, its role gates, paging and the Trash).
   - `lib/entryQuery.ts`: spec ↔ URL ↔ chips, pure, with node tests. The chip editor component goes on the
     Entries page.
   - The existing status and tag filters become chips.
   - SDK types first.
2. **Save as smart collection**, with the translator and its "can't carry" messages (or Q2's alternative).
3. **The bubble link** (`openInEntries`), and the assistant told to offer it.
4. Later, optional:
   - the same builder on Assets: type, origin, searchable, used on an entry, tag, collection, size;
   - match "any", or groups (Q3);
   - combining with semantic search ("…and about repairing worn knees"), which ties in with hybrid search and
     pgvector.

## Questions for Jared (recommendation first)

1. **Where first?** Entries (recommended: the richest fields, and the engine exists); Assets next with its own
   dimensions; an all-in-one search later.
2. **Saving:** URL plus "Save as smart collection" (recommended), or also separate "saved searches"? Smart
   collections already update themselves and show in the sidebar.
3. **"Any" (OR):** all-only in slice 1 (recommended; the engine ANDs), then "match any" across chips. Nested
   groups ("A and (B or C)") only if a real need shows up.
4. **Per-type fields when several types are chosen:** offer only the fields they share (recommended).
5. **Mobile:** chips wrap and the editor opens as a sheet. The pages already fit a phone (2026-10-01), so keep it so.

## Verification

- Backend: the route returns exactly what `find_entries` returns for the same spec; Trash and roles; paging; an
  unknown op is ignored and reported; the full suite.
- Frontend:
  - node tests for spec ↔ URL ↔ chips round trips;
  - `astro check` at the 39 baseline;
  - in Chrome on admin-dev: add three conditions one by one, remove the middle one, reload the URL, phone width.
- Prod, after Promote: Mash & Burn: Type Bench Note → Status Published → Tag denim. The count should match
  `find_entries` with the same spec in the bubble.
