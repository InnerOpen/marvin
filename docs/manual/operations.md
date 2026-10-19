# Operations

What an operator needs to run Marvin 1.0.0-rc.186. Settings are environment variables read by `src/marvin/core/settings/settings.py`.

## Health and version

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /healthz`, `/livez`, `/health` | none | `{"status":"ok"}` while the process is up; touches nothing |
| `GET /readyz` | none | 200 when `SELECT 1` succeeds on the database, 503 `{"status":"unavailable"}` otherwise |
| `GET /api/app/health` | none | legacy health endpoint, kept for back-compat |
| `GET /api/app/about/version` | none | `{"version": "<backend version>"}` |
| `GET /version.json` (frontend) | none | `{"frontend": "<build commit>", "backend": "<version>"}` |
| `GET /api/app/changes?since=&until=&since_commit=` | signed in | release notes between two versions, newest first (at most 20), led by an "Unreleased" entry for the image's commits since its last release; empty when no changelog is installed |

The root probes live outside `/api` so orchestrators can hit them without knowing the mount. The admin stamps the version pair into every page, polls `/version.json` once a minute and on tab focus, and shows a Reload / Later bar when either side changes, on workspace and platform admin pages alike; it never forces a reload, and **Later** hides it until the next deploy. **What's new** on the bar opens the release notes between the versions the page was rendered with and the live ones, fetched on first open from `GET /api/app/changes`. The notes come from the image's `CHANGELOG.md`; because the release job writes a release's changelog section after the image is built, CI also records the commits since the last release tag in `UNRELEASED.txt` (`docker/write-unreleased.sh`), and the list shows their `feat`, `fix`, `perf` and `docs` commits first as "Unreleased". A build without that file still works. The frontend's commit comes from `GIT_COMMIT_HASH`, set from the Dockerfile `COMMIT` build arg.

## Images

`docker/Dockerfile` has four targets; `.github/workflows/docker.yml` publishes three to `ghcr.io` on push, named after the repository in lower case:

| Target | Image | Runs |
|---|---|---|
| `production` | `ghcr.io/inneropen/marvin` | API and server-rendered frontend in one container (`start.sh`) |
| `backend` | `ghcr.io/inneropen/marvin-backend` | API only (`marvin-server`) |
| `frontend` | `ghcr.io/inneropen/marvin-frontend` | Astro SSR UI only (`start-frontend.sh`) |
| `lambda` | not published | `FROM production` |

The backend-based images carry `CHANGELOG.md` and `UNRELEASED.txt` (the update banner's release notes) and this manual (`docs/manual`, which the agents' `search_docs` / `read_doc` tools read) beside the venv, so both always match the running version.

## Helm chart

`marvin-chart/` is the current deployment unit; read [`marvin-chart/README.md`](https://github.com/InnerOpen/marvin/blob/develop/marvin-chart/README.md) for install commands. `mode: combined` (default) runs the single image; `mode: split` creates backend and frontend Deployments from the `-backend` / `-frontend` images. Overlays: `values-k8s.yaml`, `values-production.yaml`, and iwobble's `values-iwobble.yaml` (prod) / `values-dev.yaml` (marvin-dev). The chart's default database is SQLite on the data volume (one replica, no operator), and every overlay pins `config.dbEngine: postgres` and a CloudNativePG cluster. Probes default to `/healthz` (liveness, initial delay 30 s, period 10 s) and `/readyz` (readiness, initial delay 10 s, period 5 s). Use `extraEnv` for settings the chart does not model and `initContainers` plus `extraVolumes` to install integration plugins before start (worked example in the chart README).

**Graceful shutdown.** An agent run is one synchronous request that can take minutes, so a deploy lets in-flight requests finish before the API pod goes away. `shutdown.terminationGracePeriodSeconds` (default 300) is the pod's grace period and `shutdown.preStopSleepSeconds` (default 5; 0 drops the hook) a sleep before SIGTERM so the Service stops routing to the pod first. On SIGTERM the server stops taking connections and waits up to `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` for running requests; the chart sets it to the grace period minus the preStop sleep and 15 seconds for shutdown and exit. A run still going at the deadline is lost, and the next process marks it failed (see [Agents and Ask → Interrupted runs](whats-new/agents-and-ask.md)); the chart delays that sweep (`AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS`) to the grace period plus 60 seconds, so it never fails a run the old pod is still finishing.

The trade-off: a pod with a long run in flight takes that long to stop. Under the default `RollingUpdate` the new pod serves while the old one drains, so on Postgres two API processes serve at once for up to the grace period. SQLite is one process writing one file, so with `config.dbEngine: sqlite` the chart always uses `Recreate` (and refuses more than one API replica): the old pod stops before the new one opens the database, and a deploy has downtime while it drains. Postgres installs can set `{type: Recreate}` themselves (`strategy` in combined mode; in split mode the backend's own `split.backend.strategy`, so the frontend keeps rolling) to rule out overlap. Under `Recreate` the chart sweeps interrupted runs at startup, since the old pod is already gone.

**Session signing key.** JWTs are signed with `DATA_DIR/.secret`, generated on first production start; the chart has no JWT setting. Keep `DATA_DIR` on a persistent volume or every restart invalidates sessions.

!!! warning "Chart keys the app does not read"
    `config.webhookRetryAttempts` and `config.webhookRetryDelay` land in the ConfigMap but nothing in `src/` reads them. `docs/manual/reference/helm-deployment-guide.md` predates this and is superseded on this point.

## Deploying

The iwobble cluster runs two releases of the chart, both named `marvin`: `marvin-dev` (`values-dev.yaml`) and production in `marvin` (`values-iwobble.yaml`). Both pin `image.tag=develop-<7-char sha>`, the images CI built from one develop commit, and take the chart from that same commit.

**The pipeline** (`.github/workflows/promote.yml`). Every push to `develop` waits for that commit's Docker Build, Test Suite and SDK Quality Gate, re-running one GitHub cancelled for lack of a runner (up to three attempts). If develop moves on first, the newer push takes over and this run ends without deploying — except that a release commit (`chore(release): … [skip ci]`, or any push whose commits all carry a skip-CI marker) doesn't count as moving on, since it never runs Promote itself. With CI green, the commit goes to `marvin-dev` and is smoke-checked; when that passes, the same commit goes to `marvin` with the same checks. There is no approval step: a green develop push reaches production on its own, and a failing one stops at dev. The prod job deploys through the `production` environment on GitHub, which has no protection rules; giving it a required reviewer (**Settings → Environments → production**) adds an approval before production without changing the workflow. A deploy in progress is never interrupted: a newer commit waits its turn, and only the newest waiting one is kept. The deploy jobs run on the in-cluster runner set as the `deployer` ServiceAccount (`.github/deploy/promote-rbac.yaml`, which also lists the one-time GitHub settings), and never for pull requests.

Each environment runs `scripts/deploy/promote.sh` (helm upgrade, described `promote develop-<sha>`, then both rollouts) and `scripts/deploy/smoke.sh`. The smoke check needs no credentials. It goes through the release's Routes: the UI's `/healthz` and the API's `/readyz` return 200, `/version.json` reports the new frontend commit, and the new backend pods have logged no `ERROR` or `Traceback`. If the upgrade, a rollout or the smoke check fails, `scripts/deploy/rollback.sh` returns the release to the helm revision it had before, and the job fails. A failed `marvin-dev` stops the run before production.

**Manual runs.** GitHub dispatches a workflow only if the default branch (`main`) also has it, so these need `promote.yml` and `promote-release.yml` on `main` (as `deploy.yml` is); the run itself uses develop's copy. `gh workflow run promote.yml --ref develop -f sha=<commit>` promotes a commit on develop; without `sha`, develop's tip. `-f dry_run=true` renders the chart with the cluster's capabilities and server-side dry-run applies every object in both namespaces, then checks the Routes answer; nothing changes. `-f smoke_expect=<other commit>` is the rollback drill: `marvin-dev`'s smoke check expects the wrong build, fails and rolls back, and production never starts.

**Rollback by hand.** `helm history marvin -n <ns>` lists the revisions; `scripts/deploy/rollback.sh <ns> <revision>` returns to one. The database is not rolled back: the backend migrates at startup, so older code runs on the newer schema. That works for added tables and columns, not after a migration that drops or renames something the older code reads. A run killed mid-upgrade leaves the release `pending-upgrade`, and helm refuses the next upgrade until `rollback.sh` returns it to the last deployed revision.

**Without the pipeline.** `git fetch origin && scripts/deploy/promote.sh <commit> marvin values-iwobble.yaml [--dry-run]` promotes to production from a workstation logged in to the cluster. `scripts/deploy/promote.sh <commit> marvin-dev values-dev.yaml` does the same for dev. `scripts/deploy/wait-for-ci.sh <sha>` waits for a commit's CI.

**Cloudflare Tunnel connector.** `.github/deploy/cloudflared.yaml` is the `cloudflared` Deployment (two replicas) that connects the production namespace `marvin` to Cloudflare. CI does not apply it and the Helm chart does not manage it: apply it by hand with `oc apply -f .github/deploy/cloudflared.yaml`. The tunnel token comes from the Secret `cloudflared-token` in `marvin`, created out of band (`oc create secret generic cloudflared-token -n marvin --from-literal=token=<token from the Zero Trust dashboard>`); it is not in the repo. Which hostname goes to which service is configured in the Cloudflare Zero Trust dashboard (Public Hostnames), not in this file.

## Platform SMTP and alert channels

Marvin's own mail (password resets, platform alerts, the admin test, any workspace without an SMTP profile of its own) and its platform alert channels no longer depend on a workspace. They are platform settings, edited by super admins, with the environment as the baseline.

- **Platform SMTP — per field.** **Admin → Email → Platform SMTP** shows each of host, port, connection security, username, password, From name and From address with where its value comes from. A field you set there wins; a field left blank falls back to the environment's `SMTP_*`. You can override just the From address, or just the host. **Use environment settings** clears every field set there, password included. A value you type that equals the environment's is not stored (it stays "from the environment"). Mail can go out when the merged result is complete by the environment's own rule: host, port, From name and address and security, plus a username and password for TLS/SSL.
- **The password** is write-only: stored as the platform secret `PLATFORM_SMTP_PASSWORD` (a `workspace_secrets` row with no workspace), never returned — the page only says whether one is set and whether it is yours or the environment's. With `SECRET_BACKEND=env` Marvin can't store it: set `PLATFORM_SMTP_PASSWORD` in the server's environment. A workspace's **Secrets** page never lists or resolves platform secrets (note the env backend's global fallback — `MARVIN_SECRET_*` and bare names — is shared with workspaces, as before).
- **Send test** mails the signed-in admin through what is saved and shows the server's answer. A workspace with its own active SMTP profile still sends its mail through it; without one it uses the platform SMTP.
- **Alert channels.** **Admin → Alerts → Platform channels** holds the platform's own connections (Apprise URLs first). See [Getting alerts outside Marvin](offsite-backup.md#getting-alerts-outside-marvin).
- **Audit.** Each change is recorded as `platform_settings_changed` with no workspace — field names and values, and only "password changed".
- **API** (super admin): `GET`/`PUT`/`DELETE /api/admin/email/platform-smtp` (`DELETE` = use the environment), `POST /api/admin/email/platform-smtp/test`. Stored in `platform_settings` under `smtp` (only the fields set there) and `platform_connections`.
- **Upgrading.** Migration `3442416ae2bd` copies the platform workspace's active SMTP profile (only when the environment's `SMTP_*` are incomplete — the case where that profile was sending platform mail — and only the fields that differ from the environment) and the integrations its alert routes use, with the same ids. With `SECRET_BACKEND=database` the credentials move verbatim into platform secrets; with any other backend the migration logs it and **Admin → Email** shows the password as missing until you enter it again, and a channel's credential has to be re-entered (**Replace URLs**). The workspace's own rows are left untouched, so a rollback works.

## Workspaces: first boot, deleting, and what stays behind

**First boot.** A fresh install creates **no workspace**, demo and dev installs included. It creates one user, the first super admin (`DEFAULT_EMAIL`, `DEFAULT_PASSWORD`; the password is logged once if unset), with no home workspace and no membership. Sign in: that account lands in **Admin**, which works with zero workspaces, and **Admin → Workspaces → Create the first workspace** is where content starts. The admin who creates a workspace becomes its owner and it becomes their current workspace. Anyone else who signs up (OIDC, LDAP, an Admin-created user) waits on an "invite" page until they are added to one. Demo mode (`IS_DEMO`) creates its four sample users but, like a real install, no workspace to put them in.

**No workspace is special.** There used to be one "platform workspace" (`groups.is_platform`, named by `DEFAULT_GROUP`, called "Marvin Admin" on production) that platform alerts and shared services ran from. Platform SMTP, alert channels and secrets now live in platform settings (see above), so it is an ordinary workspace: any workspace can be renamed (name and slug) and deleted. `DEFAULT_GROUP` (chart: `config.platformWorkspaceName`) is retired: it names nothing, and the API logs one warning at startup while it is still set — remove it. Migration `a225a6254088` records the workspace that carried the marker as `{id, name}` in `platform_settings.retired_platform_workspace`, then drops `groups.is_platform` and its index. Its downgrade puts both back and marks that workspace again if it still exists.

- **Renaming.** **Admin → Workspaces → Manage** changes the name and slug (`PUT /api/admin/groups/{id}`, slug optional, derived from the name when omitted; 409 if another workspace has the name or slug). The current workspace is stored by id, so nobody's selection changes. The old slug is kept as an alias (`group_slug_aliases`): Publishing API URLs (`/api/publish/<old-slug>/…`), switching by slug (CLI `--workspace`), `storage_migrate --workspace` and the backup lists (zips are `<slug>-backup-…`) still find the workspace. Renaming back drops the alias; no workspace can take a slug that is someone's alias.
- **Deleting.** **Admin → Workspaces → Manage → Delete workspace** (or **Settings → General → Danger Zone**, which links there). The panel shows what goes (members, entries, files and their size, integrations, scheduled tasks, SMTP profiles, users whose home it is), when the workspace was last backed up, **Back up now**, and asks for its **name, typed**. A delete needs a backup bundle of it from the **last 24 hours**; without one the only way is the explicit **Delete without a backup** box. API: `GET /api/admin/groups/{id}/delete-preview`, then `DELETE /api/admin/groups/{id}?confirm_name=<name>[&skip_backup=true][&force=true]` (400 `confirm_name_mismatch`; 409 `backup_required`; 400 for members or entries unless `force=true`; the UI always sends `force`). Users with it as their home keep their account and lose the home; memberships go with it.
- **Events.** Platform events that mention the workspace (sign-ins, token refreshes, backups, storage changes: the platform-scope types) stay in the Event Log with no workspace; its own events go. `workspace_deleted` is sent after the delete with no workspace and the workspace's name in its data, and says when there was no backup.
- **Its stored files** (platform storage or the workspace's own bucket) are **not** deleted with it. The delete records, per storage location, the key prefix (the workspace's storage code), any older-layout keys, how many files and how many bytes (`deleted_workspace_storage`, migration `6d4b5730ec18`). The daily system task **Purge Deleted Workspace Storage** deletes them **30 days** after the delete. **Admin → Storage → Files of deleted workspaces** lists what is waiting: **Purge now** deletes at once, **Keep** means never purged. API: `GET /api/admin/storage/deleted-workspaces`, `POST …/{id}/purge`, `POST …/{id}/keep` (audited as `platform_settings_changed`). A workspace's own bucket is reached through its connection and keys, which go with the workspace, so the delete copies the keys into platform secrets named `DELETED_WS_<id>_<SETTING>` and removes them when the files are purged or kept. With `SECRET_BACKEND=env` Marvin can't store them: that location is listed as unreachable and its files stay in the bucket. Workspace backups in a workspace's own backup bucket, and bundles in `DATA_DIR/backups`, are not touched.
- **Restoring a deleted workspace.** Create a workspace and import its bundle (**Admin → Backups → Import**); the new workspace has a new id. See [Off-site backup](offsite-backup.md#one-workspace-from-a-bundle).

## Scheduler

Every API process starts the scheduler; a database lease (`services/scheduler/leader.py`, one row, conditional `UPDATE`) makes exactly one replica run each tick, on SQLite as well as Postgres. `SCHEDULER_INTERVAL_SECONDS` (default 60) is the frequent tick that delivers webhooks, fires due scheduled tasks and renews the lease, so a task can run up to one interval late. `SCHEDULER_LEASE_TTL_SECONDS` (default 150) must be at least twice the interval or the app refuses to start. Set `SCHEDULER_ENABLED=false` on pods that should only serve requests. The same tick also sends queued site rebuilds (see [Site rebuilds](#site-rebuilds)). System tasks seeded at startup (idempotently by slug, so an upgrade adds new ones): `prune_event_logs`, `prune_ai_executions`, `prune_scheduled_task_executions` and `resync_smart_collections` on a 24-hour interval, and since rc.170 `publish_scheduled_entries` and `unpublish_expired_entries` every 5 minutes, so entries' Scheduled Publish and Expiration Date work with no setup (see [Scheduled tasks](whats-new/scheduled-tasks.md)). Idle runs of the 5-minute tasks write no execution row. `DAILY_SCHEDULE_TIME` (default `23:47`, local server time) sets the scheduler's daily callback, which has no built-in jobs today.

## Site rebuilds

A static site is rebuilt by an outgoing webhook (a deploy hook) subscribed to `webhook_triggered`. The `request_site_rebuild` handler, run from a workflow step or a scheduled task, does not send that event directly: it queues one rebuild per workspace (`services/site_rebuild.py`). The scheduler tick sends the queued rebuild once no new request has arrived for `SITE_REBUILD_QUIET_SECONDS` (default 60), or once the first request is `SITE_REBUILD_MAX_WAIT_SECONDS` old (default 600), so a bulk edit that fires a workflow per entry costs one build. Expect a single change to start building up to the quiet period plus one scheduler interval later. The request that opens a batch emits `site_rebuild_queued` once, which the admin shows as a "Site rebuild queued" toast until the rebuild is sent. The sent event's message counts the coalesced requests, and its data carries `requestCount` and the changes it covers (the newest 50, repeat edits of one thing collapsed), which the admin's **Site rebuild** toast lists. Since rc.143 published content changes queue a rebuild too, unless the workspace turns off **Rebuild the site automatically** under **Settings → General** (see [Publishing API → Site rebuilds](whats-new/publishing-api.md#site-rebuilds)). An EDITOR can also queue one with `POST /api/platform/site/rebuild` and read the queue and the last build with `GET` on the same path; the POST answers 409 when no enabled webhook or integration action is on `webhook_triggered`.

## Integration downloads

Integration providers call outside services through Marvin's HTTP client. A response larger than `INTEGRATION_HTTP_MAX_BYTES` (default 5,000,000 bytes) is refused and the provider sees an error. Raise it for providers that move files such as images.

## Storage

`STORAGE_PROVIDER` is `local` (default) or `s3`. Local files live in `STORAGE_LOCAL_ROOT` (default `DATA_DIR/assets`) and mount at `STORAGE_LOCAL_PUBLIC_URL` (default `/assets`, must stay a `/`-rooted path). Set `STORAGE_LOCAL_PUBLIC_BASE_URL` (new in rc.40, e.g. `https://api.example.com/assets`) when a site is served from another origin so asset URLs are absolute. S3-compatible storage (`s3`) is the `marvin-storage-s3` plugin, baked into the image (core's own S3 provider was removed in storage slice 7); its settings are `STORAGE_S3_ENDPOINT`, `STORAGE_S3_BUCKET`, `STORAGE_S3_REGION` (default `auto`), `STORAGE_S3_ACCESS_KEY`, `STORAGE_S3_SECRET_KEY` and optionally `STORAGE_REMOTE_PUBLIC_URL` for a CDN domain.

Files of a deleted workspace are purged 30 days after the delete, by a daily task, unless kept: see [Workspaces](#workspaces-first-boot-deleting-and-what-stays-behind).

The platform's bubble-character library (see [Agents and Ask](whats-new/agents-and-ask.md)) stores its packs through the same provider, outside any workspace: under `_platform/character-packs/<pack id>/` (on local storage, inside `STORAGE_LOCAL_ROOT`), served by the same public URL as asset files. A workspace's own bubble character is stored as ordinary workspace assets.

Since rc.159 an upload makes an image's opaque solid background transparent. Files stored before that can be cleaned the same way with `python -m marvin.scripts.repair_character_mattes`, run where the backend runs: on its own it lists what would change, and `--apply` overwrites each changed file in place at its storage key, so stored URLs keep working. It covers library packs and every workspace's and agent's own upload. A browser that cached a file may show the old one until a hard refresh.

## Admin overview

**Admin → Overview** (`GET /api/admin/overview`) opens with a health strip — one dot per thing that can be wrong
(backup problems, failing scheduled tasks, open integration alerts, unpriced AI runs this month, a stale price feed,
push keys, emailed links still pointing at localhost, and plugins with a newer release), each linking to its page —
then the version, people, plugins, backups, events and tasks cards, then **Workspaces** (entries, members, AI spend
this month against the workspace's limit, open alerts, last activity) and **AI spend** for the last 30 days across all
workspaces, each day's bar shaded by the share of the prompt the providers served from cache.

Below them, **Recent sign-ins** lists the eight people who signed in last, newest first, from the time each password,
LDAP or OpenID sign-in is recorded on the account (sign-ins before this release aren't known). **Plugin updates**
lists each plugin installed from a GitHub release whose repository has a newer version tag, with the installed and
newest versions. The check asks GitHub at most every 12 hours, in the background, so the page never waits on it and
the first look after a restart shows the previous answer. Taking an update is a Marvin release: bump the plugin's pin
in the `plugins` dependency group. The same cached answer puts an "update available → vX.Y" note on that plugin's row
in **Admin → Plugins** (`latestVersion` on `GET /api/admin/plugins`); it is a notice only, and never waits on GitHub.

**Admin → System** has an **Embeddings** card (`embeddings` on `GET /api/admin/about`) for the built-in search model:
whether it is on (`EMBEDDINGS_BUILTIN_ENABLED`) and usable, the model and its vector size, the fastembed and ONNX
Runtime versions, and every embedding model that has chunks stored, platform-wide, with how many. A model other than
the one in use is a stale index: its chunks are not searched until the workspace is reindexed (Settings → AI). The card
reads settings, package metadata and one count, so opening the page never loads the model.

**Admin → Site Settings** lists every setting the API runs with, warns at the top when the public UI address
(`BASE_URL` / `FRONTEND_URL`, the chart's `config.publicUiUrl`) is still localhost, and has a **Security** card: the
minimum password length, reset-link lifetime, sign-in session length and the sign-in throttling limits. A value set
there replaces the environment variable of the same name for the whole platform; a cleared box goes back to it.
**Admin → Email → Branding** sets the product name, footer line and accent colour every email shows.

## Retention

| What | Setting | Default |
|---|---|---|
| Event log (`prune_event_logs`) | `EVENT_LOG_RETENTION_DAYS` | 90 days; `0` keeps forever; overridable per task |
| AI executions (`prune_ai_executions`) | `AI_EXECUTION_RETENTION_DAYS` | 90 days; a workspace's `logging_config.retention_days` overrides |
| Scheduled-task execution log (`prune_scheduled_task_executions`) | task config `retention_days` | 30 days (rc.97) |
| Revoked API tokens and site clients (`prune_revoked_tokens`) | task config `age_days` | 30 days after revocation |
| Remote MCP sign-ins, tokens, connections and clients (`purge_oauth_records`) | task config `grant_days`, `client_days` | expired sign-ins and tokens at once; connections 90 days after revocation or their last token; clients 7 days unused with no connection |
| Workflow runs and their steps (`prune_workflow_runs`) | `WORKFLOW_RUN_RETENTION_DAYS` | 90 days after the run finished; a run still running or waiting is never deleted; `0` keeps forever |

Since rc.96 an automatic run whose handler returns `None` writes no execution row; manual runs always do.

## Backups

Admin: **Admin → Operations → Backups** (`/admin/backups`) and `/api/admin/backups` (`GET` list, `POST /workspaces/{workspace_id}`, `GET /workspaces/{workspace_id}/key`, `GET /{filename}`, `POST /workspaces/{workspace_id}/import`). Per workspace: **Settings → General → Backups** (`/workspace/settings/backups`) and `/api/platform/workspace` with `POST /backups`, `GET /backups`, `GET /backups/{filename}`, `GET /backup-key`, `GET /export`, `GET /export/pretty`, `POST /import`. Maintenance actions (temp cleanup, revoked-token cleanup, event cleanup, DB optimize, cache clear, stats) are under `/api/admin/maintenance`.

These are per-workspace content exports kept on the data volume. For the whole installation (users, tokens, event logs, the `.secret`, uploaded files) copied off the cluster every hour, see [Off-site backup](offsite-backup.md). To get backup and other platform alerts by email or Slack, see [Getting alerts outside Marvin](offsite-backup.md#getting-alerts-outside-marvin).

## Settings reference

| Variable | Default | Notes |
|---|---|---|
| `PRODUCTION` | `false` | enables the `.secret` file, sentinel replacement of unresolved `{{SLUG}}`s, strict CORS |
| `ENVIRONMENT_LABEL` | empty | short tag for a non-production instance, e.g. `DEV` or `STAGING`; stripped, upper-cased, cut to 12 characters. When set, the app and admin headers and the login page show it as a badge (amber for `DEV…`, purple for `STAG…`, neutral otherwise) and every tab title starts `[DEV] `. Empty shows nothing. Served on the public `/api/app/about/login-info` and the admin about endpoint as `environmentLabel`. Independent of `PRODUCTION` (runtime mode) and `IS_DEMO` (public demo). Chart: `config.environmentLabel` |
| `BASE_URL` | `http://localhost:8080` | public API URL |
| `FRONTEND_URL` | `http://localhost:4322` | public admin URL; `FRONTEND_PORT` is derived from it. When set to anything but the default, entry links that AI tools hand back are absolute |
| `API_PORT` | `8080` | port the API listens on (all interfaces) |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | unset | how long the server waits for in-flight requests after SIGTERM; unset waits until the process is killed. The Helm chart derives it from the grace period (see [Helm chart](#helm-chart)) |
| `CORS_ORIGINS` | empty | comma list; ignored outside production |
| `PUBLIC_API_URL` | empty | the API's public address; the remote MCP server's OAuth issuer (its resource is this plus `/mcp`). Chart: `config.publicApiUrl`, which also sets the frontend's `PUBLIC_MARVIN_API_URL` |
| `MCP_REMOTE_ENABLED` | `false` | the remote MCP server's switch; Admin → Site Settings → Remote MCP overrides it. With `MCP_ACCESS_TOKEN_MINUTES` (60), `MCP_REFRESH_TOKEN_DAYS` (30) and `MCP_GRANT_MAX_DAYS` (180); see [MCP and OAuth](auth-and-tokens.md#mcp-and-oauth) |
| `DATA_DIR` | unset | database, `.secret`, assets, secrets, seeds |
| `DB_ENGINE` | auto | `sqlite` or `postgres`. Unset: Postgres when `POSTGRES_SERVER` or `POSTGRES_URL_OVERRIDE` is set, else SQLite (a fresh install). SQLite is one process on one file: run **one replica** (the chart enforces it); see [SQLite](sqlite.md). `sqlite_to_postgres` moves a SQLite database to Postgres |
| `DB_SQLITE_PATH` | `DATA_DIR/marvin.db` | the SQLite file |
| `DB_SQLITE_WAL_MODE` / `DB_SQLITE_BUSY_TIMEOUT_MS` / `DB_SQLITE_WRITE_WARN_SECONDS` | `true` / `30000` / `5` | SQLite write-ahead logging, lock wait, and the slow-write-transaction warning |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_DB` | empty | or `POSTGRES_URL_OVERRIDE` for a full URL |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | SQLAlchemy pool |
| `AUTO_MIGRATE` | `true` | run Alembic at startup |
| `API_DOCS` | `true` | Swagger and ReDoc; `/openapi.json` stays public either way |
| `LOG_LEVEL` | `info` | |
| `TOKEN_TIME` | `48` | session hours |
| `ALLOW_SIGNUP` | `false` | |
| `DEFAULT_EMAIL` / `DEFAULT_PASSWORD` | `changeme@example.com` / unset | first super admin, who signs in to Admin; no workspace is created |
| `DEFAULT_GROUP` | retired | names nothing since a fresh install creates no workspace; a startup warning while it is set (see [Workspaces](#workspaces-first-boot-deleting-and-what-stays-behind)) |
| `SEED_ON_STARTUP` | `false` | |
| `SCHEDULER_ENABLED` / `SCHEDULER_INTERVAL_SECONDS` / `SCHEDULER_LEASE_TTL_SECONDS` | `true` / `60` / `150` | see Scheduler; the interval must be at least 10 |
| `SITE_REBUILD_QUIET_SECONDS` | `60` | quiet period before a queued site rebuild is sent; see [Site rebuilds](#site-rebuilds) |
| `SITE_REBUILD_MAX_WAIT_SECONDS` | `600` | longest a queued rebuild waits; must be at least `SITE_REBUILD_QUIET_SECONDS` |
| `INTEGRATION_HTTP_MAX_BYTES` | `5000000` | largest response an integration provider may download; must be at least 1 |
| `MEDIA_EMBEDS_FETCH_ENABLED` | `true` | ask media providers' oEmbed for link titles and player ids; off builds players from the link alone. See [Media embeds](whats-new/media-embeds.md#settings) |
| `EVENT_LOG_RETENTION_DAYS` / `AI_EXECUTION_RETENTION_DAYS` | `90` / `90` | |
| `STORAGE_PROVIDER` | `local` | see Storage |
| `SECRET_BACKEND` | `database` | `disk`, `env`, `vault`, `bitwarden` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_NAME`, `SMTP_FROM_EMAIL`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_AUTH_STRATEGY` | unset / `587` / `Marvin` / unset / unset / unset / `TLS` | email |
| `AI_PRICE_FEED_URL` | LiteLLM's `model_prices_and_context_window.json` on GitHub | the daily AI price feed's default URL (LiteLLM's format, https); Admin → AI Pricing can override it or switch the feed off |
| `AI_DEFAULT_PROVIDER` | empty | Empty: the first installed of `openai`, `anthropic`, `google`, `azure`, `ollama` (then any other installed provider), logged at startup; with no provider installed it only warns and platform AI is off. Set to a provider nothing provides, startup stops. OpenAI and Azure OpenAI come from the `marvin-ai-openai` plugin (baked into the image with the other site-wide plugins). `OPENAI_API_KEY`, `OPENAI_MODEL` (`gpt-4o-mini`), `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, `GOOGLE_BASE_URL`, `AZURE_BASE_URL`, `OLLAMA_BASE_URL`. The official OpenAI API is called through the Responses API; an `OPENAI_BASE_URL` pointing elsewhere (an OpenAI-compatible server) uses Chat Completions |
| `AI_DEFAULT_TEMPERATURE` | unset | sent with every AI call only when set; unset (the default since rc.149; it was `0.7`) lets each model use its own, and some reasoning models refuse any other value |
| `AI_DEFAULT_MAX_TOKENS` | unset | output-token cap when a workspace sets no **Max output tokens per request** |
| `AI_BUDGET_WARNING_PERCENT` | `80` | percent of a workspace's monthly AI cost limit that fires `ai_budget_threshold_reached` and its toast; `0` turns the warning off |
| `DOCS_BASE_URL` | `https://inneropen.github.io/marvin/` | where this manual is published; `search_docs` / `read_doc` link each section here (the text itself comes from the manual bundled with the install) |
| `MCP_TOOL_TIMEOUT_SECONDS` | `45` | how long an agent waits for one external MCP tool call; keep it well under the proxy's request timeout. Must be above 0 (rc.146) |
| `MCP_TOOL_RESULT_MAX_CHARS` | `20000` | longest external MCP tool result an agent sees; longer ones are cut with a note. Must be above 0 (rc.146) |
| `AI_ALLOW_WORKSPACE_CREDENTIALS` | `true` | workspaces may store their own provider keys |
| `AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS` | `0` | how long after startup to mark AI runs left `running` by an earlier process as failed; `0` sweeps at startup. The Helm chart sets the grace period plus 60 seconds under a rolling update, `0` under `Recreate` |
| `AI_PARKED_RUN_TTL_HOURS` | `168` | how long an agent run waiting for your approval stays decidable (7 days). An hourly task ends older ones: the pending actions are denied, the run fails "expired" and `approval_rejected` fires with reason `expired`. `0` keeps them forever |
| `AI_HANDOFF_MAX_DEPTH` | `1` | how deep agent hand-offs nest: `1` lets the main agent hand off to a specialist that cannot hand off further, `2` lets that specialist hand off once more; `0` turns hand-offs off. Each level runs inside the request of the level above |
| `OIDC_*`, `LDAP_*`, `SECURITY_*`, `AUTH_COOKIE_NAME` | see [Auth and tokens](auth-and-tokens.md) | |

The full list with docstrings is `src/marvin/core/settings/settings.py`; `docs/archive/configuration-settings.md` in the repo is older and not checked against rc.186.
