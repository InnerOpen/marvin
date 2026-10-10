# Workflow Library

Copy-paste workflow recipes for Marvin, held to what the engine can actually run. Phase 1 (this folder) is the
code-backed audit, the catalogue and the validated recipes; phase 2 (2026-10-09) gives people the same recipes in the
app — see [In the app](#in-the-app-phase-2).

## Where things live (one store)

| What | Where |
|---|---|
| Recipe definitions `<id>.json` (pure workflow JSON, `{{setup}}` placeholders) and `<id>.vars.json` | `src/marvin/services/automation/recipes/` — ships with the package, so the AI authoring guide and `draft_workflow` read the same files |
| Catalogue metadata (status, prerequisites, side effects, dependencies) + the capability-gap registry | `src/marvin/services/automation/recipes/catalogue.json` |
| Loader (`offered`, `instantiate`, `missing_prerequisites`) | `src/marvin/services/automation/recipes/__init__.py` |
| Typed placeholder substitution | `src/marvin/services/automation/library.py` |
| Readable catalogue (rendered, never hand-edited) | [`catalogue.md`](catalogue.md) ← `scripts/render_workflow_library.py` |
| Engine audit / roadmap | [`compatibility-audit.md`](compatibility-audit.md), [`roadmap.md`](roadmap.md) |
| Tests | `tests/test_workflow_library.py` |

The AI authoring guide (`workflow_authoring_guide`, section `examples`) lists the recipes **this workspace can
run** — runnable status and every prerequisite met; a prerequisite is a provider by name or a capability (`{"capability": "notify"}` — any connected integration that can notify, Slack or Apprise; the notification recipes' steps name the capability, not an action) (a Buttondown recipe is not offered where no Buttondown
connection is enabled); `recipe=<id>` shows one in full with its setup variables. `draft_workflow(recipe=<id>,
vars={…})` instantiates it with typed substitution and saves it switched off. The guide's former hard-coded
examples are now recipes in the `Starter examples` category.

## In the app (phase 2)

People reach the recipes in three places, and **installing always goes through the workflow editor** — never a blind
Install button (the Blueprints gallery taught that cards alone teach nothing):

- **Workflow editor → Start from a recipe…** (`/automation/workflows`, `components/RecipeDialog.astro`): the workflow
  recipes, searchable, ready ones first and the rest greyed with what they need; choosing one shows what it does, when
  it runs, what it changes and its setup form (pickers of this workspace's names). **Use recipe** fills the builder;
  **Save** creates it switched off. `?recipe=<id>` opens the dialog on one recipe.
- **Workflow Library** (`/automation/library`, Settings → Automation): every recipe explained, filtered by category and
  readiness — *Ready here*, *Needs setup*, *Set up elsewhere* (configuration recipes, with a link to the page each part
  is set up on) and *Not possible yet* (ideas, with the capability each waits on). Workflow recipes link to the editor.
- **Where the question gets asked:** an event's page (Subscribe → *From the Library*) lists the recipes on that event,
  and a connected integration's card lists the recipes that need its provider.

Two admin endpoints back them (`routes/automations/automations_controller.py`):

| Route | What |
|---|---|
| `GET /api/automations/library` | `recipes` (each catalogue entry, slimmed, with `missing` — this workspace's unmet prerequisites; empty means ready), `capabilities` (gap id → name, priority, acceptance) and `refs` (entry types with fields, integrations, collections, webhooks, statuses — what the setup pickers offer). |
| `POST /api/automations/library/{id}/configure` | `{vars}` → `{name, definition, issues}`: the recipe filled in, **never saved**. `404` unknown recipe, `409` not usable here (an idea, a configuration recipe, a missing prerequisite — `detail` says why), `422` a missing or mistyped value (names the variable). `issues` are what the agent's draft check would flag (a webhook id this workspace doesn't have), shown in the editor, not blocking. |

The agent's `draft_workflow(recipe=…)` and `configure` share one path, `recipes.configure_for`, so both refuse and
fill in a recipe the same way. Picker logic (`lib/workflowLibrary.ts`) is pure and tested (`workflowLibrary.test.mjs`).
Provenance ("installed from recipe X") is not recorded yet.

## Statuses (exact definitions)

- **verified-current** — the configured JSON passes `draft_issues` (the gate behind `draft_workflow` and
  `POST /api/automations`) against the fixture workspace **and** runs end to end in
  `tests/test_workflow_library.py` on deterministic data with every external call mocked (integration
  provider, outgoing webhook HTTP, AI provider, scheduled-task handler); its side effects are asserted, and
  replay safety where the recipe claims it. `verification.mocked` names what was mocked.
- **supported-after-configuration** — everything it needs exists in Marvin today, but it is configuration
  rather than a workflow (an event subscription, Automation → Notifications settings, an outgoing webhook) and
  the fixture does not provision it; `supporting_objects[].configuration` is the exact API payload. Workflow-
  shaped recipes with this status still pass the validator in CI.
- **needs-adapter** — the engine could run it; no installed integration offers the external capability.
- **needs-engine-capability** — the engine lacks a primitive; `dependencies[]` names the gap and its acceptance.
- **concept** — no concrete path yet (none at the moment: every idea mapped to a gap).

Only the first two are `runnable`; only they ship recipe files or configuration; only they are offered to agents.

## Placeholders vs templates

- `{{lower_case}}` — a **setup placeholder**, declared in `<id>.vars.json` with a type. Substitution is JSON-
  aware and typed (`library.configure`): a whole-string placeholder takes the value with its type (integer,
  boolean, object), an embedded one takes its text (string-like types only). Never string replacement.
- `${…}` / `$event.x` — Marvin **run-time templates**, left untouched (the test counts them before and after).
- `{{UPPER_CASE}}` — a Marvin **workspace secret reference**, resolved when the step runs; left untouched.

## Adding a recipe

1. Write `src/marvin/services/automation/recipes/<id>.json` as `{"name", "definition"}` and `<id>.vars.json`
   as `{"recipe", "variables": {name: {type, description, example?}}}`.
2. Add its catalogue entry to `catalogue.json` (`shape: workflow`, a `status`, `recipe: "<id>.json"`,
   `setup_variables` mirroring the vars file, `verification.test`).
3. Add fixture values for its variables and an execution test in `tests/test_workflow_library.py`
   (`TestExecution::test_<id with underscores>`), or give it `supported-after-configuration`.
4. `uv run python scripts/render_workflow_library.py` to refresh `catalogue.md`.

## How CI validates

`tests/test_workflow_library.py` fails when: a recipe file isn't catalogued (or vice versa); a runnable recipe
has no recipe file/configuration; a `needs-*` recipe ships runnable JSON; a configured recipe fails
`draft_issues`; a `verified-current` recipe's named test doesn't exist or fails; setup substitution drops a
`${…}`; `catalogue.md` is stale. The authoring guide's examples are the same store, so an unrunnable recipe
can never reach an agent.
