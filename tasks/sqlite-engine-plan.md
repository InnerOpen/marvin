# Plan: SQLite back as a supported engine — the fresh-install default (2026-10-18)

Jared (2026-10-18): "On a fresh install if it's selected (by default) then it uses it." Postgres is used when configured;
prod/dev on OpenShift stay on Postgres (chart pins `dbEngine: postgres`). SQLite was removed by `2fb44737` (engine,
chart, CI), `e4743d5a` (CI fallout), `694bd7be` (backup engine) after a misunderstanding (Jared meant deleting the SQLite
database, not the engine). Pre-removal code to restore: `2fb44737^`, `694bd7be^`. Drafted from the code; nothing built.

## 0. Model (proposed)
- One resolver `db_providers.resolve_engine(env)`: explicit `DB_ENGINE` wins; unset → `postgres` if `POSTGRES_SERVER` or
  `POSTGRES_URL_OVERRIDE` is set, else `sqlite` (Q1). Used everywhere the engine is read (`settings.py:691,1164`,
  `backup_engine/engine.py:138`, `recorder.py:205`, `scripts/backup.py:135` — all hard-code `"postgres"` today).
- Startup guard: engine defaulted to sqlite but DATA_DIR has `.secret` and no `marvin.db` → refuse to start (an existing
  install lost its DB config). Must run before `determine_secrets` creates `.secret` (`settings.py:~1155`).
- File `DATA_DIR/marvin.db`, override `DB_SQLITE_PATH` (Q5). Single writer process.

## 1. Findings
| # | Where | Problem on SQLite | Fix |
|---|---|---|---|
| 1 | `core/settings/db_providers.py:127-141` | raises for sqlite | restore `SQLiteProvider` (`2fb44737^`), + `DB_SQLITE_PATH` |
| 2 | `db/db_setup.py:31-38` | no pragmas / `check_same_thread` | Stage 1 |
| 3 | `services/dashboard.py:337` | `func.date_trunc` PG-only; swallowed by `except` at :342 → "published by week" silently empty | `func.date(…, type_=sa.Date)` + week buckets in Python |
| 4 | `services/admin_overview.py:240-253` | `func.date()` returns str on SQLite → AI spend silently zero | `sa.func.date(Run.started_at, type_=sa.Date)` |
| 5 | `services/database_report.py:111-115` | `pg_database_size`, `pg_stat_user_tables` → Admin → Database & cleanup 500 | dialect branch: `PRAGMA page_count*page_size`, `dbstat` if available else `count(*)` per table |
| 6 | `routes/admin/maintenance_controller.py:165` | `pg_database_size` swallowed → 0 | file + `-wal` size |
| 7 | `scheduled_tasks/handlers/maintenance.py:516-522` | works | + `PRAGMA wal_checkpoint(TRUNCATE)` after VACUUM |
| 8 | `services/metrics.py:240` | `with_for_update()` no-op → lost update on concurrent adds | Stage 3 |
| 9 | `metrics.py:233,259`, `automation/idempotency.py:105`, `actions/email.py:111`, `security/login_throttle.py:146` | `begin_nested()` + pysqlite default txn: RELEASE of a first-write SAVEPOINT commits → later rollback can't undo the claim | pysqlite recipe (Stage 1) |
| 10 | 10 models with `DateTime(timezone=True)` (scheduled_tasks, scheduler_lock, integration_errors, alert_incidents, automation_executions, webhooks, incoming_webhooks, event_log, integrations, webhook_execution_logs) | SQLite returns naive → `TypeError` vs aware `now` | `AwareDateTime` TypeDecorator (`_model_utils/datetime.py`), UTC on read, no migration |
| 11 | 88 `String(N)` columns | length ignored (column-length trap) | SQLite-only `before_flush` length check raising like PG (Q6) |
| 12 | `schemas/response/query_search.py:155`, `db/init_db.py:357` | pg_trgm fuzzy search PG-only → tokenized LIKE | accept + document (Q7) |
| 13 | `tests/test_scheduler_leader.py:173`, `test_webhook_mode_enum.py:19` | skipped on SQLite | unskip leader race after Stage 3; enum skip correct |

Fine already: all 20 migrations since 2026-10-13 are portable (batch_alter_table, sa.JSON, portable defaults; no JSONB /
postgresql_where / CONCURRENTLY); `5b0e7d2c9a41` guarded; `efee4271020c` has `sqlite_where`. No RETURNING / DISTINCT ON /
advisory locks / `jsonb_*` in app code; `automation/engine.py:118-126` picks the sqlite insert; `selector.py:93`,
`entries/query.py:165` branch on dialect. No pgvector (embeddings JSON + numpy). JSON NULL same. Search uses `ilike`.
Collation differs (accept).

## 2. Stage 1 — engine back, default, chart pin, pragmas (DONE, `99751304`)
- [x] Provider + settings (#1, resolver, guard); restore `DB_SQLITE_WAL_MODE`; add `DB_SQLITE_BUSY_TIMEOUT_MS=30000`.
- [x] (built: BEGIN is issued lazily before the first write or SAVEPOINT, not in the `begin` event — an eager BEGIN held every
  session's first read as a snapshot and made read-then-write fail at once with SQLITE_BUSY_SNAPSHOT, 168 test failures;
  `sqlite_begin=IMMEDIATE` is the execution option `begin_write` uses.) `db_setup.py` (SQLite only): `check_same_thread=False`; on connect `foreign_keys=ON`, `journal_mode=WAL`,
  `synchronous=NORMAL`, `busy_timeout`; SQLAlchemy pysqlite recipe (`isolation_level=None` + `begin` listener emitting
  `BEGIN`, or `BEGIN IMMEDIATE` with execution option `sqlite_begin="IMMEDIATE"`); log the SQLite version, refuse < 3.35.
  `alembic/env.py:115` keeps its own engine **without** the FK pragma (batch rebuilds with FKs on would cascade-delete
  children) — comment + test.
- [x] Chart: `_helpers.tpl:248-257` accepts `sqlite|postgres`; default `config.dbEngine: sqlite`,
  `postgres.cluster.enabled: false` (Q2); explicit pins `dbEngine: postgres` + `postgres.cluster.enabled: true` in
  `values-iwobble.yaml:35,177`, `values-dev.yaml:30,44`, `values-k8s.yaml:25` and **`values-production.yaml` (no pin
  today, `replicaCount: 2` at :5)**. SQLite guards: fail on `replicaCount>1`, `split.backend.replicaCount>1` or
  persistence off; force `strategy: Recreate`.
- [x] Compose: `docker-compose.yml:37` → `${DB_ENGINE:-sqlite}`; Postgres back behind `profiles: [postgres]`.
- [x] Taskfile: `dev:clean` removes `marvin*.db`; `py:test`/`py:coverage` per Q8.
- [x] Drop "retired" wording (`sqlite_to_postgres` :821, `backup_engine/engine.py:72-87`); converter stays as the
  sqlite → Postgres upgrade path.

## 3. Stage 2 — dialect-neutral code (DONE, `bc57be33`)
Fix #3–7, #10–12. `tests/test_dialect_neutral.py` runs every dashboard/overview widget with seeded data and asserts
non-empty results (the swallow-and-return-empty pattern at `dashboard.py:299-302,342` hid #3/#4). Migrations
up → down → up on a SQLite file.

## 4. Stage 3 — concurrency-sensitive features (DONE)
- [x] `db/locking.py::begin_write(session)`: ends the current txn; on SQLite the next starts `BEGIN IMMEDIATE` (write lock up
  front; busy_timeout waits instead of SQLITE_BUSY_SNAPSHOT); no-op on Postgres.
- [x] Metric add (`metrics.py:220-275`): atomic `UPDATE … SET value = value + :amount` (correct on both; no FOR UPDATE);
  insert keeps unique constraint + IntegrityError → update; `begin_write` first; #9 makes "failure rolls the claim back"
  hold on SQLite.
- [x] Idempotency claims (`idempotency.py:76-117`), email once-per (`actions/email.py:100-117`), upload link one-use
  (`mcp_remote/uploads.py:192-203`): already portable (unique + compare-and-set) — add `begin_write`.
- [x] Workflow entry turn (`engine.py:105-127`), scheduler lease (`leader.py:96-104`), login throttle: portable.
- [x] Watchdog: on SQLite warn when a write txn stays open > 5 s (a session held across an LLM/HTTP call blocks all writers).
- [x] Acceptance: race tests `test_workflow_metrics.py:349`, `test_remote_mcp_uploads.py:206`, `test_scheduler_leader.py:160`
  (unskipped) pass 20× in a row on SQLite.

## 5. Stage 4 — backups and restore per engine (DONE)
- Left by Stages 1-3: `check_engine` / `BackupSettings.from_env` raise "does not back up SQLite yet" for a sqlite engine; the 8
  `tests/test_backup_health.py` tests that run the Postgres job skip on a SQLite suite (`_pg_env()`), to be given a SQLite twin here.
- Full-platform backup: restore from `694bd7be^` — `snapshot_sqlite` (online backup API, read-only source,
  `integrity_check`), `backup_sqlite`, `restore_database` (moves `-wal`/`-shm` aside), gzip; `layout.db_prefix(engine)`;
  `recorder._write_sqlite`; `check_engine` accepting both. `sqlite/` is a live key family again. Backup job keeps its
  read-write data mount + node affinity (`backup-targets.yaml:159-170,241`).
- Restore is same-engine (`sqlite/*.db.gz` → `scripts/backup.py restore --into DIR`; `postgres/` → `pg_restore`);
  sqlite → Postgres via `sqlite_to_postgres` (Q4).
- Workspace bundles are logical (JSON zip + `files/`, via repositories: `repos/seed/workspace_exporter.py:102-150`,
  `workspace_seed_loader.py`, `backups_controller.py:139`, `workspace_controller.py:207`) → restore on either engine.
  Golden bundle fixture (exported from Postgres, includes a secret, `backup_key`) in `tests/fixtures/bundles/`, imported on
  both CI jobs. **Jared's journey test:** empty SQLite DATA_DIR → bootstrap admin → Admin create workspace → import
  bundle → counts, files, decrypted secrets. Known: import mints new workspace UUIDs.
- `refresh_dev.py` / `task dev:refresh` stay Postgres-only.

## 6. Stage 5 — CI and docs
- `test.yml`: restore "Backend Tests (SQLite)" (self-hosted `vars.CI_RUNNER`, no services; migrations up/down/up on a
  file; pytest; `check_name: Backend Test Results (SQLite)`); add to `test-summary` `needs:`; coverage stays on PG;
  parallel → no wall-time growth (Q3).
- `conftest.py:21` honours exported `DB_ENGINE`; SQLite sets `DB_SQLITE_PATH=tests/.temp/marvin-test-<pid>-<rand>.db`
  before importing the app, deleted at session end (parallel runs stop colliding). Keep the PG guard at :69.
- `helm.yml:44-75`: default render sqlite (Kind default install no CNPG; keep a CNPG install for `values-dev.yaml`);
  render `values-iwobble.yaml`; assert `dbEngine: "postgres"` + a CNPG `Cluster` for iwobble/dev/production.
- `docs.yml:73`, `sdk.yml:70`: drop placeholder `POSTGRES_*`.
- Docs: `postgres.md:3,31,130` ("used when configured"; copy tool = upgrade path); `operations.md:37,69,149`
  (`DB_ENGINE`, auto rule, single replica); `offsite-backup.md:15,178,240,244` (`sqlite/` live); new
  `docs/manual/sqlite.md` (file, WAL, no NFS, one replica, backups, moving to Postgres); `HELM_DEPLOYMENT_GUIDE.md`;
  brain notes.

## 7. Rollout, verification, rollback
Before merging Stage 1: diff `helm template` with `values-iwobble.yaml` and `values-dev.yaml` before/after — ConfigMap
`dbEngine` and CNPG Cluster unchanged. Promote dev → Admin → About shows `db_type: postgres` → prod. Local `.env` sets
`DB_ENGINE=postgres` (auto rule covers it anyway). Prod never writes a SQLite file → rollback = revert.

## 8. Risks
- Silent divergence (swallow-and-return-empty) → widget tests + SQLite job on every push.
- "database is locked" on long write txns → `begin_write`, busy_timeout, watchdog.
- SQLite on NFS is unsafe (WAL needs shared memory + real locks) — docs only.
- Existing install falling onto an empty SQLite DB → auto rule, `.secret` guard, pinned values.
- Plugins' own migrations (`*_alembic_version`) may be PG-only → run the plugins group on the SQLite job.
- Fuzzy search weaker on SQLite.

## 9. Decisions
- **Jared 2026-10-18:** SQLite returns as a supported engine and is the default for a fresh install; Postgres when
  configured; prod/dev stay on Postgres.
- **Jared 2026-10-18: all §10 questions as recommended** — (1) auto engine when unset, (2) chart default SQLite + every
  environment values file pins Postgres, (3) SQLite suite on every push in parallel, (4) no Postgres → SQLite conversion
  now, (5) `DATA_DIR/marvin.db`, (6) enforce `String(N)` at flush on SQLite, (7) tokenized LIKE for fuzzy search,
  (8) local `uv run pytest` defaults to SQLite with a file per run.

## 10. Questions for Jared (recommended first)
1. `DB_ENGINE` unset: auto — Postgres if `POSTGRES_*` set, else SQLite (rec.) — or plain SQLite?
2. Chart default SQLite with CNPG off and every environment values file pinning Postgres (rec.), or chart stays Postgres
   and only app/compose defaults change?
3. SQLite suite: every push, parallel on the self-hosted runner (rec.), nightly, or path-filtered?
4. Postgres → SQLite conversion: not now — bundles cover moving content, full restore stays same-engine (rec.) — or a
   two-way copy tool?
5. File path `DATA_DIR/marvin.db` (rec.) or `DATA_DIR/db/marvin.db`?
6. `String(N)` on SQLite: enforce at flush (rec.) or tests only?
7. Fuzzy search on SQLite: tokenized LIKE (rec.) or add FTS5?
8. Local `uv run pytest` default: SQLite, a file per run (rec., no container) or stay on Postgres?
