"""The backup engine: back up a Marvin data directory to one backup target, restore from it, prune it.

Grew out of the old single-target ``scripts/offsite_backup.py`` (removed in storage slice 7), moved onto the storage
contract: its S3 ``Bucket`` became any ``BackupTarget``, and assets are read through the storage
provider (``iter_keys`` + ``get``) rather than ``DATA_DIR/assets``, so backups keep working once assets
live in a cloud bucket. The key layout is unchanged (see ``layout``), so a target reads and prunes the
history the old script wrote.

What a run backs up, and how:

- the database: a ``pg_dump --format=custom`` checked with ``pg_restore --list``; the POSTGRES_*
  connection travels in PG* environment variables, never on a command line. Object metadata carries
  ``sha256``; restore checks it. The engine does not yet write or restore the ``sqlite/`` family
  (``.db.gz`` backups on a target still list, a backup run never prunes them, ``prune`` ages them out; to bring one
  over, see ``run_restore``).
- the config archive: ``.secret`` (it decrypts every stored secret, so a target must stay private),
  ``scheduler_state.json``, ``templates/``.
- an incremental asset mirror under ``assets/``: an asset is copied when the target lacks it, or the
  size or a comparable digest differs. Never deleted from the target.
- workspace backup bundles: each zip in ``DATA_DIR/backups`` (the Backups feature's, and the daily
  ``create_workspace_bundles`` task's) copied once to ``bundles/<workspace>/``, the newest
  ``retention.bundles`` per workspace kept — per-workspace restore points beside the full backup.

Each step that fails is reported and the rest still run; a family is pruned only after this run's
upload to it succeeded, counting backups that exist (a run of failures never empties a target), and
never ``assets/`` or keys the engine didn't name.

Like the old script it runs in a CronJob next to the live backend, so importing and running it must
not build Marvin's settings, create directories in DATA_DIR or open the database through SQLAlchemy:
configuration comes from the environment (``BackupSettings.from_env``).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marvin_integration_sdk.storage import BackupTarget, StorageConfigError, StorageProvider, TargetObject, read_config

from marvin.core.settings.db_providers import resolve_engine

from .layout import (
    ASSETS_PREFIX,
    BUNDLES_PREFIX,
    CONFIG_PREFIX,
    DB_PREFIX,
    PG_PREFIX,
    BackupError,
    Retention,
    asset_key,
    bundle_key,
    config_key,
    expired_bundles,
    key_timestamp,
    pg_key,
    select_expired,
    stamp,
)

log = logging.getLogger("marvin.backup")

PG_DUMP_NAME = "marvin.dump"
POSTGRES = "postgres"
_SQLITE_UNSUPPORTED = (
    "The backup engine does not back up or restore SQLite yet; it handles Postgres only. A `sqlite/` backup on a target "
    "can be brought over by downloading the `.db.gz`, gunzipping it, and loading it with the copy tool "
    "`python -m marvin.scripts.sqlite_to_postgres` (see docs/manual/postgres.md)."
)


def check_engine(engine: str) -> str:
    """`postgres`, or a ValueError saying where an old SQLite backup goes (the engine does not read it back yet)."""
    if engine == "sqlite":
        raise ValueError(_SQLITE_UNSUPPORTED)
    if engine != POSTGRES:
        raise ValueError(f"unknown DB engine {engine!r}; the backup engine supports only {POSTGRES!r}")
    return engine


# Files and directories under DATA_DIR that go into the config archive. Logs, `.temp`, `backups/`,
# the `marvin.db.pre-*` manual snapshots and the live `-wal`/`-shm` files are deliberately absent.
CONFIG_FILES = (".secret", "scheduler_state.json")
CONFIG_DIRS = ("templates",)  # operator-supplied email templates (services/email)

META_SHA256 = "sha256"  # sha256 of the stored object

CHUNK = 1024 * 1024
PG_DUMP_TIMEOUT = 1800  # seconds


# --------------------------------------------------------------------------------------------------
# Settings, targets and the asset source
# --------------------------------------------------------------------------------------------------


def normalize_prefix(prefix: str | None) -> str:
    """`dev`, `/dev/` and `dev/` all mean `dev/`; empty means the target's root."""
    prefix = (prefix or "").strip().strip("/")
    return f"{prefix}/" if prefix else ""


@dataclass
class BackupSettings:
    data_dir: Path
    engine: str = POSTGRES
    prefix: str = ""
    retention: Retention = field(default_factory=Retention)
    asset_provider: str = "local"
    assets_root: Path | None = None  # the local provider's root (default DATA_DIR/assets)
    extra_asset_providers: tuple[str, ...] = ()  # BACKUP_ASSET_PROVIDERS: more providers to mirror
    # libpq environment for pg_dump (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE); never logged.
    pg_env: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.engine = check_engine(self.engine)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BackupSettings:
        """BACKUP_DATA_DIR (default `/app/data`), BACKUP_DB_ENGINE (default: the engine ``resolve_engine`` finds in the
        environment; only `postgres` is accepted for now),
        BACKUP_PREFIX (else BACKUP_S3_PREFIX, so the old script's environment carries over),
        BACKUP_KEEP_HOURLY / _DAILY / _WEEKLY, STORAGE_PROVIDER + STORAGE_LOCAL_ROOT (where assets are
        read from), BACKUP_ASSET_PROVIDERS (comma-separated providers mirrored as well: an admin can send
        new uploads to another provider than STORAGE_PROVIDER, which this job can't see),
        POSTGRES_SERVER / _PORT / _USER / _PASSWORD / _DB."""
        env = dict(os.environ if env is None else env)
        data_dir = Path(env.get("BACKUP_DATA_DIR") or "/app/data")
        return cls(
            data_dir=data_dir,
            engine=(env.get("BACKUP_DB_ENGINE") or resolve_engine(env)).lower(),
            prefix=normalize_prefix(env.get("BACKUP_PREFIX") or env.get("BACKUP_S3_PREFIX")),
            retention=Retention.from_env(env),
            asset_provider=env.get("STORAGE_PROVIDER") or "local",
            assets_root=Path(env["STORAGE_LOCAL_ROOT"]) if env.get("STORAGE_LOCAL_ROOT") else data_dir / "assets",
            extra_asset_providers=tuple(p.strip() for p in (env.get("BACKUP_ASSET_PROVIDERS") or "").split(",") if p.strip()),
            pg_env=pg_env_from(env),
        )


def pg_env_from(env: Mapping[str, str]) -> dict[str, str]:
    """The libpq variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE) from Marvin's POSTGRES_*."""
    return {
        pg: env[app]
        for pg, app in (
            ("PGHOST", "POSTGRES_SERVER"),
            ("PGPORT", "POSTGRES_PORT"),
            ("PGUSER", "POSTGRES_USER"),
            ("PGPASSWORD", "POSTGRES_PASSWORD"),
            ("PGDATABASE", "POSTGRES_DB"),
        )
        if env.get(app)
    }


class PrefixedTarget(BackupTarget):
    """Another target with ``prefix`` (e.g. `dev/`) prepended to every key on the way out and stripped on
    the way back, so naming, retention and the asset diff work in keys relative to it and an
    environment under a prefix never sees (or prunes) another's objects."""

    def __init__(self, inner: BackupTarget, prefix: str) -> None:
        self.inner, self.prefix = inner, prefix
        self.slug = inner.slug

    def put_file(self, key, path, metadata=None, content_type=None):
        self.inner.put_file(self.prefix + key, path, metadata, content_type)

    def get(self, key, dest):
        return self.inner.get(self.prefix + key, dest)

    def list(self, prefix):
        n = len(self.prefix)
        return {k[n:]: TargetObject(k[n:], o.size, o.digest, o.algorithm, o.metadata) for k, o in self.inner.list(self.prefix + prefix).items()}

    def delete(self, keys):
        self.inner.delete([self.prefix + k for k in keys])

    def head(self, key):
        obj = self.inner.head(self.prefix + key)
        return None if obj is None else TargetObject(key, obj.size, obj.digest, obj.algorithm, obj.metadata)

    def describe(self) -> str:
        return f"{self.inner.describe()} (prefix {self.prefix})"


def open_target(slug: str, env: Mapping[str, Any] | None = None, prefix: str = "") -> BackupTarget:
    """The backup target of type ``slug`` (built-in ``local``, or an installed plugin's), built from the
    settings it declares, read from ``env``. Raises ``StorageConfigError``."""
    from marvin.services.storage import registry

    target_cls = registry.get_plugin(slug, needs="target").target
    try:
        target = target_cls.from_config(read_config(target_cls.settings, os.environ if env is None else env))
    except StorageConfigError as e:
        raise StorageConfigError(f"backup target {slug!r}: {e}") from e
    return PrefixedTarget(target, prefix) if prefix else target


def open_asset_source(settings: BackupSettings, env: Mapping[str, Any] | None = None, slug: str | None = None) -> StorageProvider | None:
    """The storage provider assets are read from (``slug``, default STORAGE_PROVIDER), or None for
    local when its assets directory doesn't exist yet (nothing uploaded; the engine never creates it)."""
    slug = slug or settings.asset_provider
    if slug == "local":
        from marvin.services.storage.local_provider import LocalStorageProvider

        root = settings.assets_root or settings.data_dir / "assets"
        return LocalStorageProvider(root=root) if root.is_dir() else None
    from marvin.services.storage import registry

    provider_cls = registry.get_plugin(slug, needs="provider").provider
    return provider_cls.from_config(read_config(provider_cls.settings, os.environ if env is None else env))


def asset_provider_slugs(settings: BackupSettings) -> list[str]:
    """Every provider the mirror reads, in order: local (built in: rows can live there whatever new
    uploads use), STORAGE_PROVIDER, then BACKUP_ASSET_PROVIDERS."""
    return list(dict.fromkeys(["local", settings.asset_provider, *settings.extra_asset_providers]))


def open_asset_sources(settings: BackupSettings, env: Mapping[str, Any] | None = None) -> tuple[list[StorageProvider], list[str]]:
    """(the providers to mirror assets from, why any of them couldn't be opened). A provider that
    can't be opened fails the asset step only: the database and config backups still run."""
    sources: list[StorageProvider] = []
    problems: list[str] = []
    for slug in asset_provider_slugs(settings):
        try:
            source = open_asset_source(settings, env, slug)
        except Exception as exc:  # StorageConfigError, or a plugin failing to build its client
            problems.append(f"assets from {slug}: {exc}")
            log.error("assets from %s: %s", slug, exc)
            continue
        if source is not None:
            sources.append(source)
    return sources, problems


# --------------------------------------------------------------------------------------------------
# Hashing and archives
# --------------------------------------------------------------------------------------------------


def explain(exc: BaseException):
    """A plain explanation of a storage error, e.g. "the key is invalid or revoked … (InvalidAccessKeyId)"."""
    from marvin.services.storage.healthcheck import explain as _explain

    return _explain(exc)


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


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


# --------------------------------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------------------------------


@dataclass
class Report:
    target: str = ""
    db_key: str | None = None
    db_bytes: int = 0
    db_gz_bytes: int = 0
    config_key: str | None = None
    config_files: list[str] = field(default_factory=list)
    assets_uploaded: int = 0
    assets_uploaded_bytes: int = 0
    assets_unchanged: int = 0
    bundles_uploaded: int = 0
    bundles_uploaded_bytes: int = 0
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
        parts = [db, config, assets]
        if self.bundles_uploaded:
            parts.append(f"bundles {self.bundles_uploaded} {verb} ({_mb(self.bundles_uploaded_bytes)})")
        parts += [f"pruned {self.pruned}", f"{seconds:.1f}s"]
        if dry_run:
            parts.insert(0, "DRY RUN")
        if self.failures:
            parts.append(f"{len(self.failures)} failure(s): " + "; ".join(self.failures[:5]))
        return f"backup[{self.target}] {status}: " + ", ".join(parts)


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def backup_database(settings: BackupSettings, target: BackupTarget, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    """Back up the database for the configured engine. The engine seam lives here."""
    backup_postgres(settings, target, now, work, report, dry_run)


def _run_pg(args: list[str], settings: BackupSettings, what: str) -> subprocess.CompletedProcess:
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


def dump_postgres(settings: BackupSettings, dest: Path) -> int:
    """pg_dump the database to `dest` (custom format: compressed, selective restore with pg_restore)
    and prove the archive reads back; returns its number of table-data entries."""
    _run_pg(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={dest}"], settings, "pg_dump")
    listing = _run_pg(["pg_restore", "--list", str(dest)], settings, "pg_restore --list").stdout
    tables = sum(1 for line in listing.splitlines() if " TABLE DATA " in line)
    if tables == 0:
        raise BackupError("pg_dump produced an archive with no table data")
    return tables


def backup_postgres(settings: BackupSettings, target: BackupTarget, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    dump = work / PG_DUMP_NAME
    tables = dump_postgres(settings, dump)  # raises before anything is uploaded
    key = pg_key(now)
    if not dry_run:
        target.put_file(key, dump, {META_SHA256: file_digest(dump)}, "application/octet-stream")
    report.db_key, report.db_bytes = key, dump.stat().st_size
    log.info("database: %s (pg_dump, %d tables, %s)", key, tables, _mb(report.db_bytes))


def backup_config(settings: BackupSettings, target: BackupTarget, now: datetime, work: Path, report: Report, dry_run: bool) -> None:
    archive = work / "config.tar.gz"
    names = build_config_archive(settings.data_dir, archive)
    if ".secret" not in names:
        log.warning("config: %s/.secret not found; a restore of this backup cannot decrypt stored secrets", settings.data_dir)
    if not names:
        raise BackupError("config: none of .secret, scheduler_state.json, templates/ found")
    key = config_key(now)
    if not dry_run:
        target.put_file(key, archive, {META_SHA256: file_digest(archive)}, "application/gzip")
    report.config_key, report.config_files = key, names
    log.info("config: %s (%s)", key, ", ".join(names))


def asset_needs_copy(source: StorageProvider, key: str, remote: TargetObject | None) -> bool:
    """Copy when the target lacks the asset, the size differs, or both sides can name a digest in the
    same algorithm and they differ. A target digest that isn't a content hash (an S3 multipart ETag),
    or a provider that can't hash without downloading, leaves the size as the test: asset keys carry a
    UUID, so a changed file under the same key is the exception."""
    if remote is None:
        return True
    meta = source.get_metadata(key)
    if meta.size != remote.size:
        return True
    if not remote.algorithm or not remote.digest:
        return False
    if meta.checksum and meta.checksum_algorithm == remote.algorithm:
        ours = meta.checksum
    else:
        ours = source.checksum(key, remote.algorithm)
    return ours is not None and ours != remote.digest


type AssetSources = StorageProvider | Sequence[StorageProvider] | None


def _sources(source: AssetSources) -> list[StorageProvider]:
    if source is None:
        return []
    return [s for s in source if s is not None] if isinstance(source, Sequence) else [source]


def backup_assets(source: AssetSources, target: BackupTarget, report: Report, dry_run: bool, work: Path) -> None:
    """Mirror every key of every source (a key held by several, e.g. mid-move between providers, is
    copied once, from the first: the same key holds the same bytes on each)."""
    sources = _sources(source)
    if not sources:
        log.info("assets: no assets directory yet, nothing to mirror")
        return
    remote = target.list(ASSETS_PREFIX)
    staged = work / "asset"
    seen: set[str] = set()
    for source, key in ((s, k) for s in sources for k in s.iter_keys("")):
        if key in seen:
            continue
        seen.add(key)
        tkey = asset_key(key)
        try:
            if not asset_needs_copy(source, key, remote.get(tkey)):
                report.assets_unchanged += 1
                continue
            if dry_run:
                size = source.get_metadata(key).size
            else:
                with source.get(key) as fh, staged.open("wb") as out:
                    shutil.copyfileobj(fh, out, CHUNK)
                target.put_file(tkey, staged)
                size = staged.stat().st_size
            report.assets_uploaded += 1
            report.assets_uploaded_bytes += size
        except FileNotFoundError:
            # Listed, then deleted before its turn (a run takes minutes; someone deleted an asset meanwhile).
            # Nothing is lost — the asset is gone — so it isn't a failure; the target's copy is kept, as always.
            log.info("asset %s: deleted since the listing, skipped", key)
        except Exception as exc:  # one unreadable file must not stop the rest of the mirror
            report.failures.append(f"asset {key}: {explain(exc).code or type(exc).__name__}")
            log.error("asset %s: %s", key, exc)
        finally:
            staged.unlink(missing_ok=True)


BUNDLES_DIR = "backups"  # under DATA_DIR, where the Backups feature writes workspace bundles


def backup_bundles(settings: BackupSettings, target: BackupTarget, report: Report, dry_run: bool) -> None:
    """Copy each workspace bundle the target lacks (a bundle's name is unique, so presence is enough), then
    keep the newest `retention.bundles` per workspace. Bundles are written and thinned locally by the
    backend; the target keeps a longer history."""
    keep = settings.retention.bundles
    folder = settings.data_dir / BUNDLES_DIR
    if not keep or not folder.is_dir():
        return
    remote = target.list(BUNDLES_PREFIX)
    for path in sorted(folder.glob("*.zip")):
        key = bundle_key(path.name)
        if key is None or key in remote:
            continue
        if not dry_run:
            target.put_file(key, path, {META_SHA256: file_digest(path)}, "application/zip")
        report.bundles_uploaded += 1
        report.bundles_uploaded_bytes += path.stat().st_size
        remote[key] = TargetObject(key=key, size=path.stat().st_size)
        log.info("bundle: %s", key)
    prune_bundles(target, keep, report, dry_run, listing=remote)


def prune_bundles(target: BackupTarget, keep: int, report: Report, dry_run: bool, listing: Mapping[str, Any] | None = None) -> list[str]:
    expired = expired_bundles(listing if listing is not None else target.list(BUNDLES_PREFIX), keep)
    for key in expired:
        log.info("prune: %s%s", key, " (dry run)" if dry_run else "")
    if expired and not dry_run:
        target.delete(expired)
    report.pruned += len(expired)
    return expired


def prune(target: BackupTarget, prefix: str, retention: Retention, report: Report, dry_run: bool) -> list[str]:
    expired = select_expired(target.list(prefix), retention, prefix)
    for key in expired:
        log.info("prune: %s%s", key, " (dry run)" if dry_run else "")
    if expired and not dry_run:
        target.delete(expired)
    report.pruned += len(expired)
    return expired


def run_backup(
    settings: BackupSettings,
    target: BackupTarget,
    source: AssetSources,
    dry_run: bool = False,
    now: datetime | None = None,
    name: str = "",
) -> Report:
    """Run every step; a failed step is recorded and the rest still run. A family is pruned only when
    this run's upload to it succeeded, so failing backups never thin out the good ones."""
    now = now or datetime.now(UTC)
    report = Report(target=name or target.slug or "target")
    with tempfile.TemporaryDirectory(prefix="marvin-backup-") as tmp:
        work = Path(tmp)
        for step_name, step, prefix in (
            ("database", lambda: backup_database(settings, target, now, work, report, dry_run), PG_PREFIX),
            ("config", lambda: backup_config(settings, target, now, work, report, dry_run), CONFIG_PREFIX),
        ):
            try:
                step()
                prune(target, prefix, settings.retention, report, dry_run)
            except Exception as exc:
                report.failures.append(f"{step_name}: {explain(exc)}")
                log.error("%s: %s", step_name, exc)
        try:
            backup_assets(source, target, report, dry_run, work)
        except Exception as exc:
            report.failures.append(f"assets: {explain(exc)}")
            log.error("assets: %s", exc)
        try:
            backup_bundles(settings, target, report, dry_run)
        except Exception as exc:  # pruning happens inside, only after every copy succeeded
            report.failures.append(f"bundles: {explain(exc)}")
            log.error("bundles: %s", exc)
    return report


def run_prune(settings: BackupSettings, target: BackupTarget, dry_run: bool = False) -> Report:
    """Apply the retention to every family without backing anything up."""
    report = Report(target=target.slug)
    for prefix in (DB_PREFIX, PG_PREFIX, CONFIG_PREFIX):
        prune(target, prefix, settings.retention, report, dry_run)
    if settings.retention.bundles:
        prune_bundles(target, settings.retention.bundles, report, dry_run)
    return report


def list_backups(target: BackupTarget) -> list[TargetObject]:
    """The database and config backups in a target, oldest first per family, then the workspace bundles."""
    found: list[TargetObject] = []
    for prefix in (DB_PREFIX, PG_PREFIX, CONFIG_PREFIX):
        found += [o for k, o in sorted(target.list(prefix).items()) if key_timestamp(k) is not None]
    bundles = target.list(BUNDLES_PREFIX)
    return found + [o for k, o in sorted(bundles.items()) if bundle_key(k.rsplit("/", 1)[-1]) == k]


# --------------------------------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------------------------------


def latest_key(target: BackupTarget, prefix: str) -> str:
    stamped = [k for k in target.list(prefix) if key_timestamp(k) is not None]
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


def restore_pg_dump(target: BackupTarget, key: str, into: Path, suffix: str) -> Path:
    """Download and verify a pg_dump archive as into/marvin.dump. Loading it into a database is a
    deliberate, separate `pg_restore` (see docs/manual/postgres.md), never done here."""
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=into) as tmp:
        staged = Path(tmp) / PG_DUMP_NAME
        meta = target.get(key, staged)
        _verify_sha(staged, meta.get(META_SHA256), key)
        _move_aside(into / PG_DUMP_NAME, suffix)
        dest = into / PG_DUMP_NAME
        staged.replace(dest)
    log.info("restored %s -> %s (load it with pg_restore)", key, dest)
    return dest


def restore_config(target: BackupTarget, key: str, into: Path, suffix: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=into) as tmp:
        archive = Path(tmp) / "config.tar.gz"
        meta = target.get(key, archive)
        _verify_sha(archive, meta.get(META_SHA256), key)
        with tarfile.open(archive, "r:gz") as tar:
            tops = sorted({m.name.split("/", 1)[0] for m in tar.getmembers()})
            for top in tops:
                _move_aside(into / top, suffix)
            tar.extractall(into, filter="data")  # rejects absolute paths, `..`, links out of the directory
    if (into / ".secret").is_file():
        (into / ".secret").chmod(0o600)
    log.info("restored %s -> %s (%s)", key, into, ", ".join(tops))
    return tops


def fetch_bundle(target: BackupTarget, key: str, into: Path) -> Path:
    """Download one workspace bundle into `into`, checked against its sha256, for Admin → Backups → Import."""
    if not key.startswith(BUNDLES_PREFIX) or bundle_key(key.rsplit("/", 1)[-1]) != key:
        raise BackupError(f"{key}: not a workspace bundle key (bundles/<workspace>/<workspace>-backup-….zip)")
    into.mkdir(parents=True, exist_ok=True)
    dest = into / key.rsplit("/", 1)[-1]
    meta = target.get(key, dest)
    try:
        _verify_sha(dest, meta.get(META_SHA256), key)
    except BackupError:
        dest.unlink(missing_ok=True)
        raise
    log.info("fetched %s -> %s", key, dest)
    return dest


def _local_matches(path: Path, obj: TargetObject) -> bool:
    if path.stat().st_size != obj.size:
        return False
    if not obj.algorithm or not obj.digest:
        return True
    return file_digest(path, obj.algorithm) == obj.digest


def restore_assets(target: BackupTarget, into: Path) -> tuple[int, int]:
    """Download assets missing or different under into/assets. Never deletes local files. Returns
    (downloaded, unchanged)."""
    assets_dir = (into / "assets").resolve()
    downloaded = unchanged = 0
    for key, obj in sorted(target.list(ASSETS_PREFIX).items()):
        dest = (assets_dir / key[len(ASSETS_PREFIX) :]).resolve()
        if not dest.is_relative_to(assets_dir) or dest == assets_dir:
            raise BackupError(f"refusing asset key outside assets/: {key}")
        if dest.is_file() and _local_matches(dest, obj):
            unchanged += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        target.get(key, part)
        part.replace(dest)
        downloaded += 1
    log.info("assets: %d downloaded, %d unchanged -> %s", downloaded, unchanged, assets_dir)
    return downloaded, unchanged


def run_restore(
    target: BackupTarget,
    into: Path,
    db: str | None = None,
    config: str | None = None,
    assets: bool = True,
    skip_db: bool = False,
    skip_config: bool = False,
    force: bool = False,
    engine: str = POSTGRES,
) -> None:
    """Restore into the directory `into` (a data dir layout). The database object is the newest `postgres/`
    dump unless `db` names one, fetched and verified as marvin.dump (loading it is a separate pg_restore).

    Only Postgres is restored; engine="sqlite" (or a `sqlite/` key) raises ValueError, see `check_engine`."""
    check_engine(engine)
    if db and db.startswith(DB_PREFIX):
        raise ValueError(_SQLITE_UNSUPPORTED)
    into.mkdir(parents=True, exist_ok=True)
    db = None if skip_db else db or latest_key(target, PG_PREFIX)
    replaces = ([] if not db else [PG_DUMP_NAME]) + ([] if skip_config else [".secret"])
    occupied = [n for n in replaces if (into / n).exists()]
    if occupied and not force:
        raise BackupError(
            f"{into} already has {', '.join(occupied)}; restore into an empty directory, or stop the "
            "backend and pass --force (existing files are moved aside as *.pre-restore-<ts>)"
        )
    # Pick the objects first, so a missing backup fails before anything in `into` changes. Each
    # object is downloaded and verified before the file it replaces is moved aside.
    config = None if skip_config else config or latest_key(target, CONFIG_PREFIX)
    suffix = stamp(datetime.now(UTC))
    if db:
        restore_pg_dump(target, db, into, suffix)
    if config:
        restore_config(target, config, into, suffix)
    if assets:
        restore_assets(target, into)


__all__ = [
    "BackupError",
    "BackupSettings",
    "PrefixedTarget",
    "Report",
    "Retention",
    "list_backups",
    "asset_provider_slugs",
    "open_asset_source",
    "open_asset_sources",
    "open_target",
    "run_backup",
    "run_prune",
    "run_restore",
]
