# SQLite

SQLite is the database of a fresh install: with no database settings at all, Marvin creates `marvin.db` in its data directory and runs on it. It needs no server, no operator and no credentials, which makes it the right choice for a laptop, a demo, a single small site or a first look. A fresh install has no workspace and one super admin: sign in to Admin and create the first workspace there (see [Operations](operations.md#workspaces-first-boot-deleting-and-what-stays-behind)). Postgres is for installs that need more than one API replica or a database server of their own (see [Postgres](postgres.md)); the production and dev environments on the iwobble cluster run on it.

## Which engine an install uses

`DB_ENGINE` (the chart's `config.dbEngine`) names it, `sqlite` or `postgres`. Left unset, the engine is chosen by an auto rule: **Postgres when `POSTGRES_SERVER` or `POSTGRES_URL_OVERRIDE` is set, otherwise SQLite.** An install that already points at a Postgres server keeps using it without any change, and a fresh one needs nothing.

!!! warning "A missing setting does not move an install onto an empty database"
    If the engine is left to the auto rule, it resolves to SQLite, the data directory has a `.secret` from an earlier run and there is no database file, Marvin refuses to start and says why. That combination means an install lost its `DB_ENGINE` / `POSTGRES_*` settings (or its database file); starting would quietly create an empty database next to the old secrets and look like data loss. Restore the settings or the file, or, to really start over on SQLite, remove `.secret` too (stored secrets encrypted with it become unreadable). Setting `DB_ENGINE` explicitly skips this check.

## Where the file is

`marvin.db` in `DATA_DIR` (`/app/data` in the container). `DB_SQLITE_PATH` puts it somewhere else. Next to it SQLite keeps two side files while the app runs, `marvin.db-wal` (the write-ahead log) and `marvin.db-shm` (its shared-memory index). They belong to the database: never copy, move or delete `marvin.db` alone while the app runs, and never keep a stale `-wal` beside a database it did not come from.

## How it is configured

| Setting | Default | Meaning |
|---|---|---|
| `DB_SQLITE_PATH` | `DATA_DIR/marvin.db` | the database file |
| `DB_SQLITE_WAL_MODE` | `true` | write-ahead logging, so readers do not wait for the writer |
| `DB_SQLITE_BUSY_TIMEOUT_MS` | `30000` | how long a writer waits for the write lock before failing with "database is locked" |
| `DB_SQLITE_WRITE_WARN_SECONDS` | `5` | a warning in the log when one write transaction stays open this long (it blocks every other writer); `0` turns it off |

On every connection Marvin switches on foreign keys, WAL and `synchronous=NORMAL`, and it refuses an SQLite older than 3.35. A write transaction takes the write lock up front (`BEGIN IMMEDIATE`), so a second writer waits up to the busy timeout instead of failing halfway through. Marvin's migrations run on SQLite with Alembic's batch mode, the same revisions as on Postgres.

## What to know before choosing it

- **One process writes the file.** Run **one API replica**. The Helm chart enforces it: with `config.dbEngine: sqlite` it fails the render for `replicaCount` (or `split.backend.replicaCount`) above 1, fails without `persistence.enabled`, and always uses the `Recreate` update strategy, so the old pod has stopped before the new one opens the file. Deploys therefore have a short downtime. The scheduler's lease still works, it just never has a rival.
- **Not on NFS or another network file system.** WAL needs shared memory and real file locks, which NFS does not give reliably; a database on NFS can corrupt. Use a local or block volume (a `ReadWriteOnce` PVC from a block storage class). This is why the iwobble environments, whose only storage class is NFS, run on Postgres.
- **Search is tokenised.** Fuzzy "did you mean" matching uses Postgres's `pg_trgm`; on SQLite search matches by tokenised `LIKE`, so a typo finds less.
- **Column lengths are enforced at write time** (Marvin checks `String(N)` columns before flushing on SQLite, which would otherwise ignore them), so a value too long for Postgres fails on SQLite too.
- **No Postgres-only features in the app.** Everything in Marvin's code runs on both engines; the CI suite runs on each.

## Backups

SQLite is a first-class engine of the [off-site backup engine](offsite-backup.md): it copies the database with SQLite's online backup API while the app runs (one read transaction, so the copy is consistent), runs `PRAGMA integrity_check` on the copy, gzips it and uploads `sqlite/marvin-<stamp>.db.gz`, with the config archive and the asset mirror. Restore downloads and verifies it, moves any `marvin.db`, `-wal` and `-shm` in the target directory aside and puts the file in place:

```bash
python -m marvin.scripts.backup restore --target local --into /app/data --force   # with the app stopped
```

In the chart the backup job mounts the data volume read-write and runs on the app pod's node (the volume is `ReadWriteOnce`, and a reader of a WAL database takes its locks in `marvin.db-shm`). Per-workspace bundles (**Settings → General → Backups**) are exports of content, not of the database, and import on either engine.

For a quick manual copy with the app running, use SQLite's own tool rather than `cp`:

```bash
sqlite3 /app/data/marvin.db ".backup '/tmp/marvin-copy.db'"
```

## Moving to Postgres

When an install outgrows one replica, or needs a database server, move it:

1. Stand up Postgres and set `DB_ENGINE=postgres` with the `POSTGRES_*` settings (on the chart: `config.dbEngine: postgres` and `postgres.cluster.enabled: true`, see [Postgres](postgres.md)).
2. Copy the data with the SQLite → Postgres tool, `python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db` ([the copy tool](postgres.md#sqlite-postgres-copy-tool)). It opens the file read-only, so the SQLite file is the rollback.

A restore is **same-engine**: a `sqlite/` backup restores to SQLite, a `postgres/` one to Postgres. To carry only content across engines, export a workspace bundle on one and import it on the other.
