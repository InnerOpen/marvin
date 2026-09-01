# Forms → submittable entry types

Fold "forms" into entry_types: a form **is** a submittable entry type; a submission **is** an
entry of that type (`status="inbox"`, `created_by=null`). Reuse the field schema, the visual
schema builder, entry storage, the Entries list/detail, validation, and the event bus. The only
net-new piece is a public schema→form renderer (ported from the admin's `SchemaForm`).

Decisions (locked): renderer lives in **MarvinRenderersCore**; keep the submit URL
`/api/publish/{ws}/forms/{slug}/submit`; **no new field kinds** — infer `email`/`tel` input from a
`text` field's pattern/constraints in the renderer.

Notifications: keep emitting the scoped **`form_submission_received`** event from the submit path
(NOT `entry_created`, which fires for every entry and would over-notify). The existing template +
subscription keep working unchanged. `entry_created` still fires from `EntryService.create` for
other reactors.

A submission is an entry in the **inbox** (`status="inbox"`) — indistinguishable from any other
entry. No `FormSubmissions` row, no `Forms` row. Target end-state: **the `forms`, `form_submissions`,
and `form_rate_limits` tables are gone**; everything is `entry_types` + `entries`.

## Phase 1 — Backend: the collapse (forms become inbox entries) — DONE
- [x] `schemas/platform/entry_type_rendering.py`: added `SubmissionConfig` (success_message,
      redirect_url, enable_honeypot/honeypot_field, enable_captcha/captcha_provider/captcha_secret_ref,
      rate_limit_*, notify, title_template); hung off `CapabilitiesDefinition.submission`.
- [x] `core/permissions.py`: added `WRITE_PUBLIC_ENTRIES = "write:public_entries"`.
- [x] Public submit path (`routes/publish/forms_controller.py`): resolves `{slug}` against a
      **submittable entry type** first → honeypot → validate `data_json` against the type schema →
      `EntryService.create` (`status="inbox"`, `created_by=None`) → emit scoped `form_submission_received`.
      Legacy `Forms` fallback kept as a TRANSITIONAL bridge (removed in Phase 3).
- [x] Title derivation (`_derive_submission_title`: config template → first text value → type + time).
- [ ] Tests: submittable-type submit creates an inbox entry; validation rejects bad data (400);
      honeypot → silent success, no entry; `form_submission_received` fires.
- [ ] DEFERRED to Phase 1b: rate-limiting (needs `form_rate_limits.form_id` generalized to a
      subject_id, since it FK's to `forms.id`) + CAPTCHA (needs secret-ref resolution). Honeypot is
      the current bot gate.

## Phase 2 — Frontend: packaged schema→form renderer (MarvinRenderersCore)
- [ ] Port the admin `SchemaForm.astro` + `schema-fields/*` into MarvinRenderersCore as a public,
      unstyled `FormRenderer` consuming `EntryTypeSchemaDefinition.fields`; emit plain field names
      (not `dataJson.<key>`); infer input type from field type + pattern; drop asset/resource kinds.
- [ ] Expose the type's schema to the site (publishing API already serves entry-type schema).
- [ ] `mashandburnco/src/pages/contact.astro`: replace hand-coded fields with `<FormRenderer>`;
      keep the honeypot + `/api/forms/{slug}` POST + progressive-enhancement script.

## Phase 3 — Remove the forms tables entirely (no Forms in the DB)
- [ ] Migrate the 2 live forms (contact, newsletter) → submittable entry types (same slugs, same
      fields via schema). Discard the 3 existing test submissions (all throwaway).
- [ ] Verify the live site end-to-end against the entry-type path.
- [ ] Remove the legacy fallback in the submit path; delete `Forms`, `FormSubmissions`,
      `FormRateLimits` models + `FormRead`/`FormCreate`/`FormUpdate`/`FormSchemaDefinition` schemas +
      platform forms controller + `validate_form_submission` (converged into `validate_content`).
      NOTE: this deletes `FormRead`, so the earlier #5 serialization fix becomes moot — fine.
- [ ] Alembic migration to drop `forms`, `form_submissions`, `form_rate_limits`.

## Review
(to be filled in as phases land)
