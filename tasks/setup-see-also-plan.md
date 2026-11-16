# A step links to another setup's step, and the way back

Ask: Narrate a story's "Sounds: are these read right?" should point at Sounds for a story (with the story chosen), and that setup
should offer a clear way back to the very step it came from.

## Design
- Step key `see_also` (1..3): `{label, setup, step?, carry?: {<target key>: "<own key>" | "<own key>.<field>"}, text?}`.
  `key.field` reads a field of the chosen entry (as `prefill` does), so Sounds → Narrate can carry the story's world too.
- Link = `stepHref(target, carried, step, {back: <this page's own address>})`; the back value is the source path rebuilt by
  `stepHref(source, ctx without back, stepId)`.
- `back` is a page-own parameter (OWN_PARAMS, RESERVED_KEYS): never read as a choice. The page puts the checked marker into ctx
  after `checkedCtx` (one line), so every stepHref on the page (stepper, Continue, Previous, Change, redirects after a POST,
  wizardEmpty links) carries it without touching each call site. Leaving the setup (any non-setup link) drops it.
- `parseBack(value)`: ≤1500 chars, `/workspace/setups/<slug>` only (URL parsed against a dummy origin; origin must stay), params
  re-read with readCtx (drops nested back/notice/run), step id shape-checked; the href shown is rebuilt, never echoed.
- `WizardCameFrom.astro`: fetches the source setup (getWizard: unseen/missing → nothing), banner "You came from <name>, step N
  (“title”). ← Back to it". `WizardSeeAlso.astro`: fetches each target, missing → no link.
- Validator (`_check_see_also`): list ≤3, unknown keys, label/text length, setup slug, step id shape, carry keys/values.

## Steps
- [x] wizard.ts helpers + node tests
- [x] components + 2 small includes in [slug].astro
- [x] validator + pytest, docs
- [x] scratch Marvin + headless Chromium walk (link, banner on several steps, reload, Back, bad back)
- [ ] Marvin PR → merge → Promote; Studio package PR (see_also links, version bump)

Also (from Jared, same PR): a step's `show.empty` ({field: line} or one line) states an empty field instead of leaving it out, so
Narrate's Preview and Make steps say "Chapters to bring in: All the chapters".

## Review
- Scratch SQLite Marvin + Studio v191 on a scratch workspace, headless Chromium: link → Sounds for a story on "What the story
  calls for" with the story chosen; banner on 6 steps, after Continue, Previous, a sent form and a reload; Back lands on Narrate
  step 11 with world and story; six bad `back` values ignored or rebuilt; reverse link carries the story's world; show card reads
  "All the chapters". node --test, pytest test_wizards, ruff, biome lint, astro check (31 errors, none new).
