# Workflow Library

Copy-paste workflow recipes for Marvin, held to what the engine can actually run. Phase 1 (this folder) is the
code-backed audit, the catalogue and the validated recipes; the Library UI / install flow is phase 2.

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
run** — runnable status and every prerequisite met (a Buttondown recipe is not offered where no Buttondown
connection is enabled); `recipe=<id>` shows one in full with its setup variables. `draft_workflow(recipe=<id>,
vars={…})` instantiates it with typed substitution and saves it switched off. The guide's former hard-coded
examples are now recipes in the `Starter examples` category.

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
