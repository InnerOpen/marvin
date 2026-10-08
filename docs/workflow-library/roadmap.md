# Workflow Library — engine roadmap

Gaps ranked by how many of the 104 catalogued recipes name them (`dependencies[]` in `catalogue.json`); the
acceptance criteria are the ones the catalogue carries (`capabilities` section). CAPABILITIES.md rows from the
brief are mapped in the last column.

| # | Gap (id) | Blocks | Priority | Acceptance (summary) | CAPABILITIES.md |
|---|---|---|---|---|---|
| 1 | Free-form AI operation (`custom-operation`) | 38 | P0 | an operation step with its own prompt + JSON output schema (or a workspace-defined op with a persona resource); output schema-validated; same budget/approval/min_role gates | Typed output contracts / Provider adapters |
| 2 | Assets and resources as subjects (`asset-resource-targets`) | 28 | P1 | `asset.*` / `resource.*` context on their events; operation steps load the image for vision ops and write `alt_text` back; target `entity: asset|resource`; derivative lineage | Assets and resources |
| 3 | Create-entry action (`create-entry`) | 26 | P0 | `{"kind":"entry","op":"create",…}` → schema-validated entry, `entry_id` output, `entry_created` at depth+1, dry-run preview, idempotent on retry | Field updates and entity creation |
| 4 | Media adapters (`media-adapters`) | 24 | P1 | SDK capabilities for resize/crop/convert/OCR/render/TTS/zip; originals untouched; lineage recorded | Provider adapters |
| 5 | Approval step in a workflow (`workflow-approvals`) | 20 | P1 | durable park, Approve/Deny push reuse, `${steps.<id>.output.decision}`, expiry, version re-check; unlocks `requires_approval` actions | Durable approvals |
| 6 | Iterate / aggregate (`iterate-aggregate`) | 12 | P1 | reduce a target set into one output; bounded; per-row errors | Iteration / aggregation |
| 7 | Relative dates + cron (`relative-dates`) | 6 | P1 | `updated_before: "-30d"` (still missing); ~~cron computes `next_run_at` with timezone~~ done (`services/cron.py`) | Scheduling and waits / Queries |
| 8 | Conditional steps (`branches`) | 6 | P0 | `when` on a step against `steps.*`; skipped ≠ failed; dry run shows the branch | Branches |
| 9 | Social adapters (`social-adapters`) | 6 | P1 | draft/publish/metrics providers, publish `requires_approval` by default | Provider adapters |
| 10 | Collection-scoped steps (`collection-scope`) | 4 | P1 | `${collection.entries}`; an operation over the set | Queries / relationships |
| 11 | HTTP fetch step (`fetch`) | 4 | P1 | SSRF-guarded GET/HEAD with status/body output; link-check handler | Provider adapters |
| 12 | Durable waits (`waits`) | 4 | P1 | `{"kind":"wait","until":…}` persisted, DST-aware, cancellable, resumes once | Scheduling and waits |
| 13 | Operational events as triggers (`ops-triggers`) | 3 | P2 | ai_budget_*, integration_attention_*, webhook_delivery_failed, scheduled_task_failed triggerable with origin filtering | Event provenance |
| 14 | Data-field change detection (`data-change-detection`) | 2 | P1 | `changed_fields/before/after` cover type fields (opt-in, values elided) | Queries / relationships |
| 15 | Per-step idempotency keys (`idempotency`) | 2 | P0 | templated `idempotency_key` on webhook/integration steps; duplicate within window skips and reuses output | Idempotency |
| 16 | Form-submission classification from workflows (`form-classification`) | 2 | P0 | runner loads the entry-backed submission into `ctx.form_submission` | Typed output contracts |
| 17 | Parallel branches / joins (`joins`) | 2 | P1 | fan-out + join with deterministic merge | Parallel branches / joins |
| 18 | Member-addressed email (`member-email`) | 2 | P2 | member_added carries email / recipient_type `member`; member events triggerable | — |
| 19 | Metrics windows (`metrics`) | 2 | P2 | observations per variant/window, no causal claims | Experimental comparisons |
| 20 | Schema validation / sandbox handler (`sandbox`) | 2 | P2 | validate fetched JSON against a schema | — |
| 21 | Comment events (`comments`) | 1 | P2 | emitter + triggerable, carries entry_id | — |
| 22 | Custom emit_event names (`custom-events`) | 1 | P2 | registered `custom.<name>` events, payload, depth-bounded | Event provenance |
| 23 | Entity snapshots (`snapshots`) | 1 | P2 | capture/restore a version | Snapshots and restoration |
| 24 | Manual run parameters (`manual-params`) | 1 | P1 | typed inputs on manual/mcp triggers, `${input.*}` | Manual invocation |

## CAPABILITIES.md P0 items that already exist

| Item | Exists as |
|---|---|
| Schema-backed recipe validation | `structural_issues` on save; `draft_issues` (+ unknown keys, workspace references) for agents and the Library tests |
| Execution history / resume | `automation_executions` + step rows; integration retries resume at the failed step keeping earlier outputs (`engine.py:811` `run_retry`) |
| Failure policy | provider error policies (review / retry with backoff / notify / succeed / then), `on_failure` steps, `integration_errors: fail` |
| Event provenance | `correlation_id` across the cascade, `reaction_depth` ≤ 3, `_running` self-trigger guard |
| Dry run | `?dry_run=true` with sample events, `/preview` for targets, no side effects |
| Field updates | `set_metadata` / `set_data` (merge, schema-validated) — **no optimistic conflict check** |
| Typed output contracts | partial: operations declare `output_schema`; outputs are plain dicts, absent vs null not distinguished |
| Idempotency | partial: integration retries only |

Quick wins surfaced by the audit (not recipes, but cheap): ~~add `croniter` so cron schedules fire~~ done
without a dependency — Marvin's own `services/cron.py` (moved from Backup health) computes the next run; make
`resync_smart_collections` either work per workspace or leave the handler allowlist; expose `checksum` as an
entry-query key for duplicate-asset detection.
