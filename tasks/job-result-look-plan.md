# One look for a job's result on every guided step

Jared (2026-11-16): "the style of these output should be easier to read ... build it into the step, make sure any results from
a job look the same on all guided steps". Mock he liked: claude.ai artifact AfQjCVzG6gHF6hW2fGbead (Check the Fountain report,
chapter plan).

## Where job text shows in a guided step today
- `[slug].astro` run step, `report`: an entry field the step names (`step.report`), pre-wrapped in `aside.showcard.report`.
- `[slug].astro` run step, `jobSays`: the worker job's `log` ("What the job said": `jobLead` + "Show all of it").
- Not job output, left as they are: `run-state` lines (status, live-polled), gallery `workingOf` lines, approval cards and
  "Earlier answers" (approval text; another agent is changing the approval UI).

## Design
- `frontend/src/lib/jobResult.ts`: pure parser, text → blocks. Consumes lines in order; every line is taken by exactly one
  block, anything it does not recognise becomes a plain-text block in its place (shown pre-wrapped as today). Returns data
  (segments `{text, code?}`), never HTML; the component renders with JSX (no `set:html`).
  Blocks: verdict (tone good/warn/bad/plain) with its sub-lines, stats (an `N things, N things and N things` line), stamp
  (dated `YYYY-MM-DD HH:MM UTC · …` header), findings sections (`Title (N): said.` + indented `line N: …` rows, rows grouped
  generically by their wording with the quoted bits taken out; `name → handle` lists as pairs), chapter table
  (`  N  Name  scenes a–b · ~N pp · N beats · N lines · cast`), pairs (`Speakers: a → b; …`), made-lists (`N scenes (a, b…)`
  where the list has exactly N items), lack (`The story still lacks: …`), sheet-log rows (dated `· add · from … · +N beats`),
  text (anything else).
- A failed job: the last paragraph is the verdict (bad), as `jobLead` did.
- `frontend/src/components/JobResult.astro`: one card for both places: head (label + optional "Open … to edit it" link),
  blocks in order, long lists folded in their own `<details>`, and "The job's own text" `<details>` always there.
- Tokens only from global.css (`--panel`, `--panel-2`, `--line`, `--ink`, `--muted`, `--accent`, `--warn`, `--good`,
  `--color-error`, `--radius`), soft fills by `color-mix`; the table scrolls in its own box; no page scroll at 390 px.

## Steps
- [x] `lib/jobResult.ts` + `jobResult.test.mjs` (round-trip: every input line lands in exactly one block, in order; the three
      real samples; a `Fix before importing` case; junk text; failed and skipped logs)
- [x] `components/JobResult.astro`; `[slug].astro` uses it for `report` and `jobSays` (conditions unchanged, polling untouched)
- [x] Scratch Marvin (SQLite, own ports, own mini package in the scratch workspace only) seeded with the real texts; headless
      Chromium shots desktop/phone × light/dark in `~/.claude/jobs/d49539a2/tmp/shots/`
- [x] node --test, biome, astro check (33 old errors), ruff/pytest only if Python is touched
- [ ] PR, squash merge when green, wait for Promote
- [ ] Packages: say which steps use the look; propose a package change only if one is needed

## Review
- One parser + one component; `[slug].astro` uses it for both `report` and `jobSays` (conditions and live polling unchanged).
  `jobLead`/`shortText` (runList.ts) had no other user and went with the old block.
- Verified on a scratch SQLite Marvin with the real Check the Fountain report, chapter plan and sheet log, plus a no-report log, a
  skipped job, a failed job and a one-line log: desktop 1280 and phone 390, light and dark, no sideways page scroll; filter chips work.
- Packages: Studio's 8 run steps (3 with reports: fountain_check, split_plan, sheet_log; 5 showing the job's log when they leave a
  worker job) use it with no package change. Grace's gallery wizard has no run step; Storyworld's package has playbooks only (its
  stories go through Studio's Narrate a story).
