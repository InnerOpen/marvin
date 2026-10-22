# System skills: Playbooks the platform offers every workspace (Playbooks step 5) (2026-10-22)

Jared (2026-10-22): a plugin — or Marvin core — declares each Playbook as **workspace** (offered on the integration
card, Add → draft, editable, install-hash updates; built) or **system**: in every workspace automatically, labelled
"System · <plugin>" / "System · Marvin", read-only there, updated with the plugin/core release. A workspace can switch
one off or copy it to customise; a super admin can switch one off server-wide.

## Findings that shaped this
- Runtime reading of installed packages already exists: `services/integrations/guides.py` (`installed_guides`,
  `lru_cache`) reads each plugin's `guide.md`; system Playbooks follow the same pattern (no rows, versioned by package).
- Only integration providers carry `content` today; `StoragePlugin` (`sdk/storage/__init__.py`) and `AIProviderPlugin`
  (`sdk/ai/__init__.py`) are frozen dataclasses without it; `marvin-storage-s3` registers only `marvin.storage_providers`.
- **Social is core code, not a plugin** (`services/integrations/social*`), so "Social" skills ship in core's folder,
  labelled "System · Social".
- The SDK is optional in core (`INTEGRATIONS_AVAILABLE`): core's own skills load with core's parser
  (`skill_md.parse_skill_md`, `blueprint.payload_problem`), never via the SDK.
- Every lookup goes through `published_playbooks` / `find_published` (`services/playbooks/__init__.py`): catalog,
  `playbooks_in_effect`/tool limit, `check_agent_settings`, the three tools. `find_published` returns the entry row and
  `files.published_playbook_file(s)` reads its assets → a no-row branch is needed. `Playbook.id` is recorded in traces
  (`playbooks_used`, `lib/marvin/playbooksUsed.ts`) → a synthetic id.
- Manual-only (`disable-model-invocation: true`) never loads today for the default scope (MarvinMCP / remote MCP:
  `asked=""`) nor for a workflow agent step's `also` (`is_named` reads only the user's message). See Decision 10.
- Per-workspace switch store: shape like `hidden_tones` (nullable JSON list on `workspace_ai_settings`) — one small
  migration (`agent_tool_policies` needed one too). Server-wide: the keyed `platform_settings` table.
- Agents can't set alt text on an existing asset (only `import_asset(alt_text=…)`); out of scope, noted as a gap.

## Rules for system Playbooks (ADR-002 "Rules for Playbooks vs other know-how")
Go into `docs/manual/whats-new/playbooks.md` § System Playbooks and the SDK README; mechanical ones enforced.
1. A plugin's `guide.md` stays the reference for building workflows; a skill covers doing a job and points to it
   (`read_doc plugins/<provider>.md`), never restating actions/recipes.
2. The manual explains what a feature is; a skill is a procedure (steps, checks, good result) and links the page.
3. Workflow authoring stays with `workflow_authoring_guide` + Builder: no "how to set up a workflow" skill, or ≤ 20 lines
   that call the guide and `draft_workflow` (core review refuses longer).
4. Instructions say who, skills say how; voice lives in one skill. A system skill never sets voice/tone ("if this
   workspace has a voice Playbook in your list, load it") and never says who the agent is.
5. Manual-only by default (no key = manual-only); `disable-model-invocation: false` only for broadly useful ones.
6. Rarely `allowed-tools`: allowed (narrowing is safety), but the SDK check and core loader warn; admin page shows it.
7. Write it yourself: drafting skills save with `create_draft` / `update_draft`; lint warns on `compose_entry` /
   `revise_entry` in the body and refuses them in `allowed-tools`.
8. Slugs only: lint refuses UUID-looking tokens.

## 1. Storage: read at runtime from installed packages; no rows
- `services/playbooks/system.py` (new): `SystemPlaybook(name, source, label, version, description, body, manual_only,
  allowed_tools, files, hash)`; `system_playbooks()` builds a frozen name-keyed map once per process (`lru_cache`)
  after plugin registries load. Sources in order: core folder, integration providers, storage plugins, AI plugins.
- Validation: `payload_problem` (caps, text only, no scripts), prefix rule, lint (Rules 6–8); bad ones skipped with a
  warning into a load report (like `PluginLoadReport`); duplicate name → first source wins (core first), reported.
- Version = package version + `playbook_hash`; a release replaces text everywhere; uninstalling removes them.
- History: `load_playbook` returns version + hash; `playbooks_used` keeps `{id, name, version}`; earlier text lives in
  the package's git history; a copy snapshots.
- Why not rows: a migration + startup sync, entries are `group_id`-scoped (search, backup, trash assume it), rows would
  only be read; backups skip system skills naturally (only switches are exported).

## 2. Declaration
- SDK 0.16.0: `playbook_blueprint(__package__, "playbooks/<name>", scope="system")` → `payload["scope"]="system"`.
  Integration providers list them in a **separate** `system_playbooks` attribute (an older core reads only `content`,
  so it never offers them as Add); `StoragePlugin` / `AIProviderPlugin` gain `playbooks: tuple = ()`.
- `check_playbook(..., scope=)` refuses system in `content`, workspace in `system_playbooks`/`playbooks`, a name in
  both; runs the lint; the conformance test covers all three lists.
- Core's own: `src/marvin/system_playbooks/<area>/<name>/SKILL.md` (+ `references/`), package data; areas `marvin`
  ("System · Marvin") and `social` ("System · Social").
- Names: plugin slug prefix (`s3-`, `mastodon-`); core `<area>-` (`marvin-alt-text`, `social-auto-reply-rule`);
  `marvin-`/`social-` reserved.
- Clashes: a new workspace Playbook (editor, import, card Add, agent `create_draft`) may not take a live system name
  (`taken_where` / `_taken_message`: "…copy it instead"); an older workspace Playbook with that name **shadows** the
  system one in that workspace ("Hidden: your Playbook <name> has this name").

## 3. Catalog
- `Playbook` gains `source`, `label`; system id `system:<name>`.
- `visible_system(session, group_id)` = system minus server-off, workspace-off, shadowed, replaced-by-published-copy.
- `published_playbooks` returns workspace rows then `visible_system` (workspace first within `CATALOG_MAX`), with the
  same scope filters (chosen set, manual-only); no-scope admin screens get workspace rows only.
- `find_published` returns `(SystemPlaybook | row, Playbook)`; files branch builds `ReferenceFile` from memory;
  `read_playbook_file` cuts text like `read_asset_text` (factor `_cut_text`).
- Tools: `list_playbooks` adds `system: <label>`; `load_playbook` adds source, label, version; catalog line unchanged.
- Chosen sets: only named system skills; the picker lists them under "System". Always-load: an admin may pick one per
  agent (non-manual-only); never platform-wide. allowed-tools as any Playbook.
- `propose_playbook_change` / `replaces` on a system name refused ("copy it instead").

## 4. Switches
- Per workspace: `workspace_ai_settings.system_playbooks_off` (JSON list; one migration); exported/seeded as
  `systemPlaybooksOff`; admin-only `PUT /groups/playbooks/system/{name}` `{enabled}`; unknown names kept.
- Server-wide: `platform_settings["system_playbooks"] = {"off": [...]}`; super admin `GET/PUT /admin/system-playbooks`.
- Off / shadowed / replaced = absent everywhere (catalog, list, load, files, tool limit, always-load, chosen sets);
  agent settings show "(off)".

## 5. Copy to customise
- `POST /groups/playbooks/system/{name}/copy` `{name}` (admin): suggested name drops the prefix (`marvin-alt-text` →
  `alt-text`), must be free; `Package(kind="system")` → `create_playbook_from_package` with review source
  `{kind: "system", label, version}` ("Copied from System · Marvin 1.42.0") and `metadata_json["copiedFrom"]`; a draft.
- The copy is the workspace's own (no update link). A **published** copy replaces its original in that workspace
  (derived from `copiedFrom.name`); unpublish/trash brings it back.
- Upstream changed → hint only ("1.40.0 → 1.42.0", View it, Mark as seen); no merge.

## 6. UI
- Playbooks page: a **System** section (name, description, label chip, Manual-only / Allowed-tools badges, switch,
  View, Copy; states Off for this platform / Hidden / Replaced; grouped by label).
- Read-only view `settings/ai-playbooks/system/[name].astro` (body, files, version, source, recent uses via
  `GET /groups/playbooks/system/{name}/uses`).
- Run traces link `system:` ids; agent settings picker "System" group.
- Platform admin `admin/system-playbooks.astro` (by source, version, badges, how many workspaces switched it off,
  server switch, "Couldn't load" list); Admin → Plugins rows show "N system Playbooks".
- Integration card: "Also gives every workspace: <name> (System Playbook, read-only)" — never an Add item.

## 7. First system Playbooks (outlines)
1. `marvin-alt-text` (System · Marvin; **listed**): `view_image`; decorative vs informative; ≤ 125 chars, no "image
   of", transcribe text, summarise charts; where it goes (markdown, image-field alt, social description,
   `import_asset(alt_text=…)`); existing asset → suggestion in reply/draft. Links the assets manual page. File
   `references/examples.md`. No tools.
2. `s3-workspace-bucket` (System · S3 storage, in `marvin-storage-s3`; manual-only): bring your own bucket and read a
   failed Check connection (failure → fix table); setup steps via `read_doc workspace-storage`; what only a super admin
   can change. File `references/failures.md`.
3. `social-auto-reply-rule` (System · Social; manual-only): specific match words, per network or all, write the reply
   yourself (short, no links unless asked), test in rehearsal first; save with `create_draft` (`social-auto-reply`);
   agents never switch auto-reply on; links the Social manual. Per-network posting stays with each network's
   integration Playbook (`mastodon-post`).

## Order
1. SDK 0.16.0 (scope, fields, check + lint, contract test, README, release). 2. Core loader (`system.py`, core folder,
report, lint). 3. Wire catalog/find/files/tools/id/version/traces. 4. Switches (migration, routes, export/seed), name
clashes, proposals refusal, copy + derived replacement. 5. UI. 6. First Playbooks (two in core, one in the S3 plugin).
7. Docs (manual § System Playbooks with the Rules, SDK README, ADR-002 note). One core push; the S3 plugin after it.

## Tests
SDK: scope stamp; misplaced/duplicate refused; lint (UUID, compose_entry in allowed-tools, allowed-tools warning);
storage/AI fields default; contract test. Loader: core folder loads; bad/script/over-cap/no-prefix skipped and reported;
first source wins; loads without the SDK; manual-only default. Catalog/scope: listed after workspace's own; manual-only
loads only when named; chosen set; always-load rules; allowed-tools narrows; files; trace id + version; MCP scope per
Decision 10. Switches: both levels hide everywhere; isolation; permissions; export/seed. Names: system name refused on
create/import/Add/create_draft; older workspace name shadows. Copy: draft with files/review/copiedFrom; taken name
refused; published hides original, unpublished restores; upstream hint + Mark as seen; proposals/replaces refused.
Frontend npm tests; full SQLite + Postgres; astro check baseline; S3 plugin tests + conformance.

## Size
About 5–6 days (SDK ½; loader + catalog 1½; switches/names/copy 1; UI 1½; Playbooks + docs 1).

## Out of scope
History/diffs in Marvin; merging upstream into a copy; per-agent switch-off beyond chosen sets; a tool to set alt text
on an existing asset (gap); binary files; platform-wide always-load; hot-reloading plugins; a "how to set up a
workflow" skill; `social-cross-post`; AI-provider Playbooks (schema supports, none yet).

## Decisions (recommendations; Jared to confirm)
1. **Storage:** read at runtime from installed packages, cached per process; no rows; version = package version + hash.
2. **Declaration:** SDK 0.16.0 `scope="system"` in a separate `system_playbooks` / `playbooks` field; core's own in
   `src/marvin/system_playbooks/<area>/<name>/` (areas `marvin`, `social`).
3. **Names:** plugin-slug or area prefix; new workspace Playbooks can't take a system name; an older one shadows.
4. **Catalog:** joined after the workspace's own; same scope rules; id `system:<name>`; label in the UI only.
5. **Manual-only by default**; `marvin-alt-text` the listed exception; allowed-tools allowed but warned (none in the
   first three).
6. **Always-load:** an admin may pick one per agent; never platform-wide.
7. **Switches:** per workspace (`system_playbooks_off`, one small migration) and server-wide (`platform_settings`);
   off = absent everywhere.
8. **Copy:** a draft with `copiedFrom`; a published copy replaces its original in that workspace; upstream hint only.
9. **Read-only:** proposals / `replaces` against a system skill refused, pointing to Copy.
10. **Manual-only reach (changes current behaviour for workspace Playbooks too):** a workflow agent step's `also`
    counts as naming; MCP clients (a person driving directly) may load a manual-only Playbook by name, and
    `list_playbooks` shows it with `manualOnly: true`. Without this, manual-only skills are unreachable from workflows
    and MCP.
11. **First three:** `marvin-alt-text` (listed), `s3-workspace-bucket` (manual-only, S3 plugin),
    `social-auto-reply-rule` (manual-only).
12. **The Rules** go into the manual and SDK README; mechanical ones enforced by the SDK check and core loader.
