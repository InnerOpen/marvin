# Approvals: edit the prompt before a paid call, Redo with changes, keep the prompt that made a result

Jared 2026-11-06 (Brain `10-Tasks/TASKS.md`, "approvals that show a prompt should let you edit it"), agreed 2026-11-16
with the follow-ons (cost estimate, approve many at once, a spend limit). This is phase 1. No cheap test mode.

## What a person sees
- A spend card (Approvals page, the inline card on a guided step) shows the prompt in a box above Approve / Deny,
  holding the exact text that will be sent. Change it and approve: the call gets the changed text. Leave it: the call
  is what it is today, byte for byte.
- The Keep / Redo card shows the prompt that was used. Change it and press Redo (it reads "Redo with changes"): the
  next try starts from the changed text (its spend card shows it; a pre-approved run uses it).
- The result (the generated picture, the sound, the take's audio) keeps the whole prompt it was made from, who approved
  it and whether the prompt was changed: on the asset page.
- Decided cards say "Prompt (changed)" and fold the original under it.

## Engine (InnerOpen/marvin)
1. `approval.fields`: up to 4 `{name, label, type: text|textarea, value, max_length, required}`. `name` is
   `[a-z][a-z0-9_]{0,39}`, unique; `value` a template; `max_length` 1..20 000 (default 20 000) limits an edit only;
   `required` (default true) refuses a blank edit. v1: text types only.
2. Park resolves each `value` (no strip: the text is the text the step after it would build) and keeps the list on
   the row (`workflow_approvals.fields`, JSON). A prefill over 20 000 characters fails the step (say so).
3. `POST /approvals/{id}/decide` takes `fields: {name: text}`. Approve only: deny, expire and stale give the prefills.
   422: an unknown name, not a string, over `max_length`, blank when required, or an edit that brings in a `{{NAME}}`
   or `${` the prefill did not have (a person's text is data: it must never become a Secret or a template).
   The row keeps what was approved (`field_values`, JSON) beside the prefills.
4. Output: `${steps.<id>.output.fields.<name>}` (the text as approved, else the prefill) and `.edited` (names changed).
5. `approval.approved_when` (a condition): when it holds the step does not ask; it goes on at once as `approved`
   (`auto: true`, nobody decided), `output.fields` = the prefills. For a run whose spend a page already approved
   (`entry.data.spend_approved == yes` today skips the step with `when`, which would leave the paid step nothing to
   read). It grants nothing a skip did not: an integration that requires a person's approval still refuses.
   `when` keeps its meaning (a skipped step gives no output): make-actor-sheet's two branches each read their own
   approval. A dry run shows the fields too.
6. Redo with changes: `approval.redo: "<choice>"` names the choice that makes it again. Approved with that choice and a
   changed field, the change is kept on the row (`carry`, JSON). The next approval on the same entry with a field of
   that name starts from it instead of its `value` (once: taken, then cleared; also by an `approved_when` one).
   No entry write, no new entry-type field, no extra workflow step. Keep with a changed prompt carries nothing.
7. The prompt that made a result: a generated picture's or sound's lineage (asset metadata) keeps the whole prompt
   (`prompt` / `text`, cap 2 000 -> 20 000) and, in a run resumed past an approval, `approval_id`, `approved_by`,
   `approved_by_name`, `approved_at`, and `prompt_edited: true` when the person changed a field.
8. Events: `workflow_approval_decided` carries `edited_fields` (names only); the text stays on the row (no push or
   log carries a prompt).
9. API read: `fields` (with the prefills), `field_values`, `edited_fields`, `redo`.
10. Frontend: one pure helper (`lib/approvalFields.ts`, node --test) builds the boxes' payload and the "changed"
    state; the Approvals page, the setup page's inline card and the entry page's approvals use it; Dashboard quick
    approve sends none (the prefills apply).
11. Docs: manual's approvals/workflow step reference; schema docstring.
12. Migration: `fields`, `field_values`, `carry` JSON columns (task py:migrate on a scratch SQLite, trimmed, a
    migration test).
13. SDK first: `chore(sdk)` schema PR on InnerOpen/marvin-sdk main (no npm release), then the Marvin PR.

## Studio (iWobble/ScreenplayStudio), after the engine is deployed
Each spend approval gets `fields: [{name: prompt, label: Prompt, value: <the text the call gets today>}]`; the call
reads `${steps.spend.output.fields.prompt}` (each branch its own approval in make-actor-sheet). The keep approval gets
the same field (value `${steps.spend.output.fields.prompt}`) and `redo: "Redo"`. A spend skipped when the page already
approved it (`when: spend_approved neq yes`) becomes `approved_when: spend_approved eq yes`, so the paid step still has
its prompt. Messages stop quoting the prompt (the box shows it). No new steps. Workflows: take-sound(-created), take-music(-created), make-take, remake-take,
take-still, make-master, make-actor-sheet (person, animal), make-cover, the master-prompt writer, any other spend.
test_package_prompts: the unedited prompt stays byte-identical. Version past main, recent.md, one line in marvin.md.

## Verify
pytest (approvals, engine, integration lineage, routes, migration; SQLite + Postgres-marked), node --test, ruff,
biome; a scratch Marvin (SQLite, own ports, a fake sound/image integration): edit in the inline card, approve, the
fake got the edited text; Redo with changes; deny; the asset's lineage.

## Review (engine PR)
- Built as planned, plus: a text carried from a Redo counts as changed in the result's lineage (`prompt_edited`); the
  asset page says "approved by …, who changed the prompt" and shows a sound's `text` as its prompt; the guided page does
  not redraw under a person typing in a card; the workflow editor offers `fields.<name>` / `edited` as outputs.
- Verified: pytest 7,623 passed on SQLite (full), the approval/lineage/migration tests on Postgres; node --test 1,761;
  ruff; biome and astro check as on develop (33 old errors). A scratch Marvin (SQLite, fake sound integration) in
  headless Chromium: the Approvals page and a guided setup's run step each showed the exact prompt, sent the edited
  text, "Redo with changes" started the next try from the change, a deny sent nothing, the sounds keep their prompts.
