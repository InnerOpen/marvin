"""Move stored files between asset storage providers, without an upload freeze.

    python -m marvin.scripts.storage_migrate --to s3 --dry-run       # what would move
    python -m marvin.scripts.storage_migrate --to s3 --verify        # copy, verify, repoint each row
    python -m marvin.scripts.storage_migrate --to s3 --workspace mash-burn-co --batch 50
    python -m marvin.scripts.storage_migrate --to local              # the rollback
    python -m marvin.scripts.storage_migrate --prune-local [--dry-run]  # later: delete local copies
    python -m marvin.scripts.storage_migrate --rekey [--to s3]       # give every file an opaque key
    python -m marvin.scripts.storage_migrate --prune-old [--dry-run]    # later: delete copies at old keys

Choose the target for new uploads first (Admin → Storage), so nothing uploaded during the run is
left behind; each pass re-reads what is left and the run ends when nothing is. Files are copied, their
sha256 checked on the target (``--verify`` downloads each copy to hash it), and only then is the row
pointed at the target. Source copies are never deleted here; ``--prune-local`` deletes local copies of
files that live elsewhere, after downloading each remote copy and comparing it with the local bytes.
``--rekey`` also moves every file whose key isn't opaque yet (``<workspace code>/<yyyy>/<mm>/<uuid>.<ext>``)
to one that is: on the provider it is on, or on ``--to``'s. The old copy is kept, and old ``/assets/``
URLs keep working (served, then redirected once ``--prune-old`` has deleted it); old remote URLs (the
bucket's public domain) work only until ``--prune-old``, so rebuild the sites first.
Safe to interrupt and run again. Exit status 1 when any file failed (the rest still moved).
See services/storage/migration.py and the "Assets on R2" runbook in the manual.
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m marvin.scripts.storage_migrate", description=__doc__.splitlines()[0])
    parser.add_argument("--to", metavar="PROVIDER", help="move every file stored elsewhere to this provider (e.g. s3, local)")
    parser.add_argument("--rekey", action="store_true", help="give every file without an opaque key one (with --to: while moving it)")
    parser.add_argument("--prune-local", action="store_true", help="delete local copies of files verified on the provider their row names")
    parser.add_argument("--prune-old", action="store_true", help="delete the copies --rekey left at old keys, verified against the current copy")
    parser.add_argument("--dry-run", action="store_true", help="report what would happen; change nothing")
    parser.add_argument("--workspace", metavar="SLUG", help="only this workspace's assets (library files move in full runs only)")
    parser.add_argument("--batch", type=int, default=100, metavar="N", help="log progress every N rows (default 100)")
    parser.add_argument("--verify", action="store_true", help="download each copy and hash it, instead of trusting the target's sha256")
    args = parser.parse_args(argv)
    modes = [
        m for m, on in (("--to/--rekey", bool(args.to or args.rekey)), ("--prune-local", args.prune_local), ("--prune-old", args.prune_old)) if on
    ]
    if len(modes) != 1:
        parser.error("choose one of --to PROVIDER and/or --rekey, --prune-local, --prune-old")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("storage_migrate")

    from marvin.services.storage import StorageConfigError
    from marvin.services.storage.migration import MigrationError, migrate, prune_local, prune_old

    try:
        if args.prune_local:
            report = prune_local(workspace=args.workspace, dry_run=args.dry_run)
        elif args.prune_old:
            report = prune_old(workspace=args.workspace, dry_run=args.dry_run)
        else:
            report = migrate(args.to, rekey=args.rekey, workspace=args.workspace, batch=args.batch, verify=args.verify, dry_run=args.dry_run)
    except (StorageConfigError, MigrationError) as e:
        log.error("%s", e)
        return 2
    for failure in report.failures:
        log.error("failed: %s", failure)
    log.info("%s%s", report.summary(), " (dry run)" if args.dry_run else "")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
