"""Back up a Marvin data directory to one backup target, list its backups, restore from it, prune it.

    python -m marvin.scripts.backup run     --target TYPE [--name NAME] [--dry-run]
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
from pathlib import Path

from marvin_integration_sdk.storage import StorageConfigError

from marvin.services.backup_engine import engine
from marvin.services.backup_engine.layout import BackupError

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
    try:
        settings = engine.BackupSettings.from_env()
        target = engine.open_target(args.target, prefix=settings.prefix)
        sources, source_problems = engine.open_asset_sources(settings) if args.command == "run" else ([], [])
    except (BackupError, StorageConfigError) as exc:
        log.error("backup[%s]: %s", name, exc)
        return 2
    log.info("backup[%s]: %s %s", name, args.command, target.describe())

    if args.command == "run":
        started = time.monotonic()
        report = engine.run_backup(settings, target, sources, dry_run=args.dry_run, name=name)
        report.failures += source_problems
        log.info("%s", report.summary(time.monotonic() - started, args.dry_run))
        return 1 if report.failures else 0
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


if __name__ == "__main__":
    sys.exit(main())
