"""Refresh a non-production copy (marvin-dev) from production's newest backup — run by `task dev:refresh`.

    python -m marvin.scripts.refresh_dev --source-bucket marvin-backups --confirm-db-host marvin-dev-pg-rw [--skip-assets]

Runs inside a Job made from the copy's own backup CronJob, which already has the backup plugin, the R2 token,
the copy's database connection (POSTGRES_*) and the copy's asset storage (STORAGE_*); the source bucket is the
one thing changed. Steps:

1. fetch production's newest `postgres/` dump from the source bucket, checked against its sha256;
2. `pg_restore --clean --if-exists --no-owner --single-transaction` it into the copy's database (the backend
   is scaled to 0 meanwhile by the task, so nothing holds a lock or caches old rows);
3. drop the previous refresh's pause records, then pause everything that reaches the outside world, in the
   copy only (sqlite_to_postgres.pause_outbound: webhooks, integrations, workflows, email subscriptions, SMTP,
   MCP, scheduled tasks, auto rebuilds);
4. copy every asset the copy's storage lacks from the source's asset mirror (`assets/`), so restored rows
   don't point at missing files. Nothing is deleted from the copy's storage.

Guards, because step 2 replaces a database: it refuses when the source bucket is this job's own backup bucket
(that is production's job), and unless --confirm-db-host names the database host it is about to replace.
Production's `.secret` is not copied: the copy already has it (see docs/manual/postgres.md).

Exit status: 0 ok, 1 a step failed, 2 refused or misconfigured.
"""

from __future__ import annotations

import argparse
import logging
import mimetypes
import os
import sys
import tempfile
import time
from pathlib import Path

import sqlalchemy as sa

from marvin.scripts.sqlite_to_postgres import PAUSE_TABLE, pause_lines, pause_outbound
from marvin.services.backup_engine import engine
from marvin.services.backup_engine.layout import ASSETS_PREFIX, PG_PREFIX, BackupError

log = logging.getLogger("marvin.refresh")
SOURCE_TYPE = "s3"
PROGRESS_EVERY = 100  # assets: one HEAD each against the copy's bucket, so a thousand take minutes


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m marvin.scripts.refresh_dev", description=__doc__.split("\n\n")[0])
    p.add_argument("--source-bucket", required=True, help="production's backup bucket (e.g. marvin-backups)")
    p.add_argument("--confirm-db-host", required=True, help="the database host this replaces; must equal POSTGRES_SERVER")
    p.add_argument("--skip-assets", action="store_true", help="restore the database only")
    return p


def refuse_unless_safe(env: dict[str, str], source_bucket: str, confirm_host: str) -> str | None:
    """Why this must not run here, or None."""
    own = env.get("BACKUP_S3_BUCKET", "")
    if not own:
        return "BACKUP_S3_BUCKET is not set: run this in a Job made from the copy's backup CronJob"
    if source_bucket == own:
        return f"the source bucket {source_bucket!r} is this job's own backup bucket — this is the production job, refusing"
    if not env.get("POSTGRES_SERVER") or confirm_host != env["POSTGRES_SERVER"]:
        return f"--confirm-db-host {confirm_host!r} does not match POSTGRES_SERVER {env.get('POSTGRES_SERVER')!r}"
    return None


def restore_database(source, settings: engine.BackupSettings, work: Path) -> str:
    key = engine.latest_key(source, PG_PREFIX)
    dump = engine.restore_pg_dump(source, key, work, suffix=f".{int(time.time())}")
    engine._run_pg(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            f"--dbname={settings.pg_env['PGDATABASE']}",
            str(dump),
        ],
        settings,
        "pg_restore",
    )
    log.info("database: restored %s", key)
    return key


def repause(conn) -> dict[str, int]:
    """Pause outbound in a freshly restored copy. The dump doesn't carry the pause table, so `pg_restore --clean`
    leaves the previous refresh's records behind, and pause_outbound keeps an existing record over a new one: a row
    production switched off since then would come back on with `--unpause`. Every switch now comes from production,
    so the old records are dropped first."""
    if sa.inspect(conn).has_table(PAUSE_TABLE):
        conn.exec_driver_sql(f"DELETE FROM {PAUSE_TABLE}")
    return pause_outbound(conn)


def pause(settings: engine.BackupSettings) -> list[str]:
    pg = settings.pg_env
    url = sa.engine.URL.create(
        "postgresql+psycopg2",
        username=pg.get("PGUSER"),
        password=pg.get("PGPASSWORD"),
        host=pg.get("PGHOST"),
        port=int(pg["PGPORT"]) if pg.get("PGPORT") else None,
        database=pg.get("PGDATABASE"),
    )
    db = sa.create_engine(url)
    try:
        with db.begin() as conn:
            lines = pause_lines(repause(conn))
    finally:
        db.dispose()
    for line in lines:
        log.info("outbound: %s", line)
    return lines


def copy_missing_assets(source, settings: engine.BackupSettings, env: dict[str, str], work: Path) -> tuple[int, int]:
    """(copied, already there) from the source's asset mirror into the copy's asset storage."""
    providers, _ = engine.open_asset_sources(settings, env)
    if not providers:
        raise BackupError("no asset storage configured for the copy (STORAGE_PROVIDER / BACKUP_ASSET_PROVIDERS)")
    dest = providers[-1]  # the provider new uploads go to is listed last (BACKUP_ASSET_PROVIDERS)
    copied = present = 0
    staged = work / "asset"
    keys = sorted(source.list(ASSETS_PREFIX))
    for n, key in enumerate(keys, 1):
        if n % PROGRESS_EVERY == 0:
            log.info("assets: %d / %d checked (%d copied)", n, len(keys), copied)
        storage_key = key[len(ASSETS_PREFIX) :]
        if dest.exists(storage_key):
            present += 1
            continue
        source.get(key, staged)
        with staged.open("rb") as fh:
            dest.put(storage_key, fh, mimetypes.guess_type(storage_key)[0] or "application/octet-stream")
        staged.unlink(missing_ok=True)
        copied += 1
    log.info("assets: %d copied, %d already there (%s)", copied, present, dest.slug)
    return copied, present


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    for noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args = _parser().parse_args(argv)
    env = dict(os.environ)
    if reason := refuse_unless_safe(env, args.source_bucket, args.confirm_db_host):
        log.error("refresh: %s", reason)
        return 2
    try:
        settings = engine.BackupSettings.from_env(env)
        source = engine.open_target(SOURCE_TYPE, env={**env, "BACKUP_S3_BUCKET": args.source_bucket})
    except Exception as exc:  # noqa: BLE001 — configuration: say what, exit 2
        log.error("refresh: %s", exc)
        return 2
    log.info("refresh: from %s into %s", source.describe(), env.get("POSTGRES_SERVER"))
    with tempfile.TemporaryDirectory(prefix="marvin-refresh-") as tmp:
        work = Path(tmp)
        try:
            key = restore_database(source, settings, work)
            pause(settings)
            if args.skip_assets:
                assets = "skipped"
            else:
                copied, present = copy_missing_assets(source, settings, env, work)
                assets = f"{copied} copied, {present} already there"
        except Exception as exc:  # noqa: BLE001 — report and fail the Job
            log.error("refresh FAILED: %s", exc)
            return 1
    log.info("refresh ok: database from %s, outbound paused, assets %s", key, assets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
