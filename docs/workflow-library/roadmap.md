# Workflow Library — engine roadmap

Gaps ranked by how many of the 104 recipes catalogued when this was written named them ("Named by"); "Still waiting"
is what `catalogue.json` says today (`dependencies[]` of the recipes that are not runnable yet, plus the
configuration recipes that would become workflows). The acceptance criteria are the ones the catalogue carries
(`capabilities` section). CAPABILITIES.md rows from the brief are mapped in the last column. Audited against the code
2026-10-17: **10 done, 3 partly, 11 open.**

| # | Gap (id) | Named by | Priority | Acceptance (summary) | Still waiting | CAPABILITIES.md |
|---|---|---|---|---|---|---|
| 1 | Free-form AI operation (`custom-operation`) | 38 | P0 | ~~an operation step with its own prompt + JSON output schema; schema-validated; same gates~~ done 2026-10-11 (`a3f1058d`: `op: "custom"`, `see`, `write_back`); named reusable workspace operations are a later phase | — | Typed output contracts / Provider adapters |
| 2 | Assets and resources as subjects (`asset-resource-targets`) | 28 | P1 | ~~`asset.*` / `resource.*` context, vision ops write `alt_text` back, `entity: asset\|resource`, lineage~~ done 2026-10-11/12 (`f62a137e`, `1f5311de`, `8e9f8519`) | — | Assets and resources |
| 3 | Create-entry action (`create-entry`) | 26 | P0 | ~~`{"kind":"entry","op":"create",…}` → schema-validated entry, `entry_id`, `entry_created` at depth+1, dry-run preview, once per event~~ done 2026-10-11 (`add56c06`) | — | Field updates and entity creation |
| 4 | Media adapters (`media-adapters`) | 24 | P1 | ~~resize/crop/convert/grade/inspect/palette~~ done 2026-10-12 (`8e9f8519`); ~~render~~ done 2026-10-12 (`be1f0d39`); ~~OCR/PDF text and pages, faces/personal details~~ done 2026-10-12 (`58e99a1c`); ~~zip, printed PDF~~ done 2026-10-12 (`3b9bdfc7`); ~~background removal / provider image edits through an integration~~ done 2026-10-12 (`841483a0`); ~~watermark~~ done 2026-10-12 (`91012b2d`). **Partly: left is TTS (an audio provider)**; originals untouched | audio-edition (TTS) | Provider adapters |
| 5 | Approval step in a workflow (`workflow-approvals`) | 20 | P1 | ~~durable park, Approve/Deny, `${steps.<id>.output.decision}`, expiry, version re-check, `requires_approval` actions run when approved~~ done 2026-10-11 (`13f5aff2`); ~~one-tap Approve/Deny on the push~~ done 2026-10-11 (`befe2ef0`); ~~choices, cancel a waiting run~~ done 2026-10-13 (`f12b80c1`); ~~picture with the question~~ done 2026-10-13 (`68d8392a`) | — | Durable approvals |
| 6 | Iterate / aggregate (`iterate-aggregate`) | 12 | P1 | ~~reduce a set into one output, bounded~~ done 2026-10-12 (`891a1fc5`: a `collect` step); ~~linked items in a query~~ done 2026-10-12 (`8246d379`); ~~one AI step fanned out over the rows~~ done 2026-10-13 (`0e7c993b`: `repeat`, ≤ 25 items, no wait/approval inside) | — | Iteration / aggregation |
| 7 | Relative dates + cron (`relative-dates`) | 6 | P1 | ~~`updated_before: "-30d"`~~ done 2026-10-12 (`891a1fc5`; every query date key; `-7d`, `-12h`, `-2w`, `now`, `today`); ~~cron computes `next_run_at` with timezone~~ done (`services/cron.py`) | — | Scheduling and waits / Queries |
| 8 | Conditional steps (`branches`) | 6 | P0 | ~~`when` on a step against `steps.*`; skipped ≠ failed; dry run shows the branch~~ done 2026-10-11 (`0962dafa`) | — | Branches |
| 9 | Social adapters (`social-adapters`) | 6 | P1 | draft/publish/metrics providers, publish `requires_approval` by default. **Open**: no social provider exists | poll-companion, campaign-scoreboard | Provider adapters |
| 10 | Collection-scoped steps (`collection-scope`) | 4 | P1 | ~~`collect` reads a collection in its own order~~ done 2026-10-12 (`891a1fc5`), and an AI or `repeat` step over its rows gives the roundup (`0e7c993b`). **Partly: left is `${collection.entries}` bound on collection events** (nothing waits on it) | — | Queries / relationships |
| 11 | HTTP fetch step (`fetch`) | 4 | P1 | ~~SSRF-guarded GET/HEAD with status/body output; link-check~~ done 2026-10-12 (`8246d379`: a `fetch` step, `url` + `find`, or `links`) | — | Provider adapters |
| 12 | Durable waits (`waits`) | 4 | P1 | ~~`{"kind":"wait","for"\|"until":…}` persisted, time-zone/DST-aware, cancellable, resumes once~~ done 2026-10-13 (`37d59e9e`, `d1db9209`) | — | Scheduling and waits |
| 13 | Operational events as triggers (`ops-triggers`) | 3 | P2 | ai_budget_*, integration_attention_*, webhook_delivery_failed, scheduled_task_failed triggerable with origin filtering. **Open** (among ops events only deployment, workspace backup and workspace storage events are triggerable) | integration-health-companion, webhook-repair-desk (both run as configuration today) | Event provenance |
| 14 | Data-field change detection (`data-change-detection`) | 2 | P1 | `changed_fields/before/after` cover type fields (opt-in, values elided). **Open**: `_TRACKED_FIELDS` is still status/title/slug | — (seo-assistant and content-refresh run on workarounds) | Queries / relationships |
| 15 | Per-step idempotency keys (`idempotency`) | 2 | P0 | templated `idempotency_key` on webhook/integration steps; duplicate within window skips and reuses output. **Open**: only the integration retry seed exists | — (client-handoff and content-refresh run without it) | Idempotency |
| 16 | Form-submission classification from workflows (`form-classification`) | 2 | P0 | runner loads the entry-backed submission into `ctx.form_submission`. **Open**: only the route builds that context (`with_form_submission`) | — (form-intake-desk and intake-triage run without it) | Typed output contracts |
| 17 | Parallel branches / joins (`joins`) | 2 | P1 | fan-out + join with deterministic merge. **Open** | publication-release-gate | Parallel branches / joins |
| 18 | Member-addressed email (`member-email`) | 2 | P2 | ~~member events triggerable, `${member.*}` (id, username, name, email, role)~~ done 2026-10-13 (`382c2750`). **Partly: left is an email addressed to that person** (no workflow step sends email; member_added carries no email for subscriptions) | new-member-welcome (runs as configuration) | — |
| 19 | Metrics windows (`metrics`) | 2 | P2 | observations per variant/window, no causal claims. **Open** | social-experiment-log, campaign-scoreboard | Experimental comparisons |
| 20 | Schema validation / sandbox handler (`sandbox`) | 2 | P2 | validate fetched JSON against a schema. **Open** (a `fetch` step already returns the parsed `json`) | choose-your-own-adventure, agent-directory-intake | — |
| 21 | Comment events (`comments`) | 1 | P2 | emitter + triggerable, carries entry_id. **Open**: `comment_added/updated/deleted` are in `_NO_EMITTER`; Marvin has no comments feature | reply-drafting-desk | — |
| 22 | Custom emit_event names (`custom-events`) | 1 | P2 | ~~registered `custom.<name>` events, payload, depth-bounded~~ done 2026-10-18 (`SHA`): Settings → Automation → Custom events, typed payload fields, Emit event `payload`, triggerable and subscribable | — | Event provenance |
| 23 | Entity snapshots (`snapshots`) | 1 | P2 | capture/restore a version. **Open** (nothing waits on it) | — | Snapshots and restoration |
| 24 | Manual run parameters (`manual-params`) | 1 | P1 | ~~typed inputs on manual/mcp triggers, `${input.*}`~~ done 2026-10-12 (`5c42d5cc`) | — | Manual invocation |

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
