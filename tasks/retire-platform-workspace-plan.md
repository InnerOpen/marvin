# Plan: retire the platform workspace (2026-10-18)

Jared (2026-10-18): stop treating the install-time "Default" workspace (`groups.is_platform`, prod name "Marvin Admin")
as special, so it can be deleted like any other workspace. Drafted from the code (read-only); nothing built yet.

## 0. Model (decided)

Platform = env baseline, Admin edits override in `platform_settings` (the `services/platform_policy.py` pattern).
Workspaces have only their own settings. Default is an ordinary workspace. No Site→Default→Workspace chain.

## 1. Findings — every dependency on the marker

| # | Where | What it does today |
|---|---|---|
| 1 | `services/email/email_senders.py:342-389` | `_active_profiles` joins `Groups.is_platform`; `platform_sender()` = env SMTP else the platform workspace's active profile; `email_ready()` checks the same pair. A workspace with no profile falls back to `platform_sender()` (:304) — fine, stays. |
| 2 | `services/platform_alerts.py:120-129,176`, `alerting.py:283-313,626-657`, `routes/admin/alerts_controller.py:39,81`, `schemas/admin/platform_alerts.py:64,77`, `frontend/src/pages/admin/alerts.astro:29,72-79,132` | Alert routes list/run only `IntegrationModel` rows of the platform workspace. Email + push are already platform-level. |
| 3 | `db/models/users/users.py:163` (`group_id` NOT NULL, FK without ondelete), `:345-350` | User created with no group → platform workspace. Hit by Admin → Users create, OIDC (`core/security/providers/openid_provider.py:113`), LDAP (`ldap_provider.py:196`) — OIDC/LDAP users get no membership, only the home `group_id`. |
| 3b | `active_group_id or group_id` pattern | `routes/_base/base_controllers.py:177`, `users/workspace_activation_controller.py:36,129`, `users/api_token_controller.py:49`, `admin/storage_controller.py:123,178`, `users.py:274-281`, `schemas/user/user.py:590`. `BaseUserController.group_id` 403s with no workspace. |
| 4 | `db/init_db.py:84-86,121-143,368`; `repos/seed/init_users.py:112-147`; `core/settings/settings.py:732`; chart `values.yaml:223`, `_helpers.tpl:186`, `deployment.yaml:152`; `docs/manual/operations.md:62,158` | Fresh install creates the platform workspace and makes the admin its OWNER; demo users and legacy seeders use it. |
| 5 | `routes/admin/group_controller.py:175-188` (GET `/admin/groups/platform`), `:322-327` (409 guard), `:337-345` (blocks deleting while users have it as home); `about_controller.py:50-56,69` (`default_group`), `:226` | |
| 6 | `workspace_activation_controller.py:165-167` | Sorts platform first. |
| 6b | Frontend | `components/WorkspaceSwitcher.astro:39,56`, `layouts/AppLayout.astro:284`, `components/PlatformBadge.astro`, `pages/admin/workspaces.astro:16,50`, `admin/groups/[id].astro:34-62`, `workspace/settings/general.astro:355-360`, `lib/api/admin/workspaces.ts:14`. |
| 7 | Admin pages | `AdminLayout.astro` fetches no workspace (good). Two admin APIs need one: `admin/character_packs_controller.py:168-172` (bills AI to the current workspace), `admin/invitation_controller.py:93`. `routes/admin/platform/*` reads `user.group_id` but is not mounted (`routes/admin/__init__.py`) — dead code. |
| 8 | Secrets | No platform secret store. `workspace_secrets.group_id` NOT NULL (`db/models/groups/secrets.py:27`), but every backend already accepts `group_id=None` (disk/vault `_system`, env `GLOBAL_PREFIX`, db filters `== group_id`) — only the table blocks a platform scope. |
| 9 | Orphaned data | Platform events are written with the admin's current workspace (`storage_controller.py:123-130,178-185`, `api_token_controller.py:49`, `auth_controller.py:346`); `group_purge.py:36` deletes all `event_log` rows of the workspace → deleting Default would delete platform audit history. `workspace_deleted` is dispatched with `group_id=item_id` before the purge (`group_controller.py:362-373`) → purges itself. Scheduled tasks, backup runs, system email templates, AI prices, character packs use `group_id=None` / platform storage — safe. R2 objects stay behind when asset rows cascade. |

## 2. Stage 1 — platform SMTP and platform alert channels

**Platform secret scope.** Migration A `…_platform_secrets`: `workspace_secrets.group_id` nullable + partial unique index
`uq_workspace_secrets_platform_slug` on `slug WHERE group_id IS NULL`; model updated. `services/secrets/platform.py`:
`get/set/delete_platform_secret(slug, session=None)` wrapping the backend with `group_id=None`. Workspace secret APIs
already filter by group (`routes/groups/secrets_controller.py:40,72,78`) — test that platform rows never appear there.

**Platform SMTP.** `services/platform_smtp.py`: key `smtp` in `platform_settings`
`{enabled, host, port, username, auth_strategy, from_name, from_email, password_ref: "PLATFORM_SMTP_PASSWORD"}`, 15 s cache
like `platform_policy._stored` (cleared on save). `effective()` → `SMTPConfig(source="admin"|"env"|None)`: merged per field — each admin-set field wins,
unset fields fall back to env (decision 1). `email_senders.py`: `DefaultEmailSender`
takes a config; `platform_sender()` = `SMTPConfigSender(platform_smtp.effective())`; `email_ready(group_id)` = platform
ready or the group has an active profile; drop the `is_platform` join. Point `about_controller.py:191,226` and
`app/app_about.py:96` at effective readiness.
API (`routes/admin/email_controller.py`): `GET/PUT/DELETE /admin/email/platform-smtp` (DELETE = back to env),
`POST /admin/email/platform-smtp/test` (to the caller). `PlatformSMTPRead` (password only as `passwordSet`; `source`,
`envAvailable`, `envSummary`), `PlatformSMTPUpdate` (password write-only, blank keeps). Audited as
`platform_settings_changed` with `group_id=None` (like `alerts_controller.py:127-141`).

**Platform alert connections.** `platform_settings` key `platform_connections`:
`[{id, provider, name, config, secret_ref: "PLATFORM_CONN_<hex>", enabled}]`. Refactor `alerting.targets`/`send_route`
(`alerting.py:283,626`) to read `scope.connections(session)` → `ConnectionView(id, name, provider, config, enabled, secret())`;
`WorkspaceScope` maps `IntegrationModel` rows, `PlatformScope` maps platform connections (route-arg secrets resolve with
`group_id=None`). Delete `_platform_workspace` / `PlatformScope.workspace`; update `email_setup`/`where` strings.
Endpoints `POST/PUT/DELETE /admin/alerts/connections[/{id}]` — only installed providers with `message_actions`; Apprise
first (name + URLs, write-only, one per line — the plugin's `_parse_urls` already accepts that).
`PlatformAlertsRead.platform_workspace` → `connections`.

**Migration B `…_platform_smtp_and_alert_connections`** (data; Default's rows left untouched so rollback works): find the
`is_platform` group's active SMTP profile → `smtp` with `enabled = not env SMTP complete` (read `get_app_settings()` like
`efee4271020c:43`) so behaviour is unchanged. With `SECRET_BACKEND=database`, copy the ciphertext verbatim into a
NULL-group `PLATFORM_SMTP_PASSWORD` (same Fernet key; precedent `1467f4e1c2f7`); other backends → log, Admin shows
"password missing". For each route in `platform_alerts.routes`, copy its integration row into `platform_connections`
keeping the same id (routes/statuses need no rewrite), copying `secret_ref` and any `{{SLUG}}` secrets in args.
Downgrade: delete both keys and NULL-group rows, restore NOT NULL.

**UI.** `admin/email-settings.astro:79-100`: the read-only env card becomes a "Platform SMTP" block — source pill
(Admin / Environment / Not set), form (security TLS/SSL/None), password "set — leave blank to keep", Save / Send test /
"Use environment settings". `admin/alerts.astro`: "Platform channels" — Email to super admins, Push (both exist),
Apprise URLs (add, test, remove); routes pick from platform connections; rewrite copy at :72-79, :132. Phone (<640 px):
one column, full-width buttons, no tables.

**SDK:** regenerate MarvinSDK (uv env); SDK Quality Gate green.

**Tests:** rewrite `tests/test_platform_email_sender.py` (admin over env, env when no admin block, nothing ready, no
`is_platform` anywhere); rewrite `test_platform_alerts.py` through platform connections with a fake provider;
`test_platform_secrets.py` (uniqueness, never listed per workspace, a workspace resolve can't read a platform secret);
`test_platform_smtp_api.py` (password never returned, audited); migration test on a scratch DB (Default's profile and
routes copied).

## 3. Stage 2 — users without a home workspace; Admin with no current workspace

**Migration C:** `users.group_id` nullable, FK recreated `ondelete=SET NULL` (existing homes kept).

**Current-workspace resolver** `services/workspace/current.py::current_workspace_id(user)`: `active_group_id` if still
accessible → home if member or super admin → first membership by name → `None`. Replace every 3b site.
`BaseUserController.group_id` (`base_controllers.py:170-181`) → **409 `{"code":"no_workspace"}`** instead of 403.
`GET /self/workspaces/current` → `GroupRead | None`.

**Platform events get `group_id=None`:** `storage_controller.py:123-130,178-185` (drop `if not workspace_id: return` —
always audited), `api_token_controller.py:49-51`, `auth_controller.py:346`.

**User creation:** `users.py:318-356,405-410` — `group=None` = no home. Admin create / OIDC / LDAP users start with no
workspace → "waiting for an invite" page (Q4). Schemas `schemas/user/user.py:194,216,419-424,503`: `group`, `group_id`,
`group_slug` Optional.

**Admin APIs that need a workspace:** character-pack line writing takes an explicit `workspace_id` or 409 "pick a
workspace to bill"; invitations require `group_id` with no current workspace; delete `routes/admin/platform/`.

**Workspace create/delete:** `group_controller.py:337-345` home-workspace guard goes (delete clears homes via SET NULL;
memberships already cascade). Admin create (:112-173) sets the creator's `active_group_id` if they have no current
workspace.

**Frontend:** `WorkspaceSwitcher.astro:20-27` with no workspace → "No workspace" + "Create workspace" (super admin →
`/admin/workspaces`). `AppLayout`, `/`, `/workspace/*` with none → super admins to `/admin`, others to new
`pages/no-workspace.astro`. `admin/users.astro:73-87`, `admin/users/[id].astro:146-245` show "No home workspace".

**Tests:** `test_no_workspace.py` — a super admin with no home and no memberships gets 200 on every GET of the admin
router (iterate them); `/workspace` APIs 409 `no_workspace`; `current` null; `current_workspace_id` fallback order;
deleting someone's home clears it; platform events carry no `workspace_id`.

## 4. Stage 3 — retire the marker

**Fresh install (decided: no workspace).** `init_db.py:84-86` drop `platform_workspace_init`; `init_users.py:112-124`
admin created with no home/membership; `IS_DEMO` creates no workspace either (decision 5) — demo users start with none; legacy seeders (`init_db.py:117-119`)
skip when there is no workspace;
remove `log_name_hint` (:368). Remove `DEFAULT_GROUP` from settings (`extra="allow"`, settings.py:643, keeps old envs
booting), the chart and `docs/manual/operations.md`; one startup warning while it is still set.

**Migration D `…_drop_groups_is_platform`:** record `{id, name}` in `platform_settings.retired_platform_workspace`, then
drop `uq_groups_is_platform` and `is_platform` (`groups.py:57-78`). Downgrade re-adds and re-marks the recorded id.

**Remove the marker's code:** delete `services/group/platform_workspace.py`, `group_controller.py:22,175-188,322-327`,
`about_controller.py:50-56` (drop `default_group`); sort workspaces by name only; drop `is_platform` from
`schemas/group/group.py:85,131`; delete `PlatformBadge.astro` and its uses (6b); `general.astro:355` shows the normal
delete link; delete/rewrite `tests/test_platform_workspace.py`.

**Safer workspace deletion (`group_controller.py:295-376`):** `GET /admin/groups/{id}/delete-preview` (counts: members,
entries, assets + bytes, integrations, tasks, SMTP profiles, home users; last bundle time). DELETE requires
`confirm_name` and a bundle from the last 24 h unless `skip_backup=true` (Q2); the page offers "Back up now"
(`backups_controller.py:31`). `group_purge.py:36`: platform event types get `workspace_id=NULL` instead of deletion.
`workspace_deleted` dispatched **after** delete with `group_id=None`, name in data. Stored objects are kept 30 days, then purged by a daily system task (decision 3).

**Deleting prod's "Marvin Admin":** separate operational step after Stage 3 is verified: preview → move/export what's
worth keeping → bundle → delete.

**Tests:** fresh `init_db` creates no workspace and the admin can log in; demo mode creates "Demo"; delete requires name +
backup; platform events survive a delete; migration D up/down.

## 5. Rollout, verification, rollback

Every push to develop auto-deploys marvin-dev then prod (`promote.yml`, no gate). Before pushing Stages 1 and 3: restore a
prod `pg_dump` into `postgres:17-alpine`, `alembic upgrade head`, check the copied `smtp`, `platform_connections` and
NULL-group secrets with psql. Before Stage 1: record Default's active profile and routes
(`select * from workspace_smtp_profiles where is_active`; `platform_settings where key='platform_alerts'`); confirm prod
`SECRET_BACKEND`.
After each deploy: Admin → Email source + test send; Admin → Alerts test every channel; a password reset to yourself;
Stage 2: walk every Admin page at phone width on dev as a throwaway super admin with no memberships; Stage 3: on dev
create → preview → back up → delete a workspace.
Rollback: Stage 1 `helm rollback` works (Default's rows untouched; old code ignores new keys). Stage 2: old code breaks
only for users with no `group_id` — don't create any until it has run clean for a day. Stage 3: migration D downgrade
re-marks the recorded workspace; can't restore a deleted one.

## 6. Risks

- Non-database secret backend: no verbatim copy → admin re-enters the password.
- The env backend's global fallback (`MARVIN_SECRET_*`) already lets workspaces see global env secrets — unchanged, but
  documented.
- `AllRepositories(group_id=None)` doesn't filter by group — grep for admin-side generic secret queries that could list
  platform rows.
- SDK consumers (MarvinCLI, MarvinMCP, MarvinAstro) assuming non-null `groupId` — grep found none.
- OIDC sign-ups no longer land in a workspace (Q4).
- Postgres NULL uniqueness relies on the partial index.

## 7. Decisions

- **Jared 2026-10-18:** the model in §0 (env baseline, Admin overrides in `platform_settings`, workspaces own settings
  only, no inheritance chain).
- **Jared 2026-10-18:** fresh installs create **no workspace** — the first super admin logs into Admin (works with zero
  workspaces) and creates workspaces there; `init_db` stops creating the platform workspace; `DEFAULT_GROUP` retired.
- **Jared 2026-10-18, answers to §8:**
  1. Admin SMTP overrides env **per field** (like the security policy): each field the admin sets wins; unset fields
     fall back to env. `effective()` merges field by field; "Use environment settings" clears all admin fields.
  2. Deleting a workspace requires a bundle from the last 24 h, with an **explicit skip** (`skip_backup=true`, a ticked
     box in the UI).
  3. Stored files (R2 / BYO objects) of a deleted workspace are **deleted after a 30-day grace**: record the prefix and
     deletion time (`platform_settings.deleted_workspace_storage` or a small table), a daily system task purges entries
     older than 30 days; Admin lists pending purges with "purge now" / "keep".
  4. OIDC/LDAP sign-ups with no workspace → **"waiting for an invite" page**.
  5. Demo/dev installs create **no workspace** (like prod); demo users start with none; legacy seeders skip when there
     is no workspace.
  6. Platform alert connections: **generic storage, Apprise-first UI**.
  7. Prod's "Marvin Admin": **delete through the normal flow** after Stage 3 (preview → move what matters → bundle →
     delete).

## 8. Questions for Jared (recommended first)

1. Admin SMTP vs env: the whole block replaces env (rec.), or per-field override like the security policy?
2. Backup before deleting a workspace: require a bundle from the last 24 h with an explicit skip (rec.), always require,
   or only warn?
3. R2 files of a deleted workspace: leave them and log the prefix (rec., matches BYO decision 9), delete after a 30-day
   grace, or delete right away?
4. OIDC/LDAP sign-ups with no workspace: "waiting for an invite" page (rec.), or a setting for an auto-join workspace?
5. Demo/dev installs: create a "Demo" workspace (rec.), or none like prod?
6. Platform alert connections: generic storage with an Apprise-first UI (rec.), or Apprise URLs only?
7. After Stage 3: keep prod's "Marvin Admin" until its content is moved, then delete through the normal flow (rec.), or
   delete right away?
