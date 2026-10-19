# Flavor B — State Review

Companion to `WORKFLOW_SUGGESTIONS.md`. That document asks "what should we build?"
This one answers "what did we already build, what's actually missing, and what should
happen next."

Read as: the design in `WORKFLOW_SUGGESTIONS.md` is largely **already implemented in
skeleton form**. The gap is not design — it's validation, observability, and one
structural problem in the layer beneath it.

---

## 1. What exists today

### The engine (`src/marvin/services/automation/`)

| Concern | State |
|---|---|
| Persistence | One table, `workspace_automations`. `definition` is an opaque `sa.JSON` blob holding `{trigger, conditions, actions}` |
| Trigger kinds | `event`, `chained`, `on_error`, `manual`, `schedule` |
| Conditions | Flat AND-list. Operators: `eq`, `neq`, `contains`, `exists` |
| Actions | `operation` (AI), `emit_event`, `handler` (scheduled-task registry), `webhook` |
| Mapping | `$`-prefixed whole-string templates over `event.*`, `entry.*`, `previous.*`, `depth` |
| Execution | Fully synchronous, inline on the event-bus listener thread |
| Loop guard | `MAX_REACTION_DEPTH = 3`, `MAX_ACTIONS = 10` |
| Permissions | ADMIN/OWNER for all CRUD and manual run |
| UI | `frontend/src/pages/automation/workflows.astro` |
| Tests | `tests/test_automation_flavor_b.py` — 287 lines, matcher/engine/registry only |

The shape the design doc proposes — Trigger → Conditions → Ordered Actions —
**is the shape that exists.** `engine.py` is ~155 lines and readable. `matcher.py` is
pure and side-effect free. The action registry in `actions/base.py` is a plain dict.
For a hobby project this core is proportionate and good. Don't redesign it.

### The event bus (`src/marvin/services/event_bus_service/`)

- 9 listeners, fixed order, sync fan-out. Background via FastAPI `BackgroundTasks`
  on the HTTP path; fully inline everywhere else.
- Persisted to `event_log` (JSONB payload + indexed columns).
- Flavor A reactions that genuinely work: **AI embedding re-index** on
  publish/update, and **smart-collection sync** on the six entry lifecycle events.
- `AutomationReactionListener` is the single, clean seam into Flavor B.

### In flight, uncommitted

`incoming_webhook` (todo item T5) — model, migration, schema, and
`routes/hooks/hooks_controller.py` exist and the router is registered. This is the
**Model 2 / ingress** design: `POST /api/hooks/{token}` drops an `incoming_webhook`
event on the bus and fans out to any subscriber, rather than binding to one automation.
Correct design. The remaining piece is that `incoming_webhook` is not yet in the
automation listener's `_TRIGGERS`, so no automation can subscribe to it — which is
subsumed by the "generalize event triggers" item below rather than being a bug in the
ingress work itself.

---

## 2. The structural problem

> **Marvin has no domain service layer for entries. Entry lifecycle logic lives in the
> controller.**

`src/marvin/services/` has `ai`, `assets`, `collections`, `automation`, `webhooks`… and
no `entries`. All entry status-transition logic — which state changes are legal, which
events they emit — lives in `routes/platform/entries_controller.py:173-260`.

This directly contradicts the hierarchy the design doc asks for:

```
Marvin domain/application services
        ↑
API and UI · Flavor A listeners · Flavor B actions · MCP tools · SDK
```

There is nothing at the top of that diagram for entries to point at. The consequence is
already visible in the codebase: `runner.py:184-205` performs AI write-back by mutating
the entry and then **hand-dispatching `entry_updated` itself**, duplicating the
controller's logic. Every new entry action (`entry.publish`, `entry.archive`) written
today would duplicate it again, and each copy is a place where the event can be
forgotten — at which point chained automations silently stop firing.

**This is the highest-leverage thing to fix, and it is not on the doc's staged plan.**
Extracting `services/entries/` with `create/update/publish/unpublish/archive/restore`
that own both the mutation and the emit does three things at once: it unblocks the
entire Entry action surface, it makes chaining reliable by construction, and it is the
natural place to compute `changed_fields` / `before` / `after`.

Do this before Stage 1 of the doc's plan, not after.

---

## 3. Gaps, ranked

### Tier 1 — blocks real use

1. **No `changed_fields` / `before` / `after` on entry events.** `EventEntryData`
   carries 9 identity fields and no diff. `update_entry` loads `old_entry` and throws
   the old values away. This makes the single most valuable automation —
   "status changed draft → review" — impossible to express. Example 7 in the design
   doc cannot be built today.
2. **No execution history.** There is no `automation_executions` table and no
   per-action records. Only the `operation` action leaves a trace (an `AIExecutionModel`
   row); `webhook`, `handler`, and `emit_event` leave nothing. When an automation
   misbehaves there is no way to see what happened. This also blocks most of the UI
   story the doc sketches (history view, execution details, retry).
3. **No definition validation.** `definition` is typed as bare `dict` in the Pydantic
   schema. Malformed automations are accepted by the API and fail silently at run time.

### Tier 2 — user-visible incorrectness

4. **The event catalog advertises ~100 subscribable events; 54 of 122 enum members are
   never emitted.** All 8 site/publishing events, all 3 form-submission events, and both
   asset attach/detach events are declared and never fired. The Events UI is offering
   users subscriptions that can never deliver.
5. **The loop-guard comment in `runner.py:203` is false.** It claims the automation
   listener ignores its own writes via `integration_id`. No listener checks
   `integration_id`. Only the depth counter bounds the loop. Fix the comment or
   implement the check — the comment is currently a trap for future work.

### Tier 3 — sharp edges

7. **Interpolation is whole-string only.** `"Summary: $previous.summary"` passes
   through as a literal — only a string that *starts* with `$` is substituted. This
   will surprise every user who tries it.
8. **Only `$previous` is reachable.** The doc explicitly asks for
   `actions.<id>.output.*` precisely because actions get reordered. Today each step can
   only see the one before it.
9. **No `any` / `not` / nesting in conditions.** Flat AND only.
10. **`MAX_ACTIONS = 10` truncates silently** — `actions[:10]`, no error, no warning.
11. **`handler` action exposes the entire scheduled-task registry with no allowlist**,
    including maintenance tasks like `remove_orphaned_assets`.
12. **No per-user authorization at execution.** `user_id` is provenance only. An AUTHOR
    publishing an entry can trip an admin-authored automation that runs privileged
    handlers and webhooks under full workspace authority.
13. **`/run` does not check `enabled`** — a disabled automation can still be run
    manually.
14. **No retry, no backoff, no dead-letter, no idempotency key** anywhere.
15. **Event emission is not atomic with the mutation.** `entry_deleted` is emitted
    *before* the delete (`entries_controller.py:283`), so a failed delete still logs.
    Every emit site is wrapped in `try/except: log`, so dispatch failures are invisible
    to the caller.
16. **Test coverage stops at the predicate layer.** Zero tests for any of the four
    action executors, the controller, `RunAutomationHandler`, or write-back.

---

## 4. Recommended sequence

This replaces the doc's Stage 1–6. It is ordered by unlock, not by feature area.

### Stage 0 — Foundation (do first)

- Extract `services/entries/` — mutation + event emission together, one place.
- Add `changed_fields` / `before` / `after` to `EventEntryData`. **Changed fields plus
  scalar before/after only** — not full snapshots. Rich fields and relationships go in
  by reference (id + type), never by value. This keeps payload size bounded and avoids
  persisting content into `event_log` that the user may later delete.
- Validate `definition` with a Pydantic discriminated union.

### Stage 1 — Observability

- `automation_executions` + `automation_action_executions` tables.
- Every action writes a record. Truncate snapshots at a fixed byte cap. Never persist
  resolved secrets.
- Correlation id threaded through `dispatch`, promoted to a real column on `event_log`.
  Causation id and parent-execution id can wait; correlation alone makes a chain
  readable.

### Stage 2 — Honesty pass

- Delete the 54 dead enum members, or gate the catalog so the Events UI only advertises
  events with a real emitter. Add a test asserting every catalog entry has a dispatch
  site.
- Fix the `integration_id` comment.

### Stage 3 — Expression ergonomics

- Embedded `${...}` interpolation.
- Named step outputs: `$steps.<action-id>.output.*`, with `$previous` kept as an alias.
- `any` / `not` / nesting in conditions, plus `in`, `starts_with`, `changed`,
  `changed_from`, `changed_to`.

### Stage 4 — Action surface

Now that `services/entries/` exists, these are thin:
`entry.publish`, `entry.unpublish`, `entry.archive`, `entry.restore`,
`entry.add_to_collection`, `entry.remove_from_collection`.

Allowlist the `handler` action. Keep `entry.delete` out for now.

### Deferred — and I'd argue permanently

Branching, loops, delays, `wait_for_event`, approval gates, native Slack, notification
system, outbox, event sourcing. Every one of these is either n8n's job or requires
persisted mid-flight workflow state, which is the single largest complexity jump
available and buys the least. The doc already reaches this conclusion; I'm agreeing
with it emphatically.

---

## 5. Ideas not in the design doc

**Make the Pydantic definition schema the one source of truth.** If trigger and action
inputs are discriminated-union Pydantic models, you get validation, the
`/automation-catalog` JSON Schema, the SDK types, and the MCP tool projection all from
the same declaration. The doc treats the registry, the schemas, and the catalog as three
separate deliverables. They should be one. This is the single largest simplification
available.

**A `dry_run` flag on the engine, not a separate code path.** Thread a boolean through
`run_automations_for_event`; each action executor returns its resolved input instead of
executing. Costs ~10 lines per action and delivers the doc's "evaluate trigger and
conditions, resolve inputs, don't execute" test mode without a parallel simulation
engine.

**Guard the catalog with a test.** `test_every_catalog_entry_has_an_emitter` would have
caught all 54 dead events. Cheap, and it stops the drift from recurring.

**Reconsider the `handler` action.** It is currently the most powerful and least
constrained thing in the system — full scheduled-task registry, no allowlist, no
schema, duck-typed config. It is also the reason several proposed actions (`site.
request_build`, `ai.reindex_scope`) are arguably already implemented. Decide
deliberately: either promote specific handlers to first-class actions with schemas, or
keep `handler` as an explicit escape hatch behind an allowlist. Leaving it as-is is the
one thing I'd call a genuine risk.

**Answering the doc's Flavor A/B decision rule.** The proposed rule is right; sharpen
it to: *if disabling it would corrupt state, it's Flavor A.* Embedding, smart-collection
sync, and derivative cleanup all fail that test — they must stay Flavor A. The doc's own
Example 2 (automatic embedding as a Flavor B automation) should be rejected on exactly
this ground; it is already correctly implemented as Flavor A and should stay there.

---

## 6. What I'd simplify

- Don't normalize conditions or actions into tables. JSON + Pydantic validation is
  correct here and the query needs don't justify the join.
- Don't build an outbox. Sync fan-out with a correlation id and an execution table is
  enough to debug a hobby-scale system, and the failure mode an outbox prevents
  (process death between commit and background task) is rare enough to accept.
- Skip automation versioning as infrastructure. Snapshot the definition JSON onto the
  execution row — one column, full auditability, no revision system.
- Keep execution synchronous. The existing `BackgroundTasks` hop is sufficient. Revisit
  only if a real automation actually times out a request.
