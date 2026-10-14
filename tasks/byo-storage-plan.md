# Plan: per-workspace "bring your own storage" (2026-10-14)

Jared: "bring your own storage still important. lets create a plan for that (agent)." Drafted by a planning agent from
the code (read-only); nothing built yet. Backlog item: ~/brain/10-Tasks/TASKS.md → "bring your own storage".

## 1. Key decision: a location string, `ws:<connection_id>` for a workspace's bucket

`assets.storage_provider` is already read per row (`provider_for()`), and the migration engine, `storage_key_aliases`,
storage stats and `static.py` treat it as an opaque string — so no new column on `assets`. Platform rows keep `s3` /
`local`; workspace-bucket rows record `ws:<connection_id>` (plugin slugs can't contain `:`). The value points at a
connection row, not the workspace: re-pointing a workspace leaves old rows on `ws:<old id>`, read with the old
connection's credentials. Nothing moves unless asked.

## 2. Data model (migration `…_workspace_storage`)

- `workspace_storage_settings` (one row per workspace, like `workspace_ai_settings`): `group_id` (unique, CASCADE),
  `credential_mode` platform|workspace (no row = platform), `active_connection_id`, `bundle_mode` (slice 5),
  `updated_by`, timestamps.
- `workspace_storage_connections` (kept as history; not deleted while referenced): `id` (the `<connection_id>`),
  `group_id`, `plugin_slug` ("s3"), `label`, `settings` JSON (non-secret, keyed by the plugin's `Setting.env`:
  `STORAGE_S3_BUCKET/_ENDPOINT/_REGION/_PREFIX/_ADDRESSING_STYLE/_CHECKSUMS`), `secret_refs` JSON
  (`STORAGE_S3_ACCESS_KEY` / `_SECRET_KEY` → workspace secret slugs, never raw keys), `public_base_url` (existing
  `validate_public_base_url`), `status` unverified|ok|failing|retired, `verified_at`, `last_checked_at`, `last_error`
  (`healthcheck.scrub`), `credential_fingerprint` (HMAC of resolved keys at verification), `version` (cache key),
  `created_by`, `retired_at`. Bucket/endpoint/prefix immutable (a change = a new connection); keys and public URL
  editable (bump `version`).
- Platform policy: new `platform_settings` key `workspace_storage` = `{"allowed": false, "endpoint_policy": "known",
  "allowed_plugins": ["s3"]}`; env default `STORAGE_ALLOW_WORKSPACE_STORAGE=false` (off by default, unlike AI).

## 3. Resolution (new `services/storage/workspace.py`)

- `write_target(session, group_id) -> WriteTarget(location, provider)`: platform mode → today's provider; workspace
  mode + policy on + status ok → `("ws:<id>", provider_for_connection(conn))`; workspace mode but broken → raise
  `WorkspaceStorageUnavailable` (**fails closed**, never silently to the platform bucket).
- `provider_for_connection(conn)`: `registry.get_plugin(slug).provider.from_config(read_config(cls.workspace_settings,
  merged))`, `merged` = settings + resolved secrets; never reads env. Cached by `(conn.id, conn.version)` with the 5 s
  re-read of `CHOICE_TTL_SECONDS`. Empty keys refused (boto3 would fall back to the pod's platform credentials).
- `provider_factory.provider_for(slug)`: `ws:` → load connection → `provider_for_connection`. `public_url_for`: `ws:`
  rows use the connection's `public_base_url`.
- `AssetStorageService.for_workspace(repos)` stores the location explicitly; replace the ~10
  `AssetStorageService(repos, get_storage_provider())` call sites (assets_controller.py:148, trash.py:194,
  automation/actions/media.py:220,429, ai/media/enrichment.py:96, ai/tools/builtins_actions.py:421,
  ai_settings_controller.py:374, operations_controller.py:1033, workspace_seed_loader.py:320). Character-library
  files stay on platform storage.
- Switching modes changes only where new uploads go. Bucket down: uploads 503 with a plain message; URLs need no
  network call (fallback to the stored `public_url`); Marvin-side reads fail per asset.

## 4. Copying existing assets (explicit only)

Reuse `migration.migrate(to=location, workspace=<slug>, verify=True, dry_run=…)`: streams + sha256, compare-and-set
row repoint, repeated passes, skips already-copied, never deletes the source. Add: a guard (a `ws:` target needs the
matching workspace), a one-off scheduled-task type `migrate_workspace_storage` (Run Now/history), CLI
`storage_migrate --workspace <slug> --to ws:<id> --verify [--dry-run]`, a dry-run embedded-URL report (entries/settings
containing the old base URL; sites to rebuild). Platform copy kept, so published sites keep working until an explicit
`prune_moved(workspace, source=…)` with a 30-day grace.

## 5. Check connection and health

`POST /groups/storage-settings/connections/{id}/check`: `healthcheck.check_provider` (list/put/get/delete under
`_marvin-healthcheck/`) plus a fetch of the probe from `public_base_url` through the SSRF-guarded client; step-by-step
errors via `healthcheck.explain`; sets `status` + `credential_fingerprint` (a later mismatch marks the connection
unverified and blocks uploads). Hourly system task `check_workspace_storage`; after 2 failures emits
`workspace_storage_unhealthy`.

## 6. Security

Keys only as workspace secrets. Changes by workspace OWNER (or platform super admin); ADMIN can view. Endpoints https
only (http when not PRODUCTION); `endpoint_policy`: `known` (R2/AWS/B2 suffixes, default), `public` (public addresses
only, re-checked each build; DNS-rebinding risk remains), `any` (admin opt-in, LAN MinIO). The platform's own
bucket/endpoint/prefix is refused. Least-privilege guide in `docs/manual/workspace-storage.md`. Audit events:
`workspace_storage_mode_changed`, `_connection_changed`, `_migration_started/_finished`, `_unhealthy`,
`_policy_changed`.

## 7. Backups

The platform asset mirror can't see `ws:` buckets: exclude them in `open_asset_sources` and say so on Backup health
("Not in the platform asset mirror: <workspace> (N files, X GB, in their own bucket)"). Workspace bundles already read
through `provider_for`, so they include BYO files once `ws:` resolves; a per-workspace toggle decides. Slice 5: the
workspace's own backups to a separate private bucket, never the asset bucket.

## 8. UI

Workspace: `settings/storage.astro` (Platform/Workspace radio cards as in ai-workflow.astro, connection form with
secret pickers, Check connection steps, copy/move job with dry run and history, usage split). API
`routes/groups/storage_settings_controller.py` at `/groups/storage-settings`. Admin → Storage: policy panel, a Storage
column in "Workspace keys and public domains", `ws:*` totals.

## 9. Plugins and SDK

SDK v0.11.0: `StorageProvider.workspace_settings` (empty = unsupported), `endpoint_setting`, `describe()`, conformance
test that building from workspace settings never reads env. marvin-storage-s3 v0.2.0 declares them (keys required).
Release order: SDK tag → bump Marvin's SDK pins → plugin tag → bump the plugins pin → `uvx uv@latest lock`.

## 10. Slices

1. SDK/plugin + inert core (policy off, no UI): tables, `workspace.py`, `ws:` resolution, `for_workspace`, call-site
   sweep, fail closed. Tests with moto (two buckets). Live on marvin-dev with a throwaway R2 bucket `marvin-byo-test`.
2. Settings page, API, check connection, policy, SSRF, audit. Live owner flow on admin-dev.
3. Copy/move job with dry run, embedded-URL report, resume, prune with grace. Live copy of the dev test workspace.
4. Health task, events, Admin Storage / Backup-health visibility, bundle toggle.
5. Optional: bundles to the workspace's own private bucket.

Mash & Burn on prod only after slice 3 has run on dev.

## Progress

- Slice 1 built 2026-10-14: SDK v0.11.0, marvin-storage-s3 v0.2.0, core tables + `services/storage/workspace.py`, `ws:` reads,
  `AssetStorageService.for_workspace` on every write path, `WorkspaceStorageUnavailable` → 503. Inert: the policy is off
  and nothing in the app creates a connection yet (slice 2). Live check on marvin-dev needs a throwaway R2 bucket.

## 11. Decisions (Jared, 2026-10-14, all as recommended)

1. One global switch (`workspace_storage.allowed`), no per-workspace allow-list.
2. OWNER only (or platform super admin) changes a workspace's storage; ADMIN can view.
3. Policy turned off after opt-in: uploads to `ws:` workspaces are **blocked** (plain message), never redirected.
4. Bucket down / keys failing: **fail closed** (`WorkspaceStorageUnavailable` → 503), never the platform bucket.
5. A public URL is **required** before a connection can be verified.
6. The bucket's domain may live in the client's own account; Marvin only checks it serves the probe.
7. BYO bytes **don't count** toward storage quotas; usage is still shown per workspace.
8. Bundles include BYO files per a **per-workspace toggle**, default off.
9. Workspace deleted: objects in its bucket are **left in place**; the connection row is forgotten.
10. Default `endpoint_policy`: **`known`** (R2 / AWS / B2); an admin can widen it.

## 12. Original questions

1. Off by default with one global switch, or also a per-workspace allow-list?
2. OWNER only, or OWNER + ADMIN as for AI?
3. Policy turned off after workspaces opt in: block their uploads, or send new uploads to the platform?
4. Bucket down: fail closed (recommended) or fall back to the platform?
5. Require a public URL? (Without one, presigned URLs expire within 7 days and break built sites.)
6. A BYO bucket's domain lives in the client's own Cloudflare account — acceptable?
7. Leave BYO bytes out of storage quotas? Show usage per workspace?
8. Should workspace bundles include BYO files (size, egress)?
9. Workspace deleted: leave objects in its bucket (recommended) or delete them?
10. Default endpoint policy: `known` or `public`?
