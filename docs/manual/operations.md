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

`marvin-chart/` is the current deployment unit; read [`marvin-chart/README.md`](https://github.com/InnerOpen/marvin/blob/develop/marvin-chart/README.md) for install commands. `mode: combined` (default) runs the single image; `mode: split` creates backend and frontend Deployments from the `-backend` / `-frontend` images. Overlays: `values-k8s.yaml`, `values-staging.yaml`, `values-production.yaml`. Probes default to `/healthz` (liveness, initial delay 30 s, period 10 s) and `/readyz` (readiness, initial delay 10 s, period 5 s). Use `extraEnv` for settings the chart does not model and `initContainers` plus `extraVolumes` to install integration plugins before start (worked example in the chart README).

**Graceful shutdown.** An agent run is one synchronous request that can take minutes, so a deploy lets in-flight requests finish before the API pod goes away. `shutdown.terminationGracePeriodSeconds` (default 300) is the pod's grace period and `shutdown.preStopSleepSeconds` (default 5; 0 drops the hook) a sleep before SIGTERM so the Service stops routing to the pod first. On SIGTERM the server stops taking connections and waits up to `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` for running requests; the chart sets it to the grace period minus the preStop sleep and 15 seconds for shutdown and exit. A run still going at the deadline is lost, and the next process marks it failed (see [Agents and Ask → Interrupted runs](whats-new/agents-and-ask.md)); the chart delays that sweep (`AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS`) to the grace period plus 60 seconds, so it never fails a run the old pod is still finishing.

The trade-off: a pod with a long run in flight takes that long to stop. Under the default `RollingUpdate` the new pod serves while the old one drains, so with SQLite on a shared volume two processes write at once for up to the grace period. To rule that out, set the API pod's strategy to `{type: Recreate}` (`strategy` in combined mode; in split mode the backend's own `split.backend.strategy`, so the frontend keeps rolling) and accept downtime while the old pod drains, or use Postgres. Under `Recreate` the chart sweeps interrupted runs at startup, since the old pod is already gone.

!!! warning "Two chart keys the app does not read"
    - `JWT_SECRET` is rendered into the Deployment (`templates/deployment.yaml`, `_helpers.tpl`) but nothing in `src/` reads it. The signing secret is `DATA_DIR/.secret`, generated on first production start; keep `DATA_DIR` on a persistent volume or every restart invalidates sessions.
    - `config.webhookRetryAttempts` and `config.webhookRetryDelay` land in the ConfigMap but nothing in `src/` reads them.

    `docs/HELM_DEPLOYMENT_GUIDE.md` and `docs/OPENSHIFT_DEPLOYMENT.md` predate this and are superseded on these two points.

## Scheduler

Every API process starts the scheduler; a database lease (`services/scheduler/leader.py`, one row, conditional `UPDATE`) makes exactly one replica run each tick, on SQLite as well as Postgres. `SCHEDULER_INTERVAL_SECONDS` (default 60) is the frequent tick that delivers webhooks, fires due scheduled tasks and renews the lease, so a task can run up to one interval late. `SCHEDULER_LEASE_TTL_SECONDS` (default 150) must be at least twice the interval or the app refuses to start. Set `SCHEDULER_ENABLED=false` on pods that should only serve requests. The same tick also sends queued site rebuilds (see [Site rebuilds](#site-rebuilds)). System tasks seeded at startup (idempotently by slug, so an upgrade adds new ones): `prune_event_logs`, `prune_ai_executions`, `prune_scheduled_task_executions` and `resync_smart_collections` on a 24-hour interval, and since rc.170 `publish_scheduled_entries` and `unpublish_expired_entries` every 5 minutes, so entries' Scheduled Publish and Expiration Date work with no setup (see [Scheduled tasks](whats-new/scheduled-tasks.md)). Idle runs of the 5-minute tasks write no execution row. `DAILY_SCHEDULE_TIME` (default `23:47`, local server time) sets the scheduler's daily callback, which has no built-in jobs today.

## Site rebuilds

A static site is rebuilt by an outgoing webhook (a deploy hook) subscribed to `webhook_triggered`. The `request_site_rebuild` handler, run from a workflow step or a scheduled task, does not send that event directly: it queues one rebuild per workspace (`services/site_rebuild.py`). The scheduler tick sends the queued rebuild once no new request has arrived for `SITE_REBUILD_QUIET_SECONDS` (default 60), or once the first request is `SITE_REBUILD_MAX_WAIT_SECONDS` old (default 600), so a bulk edit that fires a workflow per entry costs one build. Expect a single change to start building up to the quiet period plus one scheduler interval later. The request that opens a batch emits `site_rebuild_queued` once, which the admin shows as a "Site rebuild queued" toast until the rebuild is sent. The sent event's message counts the coalesced requests, and its data carries `requestCount` and the changes it covers (the newest 50, repeat edits of one thing collapsed), which the admin's **Site rebuild** toast lists. Since rc.143 published content changes queue a rebuild too, unless the workspace turns off **Rebuild the site automatically** under **Settings → General** (see [Publishing API → Site rebuilds](whats-new/publishing-api.md#site-rebuilds)).

## Integration downloads

Integration providers call outside services through Marvin's HTTP client. A response larger than `INTEGRATION_HTTP_MAX_BYTES` (default 5,000,000 bytes) is refused and the provider sees an error. Raise it for providers that move files such as images.

## Storage

`STORAGE_PROVIDER` is `local` (default) or `s3`. Local files live in `STORAGE_LOCAL_ROOT` (default `DATA_DIR/assets`) and mount at `STORAGE_LOCAL_PUBLIC_URL` (default `/assets`, must stay a `/`-rooted path). Set `STORAGE_LOCAL_PUBLIC_BASE_URL` (new in rc.40, e.g. `https://api.example.com/assets`) when a site is served from another origin so asset URLs are absolute. S3-compatible storage uses `STORAGE_S3_ENDPOINT`, `STORAGE_S3_BUCKET`, `STORAGE_S3_REGION` (default `auto`), `STORAGE_S3_ACCESS_KEY`, `STORAGE_S3_SECRET_KEY` and optionally `STORAGE_REMOTE_PUBLIC_URL` for a CDN domain.

The platform's bubble-character library (see [Agents and Ask](whats-new/agents-and-ask.md)) stores its packs through the same provider, outside any workspace: under `_platform/character-packs/<pack id>/` (on local storage, inside `STORAGE_LOCAL_ROOT`), served by the same public URL as asset files. A workspace's own bubble character is stored as ordinary workspace assets.

Since rc.159 an upload makes an image's opaque solid background transparent. Files stored before that can be cleaned the same way with `python -m marvin.scripts.repair_character_mattes`, run where the backend runs: on its own it lists what would change, and `--apply` overwrites each changed file in place at its storage key, so stored URLs keep working. It covers library packs and every workspace's and agent's own upload. A browser that cached a file may show the old one until a hard refresh.

## Retention

| What | Setting | Default |
|---|---|---|
| Event log (`prune_event_logs`) | `EVENT_LOG_RETENTION_DAYS` | 90 days; `0` keeps forever; overridable per task |
| AI executions (`prune_ai_executions`) | `AI_EXECUTION_RETENTION_DAYS` | 90 days; a workspace's `logging_config.retention_days` overrides |
| Scheduled-task execution log (`prune_scheduled_task_executions`) | task config `retention_days` | 30 days (rc.97) |

Since rc.96 an automatic run whose handler returns `None` writes no execution row; manual runs always do.

## Backups

Admin: **Admin → Operations → Backups** (`/admin/backups`) and `/api/admin/backups` (`GET` list, `POST /workspaces/{workspace_id}`, `GET /workspaces/{workspace_id}/key`, `GET /{filename}`, `POST /workspaces/{workspace_id}/import`). Per workspace: **Settings → General → Backups** (`/workspace/settings/backups`) and `/api/platform/workspace` with `POST /backups`, `GET /backups`, `GET /backups/{filename}`, `GET /backup-key`, `GET /export`, `GET /export/pretty`, `POST /import`. Maintenance actions (temp cleanup, revoked-token cleanup, event cleanup, DB optimize, cache clear, stats) are under `/api/admin/maintenance`.

## Settings reference

| Variable | Default | Notes |
|---|---|---|
| `PRODUCTION` | `false` | enables the `.secret` file, sentinel replacement of unresolved `{{SLUG}}`s, strict CORS |
| `BASE_URL` | `http://localhost:8080` | public API URL |
| `FRONTEND_URL` | `http://localhost:4322` | public admin URL; `FRONTEND_PORT` is derived from it. When set to anything but the default, entry links that AI tools hand back are absolute |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8080` | bind address |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | unset | how long the server waits for in-flight requests after SIGTERM; unset waits until the process is killed. The Helm chart derives it from the grace period (see [Helm chart](#helm-chart)) |
| `CORS_ORIGINS` | empty | comma list; ignored outside production |
| `DATA_DIR` | unset | database, `.secret`, assets, secrets, seeds |
| `DB_ENGINE` | `sqlite` | or `postgres` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_DB` | empty | or `POSTGRES_URL_OVERRIDE` for a full URL |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | SQLAlchemy pool |
| `DB_SQLITE_WAL_MODE` | `true` | |
| `AUTO_MIGRATE` | `true` | run Alembic at startup |
| `API_DOCS` | `true` | Swagger and ReDoc; `/openapi.json` stays public either way |
| `LOG_LEVEL` | `info` | |
| `TOKEN_TIME` | `48` | session hours |
| `ALLOW_SIGNUP` | `false` | |
| `DEFAULT_EMAIL` / `DEFAULT_PASSWORD` | `changeme@example.com` / unset | first super admin |
| `DEFAULT_GROUP` | `Default` | first workspace |
| `SEED_ON_STARTUP` | `false` | |
| `SCHEDULER_ENABLED` / `SCHEDULER_INTERVAL_SECONDS` / `SCHEDULER_LEASE_TTL_SECONDS` | `true` / `60` / `150` | see Scheduler; the interval must be at least 10 |
| `SITE_REBUILD_QUIET_SECONDS` | `60` | quiet period before a queued site rebuild is sent; see [Site rebuilds](#site-rebuilds) |
| `SITE_REBUILD_MAX_WAIT_SECONDS` | `600` | longest a queued rebuild waits; must be at least `SITE_REBUILD_QUIET_SECONDS` |
| `INTEGRATION_HTTP_MAX_BYTES` | `5000000` | largest response an integration provider may download; must be at least 1 |
| `EVENT_LOG_RETENTION_DAYS` / `AI_EXECUTION_RETENTION_DAYS` | `90` / `90` | |
| `STORAGE_PROVIDER` | `local` | see Storage |
| `SECRET_BACKEND` | `database` | `disk`, `env`, `vault`, `bitwarden` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_NAME`, `SMTP_FROM_EMAIL`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_AUTH_STRATEGY` | unset / `587` / `Marvin` / unset / unset / unset / `TLS` | email |
| `AI_DEFAULT_PROVIDER` | `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` (`gpt-4o-mini`), `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, `GOOGLE_BASE_URL`, `AZURE_BASE_URL`, `OLLAMA_BASE_URL`. The official OpenAI API is called through the Responses API; an `OPENAI_BASE_URL` pointing elsewhere (an OpenAI-compatible server) uses Chat Completions |
| `AI_DEFAULT_TEMPERATURE` | unset | sent with every AI call only when set; unset (the default since rc.149; it was `0.7`) lets each model use its own, and some reasoning models refuse any other value |
| `AI_DEFAULT_MAX_TOKENS` | unset | output-token cap when a workspace sets no **Max output tokens per request** |
| `AI_BUDGET_WARNING_PERCENT` | `80` | percent of a workspace's monthly AI cost limit that fires `ai_budget_threshold_reached` and its toast; `0` turns the warning off |
| `DOCS_BASE_URL` | `https://inneropen.github.io/marvin/` | where this manual is published; `search_docs` / `read_doc` link each section here (the text itself comes from the manual bundled with the install) |
| `MCP_TOOL_TIMEOUT_SECONDS` | `45` | how long an agent waits for one external MCP tool call; keep it well under the proxy's request timeout. Must be above 0 (rc.146) |
| `MCP_TOOL_RESULT_MAX_CHARS` | `20000` | longest external MCP tool result an agent sees; longer ones are cut with a note. Must be above 0 (rc.146) |
| `AI_ALLOW_WORKSPACE_CREDENTIALS` | `true` | workspaces may store their own provider keys |
| `AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS` | `0` | how long after startup to mark AI runs left `running` by an earlier process as failed; `0` sweeps at startup. The Helm chart sets the grace period plus 60 seconds under a rolling update, `0` under `Recreate` |
| `OIDC_*`, `LDAP_*`, `SECURITY_*`, `AUTH_COOKIE_NAME` | see [Auth and tokens](auth-and-tokens.md) | |

The full list with docstrings is `src/marvin/core/settings/settings.py`; `docs/configuration-settings.md` in the repo is older and not checked against rc.186.
