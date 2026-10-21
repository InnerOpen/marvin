# Workflows page: organised like the Workflow Library (2026-10-21)

Jared: "I think 'Workflows' is going to get pretty messy. I wonder if we can organize so when many workflows exist, they're
easy to find." / "It should probably be similar to workflow library."

## Today
`/automation/workflows` is one flat list of large cards in creation order, each with seven buttons (Run, Dry run, Runs,
Disable, Edit, Copy JSON, Delete). No search, filters or grouping; an "Installed by <integration>" badge is the only hint of
where a workflow came from. Every integration adds 3–4 workflows (Buttondown 5, Cloudflare 3, n8n 1–3, Social…), so the list
grows fast and a person's own workflows get lost among them.

## The shape (same parts as the Workflow Library page)
- **FilterBar** at the top (the Library's component): search over name, slug and the trigger summary ("When a Bench Note is
  published"), plus three filters:
  - **From**: All · Yours · From the Library · each connected integration (by name).
  - **Status**: All · On · Off.
  - **Starts**: All · When something happens (events) · On a schedule · From a webhook · By hand.
- **Sections with headings**, in this order, each drawn only when it has workflows and hidden when filters empty it (the
  Library's `cat-group` behaviour):
  1. **Yours**: made by a person, not from a recipe or an integration.
  2. **From the Library**: made from a Workflow Library recipe (`source_recipe`), with the recipe's name and an
     "update available" note when the recipe changed (the data exists: `source_recipe_version`).
  3. **One section per integration** (`source_integration_id`), headed by its logo and name, e.g. *Buttondown · 5 workflows,
     4 on*. Integration sections sort by name.
  Within a section: enabled first, then by name.
- **Compact cards** like the Library's: name, the one-line trigger summary, an On/Off switch, and the last run's outcome when
  known; the rarely used actions (Dry run, Runs, Copy JSON, Delete) move into a "⋯" menu, keeping **Run** and **Edit**
  visible. The "Installed by" badge goes (the section says it).
- **Empty filter result**: "No workflow matches. Try another search, or show all." (Library wording).
- **Links keep working**: `?workflow=<id>` (and the Library's "set up from this recipe" handoff) shows that one card whatever
  the filters, scrolled into view — as the Library does for `#recipe-<id>`.
- **Phone**: the FilterBar wraps, cards stay compact, the "⋯" menu opens as a sheet.
- The chosen filters are remembered per browser (localStorage, wrapped in try/catch), like other list pages.

## Data
Everything except the last run is already on each workflow in the list response (`source_integration_id`,
`source_blueprint`, `source_recipe`, `source_recipe_version`, `enabled`, `definition.trigger`). **Last run** (status and
time) is a small API addition: `last_run_at` / `last_run_status` on the list rows, from the newest execution per workflow in
one query. That changes the OpenAPI, so the TS SDK is regenerated.

## Code
- `frontend/src/lib/workflowList.ts` (new, like `workflowLibrary.ts`): `groupWorkflows`, `matches` (search + filters),
  `triggerKind`, section titles and counts — pure, with `node --test` tests.
- `pages/automation/workflows.astro`: render sections from it; move the list rendering out of the 2,800-line page script where
  practical (the builder stays put).
- Backend: the last-run fields on the list.

## Not in this pass (later, if wanted)
- Folders or tags for your own workflows (needs a field on the workflow; a migration).
- Bulk actions (turn several off).
- "Edited in this workspace" vs "Update available" for integration workflows: that is the blueprint edit-protection item
  already on the backlog, and it would show in these integration sections.

## Decisions (recommendations; Jared to confirm)
1. Section order Yours → From the Library → integrations.
2. Sections always expanded (as in the Library), with the filters doing the narrowing; no collapse state to remember.
3. Run and Edit stay on the card; the rest go in "⋯".
4. Include the last-run outcome (small API change) in this pass.

## Tests
Grouping and ordering (yours / library / per integration, enabled first), search and each filter, the linked card shown
despite filters, empty result; the last-run fields (newest execution, none yet, workspace isolation) on both engines;
frontend tests and astro check at baseline; a browser check at desktop and phone width.
