"""Move stored files between asset storage providers, without an upload freeze.

    python -m marvin.scripts.storage_migrate --to s3 --dry-run       # what would move
    python -m marvin.scripts.storage_migrate --to s3 --verify        # copy, verify, repoint each row
    python -m marvin.scripts.storage_migrate --to s3 --workspace mash-burn-co --batch 50
    python -m marvin.scripts.storage_migrate --to local              # the rollback
    python -m marvin.scripts.storage_migrate --prune-local [--dry-run]  # later: delete local copies

Choose the target for new uploads first (Admin → Storage), so nothing uploaded during the run is
left behind; each pass re-reads what is left and the run ends when nothing is. Files are copied, their
sha256 checked on the target (``--verify`` downloads each copy to hash it), and only then is the row
pointed at the target. Source copies are never deleted here; ``--prune-local`` deletes local copies of
files that live elsewhere, after downloading each remote copy and comparing it with the local bytes.
Safe to interrupt and run again. Exit status 1 when any file failed (the rest still moved).
See services/storage/migration.py and the "Assets on R2" runbook in the manual.
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m marvin.scripts.storage_migrate", description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--to", metavar="PROVIDER", help="move every file stored elsewhere to this provider (e.g. s3, local)")
    mode.add_argument("--prune-local", action="store_true", help="delete local copies of files verified on the provider their row names")
    parser.add_argument("--dry-run", action="store_true", help="report what would happen; change nothing")
    parser.add_argument("--workspace", metavar="SLUG", help="only this workspace's assets (library files move in full runs only)")
    parser.add_argument("--batch", type=int, default=100, metavar="N", help="log progress every N rows (default 100)")
    parser.add_argument("--verify", action="store_true", help="download each copy and hash it, instead of trusting the target's sha256")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("storage_migrate")

    from marvin.services.storage import StorageConfigError
    from marvin.services.storage.migration import MigrationError, migrate, prune_local

    try:
        if args.prune_local:
            report = prune_local(workspace=args.workspace, dry_run=args.dry_run)
        else:
            report = migrate(args.to, workspace=args.workspace, batch=args.batch, verify=args.verify, dry_run=args.dry_run)
    except (StorageConfigError, MigrationError) as e:
        log.error("%s", e)
        return 2
    for failure in report.failures:
        log.error("failed: %s", failure)
    log.info("%s%s", report.summary(), " (dry run)" if args.dry_run else "")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
