"""Back up a Marvin data directory to one backup target, list its backups, restore from it, prune it.

    python -m marvin.scripts.backup run     --target TYPE [--name NAME] [--dry-run]
    python -m marvin.scripts.backup test    --target TYPE [--name NAME]
    python -m marvin.scripts.backup list    --target TYPE
    python -m marvin.scripts.backup prune   --target TYPE [--dry-run]
    python -m marvin.scripts.backup restore --target TYPE --into DIR [--db-key KEY] [--config-key KEY]
                                            [--skip-db] [--skip-config] [--skip-assets] [--force]

TYPE is the target's type: the built-in `local` (a directory on another volume, BACKUP_LOCAL_ROOT) or
a storage plugin's target slug (e.g. `s3`); it defaults to BACKUP_TARGET. NAME labels the target in
logs (default: TYPE). Each target runs on its own (one CronJob per target), with its own retention
(BACKUP_KEEP_HOURLY / _DAILY / _WEEKLY, default 48 / 30 / 0) and optional key prefix (BACKUP_PREFIX).
The rest of the configuration is the environment; see marvin.services.backup_engine.engine.

Exit status: 0 ok, 1 a step failed (the others still ran), 2 configuration error.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from marvin_integration_sdk.storage import StorageConfigError

from marvin.services.backup_engine import engine, recorder
from marvin.services.backup_engine.layout import BackupError
from marvin.services.storage.healthcheck import check_target, explain, scrub

log = logging.getLogger("marvin.backup")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m marvin.scripts.backup", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def command(name: str, help: str) -> argparse.ArgumentParser:
        c = sub.add_parser(name, help=help)
        c.add_argument("--target", default=os.environ.get("BACKUP_TARGET"), help="target type: local, or a plugin's slug (default: BACKUP_TARGET)")
        c.add_argument("--name", default=os.environ.get("BACKUP_TARGET_NAME"), help="label for logs (default: the type)")
        return c

    run = command("run", "back up DATA_DIR to the target")
    run.add_argument("--dry-run", action="store_true", help="snapshot and verify locally, report what would change, upload/delete nothing")
    command("test", "check the target's credentials: list, put, get and delete one small object")
    command("list", "list the database and config backups in the target")
    pr = command("prune", "apply the retention without backing up")
    pr.add_argument("--dry-run", action="store_true")
    r = command("restore", "restore a backup into a directory")
    r.add_argument("--into", type=Path, required=True, help="directory to restore into (a data dir layout)")
    r.add_argument("--db-key", help="sqlite/... or postgres/... object to restore (default: the newest for the DB engine)")
    r.add_argument("--config-key", help="config/... object to restore (default: the newest)")
    r.add_argument("--skip-db", action="store_true")
    r.add_argument("--skip-config", action="store_true")
    r.add_argument("--skip-assets", action="store_true")
    r.add_argument("--force", action="store_true", help="replace an existing marvin.db/.secret in --into; only with the backend stopped")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    for noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args = _parser().parse_args(argv)
    if not args.target:
        log.error("no target type: pass --target or set BACKUP_TARGET")
        return 2
    name = args.name or args.target
    if args.command == "run":
        return run(args.target, name, dry_run=args.dry_run)
    try:
        settings = engine.BackupSettings.from_env()
        target = engine.open_target(args.target, prefix=settings.prefix)
    except (BackupError, StorageConfigError) as exc:
        log.error("backup[%s]: %s", name, exc)
        return 2
    log.info("backup[%s]: %s %s", name, args.command, target.describe())

    if args.command == "test":
        result = check_target(target)
        for line in result.lines():
            sys.stdout.write(f"{line}\n")
        log.info("backup[%s]: test %s (%s)", name, "ok" if result.ok else "FAILED", result.key)
        return 0 if result.ok else 1
    try:
        if args.command == "list":
            for obj in engine.list_backups(target):
                sys.stdout.write(f"{obj.key}\t{obj.size}\n")
        elif args.command == "prune":
            report = engine.run_prune(settings, target, dry_run=args.dry_run)
            log.info("backup[%s]: pruned %d%s", name, report.pruned, " (dry run)" if args.dry_run else "")
        else:
            engine.run_restore(
                target,
                args.into,
                db=args.db_key,
                config=args.config_key,
                assets=not args.skip_assets,
                skip_db=args.skip_db,
                skip_config=args.skip_config,
                engine=settings.engine,
                force=args.force,
            )
    except Exception as exc:
        log.error("backup[%s]: %s failed: %s", name, args.command, exc)
        return 1
    return 0


def run(target_type: str, name: str, dry_run: bool = False, env: dict[str, str] | None = None) -> int:
    """Back up to one target and record the run (unless a dry run), whatever happens: a target that can't
    be opened is a failed run too, so a revoked key shows up in Marvin, not only in the job's log."""
    env = dict(os.environ if env is None else env)
    started_at, started = datetime.now(UTC), time.monotonic()
    schedule, time_zone = recorder.schedule_from_env(env)
    record = recorder.RunRecord(
        target_name=name,
        target_type=target_type,
        status="failed",
        started_at=started_at,
        finished_at=started_at,
        schedule=schedule,
        time_zone=time_zone,
        db_engine=(env.get("BACKUP_DB_ENGINE") or env.get("DB_ENGINE") or "sqlite").lower(),
        settings=recorder.target_settings(target_type, env),
    )

    def finish(code: int, error: str | None = None) -> int:
        record.finished_at = datetime.now(UTC)
        record.error_summary = scrub(error, env)
        if not dry_run:
            recorder.record_run(record, env)
        return code

    try:
        settings = engine.BackupSettings.from_env(env)
        record.retention = (settings.retention.hourly, settings.retention.daily, settings.retention.weekly)
        target = engine.open_target(target_type, env, prefix=settings.prefix)
        sources, source_problems = engine.open_asset_sources(settings, env)
    except Exception as exc:  # BackupError, StorageConfigError, or a plugin failing to build its client
        why = explain(exc)
        log.error("backup[%s]: %s", name, why)
        record.failures = 1
        return finish(2, f"target: {why}")
    try:
        record.location = target.describe()
    except Exception:
        record.location = None
    log.info("backup[%s]: run %s", name, record.location or target_type)

    try:
        report = engine.run_backup(settings, target, sources, dry_run=dry_run, name=name)
    except Exception as exc:  # run_backup catches each step's errors; this is a bug or the machine failing
        log.exception("backup[%s]: run failed", name)
        record.failures = 1
        return finish(1, f"run: {explain(exc)}")
    report.failures += source_problems
    log.info("%s", report.summary(time.monotonic() - started, dry_run))
    record.status = recorder.status_of(bool(report.db_key), len(report.failures))
    record.db_key = report.db_key
    record.db_bytes = report.db_bytes or None
    record.db_gz_bytes = report.db_gz_bytes or None
    record.config_items = len(report.config_files) if report.config_key else None
    record.assets_uploaded = report.assets_uploaded
    record.assets_uploaded_bytes = report.assets_uploaded_bytes
    record.assets_unchanged = report.assets_unchanged
    record.pruned = report.pruned
    record.failures = len(report.failures)
    return finish(1 if report.failures else 0, summarize_failures(report.failures) or None)


def summarize_failures(failures: list[str], limit: int = 5) -> str:
    """The run's failures on one line, steps that failed for the same reason folded together: a revoked key
    reads "database, config, assets: the key is invalid or revoked … (InvalidAccessKeyId)", not three times."""
    grouped: dict[str, list[str]] = {}
    for failure in failures:
        step, sep, why = failure.partition(": ")
        if not sep:
            step, why = "", failure
        grouped.setdefault(why, []).append(step)
    parts = [f"{', '.join(s for s in steps if s)}: {why}" if any(steps) else why for why, steps in grouped.items()]
    more = len(parts) - limit
    return "; ".join(parts[:limit]) + (f"; and {more} more" if more > 0 else "")


if __name__ == "__main__":
    sys.exit(main())
