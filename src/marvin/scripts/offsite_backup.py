"""Off-site backup and restore of a Marvin data directory to S3-compatible storage.

Built for Cloudflare R2, works against any S3 API (MinIO, AWS). It backs up what a restore needs and
Marvin's own per-workspace export does not: the whole database (users, tokens, secrets, logs), the
installation secret, and the uploaded files.

    python -m marvin.scripts.offsite_backup [backup] [--dry-run]
    python -m marvin.scripts.offsite_backup list
    python -m marvin.scripts.offsite_backup restore --target DIR [--db-key KEY] [--config-key KEY]
                                                    [--skip-assets] [--force]

Bucket layout (every key under BACKUP_S3_PREFIX, e.g. `dev/`, when set — one bucket, separate
environments, each with its own retention):

    sqlite/marvin-<UTC YYYYmmddTHHMMSSZ>.db.gz          consistent SQLite snapshot (gzip)
    postgres/marvin-<UTC YYYYmmddTHHMMSSZ>.dump         pg_dump --format=custom (DB_ENGINE=postgres)
    config/marvin-config-<UTC YYYYmmddTHHMMSSZ>.tar.gz  .secret, scheduler_state.json, templates/
    assets/<path under DATA_DIR/assets>                 incremental mirror, never deleted remotely

Database and config objects carry `sha256` (of the object) in their metadata, and the SQLite snapshot
also `db-sha256` (of the uncompressed file); restore checks both. Retention keeps the newest backup of
each of the last KEEP_DAILY days that have one, plus the newest of each of the last KEEP_WEEKLY ISO
weeks — and for `postgres/` (dumped hourly) also the newest of each of the last KEEP_HOURLY hours; it
never touches `assets/` or keys it did not name.

With Postgres the dump is the database backup (no WAL archiving / point-in-time recovery, by choice),
so a Postgres release runs this hourly. It is taken with the POSTGRES_* connection the app uses
(passed to pg_dump through PG* environment variables, never the command line) and checked with
`pg_restore --list` before upload. `restore` downloads and verifies it as DIR/marvin.dump; loading it
is a deliberate `pg_restore` (docs/manual/postgres.md), never automatic.

The config archive holds `.secret`, the key that decrypts encrypted values in the database. Anyone
who can read the bucket can read every secret Marvin stores, so the bucket must stay private and its
credentials scoped to it.

Configuration (environment): BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET, AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, BACKUP_S3_REGION (default `auto`, right for R2), BACKUP_S3_PREFIX (default none),
BACKUP_DATA_DIR (default `/app/data`), BACKUP_DB_ENGINE (default: DB_ENGINE, else `sqlite`); for
Postgres also POSTGRES_SERVER, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB.

Deliberately standalone (stdlib + boto3, no Marvin settings import): it runs in a CronJob next to
the live backend and must not create directories, read `.secret` through the app, or open the
database through SQLAlchemy. See docs/manual/offsite-backup.md for the runbook.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("marvin.offsite_backup")

DB_NAME = "marvin.db"
PG_DUMP_NAME = "marvin.dump"
DB_PREFIX = "sqlite/"
PG_PREFIX = "postgres/"
CONFIG_PREFIX = "config/"
ASSETS_PREFIX = "assets/"
TS_FORMAT = "%Y%m%dT%H%M%SZ"
# Files and directories under DATA_DIR that go into the config archive. Logs, `.temp`, `backups/`,
# the `marvin.db.pre-*` manual snapshots and the live `-wal`/`-shm` files are deliberately absent.
CONFIG_FILES = (".secret", "scheduler_state.json")
CONFIG_DIRS = ("templates",)  # operator-supplied email templates (services/email)

KEEP_DAILY = 14
KEEP_WEEKLY = 8
# postgres/ dumps run hourly (backup.schedule), so they also keep the newest of each of the last
# KEEP_HOURLY hours that have one; sqlite/ and config/ keep the daily + weekly rule only.
KEEP_HOURLY = 48

META_SHA256 = "sha256"  # sha256 of the stored object (the .gz)
META_DB_SHA256 = "db-sha256"  # sha256 of the uncompressed database

CHUNK = 1024 * 1024
# The keys this script names (and so may prune): each family with its own extension.
_KEY_EXT = {"sqlite/marvin-": ".db.gz", "postgres/marvin-": ".dump", "config/marvin-config-": ".tar.gz"}
_STAMPED_KEY = re.compile(
    r"^(?P<family>sqlite/marvin-|postgres/marvin-|config/marvin-config-)(?P<ts>\d{8}T\d{6}Z)(?P<ext>\.db\.gz|\.dump|\.tar\.gz)$"
)
PG_DUMP_TIMEOUT = 1800  # seconds


class BackupError(Exception):
    """A step failed; the message is safe to log (it never carries credentials)."""


# --------------------------------------------------------------------------------------------------
# Key naming and retention
# --------------------------------------------------------------------------------------------------


def stamp(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime(TS_FORMAT)


def db_key(ts: datetime) -> str:
    return f"{DB_PREFIX}marvin-{stamp(ts)}.db.gz"


def pg_key(ts: datetime) -> str:
    return f"{PG_PREFIX}marvin-{stamp(ts)}.dump"


def db_prefix(engine: str) -> str:
    return PG_PREFIX if engine == "postgres" else DB_PREFIX


def config_key(ts: datetime) -> str:
    return f"{CONFIG_PREFIX}marvin-config-{stamp(ts)}.tar.gz"


def asset_key(rel_path: str) -> str:
    return ASSETS_PREFIX + rel_path


def key_timestamp(key: str) -> datetime | None:
    """The UTC timestamp a `sqlite/`, `postgres/` or `config/` key was named with, or None for any other key."""
    m = _STAMPED_KEY.match(key)
    if not m or _KEY_EXT[m["family"]] != m["ext"]:
        return None
    return datetime.strptime(m["ts"], TS_FORMAT).replace(tzinfo=UTC)


def select_retained(keys: Iterable[str], keep_daily: int = KEEP_DAILY, keep_weekly: int = KEEP_WEEKLY, keep_hourly: int = 0) -> set[str]:
    """Keys to keep: the newest per UTC hour for the newest `keep_hourly` hours that have a backup, the
    newest per UTC day for the newest `keep_daily` days that have one, plus the newest per ISO week for
    the newest `keep_weekly` weeks. Counting periods that *have* a backup (not calendar periods back
    from now) means a gap in backups never empties the bucket."""
    stamped = sorted(((ts, k) for k in keys if (ts := key_timestamp(k)) is not None), reverse=True)
    newest: dict[str, dict[Any, str]] = {"hour": {}, "day": {}, "week": {}}
    for ts, key in stamped:  # newest first, so the first key seen per period is the newest
        newest["hour"].setdefault((ts.date(), ts.hour), key)
        newest["day"].setdefault(ts.date(), key)
        newest["week"].setdefault(ts.isocalendar()[:2], key)
    keep = set(list(newest["hour"].values())[:keep_hourly])
    keep |= set(list(newest["day"].values())[:keep_daily])
    return keep | set(list(newest["week"].values())[:keep_weekly])


def select_expired(keys: Iterable[str], keep_daily: int = KEEP_DAILY, keep_weekly: int = KEEP_WEEKLY, keep_hourly: int = 0) -> list[str]:
    """Stamped keys outside the retention set. Keys this script did not name are never expired."""
    keys = list(keys)
    keep = select_retained(keys, keep_daily, keep_weekly, keep_hourly)
    return sorted(k for k in keys if key_timestamp(k) is not None and k not in keep)


# --------------------------------------------------------------------------------------------------
# Hashing, SQLite and archives
# --------------------------------------------------------------------------------------------------


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def check_integrity(path: Path) -> None:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"integrity_check could not read {path.name}: {exc}") from exc
    finally:
        conn.close()
    if rows != [("ok",)]:
        raise BackupError(f"integrity_check failed on {path.name}: {[r[0] for r in rows[:5]]}")


def snapshot_sqlite(src: Path, dest: Path) -> None:
    """Copy a live SQLite database with the online backup API, then verify the copy.

    The source is opened read-only, and one backup step copies every page under a single read
    transaction, so the copy is a consistent snapshot even while the backend writes (WAL mode lets
    writers carry on meanwhile). The copy is switched to rollback-journal mode so it is one
    self-contained file; the app turns WAL back on when it opens a restored file.
    """
    if not src.is_file():
        raise BackupError(f"database not found: {src}")
    source = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True, timeout=60)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
    finally:
        target.close()
        source.close()
    check_integrity(dest)


def gzip_file(src: Path, dest: Path) -> None:
    with src.open("rb") as fin, gzip.open(dest, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout, CHUNK)


def gunzip_file(src: Path, dest: Path) -> None:
    with gzip.open(src, "rb") as fin, dest.open("wb") as fout:
        shutil.copyfileobj(fin, fout, CHUNK)


def build_config_archive(data_dir: Path, dest: Path) -> list[str]:
    """Tar the config files that exist; return the names archived."""
    names: list[str] = []
    with tarfile.open(dest, "w:gz") as tar:
        for name in CONFIG_FILES:
            if (data_dir / name).is_file():
                tar.add(data_dir / name, arcname=name)
                names.append(name)
        for name in CONFIG_DIRS:
            if (data_dir / name).is_dir():
                tar.add(data_dir / name, arcname=name)
                names.append(f"{name}/")
    return names


def iter_local_assets(assets_dir: Path) -> Iterator[tuple[str, Path]]:
    """(relative posix path, path) for every regular file under assets_dir, sorted, symlinks skipped."""
    if not assets_dir.is_dir():
        return
    for root, dirs, files in os.walk(assets_dir):
        dirs.sort()
        for name in sorted(files):
            path = Path(root, name)
            if path.is_file() and not path.is_symlink():
                yield path.relative_to(assets_dir).as_posix(), path


# --------------------------------------------------------------------------------------------------
# Object store
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoteObject:
    key: str
    size: int
    etag: str


def asset_needs_upload(path: Path, remote: RemoteObject | None) -> bool:
    """Upload when the key is missing, the size differs, or a single-part ETag (the object's MD5)
    differs from the local file's MD5. A multipart ETag (`<md5>-<parts>`) is not a content hash, so
    for those a matching size counts as unchanged; this script uploads single-part, so that only
    arises for objects put there some other way."""
    if remote is None:
        return True
    if remote.size != path.stat().st_size:
        return True
    etag = remote.etag.strip('"')
    if not etag or "-" in etag:
        return False
    return file_digest(path, "md5") != etag


class Bucket:
    """The handful of S3 calls the backup makes, over a boto3 client (or a test double).

    `root` (BACKUP_S3_PREFIX, e.g. `dev/`) is prepended to every key on the way out and stripped on
    the way back, so the rest of the script — naming, retention, the asset diff — works in keys
    relative to it and an environment under a prefix never sees (or prunes) another's objects."""

    def __init__(self, client: Any, name: str, root: str = "") -> None:
        self.client = client
        self.name = name
        self.root = root

    def list(self, prefix: str) -> dict[str, RemoteObject]:
        found: dict[str, RemoteObject] = {}
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.name, Prefix=self.root + prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"][len(self.root) :]
                found[key] = RemoteObject(key, int(obj["Size"]), obj.get("ETag", ""))
        return found

    def put_file(self, key: str, path: Path, metadata: dict[str, str] | None = None, content_type: str | None = None) -> None:
        # One PUT per object (no multipart), so the ETag is the MD5 the asset diff compares against.
        extra = {"ContentType": content_type} if content_type else {}
        with path.open("rb") as fh:
            self.client.put_object(Bucket=self.name, Key=self.root + key, Body=fh, Metadata=metadata or {}, **extra)

    def download(self, key: str, dest: Path) -> dict[str, str]:
        resp = self.client.get_object(Bucket=self.name, Key=self.root + key)
        with dest.open("wb") as fh:
            shutil.copyfileobj(resp["Body"], fh, CHUNK)
        return {k.lower(): v for k, v in (resp.get("Metadata") or {}).items()}

    def delete(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):
            batch = [self.root + k for k in keys[i : i + 1000]]
            resp = self.client.delete_objects(Bucket=self.name, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True})
            if errors := resp.get("Errors"):
                raise BackupError(f"delete failed for {len(errors)} object(s), first: {errors[0].get('Key')} {errors[0].get('Code')}")


def normalize_prefix(prefix: str | None) -> str:
    """`dev`, `/dev/` and `dev/` all mean `dev/`; empty means the bucket root."""
    prefix = (prefix or "").strip().strip("/")
    return f"{prefix}/" if prefix else ""


@dataclass
class Settings:
    endpoint: str
    bucket: str
    region: str
    data_dir: Path
    engine: str
    prefix: str = ""
    # libpq environment for pg_dump (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE); never logged.
    pg_env: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        missing = [n for n in ("BACKUP_S3_ENDPOINT", "BACKUP_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not env.get(n)]
        if missing:
            raise BackupError(f"missing environment: {', '.join(missing)}")
        return cls(
            endpoint=env["BACKUP_S3_ENDPOINT"],
            bucket=env["BACKUP_S3_BUCKET"],
            region=env.get("BACKUP_S3_REGION") or "auto",
            data_dir=Path(env.get("BACKUP_DATA_DIR") or "/app/data"),
            engine=(env.get("BACKUP_DB_ENGINE") or env.get("DB_ENGINE") or "sqlite").lower(),
            prefix=normalize_prefix(env.get("BACKUP_S3_PREFIX")),
            pg_env={
                pg: env[app]
                for pg, app in (
                    ("PGHOST", "POSTGRES_SERVER"),
                    ("PGPORT", "POSTGRES_PORT"),
                    ("PGUSER", "POSTGRES_USER"),
                    ("PGPASSWORD", "POSTGRES_PASSWORD"),
                    ("PGDATABASE", "POSTGRES_DB"),
                )
                if env.get(app)
            },
        )


def make_bucket(settings: Settings) -> Bucket:
    import boto3
    from botocore.config import Config

    # Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY via boto3's own lookup; this
    # module never reads or logs them. Checksums only when required: R2 and older MinIO reject or
    # ignore some of the flexible checksums newer botocore adds by default.
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        retries={"max_attempts": 5, "mode": "standard"},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    client = boto3.client("s3", endpoint_url=settings.endpoint, region_name=settings.region, config=config)
    return Bucket(client, settings.bucket, settings.prefix)


# --------------------------------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------------------------------


@dataclass
class Report:
    db_key: str | None = None
    db_bytes: int = 0
    db_gz_bytes: int = 0
    config_key: str | None = None
    config_files: list[str] = field(default_factory=list)
    assets_uploaded: int = 0
    assets_uploaded_bytes: int = 0
    assets_unchanged: int = 0
    pruned: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self, seconds: float, dry_run: bool) -> str:
        status = "FAILED" if self.failures else "ok"
        verb = "would upload" if dry_run else "uploaded"
        if not self.db_key:
            db = "db not backed up"
        elif self.db_gz_bytes:
            db = f"db {_mb(self.db_bytes)} -> {_mb(self.db_gz_bytes)} gz ({self.db_key})"
        else:
            db = f"db {_mb(self.db_bytes)} ({self.db_key})"
        config = f"config {len(self.config_files)} item(s)" if self.config_key else "config not backed up"
        assets = f"assets {self.assets_uploaded} {verb} ({_mb(self.assets_uploaded_bytes)}), {self.assets_unchanged} unchanged"
        parts = [db, config, assets, f"pruned {self.pruned}", f"{seconds:.1f}s"]
        if dry_run:
            parts.insert(0, "DRY RUN")
        if self.failures:
            parts.append(f"{len(self.failures)} failure(s): " + "; ".join(self.failures[:5]))
        return f"offsite-backup {status}: " + ", ".join(parts)


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def backup_database(settings: Settings, bucket: Bucket, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    """Back up the database for the configured engine. The engine seam lives here."""
    if settings.engine == "sqlite":
        backup_sqlite(settings, bucket, now, work, report, dry_run)
    elif settings.engine == "postgres":
        backup_postgres(settings, bucket, now, work, report, dry_run)
    else:
        raise BackupError(f"unknown DB engine {settings.engine!r}")


def backup_sqlite(settings: Settings, bucket: Bucket, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    snapshot = work / DB_NAME
    snapshot_sqlite(settings.data_dir / DB_NAME, snapshot)  # raises before anything is uploaded
    packed = work / f"{DB_NAME}.gz"
    gzip_file(snapshot, packed)
    key = db_key(now)
    meta = {META_SHA256: file_digest(packed), META_DB_SHA256: file_digest(snapshot)}
    if not dry_run:
        bucket.put_file(key, packed, meta, "application/gzip")
    report.db_key, report.db_bytes, report.db_gz_bytes = key, snapshot.stat().st_size, packed.stat().st_size
    log.info("database: %s (%s, gz %s)", key, _mb(report.db_bytes), _mb(report.db_gz_bytes))


def _run_pg(args: list[str], settings: Settings, what: str) -> subprocess.CompletedProcess:
    """Run a libpq client with the connection in its environment (never argv: /proc/<pid>/cmdline is
    world-readable). stderr is surfaced on failure; it never carries the password."""
    missing = [k for k in ("PGHOST", "PGUSER", "PGDATABASE") if not settings.pg_env.get(k)]
    if missing:
        raise BackupError(f"{what}: POSTGRES_SERVER/POSTGRES_USER/POSTGRES_DB not set")
    env = {**os.environ, **settings.pg_env}
    try:
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=PG_DUMP_TIMEOUT, check=False)
    except FileNotFoundError as exc:
        raise BackupError(f"{what}: {args[0]} not found (the backend image needs postgresql-client)") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"{what}: timed out after {PG_DUMP_TIMEOUT}s") from exc
    if result.returncode != 0:
        raise BackupError(f"{what} failed ({result.returncode}): {result.stderr.strip()[-500:]}")
    return result


def dump_postgres(settings: Settings, dest: Path) -> int:
    """pg_dump the database to `dest` (custom format: compressed, selective restore with pg_restore)
    and prove the archive reads back; returns its number of table-data entries."""
    _run_pg(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={dest}"], settings, "pg_dump")
    listing = _run_pg(["pg_restore", "--list", str(dest)], settings, "pg_restore --list").stdout
    tables = sum(1 for line in listing.splitlines() if " TABLE DATA " in line)
    if tables == 0:
        raise BackupError("pg_dump produced an archive with no table data")
    return tables


def backup_postgres(settings: Settings, bucket: Bucket, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    dump = work / "marvin.dump"
    tables = dump_postgres(settings, dump)  # raises before anything is uploaded
    key = pg_key(now)
    if not dry_run:
        bucket.put_file(key, dump, {META_SHA256: file_digest(dump)}, "application/octet-stream")
    report.db_key, report.db_bytes = key, dump.stat().st_size
    log.info("database: %s (pg_dump, %d tables, %s)", key, tables, _mb(report.db_bytes))


def backup_config(settings: Settings, bucket: Bucket, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    archive = work / "config.tar.gz"
    names = build_config_archive(settings.data_dir, archive)
    if ".secret" not in names:
        log.warning("config: %s/.secret not found; a restore of this backup cannot decrypt stored secrets", settings.data_dir)
    if not names:
        raise BackupError("config: none of .secret, scheduler_state.json, templates/ found")
    key = config_key(now)
    if not dry_run:
        bucket.put_file(key, archive, {META_SHA256: file_digest(archive)}, "application/gzip")
    report.config_key, report.config_files = key, names
    log.info("config: %s (%s)", key, ", ".join(names))


def backup_assets(settings: Settings, bucket: Bucket, report: Report, dry_run: bool) -> None:
    remote = bucket.list(ASSETS_PREFIX)
    for rel, path in iter_local_assets(settings.data_dir / "assets"):
        key = asset_key(rel)
        try:
            if not asset_needs_upload(path, remote.get(key)):
                report.assets_unchanged += 1
                continue
            if not dry_run:
                bucket.put_file(key, path)
            report.assets_uploaded += 1
            report.assets_uploaded_bytes += path.stat().st_size
        except Exception as exc:  # one unreadable file must not stop the rest of the mirror
            report.failures.append(f"asset {rel}: {type(exc).__name__}")
            log.error("asset %s: %s", rel, exc)


def prune(bucket: Bucket, prefix: str, report: Report, dry_run: bool) -> None:
    expired = select_expired(bucket.list(prefix), keep_hourly=KEEP_HOURLY if prefix == PG_PREFIX else 0)
    for key in expired:
        log.info("prune: %s%s", key, " (dry run)" if dry_run else "")
    if expired and not dry_run:
        bucket.delete(expired)
    report.pruned += len(expired)


def run_backup(settings: Settings, bucket: Bucket, dry_run: bool = False, now: datetime | None = None) -> Report:
    """Run every step; a failed step is recorded and the rest still run. A prefix is pruned only
    when this run's upload to it succeeded, so failing backups never thin out the good ones."""
    now = now or datetime.now(UTC)
    report = Report()
    with tempfile.TemporaryDirectory(prefix="marvin-backup-") as tmp:
        work = Path(tmp)
        for name, step, prefix in (
            ("database", lambda: backup_database(settings, bucket, now, work, report, dry_run), db_prefix(settings.engine)),
            ("config", lambda: backup_config(settings, bucket, now, work, report, dry_run), CONFIG_PREFIX),
        ):
            try:
                step()
                prune(bucket, prefix, report, dry_run)
            except Exception as exc:
                report.failures.append(f"{name}: {exc}")
                log.error("%s: %s", name, exc)
    try:
        backup_assets(settings, bucket, report, dry_run)
    except Exception as exc:
        report.failures.append(f"assets: {exc}")
        log.error("assets: %s", exc)
    return report


# --------------------------------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------------------------------


def latest_key(bucket: Bucket, prefix: str) -> str:
    stamped = [k for k in bucket.list(prefix) if key_timestamp(k) is not None]
    if not stamped:
        raise BackupError(f"no backups under {prefix}")
    return max(stamped, key=lambda k: key_timestamp(k))  # type: ignore[arg-type, return-value]


def _verify_sha(path: Path, expected: str | None, what: str) -> None:
    if not expected:
        raise BackupError(f"{what}: no sha256 in object metadata; refusing to trust it")
    if file_digest(path) != expected:
        raise BackupError(f"{what}: sha256 mismatch (corrupt download or object)")


def _move_aside(path: Path, suffix: str) -> None:
    if path.exists():
        aside = path.with_name(f"{path.name}.pre-restore-{suffix}")
        path.rename(aside)
        log.info("moved existing %s to %s", path.name, aside.name)


def restore_database(bucket: Bucket, key: str, target: Path, suffix: str) -> Path:
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=target) as tmp:
        packed = Path(tmp) / "db.gz"
        meta = bucket.download(key, packed)
        _verify_sha(packed, meta.get(META_SHA256), key)
        staged = Path(tmp) / DB_NAME
        gunzip_file(packed, staged)
        _verify_sha(staged, meta.get(META_DB_SHA256), f"{key} (uncompressed)")
        check_integrity(staged)
        # A leftover -wal/-shm beside the restored file would be replayed onto it: move all three.
        for name in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm"):
            _move_aside(target / name, suffix)
        dest = target / DB_NAME
        staged.replace(dest)
    log.info("restored %s -> %s", key, dest)
    return dest


def restore_pg_dump(bucket: Bucket, key: str, target: Path, suffix: str) -> Path:
    """Download and verify a pg_dump archive as target/marvin.dump. Loading it into a database is a
    deliberate, separate `pg_restore` (see docs/manual/postgres.md) — never done here."""
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=target) as tmp:
        staged = Path(tmp) / PG_DUMP_NAME
        meta = bucket.download(key, staged)
        _verify_sha(staged, meta.get(META_SHA256), key)
        _move_aside(target / PG_DUMP_NAME, suffix)
        dest = target / PG_DUMP_NAME
        staged.replace(dest)
    log.info("restored %s -> %s (load it with pg_restore)", key, dest)
    return dest


def restore_config(bucket: Bucket, key: str, target: Path, suffix: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=target) as tmp:
        archive = Path(tmp) / "config.tar.gz"
        meta = bucket.download(key, archive)
        _verify_sha(archive, meta.get(META_SHA256), key)
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            tops = sorted({m.name.split("/", 1)[0] for m in members})
            for top in tops:
                _move_aside(target / top, suffix)
            tar.extractall(target, filter="data")  # rejects absolute paths, `..`, links out of target
    if (target / ".secret").is_file():
        (target / ".secret").chmod(0o600)
    log.info("restored %s -> %s (%s)", key, target, ", ".join(tops))
    return tops


def restore_assets(bucket: Bucket, target: Path) -> tuple[int, int]:
    """Download assets missing or different locally. Never deletes local files. Returns
    (downloaded, unchanged)."""
    assets_dir = (target / "assets").resolve()
    downloaded = unchanged = 0
    for key, obj in sorted(bucket.list(ASSETS_PREFIX).items()):
        dest = (assets_dir / key[len(ASSETS_PREFIX) :]).resolve()
        if not dest.is_relative_to(assets_dir) or dest == assets_dir:
            raise BackupError(f"refusing asset key outside assets/: {key}")
        if dest.is_file() and not asset_needs_upload(dest, obj):  # same test, other direction
            unchanged += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        bucket.download(key, part)
        part.replace(dest)
        downloaded += 1
    log.info("assets: %d downloaded, %d unchanged -> %s", downloaded, unchanged, assets_dir)
    return downloaded, unchanged


def run_restore(
    bucket: Bucket,
    target: Path,
    db: str | None = None,
    config: str | None = None,
    assets: bool = True,
    skip_db: bool = False,
    skip_config: bool = False,
    force: bool = False,
    engine: str = "sqlite",
) -> None:
    """Restore into `target`. The database object is the newest of the engine's family unless `db`
    names one; a `postgres/` key is fetched as marvin.dump, a `sqlite/` key restored as marvin.db."""
    target.mkdir(parents=True, exist_ok=True)
    db = None if skip_db else db or latest_key(bucket, db_prefix(engine))
    is_pg = bool(db and db.startswith(PG_PREFIX))
    replaces = ([] if not db else [PG_DUMP_NAME if is_pg else DB_NAME]) + ([] if skip_config else [".secret"])
    occupied = [n for n in replaces if (target / n).exists()]
    if occupied and not force:
        raise BackupError(
            f"{target} already has {', '.join(occupied)}; restore into an empty directory, or stop the "
            "backend and pass --force (existing files are moved aside as *.pre-restore-<ts>)"
        )
    # Pick the objects first, so a missing backup fails before anything in target changes. Each
    # object is downloaded and verified before the file it replaces is moved aside.
    config = None if skip_config else config or latest_key(bucket, CONFIG_PREFIX)
    suffix = stamp(datetime.now(UTC))
    if db:
        (restore_pg_dump if is_pg else restore_database)(bucket, db, target, suffix)
    if config:
        restore_config(bucket, config, target, suffix)
    if assets:
        restore_assets(bucket, target)


# --------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m marvin.scripts.offsite_backup", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command")
    b = sub.add_parser("backup", help="back up DATA_DIR (the default command)")
    b.add_argument("--dry-run", action="store_true", help="snapshot and verify locally, list what would change, upload/delete nothing")
    sub.add_parser("list", help="list database and config backups in the bucket")
    r = sub.add_parser("restore", help="restore a backup into a directory")
    r.add_argument("--target", type=Path, required=True, help="directory to restore into (a data dir layout)")
    r.add_argument("--db-key", help="sqlite/... or postgres/... object to restore (default: the newest for DB_ENGINE)")
    r.add_argument("--config-key", help="config/... object to restore (default: the newest)")
    r.add_argument("--skip-db", action="store_true")
    r.add_argument("--skip-config", action="store_true")
    r.add_argument("--skip-assets", action="store_true")
    r.add_argument("--force", action="store_true", help="replace an existing marvin.db/.secret in --target; only with the backend stopped")
    p.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)  # `offsite_backup --dry-run`
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    for noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args = _parser().parse_args(argv)
    command = args.command or "backup"
    try:
        settings = Settings.from_env()
        bucket = make_bucket(settings)
    except BackupError as exc:
        log.error("%s", exc)
        return 2

    if command == "backup":
        started = time.monotonic()
        report = run_backup(settings, bucket, dry_run=args.dry_run)
        log.info("%s", report.summary(time.monotonic() - started, args.dry_run))
        return 1 if report.failures else 0
    try:
        if command == "list":
            for prefix in (DB_PREFIX, PG_PREFIX, CONFIG_PREFIX):
                for key, obj in sorted(bucket.list(prefix).items()):
                    sys.stdout.write(f"{key}\t{obj.size}\n")
        else:
            run_restore(
                bucket,
                args.target,
                db=args.db_key,
                config=args.config_key,
                assets=not args.skip_assets,
                skip_db=args.skip_db,
                skip_config=args.skip_config,
                engine=settings.engine,
                force=args.force,
            )
    except Exception as exc:
        log.error("%s failed: %s", command, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
