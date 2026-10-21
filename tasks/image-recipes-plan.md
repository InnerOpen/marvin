# Image recipes: suggest an image, and create one for an entry (2026-10-21)

Jared: "attach that as a recipe … available for anything that can create an image … and then put it into the library" /
"we should be able to pass an entry and say, hey, create an image around this entry and add it to this entry" / "I can
also add it to an MCP endpoint and then essentially request that the MCP create the image too" / "all through the
workflow" / "go on the image recipes, plan it".

## Why
Mash & Burn's Bench Notes should always carry an image. Today that is two hand-built workflows on one workspace
(`bench-note-image-suggestion`, `bench-note-generate-image`) and only OpenAI can fill the second. Agents can't generate
images themselves (no tool calls an integration action), and that boundary stays: **everything goes through a workflow**,
which an admin approves once and anyone — a person, an agent (`run_workflow`), an MCP client (`marvin_run_workflow`) —
then runs, with one set of permissions and one run history.

## The two recipes (core, in the Workflow Library)
Both live in `src/marvin/services/automation/recipes/` (`<id>.json` + `<id>.vars.json`) with catalogue entries, so the
Library, the authoring guide and `draft_workflow(recipe=…)` all offer them.

### 1. `suggest-entry-image` — "Suggest an image for new entries"
- **Trigger:** `entry_created`. **Conditions:** the entry is of `{{entry_type}}`; it has no image; it has no
  `{{suggestion_key}}` yet (`not … exists`).
- **Steps:** an AI `custom` operation reads the entry (title, summary, body field `{{body_field}}`) and returns one or two
  sentences describing the photo to take — the subject the entry is actually about, angle, focus, light, no text or
  logos, no people's faces, nothing the entry doesn't mention — styled by `{{style_note}}`; then `set_metadata`
  `{{suggestion_key}}`.
- **Variables:** `entry_type` (entry_type_slug), `body_field` (field_key, default `body`), `style_note` (text, optional,
  e.g. "documentary workshop photo, warm light"), `suggestion_key` (text, default `image_suggestion`).
- **Prerequisites:** AI available for workflows. No integration.

### 2. `create-entry-image` — "Create an image for this entry"
- **Trigger:** manual, with one input `entry` (type entry, required) — so the Run button asks for the entry, an agent or
  MCP client passes it (`run_workflow` inputs `{entry: <id or slug>}`), and the run acts on that entry.
- **Conditions:** the entry is of `{{entry_type}}` (left blank ⇒ any type).
- **Steps:**
  1. *Only when the entry has no `{{suggestion_key}}`* (a step `when`): the same AI step as recipe 1 writes the prompt from
     the entry, and saves it as `{{suggestion_key}}`, so a later run reuses it.
  2. An integration step on `{{image_integration}}` with **capability `image.generate`** (not a named action — any image
     provider qualifies), prompt `{{style_prefix}} ${entry.metadata.<suggestion_key>}`, `count: 1`, **`attach_as:
     {{role}}`** (default `hero`). The picture is kept as an asset and linked to the entry (existing image-capability
     behaviour).
- **Variables:** `image_integration` (integration_slug — the Library lists only connections with `image.generate`),
  `entry_type` (entry_type_slug, optional), `role` (text, default `hero`), `style_prefix` (text, default "Documentary
  photograph, natural light, no text, no logos, no people's faces."), `suggestion_key`, `body_field`.
- **Prerequisites:** a connection with capability `image.generate` (OpenAI Images today); AI available (for step 1).
- **Description** says plainly: made by hand from the Run button, by an agent, or over MCP; it spends image credits on
  the chosen connection; the image lands on the entry for review before anything is published.

## Agents and MCP
No new agent tool. Agents already have `run_workflow` (in-app and both MCP servers); the recipe's single `entry` input is
what they pass. The recipe's catalogue description and the workflow's own description tell an agent when to use it ("the
maker asks for a generated image for an entry"). The `bench-note-writing` Playbook gets one line pointing at the
installed workflow (Mash & Burn).

## Fix on the way: the validator and `not` groups
`POST /api/automations/validate` warns "Condition has no field" for `{"not": {...}}` (and `any`/`all`) condition groups the
engine evaluates fine — and these recipes use them (workflow conditions and the step `when`). Teach the validator about
groups (recurse) so the recipes validate clean. Already on the backlog; done here.

## Mash & Burn afterwards
Replace the two hand-built workflows with ones installed from these recipes (same behaviour, now listed under **From the
Library**, and "update available" when the recipes change): suggest on (entry type `bench-note`), create installed with
`gpt_image`, off until Jared switches it on. Delete the hand-built ones after.

## Tests
- Recipe files: load, instantiate with typed variables, structural validation clean (with the validator fix), catalogue
  entry complete (prerequisites: capability `image.generate`; AI), rendered `catalogue.md` regenerated
  (`scripts/render_workflow_library.py`); the Library offers recipe 2 only when an `image.generate` connection exists.
- Engine, with a fake image provider declaring `image.generate`:
  - recipe 1 writes the suggestion for a new entry of the type; skips one with an image or a suggestion; skips other types;
  - recipe 2 with an existing suggestion → one generate call with that prompt, asset kept, attached in `role`;
  - recipe 2 without a suggestion → the AI step writes and saves it first, then generates;
  - recipe 2 run through `run_workflow` with `{entry: …}` (the agent/MCP path);
  - workspace isolation; the run is recorded.
- Validator: group conditions validate without warnings; a group with an empty child still warns.
- Full SQLite and Postgres suites; frontend untouched unless the Library card needs a capability hint.

## Order and size
One pass, one push: validator fix → recipe 1 → recipe 2 → catalogue + docs (`docs/workflow-library`, the manual's
workflows page) → tests → then Mash & Burn's swap (data, by API, after the release). Small: two recipe files, catalogue
entries, a validator change, tests.

## Decisions (recommendations)
1. Core recipes keyed to the `image.generate` capability, not an OpenAI-plugin recipe — any image provider qualifies.
2. The prompt is the entry's saved suggestion; recipe 2 writes one first when missing, and saves it for reuse.
3. Recipe 2 is manual (Run button / agent / MCP); no automatic generation anywhere — image credits are spent only on
   request.
4. Fix the `not`-group validator warning as part of this.
5. Swap Mash & Burn's hand-built workflows for recipe-installed ones after release.

## Review (built 2026-10-21, branch `wl/image-recipes`)
Built as planned, with these differences:
- **Approval step in recipe 2.** OpenAI Images' `generate` is approval-gated, and capability routing skipped every gated
  action except the public-facing social ones — a bare `capability: "image.generate"` step could never run on it. Added
  `alert_routing.APPROVABLE_CAPABILITIES` (`GATED_CAPABILITIES` + `image.generate`): such a step runs on a gated action once
  the run is past an Approval step, and `capabilities_of` now reports it so the Library readiness check and the step
  validator see the connection. The draft check (`_image_generate_issue`) asks for the approval step. Recipe 2 therefore
  asks an editor to approve before spending credits (one click on the Run button / in approvals).
- **No `body_field` variable, no `entry_type` on recipe 2.** The custom AI step's default `see: item` already gives the AI the
  whole entry; recipe variables have no optional/blank support, and a manual run on a chosen entry needs no type guard.
  Recipe 1: `entry_type`, `style_note`, `suggestion_key`. Recipe 2: `image_integration`, `role`, `style_prefix`,
  `style_note`, `suggestion_key`.
- Guide-size budget in `test_guide_offers_the_recipes_this_workspace_can_run` raised 16,500 → 17,000 (two more recipes).
- Not done (data, after release): Mash & Burn swap and the `bench-note-writing` Playbook line.
