# Integrations ship their own Playbooks (Playbooks step 4, second half) (2026-10-22)

Jared: "Integration shipping their own sounds good." Design: ADR-002 scope item 4 ("plugins shipping Playbooks from
their integration cards; design kept compatible"). The GitHub-sync half is dropped.

## Why
An integration knows things a workspace doesn't — what makes a good Buttondown issue, how to read a failed Cloudflare
Pages build, how a Mastodon post is counted. Today that know-how sits in the plugin's `guide.md` (read only when
building workflows). This lets a plugin ship Playbooks like it ships workflows: listed under the card's Content, added
by an admin, updated with edit protection, listed under "What it installed".

## Findings that shaped this
- Integration actions are not agent tools; agents reach an integration only via `run_workflow` (ADMIN) or as a
  workflow's agent step.
- Entries have no `InstalledByMixin` columns → provenance in `metadata_json` (no migration).
- Playbook writers (`EntryService.create`, `attach_reference`, `upload_asset`) commit → Playbooks apply last in
  `apply_many`, the documented exception to "apply never commits".
- An older Marvin refuses `kind="playbook"` per item (the `BlueprintKind` Literal) and skips it with a warning; the
  plugin's other content still loads.

## 1. Declaration (SDK 0.15.0)
- A real skill folder as package data: `marvin_integration_<x>/playbooks/<name>/SKILL.md` (+ `references/*.md`).
- `marvin_integration_sdk/playbooks.py` (new): `playbook_blueprint(__package__, "playbooks/<name>")` →
  `ContentBlueprint(kind="playbook", slug=<SKILL name>, name=<title>, description=<frontmatter>, required=False,
  payload={"skill_md": text, "files": {path: text}})`.
- Text only (`.md .txt .json .csv .yaml`); SKILL.md ≤ 64 KB; ≤ 20 files ≤ 64 KB each; ≤ 256 KB total; no
  `scripts/` or script extensions (same list as `importer.SCRIPT_EXTENSIONS`), no absolute paths or `..`.
- `check_playbook(blueprint, provider)`: name pattern, provider prefix, description ≤ 1024, referenced files present,
  `allowed-tools` tokens look like Marvin tools. Conformance test `test_playbooks_are_well_formed`.
- Core: `"playbook"` in `BlueprintKind`; `_payload_fits_kind` re-validates (parse, name == slug, paths, caps); the
  prefix rule in `catalog._provider_blueprints`. Core never trusts the SDK's checks.

## 2. Install: Add from the card → arrives as a draft
- Shown under "Optional" with kind noun "Playbook" (never required).
- Add (`POST /groups/blueprints/{slug}/apply`, admin) → `_create_playbook`: `ensure_playbook_type`, build an importer
  `Package(kind="integration", …)`, `review_package`, `EntryService.create(status="draft")`, attach files,
  `metadata_json = {importReview (source integration), installedBy}`. Factor `create_playbook_from_package(...)` out
  of `import_package` so import and blueprint share one writer.
- Card after Add: ✓ "Draft: review and publish" → link to the Playbooks page. `BlueprintRead` gains `installed_id`,
  `installed_status`.
- `apply_many` order: playbook last (commits; documented).

## 3. Naming: provider prefix; collisions refuse
- Names must start with `<provider-slug>-` (e.g. `buttondown-newsletter-issue`, `cloudflare-pages-failed-build`,
  `mastodon-post`); SDK checks, core enforces.
- Applied = a Playbook with that slug, not trashed, `installedBy.source == blueprint.source`.
- Taken name (any other entry, a person's Playbook, or in the Trash) → Add refused, never renamed or adopted.
  `BlueprintRead.conflict` (via `blueprint_conflict()` reusing `importer._taken_message`); card shows it instead of Add.

## 4. Updates and edit protection
- `UPDATABLE_KINDS = ("workflow", "playbook")`; generalise to `state_from_hashes(have, stored, declared)`.
- `playbook_hash`: `definition_hash` over `proposals.CHANGE_KEYS` fields + `{path: sha256(text)}`. Stored in
  `installedBy.hash`; "have" uses `installedBy.fileShas` when the row's `{path: asset_id}` equals `installedBy.assets`,
  else files read as edited (verify assets can't be replaced in place; else compare checksum/size).
- Update: text via `EntryService.update` (history, same id, status kept); files: new/changed → new asset +
  `attach_reference`, removed → `remove_reference` + trash its Playbook-scope asset, unchanged left; review re-run;
  `installedBy` rewritten. `needs_confirmation` for edited / edited_update / differs unless `replace_edits`.
- Card: same `STATE_TAG` + Update; the confirm says it replaces changes made here, the old version stays in history,
  and published means agents use the new version at once. Admin-only.

## 5. Footprint, provenance, removed integration
- `metadata_json["installedBy"] = {source, integrationId, blueprint, hash, fileShas, assets}` (`PROVENANCE_KEY`).
  Check the Playbook editor never overwrites `metadataJson` wholesale.
- Footprint: `installed_items` adds `"playbooks"` (filter `all_playbooks` on `installedBy.integrationId`;
  enabled = published); `IntegrationFootprint.playbooks`; `integrationFootprint.ts` KINDS + `?from=integration:<id>`.
- Removed integration: Playbook stays (published keeps working), labelled "From a removed integration" on the
  Playbooks page; not part of "Delete all of these". Re-adding the provider and Update rebinds it.
- Review source `kind: "integration"`: "Installed by the Buttondown integration".

## 6. Agent visibility: no gating
Published integration Playbooks are in every agent's catalog like any other (subject to chosen set, always-load,
manual-only). Not hidden when the integration is off. Later maybe a catalog suffix "(Buttondown is off)".

## 7. allowed-tools: Marvin tools only; narrows, never widens
Unchanged rule. Integration actions are reached via the plugin's own workflows (`run_workflow`) or a workflow agent
step. Provider actions as agent tools are out of scope.

## 8. First Playbooks (outline)
1. `buttondown-newsletter-issue` — fields that make the email (title = subject ≤ 60, `preview` ≤ 140, body
   markdown), structure, what Buttondown renders, lifecycle (publishing sends; agents never publish; write yourself,
   `create_draft` / `update_draft`). Files: `references/checklist.md`, `references/example-issue.md`. No tool list.
2. `cloudflare-pages-failed-build` — find the failure (`site_deployment_failed` event, its build-log tail, Results),
   steps (`list_events` → `describe_event` → `get_workflow`), common causes, the answer's shape; never guess past the
   log. File: `references/causes.md`. Tools: `list_events describe_event get_workflow find_entries get_entry`.
3. `mastodon-post` — ≤ 500 chars (URL = 23), shape, CamelCase hashtags, alt text, content warnings; output is text
   for an Approval step then `social.post`. File: `references/examples.md`. Bluesky later.

## Order
1. SDK 0.15.0 (helper, check, contract test, docs, release). 2. Core schema + catalog. 3. Core apply/update/state
(+ shared writer, conflict, BlueprintRead fields, apply order). 4. Footprint + page labels + review source. 5. Card UI.
6. Plugins (Buttondown, Cloudflare Pages, Mastodon: folder + blueprint, SDK pin, version bump). 7. Docs (manual
Playbooks page, SDK README, ADR-002 note). One core push.

## Tests
SDK: helper reads a folder, JSON-safe; refuses scripts / `..` / over-cap / missing prefix / missing referenced file;
contract test. Core: bad SKILL.md, name ≠ slug, script path, missing prefix → skipped with warning, others load; older
Marvin skips the kind. Apply: draft with files, importReview, installedBy; re-Add no-op; taken name refused with
conflict; non-admin refused; playbooks last; asset rejection in detail. State/update: every state; Update replaces
text + files, keeps id/status, history, rewrites hash; needs_confirmation; forced restore. Footprint: listed, totals,
isolation; removed integration label; `delete_removed` leaves it. Agents: published appears and loads, draft doesn't,
disabled integration doesn't hide, allowed-tools narrows and is capped. Frontend npm tests. Full SQLite + Postgres;
astro check baseline; each plugin's tests + conformance.

## Size
About 4–5 days (SDK ½; core 2–2½; UI + docs ½–1; three Playbooks ~1).

## Out of scope
GitHub sync; integration actions as agent tools; hiding when the integration is off; auto-apply/auto-update; binary
reference files; per-connection Playbooks; core-shipped Playbooks (schema allows later); networks beyond Mastodon in the
first pass; bulk-deleting removed-integration Playbooks.

## Decisions (recommendations; Jared to confirm)
1. Declaration: a skill folder as package data, packed by the SDK's `playbook_blueprint`; text only, capped, no scripts;
   SDK 0.15.0.
2. Arrives as a **draft** with the import review; an admin publishes on the Playbooks page.
3. Names carry the **provider prefix**; a taken name **refuses** (card shows the conflict).
4. Updates use the **install-hash states**; Update replaces in place and confirms when edited/unknown.
5. Provenance in `metadata_json["installedBy"]`, no migration; listed under What it installed; after removal it stays,
   labelled, not bulk-deleted.
6. **No visibility gating** by the integration being on.
7. `allowed-tools` names **Marvin tools only**; narrows, never widens.
8. First three: `buttondown-newsletter-issue`, `cloudflare-pages-failed-build`, `mastodon-post`.
9. Playbook apply commits and runs last in `apply_many` (documented exception).
