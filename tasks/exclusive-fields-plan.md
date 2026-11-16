# One or the other: `exclusive_with`, and a file field that reads as text (`preview: "text"`)

Ask (Jared): a story keeps its script in the Fountain box OR the Fountain file, never both ("add the guard or hide the option if
one is already there"); and "I should be able to READ the script in Edit story, whether it's pasted or uploaded."

## Facts that decide it
- Every write sends the whole `data_json` (edit form, wizard `setData`, workflow `_merge`), so "what this write sets" is a
  comparison with the stored row. Rule: refuse when both are filled after the write and were not both filled before
  (create: before = empty). null, "", whitespace, [] are empty. A record already in both saves as it is.
- All entry writes go through `EntriesRepository.create/update` (REST, EntryService, workflows, AI authoring, public forms,
  seeds); AI suggestions go through `apply_fields`. Keep the check out of `ContentValidator.validate_content`
  (`collect.entry_problem` would start flagging old records).
- Package update adds keys a field lacks (`exclusive_with`, `preview` arrive); a changed helpText does not.
- The guided "Narrate a story" has both fields in one `details` form step (the old how/fountain_text/fountain_upload
  steps are gone since v180), drawn by SchemaForm: the live UI comes from the components.
- `/api/platform/assets/{id}/content` serves the bytes through the API, authorised: no new route, no OpenAPI change.

## Engine (Marvin)
- [x] `entry_type_schema.py`: `exclusive_with: list[identifier]` on every field (not itself, no repeats); `preview: "text"`
      on asset fields. A partner missing from the schema is ignored at write time, refused when a package is applied.
- [x] `content_validator.py`: `exclusive_pairs`, `exclusive_conflict(schema, data, before)`; repo create/update/apply_fields
      refuse with 422 naming both fields.
- [x] Frontend: `lib/exclusiveFields.ts` (pure, tested); SchemaForm wraps fields of a pair, a script blocks/unblocks live,
      warns when both were filled at load (a partner not on the same form is left to the save's refusal).
- [x] `wizardActions.ts` upload step: refuse before uploading when the partner holds something (no orphan asset).
- [x] `LinkedItemsField`: `preview: "text"` reader (lazy on open, 1.5 MB cap, line numbers, `#L17`), `lib/textReader.ts`.
- [x] Schema editor: "Use one or the other with" and "Show the file's text" inputs; docs.
- [x] Tests: pytest (schema, repo rule, workflow set_data, apply_fields), node --test, ruff, biome, astro check.

## Studio
- [ ] story `fountain`/`fountain_file`: `exclusive_with`, plain helpText, `preview: "text"` on the file; version +1 past main
      (after a9c7acc411217e882's bump); playbook references equal; package test.

## Verify
Scratch Marvin (SQLite, own ports, scratch workspace only): type text -> file blocked; clear -> back; choose file -> text
blocked; both from old data -> warning; API write of both -> 422; wizard details step; upload step refusal; reader with a
250 KB / 4,600-line file, open/closed light/dark.

## Review (engine)
- Built as planned, plus: the guided form step says the refusal in its own words before it writes (`writeRefusal`), as the
  API's raw 422 text would otherwise show; a Read-the-file disclosure marker; schema editor inputs keep both settings.
- Wizard decision: refuse with a message (no step's words say it replaces the other field): the upload step before uploading
  (no asset left behind), a form step before saving. The Studio's Narrate a story has both fields on one `details` form,
  where the live closing already prevents it.
- Verified: pytest (new file + related suites; full SQLite suite green), node --test 1,790, ruff, biome, astro check (33 old).
  Scratch Marvin (SQLite, mini package in the scratch workspace only) in headless Chromium: text closes the file (and back,
  whitespace counts as empty), a chosen file closes the text (and back), both from old data warn on both and save as they are,
  API create/patch of both 422, a text-for-file swap saves, guided details/paste/upload steps, the reader with a 238 KB,
  4,600-line BOM+CRLF file (drawn in ~200 ms on open, HTML shown as text, #L17), light/dark, 390 px no sideways scroll.
