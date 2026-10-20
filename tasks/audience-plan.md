# Audience: form submissions and newsletter signups (2026-10-20)

Jared: "Form Submissions should live in Audience for sure. Signups should live there too. And potentially be internal
entries? Newsletter entries are content and should live in Entries... but be acted upon by the functionality that
Buttondown integration provides." Confirmed: a per-form switch, defaulting to Audience. "yes to both, push it and plan it".

## The split
| Kind | Lives in | Acted on by |
|---|---|---|
| Newsletter issues (what you write and send) | Entries (unchanged) | Buttondown: publishing an issue emails it |
| Signups (someone joins the list) | Audience › Subscribers, internal entries | Buttondown: subscribe on signup; confirmed/unsubscribed status |
| Form submissions (people writing to you) | Audience › Submissions, internal entries | review, the new-submission trigger, spam protection |
| Forms that make content (testimonials, "share your project") | Entries › Inbox (as today) | normal review and publish |

```
AUDIENCE    Social ▾        Inbox · Instagram · Mastodon
            Submissions ▾   Contact (12 new) · Workshop enquiry (3)    ← one entry per Audience form
            Subscribers     ← signups: pending · confirmed · unsubscribed · problems
```
Each appears only when something feeds it: an Audience form for Submissions, a signup form for Subscribers, a social
network for Social.

## 1. Where a form's submissions go (core)
- **New submission setting** on a submittable entry type: `capabilities.submission.destination: "audience" |
  "entries"`, defaulting to `audience`.
  - Audience makes the type **internal**: the existing internal flag (`services/entry_listing.py`) treats a
    submittable type with destination audience as `listed: false`. Out of All entries, the status lists and their
    counts, search, the AI index and publishing.
  - Entries keeps today's behaviour (Entries › Inbox for review).
- **Signup forms:** a second setting, `capabilities.submission.kind: "message" | "signup"` (default message), marks a
  form whose entries are newsletter signups. It decides Submissions vs Subscribers. Buttondown's `signup_type` parameter
  names such a type, so applying Buttondown's blueprint can set it.
- **Existing submittable types** become Audience (Jared: nothing existing matters). The newsletter signup type gets
  `kind: signup`, if it's the one Buttondown was applied with.
- The entry type editor's Submission settings get both switches with one line of explanation each.
- **Unchanged:** the submission itself. It's still an entry plus its `form_submissions` record (spam verdict); a
  suspicious one is `needs_review`, a clean one `inbox`; the `form_submission_received` and entry triggers fire as
  now; match-field (one entry per person) and notifications work as before. Workflows that name the type explicitly
  (Buttondown's) still find internal entries.

## 2. Audience › Submissions (core)
- Sidebar: Submissions ▾ with one child per Audience message form (the type's name and icon), each with a new count
  (`inbox` and `needs_review`).
- Page `/workspace/audience/submissions` (all forms) and `/workspace/audience/submissions/<type slug>`:
  - compact rows: who (the name or email field when the schema has one), a text excerpt, the form, when, and
    status: New (inbox), Suspicious (needs_review, with the protection verdict), Handled (archived);
  - tap a row to open it: every field, the spam verdict and source (IP, referrer, user agent from `form_submissions`),
    and actions: Mark handled (archive), Not spam (back to new), Delete (Trash), Open as entry (the entry editor,
    returning here), "Make this content" (move it to an Entries form? probably not; keep it simple);
  - filters: form, status, search.
- Phone: compact rows, tap to open.
- **Empty state:** no Audience form means Submissions isn't drawn at all.

## 3. Audience › Subscribers (core)
- Shown when a form has `kind: signup`.
- Page `/workspace/audience/subscribers`: one row per signup entry (one per reader with the match field). Email, name
  if any, signed up when, and status, read from the entry status as Buttondown mirrors it: Pending (inbox),
  Confirmed (published), Unsubscribed (archived), Problem (needs_review, with the review reason, e.g. Buttondown
  refused it). Counts per status at the top, filters, search.
- Actions: open the entry; delete (Trash). Subscribing and unsubscribing stay Buttondown's (its workflows and webhook),
  shown as a note when Buttondown is connected.
- No mailing-list integration connected: Subscribers still lists signups (a site can collect them without Buttondown),
  with a hint to connect one.

## 4. Buttondown plugin (release)
- Stop shipping the two collections ("Confirmed subscribers", "Unsubscribed"); Subscribers replaces them. Keep the
  webhook and the workflows.
- When applying, set the chosen `signup_type`'s `submission.kind: signup` (and `destination: audience`), if core
  lets a blueprint set those (today it can add fields, not change submission settings; add a narrow core hook if
  needed, else document the manual step).
- README and guide updated.
- **Core cleanup:** remove those two collections in existing workspaces if they're still the plugin's smart
  collections (same pattern as the Instagram leftovers migration).

## 5. Tests and docs
- **Tests:**
  - the destination flag making a type internal, across every list/count/search/index path, reusing
    `tests/test_internal_entry_types.py`;
  - the entries destination unchanged;
  - submissions and subscribers APIs, statuses and actions;
  - roles (EDITOR+ read and act; ADMIN for type settings);
  - the sidebar summary showing each item only when fed;
  - the Buttondown workflows still finding internal signup entries;
  - the cleanup migration.
- **Docs:** a manual page "Audience" (Social, Submissions, Subscribers); forms docs (the two settings); the
  Buttondown integration docs.

## Phases
1. Core: the destination/kind settings + internal + Submissions + the Audience summary. Ship.
2. Subscribers + the Buttondown release + the collections cleanup. Ship.

## Review, phase 1 (2026-10-23)
- **Decision (Jared, during the build): internal is one flag, and it is visible.** A type is internal only when
  `capabilities.listed` is false. Not by slug (`INTERNAL_SLUGS` is gone, backend and frontend) and not by destination.
  - Migration `a1d7c35e9f20` (data only, downgrade is a no-op) sets `listed: false` on every `social-auto-reply` and
    `social-reply-log` type and on every submittable type whose `submission.destination` isn't `entries`, and removes what is
    derived from the flag for their entries (smart-collection membership except the Trash, embeddings).
  - The `destination` setting stays and decides where submissions are read (Audience › Submissions lists Audience-destination
    forms whether or not they are listed). Choosing it **sets `listed` as a default** on create and update (audience: false,
    entries: true; a type that stops being an Audience form is listed again; a `listed` the caller changed in the same request
    wins): `services/entry_listing.with_destination_default`, applied by `EntryTypesRepository`. After that `listed` is toggled on
    its own; an Audience form switched to listed shows in both places.
  - UI: **Show in content lists** switch on the entry type editor (with "Used by Audience › Submissions" and the like), an
    **Internal** badge with a reason tooltip on the Content model list. Whoever can edit entry types edits it.
- **Built:**
  - Settings: `capabilities.submission.destination` (audience | entries, default audience) and `kind` (message | signup, default
    message) in `SubmissionConfig` (invalid values are refused on save), and in the editor's Submission settings with one line each.
    Nothing stores an explicit value today, so existing forms are audience and message by the default; the migration above only sets
    the `listed` flag.
  - Audience API under `/api/groups/audience` (EDITOR and above): `GET /summary`, `GET /submissions`, `GET /submissions/{id}`,
    `POST /submissions/{id}/handled`, `POST /submissions/{id}/reopen`, `DELETE /submissions/{id}` (to the Trash). Actions are
    ordinary entry status changes, so events fire as in the editor.
  - Sidebar: the Audience heading is drawn when Social or Submissions has something; Submissions folds to one child per Audience
    message form (name, icon, new count) and an "All submissions" link when there are several. The counts follow an action.
  - Pages `/workspace/audience/submissions` and `/workspace/audience/submissions/<form slug>`: compact rows (who, excerpt, form,
    when, status badge), a detail dialog (fields, spam check, source, actions, "Open as entry" with `?return=`), form, status and
    search filters, an empty state. Phone: the same compact rows, tap to open.
  - Dashboard: `attention.audienceNew` and a "New form submissions (Audience)" line; the inbox and needs-review lines count only
    listed entries, so nothing is double counted. The app icon badge is unchanged (it counts the entry inbox, as Social's comments
    aren't in it either).
  - Docs: the Audience manual page, the forms page, the Social page's internal-type section, glossary and index.
- **What differs from the brief:**
  - There is **no `form_submissions` record** for a form submission: the public route writes only the entry, with the protection's
    reasons, IP, user agent and referrer on `metadata_json.submission` (`form_submissions` is the legacy Forms table, FK to `forms`).
    So the verdict is `{flagged, reasons}`, with no score or flags, and the source comes from the entry. The API reads that.
  - **IP:** an ADMIN or above sees it whole; an EDITOR sees `203.0.113.x` (IPv6: first three groups). That is the Audience view only:
    `metadata_json.submission.ip_address` is on the entry itself, which every member reads through the entries API. Hiding it
    there is a separate change (open).
  - The migration, not the default, flags existing forms: the default alone no longer makes a type internal.
  - A pre-existing editor bug was fixed on the way: a cleared Submission settings box was saved as `null`, which the API refuses
    for `honeypotField` (422), so saving any form that never set a honeypot name failed. A cleared box now drops its key.
- **Tests:** `tests/test_audience_submissions.py` (settings and validation, the flag-only rule, the destination default, the listed
  toggle across lists, collections and the index, summary, list filters, actions, roles, IP, dashboard),
  `tests/test_migration_audience_submissions.py` (both engines), `tests/test_internal_entry_types.py` (flag only; a listed rule type
  shows everywhere while the engine and Rules still work), frontend `audience.test.mjs` and `entryTypeListing.test.mjs`.
  Backend 5771 passed on SQLite, 5804 on Postgres; frontend 850; astro check stays at 34 errors, `astro build` ok.
- **Open:**
  - Signup forms (kind signup) are listed nowhere in Audience until phase 2 (Subscribers); they and their entries are still found by
    type, so Buttondown's workflow keeps working. Their pending and problem counts aren't on the dashboard yet either.
  - The entries API still returns a submission's whole IP to any member (see above).
  - The app icon badge doesn't include Audience submissions.
  - The editor's Back link for an Audience form's entry opened without `?return=` goes to All entries.

## Review, phase 2 (2026-10-24)
- **Built (core):**
  - **Audience › Subscribers.** Shown when any submittable type has `submission.kind: signup`, **whatever its destination** (the kind alone
    decides; the editor's Signup setting is visible for both destinations now). API under `/api/groups/audience`, EDITOR and above:
    `GET /summary` (`signups` now carries `pending`, `confirmed`, `unsubscribed`, `problem` and `waiting` = pending + problem, per form too),
    `GET /subscribers` (filters `form`, `status` (repeatable), `q` over email/name/title, `since`/`until`, paging, newest first; `counts` follow
    the form filter; `integrations`), `GET /subscribers/{id}` (fields, source with the IP masked below ADMIN, status history from the event
    log), `DELETE /subscribers/{id}` (Trash). Status mapping: inbox pending (and any unsettled status), published confirmed, archived
    unsubscribed, needs_review problem, with the latest review reason. Trashed entries are not counted or listed.
  - **Integration note.** `integrations` = enabled connections with a workflow they installed that names the signup form (a condition
    `entry.entry_type` eq/in, or an entry step's `entity_query.entry_type`), or whose provider declares a blueprint with an entry-type parameter
    defaulting to the form. Nothing is matched by name. It is computed for the Subscribers list only, not for the sidebar's summary (which is read on
    every page). The page says that integration handles subscribing and unsubscribing, or hints to connect one.
  - **Sidebar and page.** A plain **Subscribers** item after Submissions with a pending + problems badge; page `/workspace/audience/subscribers`:
    four count tiles (tap to filter), the note, filters (form when several, status, search, a folded date range), compact rows on every screen (tap
    to open), a detail dialog (fields, history, source, Open as entry with `?return=`, Delete), an empty state. The badge and tiles follow a delete.
  - **Dashboard (decision):** `attention.audienceProblems` (+ a line linking to Subscribers filtered to problems) counts only signups that need
    a look. A pending signup is routine and nobody's to-do, so it isn't there; the sidebar badge counts both, as asked.
  - **Privacy fix.** `services/entry_privacy.py`: an ADMIN and above sees `metadata_json.submission.ip_address` whole, everyone else masked (the
    Audience mask). Applied on the entries API (list, one, search, create/update/restore/suggestion responses), a collection's entries, the
    assistants' and MCP's `get_entry` and `find_entries` (`include_metadata`), the snapshot diff and restore result, and the Event Log's detail
    (the `form_submission_received` payload carries the IP). Saving never writes the masked form back (`keep_recorded_ip` for non-admins; the
    editor posts the metadata box as it read it). The publishing API never carries the address (a published content form's entry reached sites with it).
    Not covered, by design or left open: the admin-only workspace export (whole), the legacy Forms submissions list (editors, separate table),
    workflow run context (`entry.metadata`, the author's privileges).
  - **Cleanup migration `c4e8a2d19f57`** (data only, no-op downgrade, idempotent, SQLite and PostgreSQL): removes `confirmed-subscribers` /
    `unsubscribed` only when exactly the plugin's (name, smart, private, entry target, no other blueprint's, rules exactly
    `{entry_types: [one], statuses: [published | archived], match: all}`); marks the signup type `kind: signup` (and `destination: audience` where none
    is stored) read from Buttondown's install: the subscribe workflow's `entry.entry_type eq` condition, else the confirm/unsubscribe workflows'
    `entity_query.entry_type`, else the plugin default `newsletter` when a `buttondown` integration exists (the plugin keeps `signup_type` nowhere
    else: a blueprint parameter is substituted into what it creates). A stored kind or destination is never overwritten. Coordinator's live finding
    (Mash & Burn: `newsletter` unlisted with no kind) is this case.
  - **Blueprint hook (justified):** `entry_fields` blueprints may carry `payload.submission: {destination?, kind?}` (nothing else, validated),
    applied to a submittable type for the keys it doesn't store (create what is missing, never overwrite; choosing a destination sets `listed` like the
    editor; entries follow). Chosen over a new blueprint kind (a kind needs an SDK change, the card's kind list, ordering and an updater) and over a free
    `capabilities` merge (too broad: honeypot, captcha, rate limits would become blueprint business). `entry_fields` already means "settings on an existing
    type", and the SDK's `payload` is a free dict, so no SDK release is needed. "Applied" now also needs the declared settings stored. Old cores:
    the catalog skips a blueprint whose `fields` is empty, so a provider that wants to stay valid there also declares a field (Buttondown declares `email`,
    which its signup workflow reads); the `submission` block is ignored and the type's Signup setting is set by hand.
- **Plugin (Buttondown 0.8.0):** no collections; required `buttondown-signup-form` blueprint (the hook + `email` field); README/guide rewritten.
- **Tests:** `test_audience_subscribers.py` (summary and status mapping, list, filters, roles, detail, history, delete, integrations note, dashboard,
  Buttondown's confirm/unsubscribe steps finding the unlisted signup), `test_entry_ip_privacy.py` (every path, roles, write-back, publishing, events),
  `test_migration_audience_subscribers.py` (both engines, exact match, lookalikes, idempotent, up/down/up, the named-type resolution),
  `test_blueprint_submission_hook.py`; frontend `audience.test.mjs` (+25) and `entryTypeListing.test.mjs`.
- **Open:**
  - The app icon badge still doesn't count Audience (submissions or signups).
  - The OpenAPI spec changed (new routes and schemas, `AudienceSignupsSummary`, dashboard `audienceProblems`); the SDK is regenerated separately.
  - A signup's status is Marvin's word for the entry status: a manual archive in Marvin reads as unsubscribed even if Buttondown still lists them.
  - The event-log status history is as complete as the log (pruned events leave a shorter story).

## Decisions after phase 2 (2026-10-20)
Jared: "go with your recommendations on all three".
- **`listed` alone:** unchanged. `{"listed": "unlisted"}` is every internal entry; `listed` / `any` alone match nothing, like an empty rule set.
- **Workflow queries by collection:** a query that names a collection returns what it holds, internal entries included
  (`services/entries/query.py`); without a collection, type or entries it still never reaches them.
- **Dashboard:** counts problem signups only; a pending signup is routine. The sidebar badge counts both.
