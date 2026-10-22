# Workflow canvas — plan (release 1: view + run replay)

A node-graph view of a workflow, like n8n's canvas, as a companion to the form and **Edit as JSON**. The definition stays
the single source of truth: the canvas draws it and (from release 2) writes back to it. No free-form graph, no new
drawing library: Marvin's workflows are a trigger + an ordered list of steps with one level of containers, so the layout
is computed, not hand-placed.

Decisions (Jared, 2026-10-22):
- **Where:** a **Canvas** tab in the workflow builder beside the guided form and Edit as JSON — the same unsaved draft in
  three views — plus an "Open canvas" link on each workflow card that opens the builder on that tab.
- **Direction:** **left to right** (trigger left, steps across, parallel branches stacked); **top to bottom under ~720px**
  (phones).
- **Release 1:** view + run replay. Editing on the canvas is release 2.
- **Runs it follows:** a Run started from the canvas, runs that are waiting (wait / approval), any past run (picker), and runs
  that start on their own while it is open.
- **Node panel:** the step's settings (read-only, "Edit in form" jump), this run's output / error / duration, **what it
  received** (needs a backend addition, below), and its condition in plain words with whether it passed.
- **Extras in release 1:** data-reference lines, validation warnings on nodes, pan / zoom / fit, minimap.
- **Live updates:** ride the bell's existing poll — no new stream, no extra idle requests (after today's overload).

## What the definition gives us (verified)

`schemas/group/automation_definition.py` (`AutomationDefinition`, line ~983; JSON Schema served by
`GET /api/automations/options` as `definition_schema`):
- `trigger` by `type`: event | manual | schedule | chained | on_error | incoming_webhook | mcp.
- `target` `{entity, query}`, top-level `conditions`.
- `actions`: steps by `kind` (20 kinds, `ACTION_MODELS`); every step has optional `id` and `when` (a leaf
  `{field, op, value}` or `{all|any|not}` groups). A false `when` = skipped, the run goes on.
- Containers (one level only): `repeat` (`for_each`, `as`, `steps` 1–5, `limit` ≤25, `on_item_error`) and `parallel`
  (`branches` 2–5 `{name, steps}`, `join` all|any, `on_branch_failure`). No wait / approval / repeat / parallel inside them.
- Pauses: `wait` (`for` | `until` + `offset`, `at`), `approval` (`message`, `approvers`, `expires_in_hours`, `choices`).
- `on_failure`: a step list run on failure (`${error.*}`).
- References: `${steps.<id or index>.output.*}`, `${previous.*}`, `${steps.<id>.output.branches.<name>.*}`, `${<as>.*}`,
  `${each.number|count}`.

Runs: `automation_executions` + `automation_action_executions` (`db/models/groups/automation_executions.py:84`) — per step
`action_index`, `kind`, `label`, `status` (success | failed | skipped; run can be waiting), `error`, `duration_ms`,
`output_snapshot` (truncated), `handling`, `target_index`. Detail: `GET /api/automations/{id}/executions/{exec_id}` →
`AutomationExecutionDetail` (`schemas/group/automation.py:311`, includes `actions[]` and `definition_snapshot`); the
frontend has `getAutomationExecution` (`lib/api/automations.ts:120`).

## Layout (pure, tested)

`lib/workflowCanvas/layout.ts` — `layout(definition, { direction: "ltr" | "ttb" }) → { nodes, edges, groups, size }`:
- Columns (ltr) or rows (ttb): Trigger → (Target, if set) → each step in order → End.
- A step with `when`: a condition badge on the node and a dashed "skip" edge around it to the next step.
- `repeat`: a framed group holding its inner steps in a lane, labelled "For each <as> in …  (max N)".
- `parallel`: branches as stacked lanes inside a frame between a split and a join node ("all" / "any").
- `wait` / `approval`: pause-shaped nodes.
- `on_failure`: its own lane below the main flow, entered from a "On failure" node.
- Each node keeps its **path** in the definition (`actions[3]`, `actions[2].branches[1].steps[0]`) and its run key
  (`action_index` — confirm how nested steps are indexed in the recorder before wiring replay; see Open questions).
- Reference edges: scan each step's strings for `${steps.X…}` / `${previous…}` and draw faint links to the producing node.
Unit tests: linear, when, repeat, parallel, on_failure, references, ttb vs ltr sizes.

## Rendering

`components/WorkflowCanvas.astro` + `lib/workflowCanvas/render.ts`: one SVG for edges/frames and absolutely positioned
HTML nodes (text, icons, focus, accessibility come free). Node: kind icon, label (`label` / kind name), step id chip,
condition badge, validation warning dot, run status ring (green / red / grey / amber waiting) and duration.
- **Pan / zoom / fit:** drag the background, wheel / pinch to zoom, a Fit button; keyboard: arrows move between nodes,
  Enter opens the panel. **Minimap** in a corner (a scaled copy of node boxes + the viewport rectangle).
- Styles follow the site rules: cards `--panel` on `--bg`, frames `--bg` with `--line`, status colours from the tokens.

## Node panel

A right-hand drawer (bottom sheet on phones):
- **Settings:** the step's fields in plain words, from the same labels the form uses (`workflowLabels.json`); "Edit in
  form" switches tab and scrolls to the step.
- **Condition:** the `when` in words ("Runs only when status is approved"), and on a replayed run whether it passed
  (skipped ⇒ it didn't).
- **This run:** status, duration, error, output (pretty JSON, truncated note).
- **What it received:** the step's resolved input (new — below).
- **Validation:** the editor's existing warnings for this step (`POST /api/automations/validate` results, keyed by path).

## Run replay and following runs

- **Run picker** in the canvas toolbar: the last ~20 runs (existing executions list), newest first; choosing one paints it.
- **Run from the canvas:** the existing Run (manual / test run) call; the canvas then follows that execution.
- **Following without new load:** ActivityToaster already polls the activity feeds every few seconds. It will dispatch a
  `marvin:activity` DOM event with each poll's new events. The canvas listens: an event naming this workflow's run
  (started / finished / waiting / failed) makes it fetch that run once and repaint. While a run is **in flight and the tab
  is visible**, the canvas also refetches that one run on each bell tick (step progress isn't in the feed), and stops when
  it finishes or the tab hides. Idle canvases make no requests.
- **Waiting runs:** a run parked on `wait` shows "until …" on the node; on `approval`, the node shows Approve / Deny
  (the same decide call the Approvals page uses, same permission check).
- **Runs that start on their own:** a feed event for a new run of this workflow while the canvas is open → it switches to
  following it (with a small "Following run started 12:04 — stay on the previous run" toggle so nothing jumps unasked).

## Backend additions

1. **Record what each step received:** `input_snapshot` (JSON, truncated like `output_snapshot`) on
   `automation_action_executions`, written by `services/automation/recorder.py` with the step's **resolved** parameters
   after `${…}` substitution (not raw secrets: reuse the redaction the recorder already applies to outputs; never record
   credential values or `{{SECRET}}` expansions). Alembic migration (nullable column; old runs show "not recorded").
   Expose it in `AutomationExecutionDetail.actions[]`. **SDK regeneration and release first** (release order).
2. **Activity events carry the workflow id and execution id** for run started / finished / waiting / failed (check what the
   feed already sends; add only what's missing).
3. Confirm the run detail returns nested steps' records with enough to map them to definition paths
   (`action_index` + container/branch/item index). If not, add `path` to the step record (same migration).

Tests: recorder writes a redacted `input_snapshot`; detail returns it; migration up/down; feed events include ids.

## Out of scope for release 1 (release 2+)

Editing on the canvas (add between, drag to reorder, edit in the panel, wrap in repeat / parallel, delete), multi-select,
copy/paste of steps, comments/notes on the canvas, a full live stream (SSE / LISTEN-NOTIFY).

## Open questions (to settle while building, not blockers)

- How the recorder numbers steps inside `repeat` items and `parallel` branches (`action_index` + `target_index` alone may
  not be enough) — decides backend addition 3.
- Whether a run's `definition_snapshot` should drive the replayed drawing (yes, if it differs from the current draft:
  replay the shape that actually ran, with a "this run used an earlier version" note).
- Performance ceiling: biggest real workflow today is ~15 steps; target smooth pan/zoom at 100 nodes.

## Steps

- [ ] Backend: confirm nested step indexing; add `input_snapshot` (+ `path` if needed) with redaction; migration; detail
      schema; activity event ids; tests (SQLite + Postgres); export OpenAPI, regenerate + release SDK first.
- [ ] `lib/workflowCanvas/layout.ts` + unit tests (ltr / ttb, when, repeat, parallel, on_failure, references).
- [ ] Renderer: SVG edges + HTML nodes, status rings, warnings, pan / zoom / fit, minimap, keyboard nav.
- [ ] Canvas tab in the builder + "Open canvas" on cards; switching tabs keeps the draft.
- [ ] Node panel (settings in words, condition, run output, received input, validation).
- [ ] Run picker, Run from canvas, follow via the bell's poll (`marvin:activity` event), waiting / approval actions,
      auto-follow toggle.
- [ ] Phone: ttb layout under 720px, bottom-sheet panel; check with real workflows (not empty pages).
- [ ] Docs page; frontend tests; astro check at baseline; check in Jared's browser before push.

## Review

(to fill in after building)
