"""The backup engine (services/backup_engine, scripts/backup): key layout and per-target retention, the built-in
local target (conformance kit, atomic writes, sidecar digests, the same-volume guardrail), and backup /
restore round trips through it, assets read via the storage provider. The database is Postgres only (pg_dump
and pg_restore are faked); the old `sqlite/` key family is legacy: listed and pruned, never written or restored."""

import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from marvin_integration_sdk.storage import StorageConfigError, TargetObject
from marvin_integration_sdk.storage.memory import MemoryBackupTarget, MemoryStorageProvider
from marvin_integration_sdk.storage.testing import BackupTargetContract

from marvin.services.backup_engine import engine as eng
from marvin.services.backup_engine import layout as keys
from marvin.services.backup_engine import local_target as lt
from marvin.services.backup_engine.layout import Retention
from marvin.services.backup_engine.local_target import LocalBackupTarget
from marvin.services.storage.local_provider import LocalStorageProvider

NOW = datetime(2026, 10, 6, 7, 15, 0, tzinfo=UTC)
REPO_SRC = Path(__file__).resolve().parents[1] / "src"


PG_ENV = {"PGHOST": "marvin-dev-pg-rw", "PGPORT": "5432", "PGUSER": "marvin", "PGPASSWORD": "pg-pass-do-not-print", "PGDATABASE": "marvin"}


class FakePg:
    """Stands in for subprocess.run of pg_dump / pg_restore --list."""

    def __init__(self, returncode: int = 0, tables: int = 3) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.returncode, self.tables = returncode, tables

    def __call__(self, args, env, capture_output, text, timeout, check):
        self.calls.append((list(args), dict(env)))
        if args[0] == "pg_dump":
            if self.returncode == 0:
                Path(next(a.split("=", 1)[1] for a in args if a.startswith("--file="))).write_bytes(b"PGDMP" + b"x" * 64)
            return subprocess.CompletedProcess(args, self.returncode, "", "pg_dump: error: connection refused")
        listing = "\n".join(f"{i}; 0 0 TABLE DATA public t{i} marvin" for i in range(self.tables))
        return subprocess.CompletedProcess(args, 0, listing, "")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "assets" / "ws1").mkdir(parents=True)
    (d / ".secret").write_text("s3cr3t-installation-key")
    (d / "scheduler_state.json").write_text('{"last": 1}')
    (d / "assets" / "ws1" / "a.png").write_bytes(b"\x89PNG" + b"a" * 100)
    (d / "assets" / "b.txt").write_text("hello")
    # Things that must not be backed up.
    (d / ".temp").mkdir()
    (d / ".temp" / "scratch").write_text("x")
    (d / "marvin.db.pre-migration").write_text("old")
    return d


@pytest.fixture
def settings(data_dir: Path, monkeypatch) -> eng.BackupSettings:
    monkeypatch.setattr(eng.subprocess, "run", FakePg())  # a test that wants another pg_dump patches over this
    return eng.BackupSettings(data_dir=data_dir, assets_root=data_dir / "assets", pg_env=PG_ENV)


@pytest.fixture
def target(tmp_path: Path) -> LocalBackupTarget:
    root = tmp_path / "nas"
    root.mkdir()
    return LocalBackupTarget(root)  # no data_dir: the guardrail has its own tests


@pytest.fixture
def source(data_dir: Path) -> LocalStorageProvider:
    return LocalStorageProvider(root=data_dir / "assets")


def _keys(target) -> set[str]:
    return set(target.list(""))


# --- key layout and retention ---------------------------------------------------------------------


def test_key_layout_is_the_old_scripts():
    """The names the old offsite_backup.py wrote (removed in slice 7), so a target reads and prunes that history."""
    assert keys.db_key(NOW) == "sqlite/marvin-20261006T071500Z.db.gz"  # legacy family: still named, never written
    assert keys.key_timestamp(keys.db_key(NOW)) == NOW
    assert keys.pg_key(NOW) == "postgres/marvin-20261006T071500Z.dump"
    assert keys.config_key(NOW) == "config/marvin-config-20261006T071500Z.tar.gz"
    assert keys.asset_key("ws1/a.png") == "assets/ws1/a.png"


@pytest.mark.parametrize("key", ["assets/sqlite/marvin-20261006T071500Z.db.gz", "sqlite/marvin-20261006T071500Z.dump", "sqlite/other.db.gz"])
def test_foreign_keys_have_no_timestamp(key):
    assert keys.key_timestamp(key) is None


def _hourly(prefix_key, hours: int, start: datetime = NOW) -> list[str]:
    return [prefix_key(start - timedelta(hours=h)) for h in range(hours)]


def test_default_retention_is_30_days_hourly_for_the_last_two():
    assert Retention() == Retention(hourly=48, daily=30, weekly=0)
    dumps = _hourly(keys.pg_key, 24 * 60)  # 60 days of hourly dumps
    kept = set(dumps) - set(keys.select_expired(dumps, Retention(), keys.PG_PREFIX))
    newest_48 = set(dumps[:48])
    assert newest_48 <= kept
    days = {keys.key_timestamp(k).date() for k in kept}
    assert len(days) == 30
    overlap = len({keys.key_timestamp(k).date() for k in newest_48})  # days the 48 hours touch: their newest counts once
    assert len(kept) == 48 + 30 - overlap


def test_hourly_applies_to_database_backups_not_the_config_archive():
    configs = _hourly(keys.config_key, 72)
    kept = set(configs) - set(keys.select_expired(configs, Retention(), keys.CONFIG_PREFIX))
    assert len(kept) == 4  # one per day: 72 hours touch four UTC days
    sqlite = _hourly(keys.db_key, 72)
    assert len(set(sqlite) - set(keys.select_expired(sqlite, Retention(), keys.DB_PREFIX))) == 48 + 1


def test_retention_counts_periods_with_backups_not_calendar_days():
    old = [keys.pg_key(NOW - timedelta(days=400 + d)) for d in range(3)]  # a long gap, then nothing new
    assert keys.select_expired(old, Retention(hourly=0, daily=2), keys.PG_PREFIX) == [old[2]]


def test_retention_never_expires_keys_it_did_not_name():
    foreign = ["postgres/manual-copy.dump", "postgres/marvin-20200101T000000Z.dump.bak"]
    assert keys.select_expired(foreign + [keys.pg_key(NOW)], Retention(hourly=0, daily=1), keys.PG_PREFIX) == []


def test_retention_r2_rule_keeps_8_weekly():
    dumps = [keys.pg_key(NOW - timedelta(days=d)) for d in range(120)]
    kept = set(dumps) - set(keys.select_expired(dumps, Retention(hourly=48, daily=30, weekly=8), keys.PG_PREFIX))
    assert max(NOW - keys.key_timestamp(k) for k in kept) > timedelta(days=45)  # weeks reach past the 30 days


@pytest.mark.parametrize(
    "env, expected",
    [({}, Retention()), ({"BACKUP_KEEP_HOURLY": "24", "BACKUP_KEEP_DAILY": "7", "BACKUP_KEEP_WEEKLY": "0"}, Retention(24, 7, 0))],
)
def test_retention_from_env(env, expected):
    assert Retention.from_env(env) == expected


@pytest.mark.parametrize("env", [{"BACKUP_KEEP_DAILY": "0"}, {"BACKUP_KEEP_HOURLY": "-1"}, {"BACKUP_KEEP_WEEKLY": "two"}])
def test_bad_retention_is_refused(env):
    with pytest.raises(keys.BackupError):
        Retention.from_env(env)


def test_settings_from_env():
    s = eng.BackupSettings.from_env(
        {
            "BACKUP_DATA_DIR": "/data",
            "DB_ENGINE": "Postgres",
            "BACKUP_S3_PREFIX": "/dev/",
            "BACKUP_KEEP_DAILY": "7",
            "POSTGRES_SERVER": "pg",
            "POSTGRES_USER": "marvin",
            "POSTGRES_PASSWORD": "pw",
            "POSTGRES_DB": "marvin",
        }
    )
    assert (s.data_dir, s.engine, s.prefix, s.retention.daily) == (Path("/data"), "postgres", "dev/", 7)
    assert (s.asset_provider, s.assets_root) == ("local", Path("/data/assets"))
    assert s.pg_env == {"PGHOST": "pg", "PGUSER": "marvin", "PGPASSWORD": "pw", "PGDATABASE": "marvin"}
    assert "pw" not in repr(s)
    assert eng.BackupSettings.from_env({"BACKUP_PREFIX": "nas", "BACKUP_S3_PREFIX": "dev"}).prefix == "nas/"


# --- the local target -----------------------------------------------------------------------------


class TestLocalTargetConformance(BackupTargetContract):
    @pytest.fixture
    def target(self, tmp_path):
        root = tmp_path / "nas"
        root.mkdir()
        return LocalBackupTarget(root)


def test_local_target_refuses_a_missing_root(tmp_path):
    with pytest.raises(StorageConfigError, match="does not exist"):
        LocalBackupTarget(tmp_path / "not-mounted")


def test_local_target_refuses_the_data_directory(tmp_path, data_dir):
    with pytest.raises(StorageConfigError, match="inside the data directory"):
        LocalBackupTarget(data_dir, data_dir=data_dir)
    (data_dir / "backups").mkdir()
    with pytest.raises(StorageConfigError, match="inside the data directory"):
        LocalBackupTarget(data_dir / "backups", data_dir=data_dir)


def test_local_target_refuses_the_data_volume(tmp_path, data_dir):
    root = tmp_path / "nas"
    root.mkdir()
    with pytest.raises(StorageConfigError, match="same filesystem"):
        LocalBackupTarget(root, data_dir=data_dir)  # both under tmp_path: one filesystem


def test_local_target_accepts_another_volume(tmp_path, data_dir, monkeypatch):
    root = tmp_path / "nas"
    root.mkdir()
    real = lt._device
    monkeypatch.setattr(lt, "_device", lambda p: real(p) + (1 if Path(p) == root.resolve() else 0))
    assert LocalBackupTarget(root, data_dir=data_dir).root == root.resolve()


def test_local_target_from_config(tmp_path, data_dir):
    with pytest.raises(StorageConfigError, match="same filesystem"):
        eng.open_target("local", {"BACKUP_LOCAL_ROOT": str(tmp_path), "BACKUP_DATA_DIR": str(data_dir)})
    with pytest.raises(StorageConfigError, match="BACKUP_LOCAL_ROOT"):
        eng.open_target("local", {})


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a", "a/", "a\\b", "assets/.marvin-tmp-x"])
def test_local_target_refuses_odd_keys(target, tmp_path, key):
    src = tmp_path / "f"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        target.put_file(key, src)


def test_local_target_keeps_sha256_in_a_sidecar_and_leaves_no_temp_files(target, tmp_path):
    src = tmp_path / "f"
    src.write_bytes(b"payload")
    target.put_file("config/x.tar.gz", src, {"SHA256": "abc"})
    side = json.loads((target.root / "config" / "x.tar.gz.meta.json").read_text())
    assert side["digest"] == hashlib.sha256(b"payload").hexdigest() and side["metadata"] == {"sha256": "abc"}
    assert sorted(p.name for p in (target.root / "config").iterdir()) == ["x.tar.gz", "x.tar.gz.meta.json"]


def test_an_asset_ending_in_meta_json_is_still_an_object(target, tmp_path):
    src = tmp_path / "f"
    src.write_bytes(b"{}")
    target.put_file("assets/ws/uuid-notes.meta.json", src)
    assert set(target.list("assets/")) == {"assets/ws/uuid-notes.meta.json"}


def test_a_file_without_a_sidecar_has_no_digest(target):
    (target.root / "assets").mkdir()
    (target.root / "assets" / "orphan.txt").write_bytes(b"x")
    (target.root / "assets" / ".marvin-tmp-abc-half.txt").write_bytes(b"partial")  # an interrupted write
    assert target.list("assets/") == {"assets/orphan.txt": TargetObject("assets/orphan.txt", 1)}


# --- backup ---------------------------------------------------------------------------------------


def test_backup_writes_db_config_and_assets(settings, target, source):
    report = eng.run_backup(settings, target, source, now=NOW)
    assert report.failures == []
    assert _keys(target) == {keys.pg_key(NOW), keys.config_key(NOW), "assets/ws1/a.png", "assets/b.txt"}
    meta = target.head(keys.pg_key(NOW)).metadata
    out = target.root / "dump.out"
    target.get(keys.pg_key(NOW), out)
    assert meta[eng.META_SHA256] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert (report.assets_uploaded, report.assets_unchanged) == (2, 0)


def test_second_run_copies_only_changed_assets(settings, target, source, data_dir):
    eng.run_backup(settings, target, source, now=NOW)
    again = eng.run_backup(settings, target, source, now=NOW + timedelta(hours=1))
    assert (again.assets_uploaded, again.assets_unchanged) == (0, 2)
    (data_dir / "assets" / "b.txt").write_text("HELLO")  # same size, new content: the digest catches it
    third = eng.run_backup(settings, target, source, now=NOW + timedelta(hours=2))
    assert (third.assets_uploaded, third.assets_unchanged) == (1, 1)


def test_backup_never_deletes_target_assets(settings, target, source, data_dir):
    eng.run_backup(settings, target, source, now=NOW)
    (data_dir / "assets" / "b.txt").unlink()
    eng.run_backup(settings, target, source, now=NOW + timedelta(days=1))
    assert "assets/b.txt" in _keys(target)


def test_an_asset_deleted_after_the_listing_is_skipped_not_a_failure(settings, target, source, data_dir, monkeypatch):
    listed = list(source.iter_keys(""))
    monkeypatch.setattr(source, "iter_keys", lambda prefix="": iter(listed))
    (data_dir / "assets" / "b.txt").unlink()  # deleted mid-run, after the mirror listed it

    report = eng.run_backup(settings, target, source, now=NOW)

    assert report.failures == []
    assert (report.assets_uploaded, report.assets_unchanged) == (1, 0)


def test_dry_run_writes_and_deletes_nothing(settings, target, source):
    old = keys.pg_key(NOW - timedelta(days=400))
    src = target.root.parent / "old"
    src.write_bytes(b"x")
    target.put_file(old, src)
    report = eng.run_backup(settings, target, source, dry_run=True, now=NOW)
    assert _keys(target) == {old}
    assert report.assets_uploaded == 2 and "DRY RUN" in report.summary(1.0, True)


def test_backup_prunes_old_snapshots_by_the_targets_retention(settings, target, source):
    src = target.root.parent / "old"
    src.write_bytes(b"x")
    for d in range(1, 40):
        target.put_file(keys.pg_key(NOW - timedelta(days=d)), src)
    settings.retention = Retention(hourly=0, daily=7)
    report = eng.run_backup(settings, target, source, now=NOW)
    remaining = set(target.list("postgres/"))
    assert keys.pg_key(NOW) in remaining and len(remaining) == 7
    assert report.pruned == 33


def test_a_failed_dump_aborts_db_upload_and_its_pruning_but_not_the_rest(settings, target, source, monkeypatch):
    src = target.root.parent / "old"
    src.write_bytes(b"x")
    stale = [keys.pg_key(NOW - timedelta(days=d)) for d in range(1, 60)]
    for k in stale:
        target.put_file(k, src)

    monkeypatch.setattr(eng.subprocess, "run", FakePg(tables=0))  # a dump with no table data fails its check
    report = eng.run_backup(settings, target, source, now=NOW)
    assert keys.pg_key(NOW) not in _keys(target)
    assert set(stale) <= _keys(target)
    assert keys.config_key(NOW) in _keys(target) and "assets/b.txt" in _keys(target)
    assert any("no table data" in f for f in report.failures)


def test_assets_are_read_through_any_storage_provider(settings, target):
    remote = MemoryStorageProvider()
    remote.put("ws1/cloud.png", io.BytesIO(b"from the bucket"), "image/png")
    report = eng.run_backup(settings, target, remote, now=NOW)
    assert report.failures == [] and "assets/ws1/cloud.png" in _keys(target)
    assert eng.run_backup(settings, target, remote, now=NOW + timedelta(hours=1)).assets_unchanged == 1


class Md5Target(MemoryBackupTarget):
    """An S3-like target: digests are MD5 ETags."""

    def _object(self, key):
        data, metadata = self.objects[key]
        return TargetObject(key, len(data), hashlib.md5(data).hexdigest(), "md5", dict(metadata))


def test_digest_comparison_crosses_algorithms(settings, source, data_dir):
    target = Md5Target()
    eng.run_backup(settings, target, source, now=NOW)
    assert eng.run_backup(settings, target, source, now=NOW + timedelta(hours=1)).assets_uploaded == 0
    (data_dir / "assets" / "b.txt").write_text("HELLO")
    assert eng.run_backup(settings, target, source, now=NOW + timedelta(hours=2)).assets_uploaded == 1


def test_no_assets_directory_is_not_an_error(settings, target, data_dir):
    import shutil

    shutil.rmtree(data_dir / "assets")
    assert eng.open_asset_source(settings) is None
    report = eng.run_backup(settings, target, None, now=NOW)
    assert report.failures == [] and keys.pg_key(NOW) in _keys(target)
    assert not (data_dir / "assets").exists()  # never created


def test_prefix_keeps_an_environment_to_itself(settings, source, tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    shared = LocalBackupTarget(root)
    eng.run_backup(settings, eng.PrefixedTarget(shared, "dev/"), source, now=NOW)
    assert all(k.startswith("dev/") for k in _keys(shared))
    prod = eng.PrefixedTarget(shared, "prod/")
    assert prod.list("") == {}
    assert eng.run_prune(settings, prod).pruned == 0


# --- postgres -------------------------------------------------------------------------------------


def test_postgres_dump_is_written_verified_and_pruned(settings, target, source, monkeypatch):
    fake = FakePg()
    monkeypatch.setattr(eng.subprocess, "run", fake)
    src = target.root.parent / "old"
    src.write_bytes(b"old")
    for d in range(1, 120):
        target.put_file(keys.pg_key(NOW - timedelta(days=d)), src)
    keep_sqlite = keys.db_key(NOW - timedelta(days=400))  # the legacy sqlite/ family is not this run's to prune
    target.put_file(keep_sqlite, src)

    report = eng.run_backup(settings, target, source, now=NOW)

    assert report.failures == []
    obj = target.head(keys.pg_key(NOW))
    assert obj.metadata[eng.META_SHA256] == obj.digest  # sha256 of the dump, as the local target hashes it too
    assert keys.pg_key(NOW - timedelta(days=119)) not in _keys(target) and keep_sqlite in _keys(target)
    assert [c[0][0] for c in fake.calls] == ["pg_dump", "pg_restore"]
    for args, env in fake.calls:
        assert env["PGPASSWORD"] == PG_ENV["PGPASSWORD"]  # the password travels in the environment...
        assert not any(PG_ENV["PGPASSWORD"] in a for a in args)  # ...never on the command line
    assert PG_ENV["PGPASSWORD"] not in report.summary(1.0, False)


@pytest.mark.parametrize("fake, message", [(FakePg(returncode=1), "connection refused"), (FakePg(tables=0), "no table data")])
def test_a_bad_postgres_dump_writes_nothing(settings, target, source, monkeypatch, fake, message):
    monkeypatch.setattr(eng.subprocess, "run", fake)
    report = eng.run_backup(settings, target, source, now=NOW)
    assert not target.list("postgres/")
    assert any(message in f for f in report.failures)


def test_postgres_without_a_connection_is_a_reported_failure(settings, target, source):
    settings.pg_env = {}
    report = eng.run_backup(settings, target, source, now=NOW)
    assert any("POSTGRES_SERVER" in f for f in report.failures)
    assert keys.config_key(NOW) in _keys(target)


def test_missing_pg_dump_binary_says_what_to_install(settings, target, source, monkeypatch):
    def missing(*a, **kw):
        raise FileNotFoundError("pg_dump")

    monkeypatch.setattr(eng.subprocess, "run", missing)
    assert any("postgresql-client" in f for f in eng.run_backup(settings, target, source, now=NOW).failures)


def test_only_postgres_is_a_backup_engine(data_dir):
    assert eng.BackupSettings(data_dir=data_dir).engine == "postgres"
    with pytest.raises(ValueError, match="unknown DB engine 'oracle'"):
        eng.BackupSettings(data_dir=data_dir, engine="oracle")
    with pytest.raises(ValueError, match="sqlite_to_postgres"):
        eng.BackupSettings(data_dir=data_dir, engine="sqlite")
    with pytest.raises(ValueError, match="sqlite_to_postgres"):
        eng.BackupSettings.from_env({"DB_ENGINE": "sqlite"})


# --- restore --------------------------------------------------------------------------------------


def test_restore_round_trip(settings, target, source, data_dir, tmp_path):
    eng.run_backup(settings, target, source, now=NOW)
    into = tmp_path / "restore"
    eng.run_restore(target, into)
    assert (into / "marvin.dump").read_bytes().startswith(b"PGDMP")  # fetched and verified, never loaded
    assert (into / ".secret").read_text() == "s3cr3t-installation-key"
    assert oct((into / ".secret").stat().st_mode & 0o777) == "0o600"
    assert (into / "assets" / "ws1" / "a.png").read_bytes() == (data_dir / "assets" / "ws1" / "a.png").read_bytes()
    assert not (into / ".temp").exists() and not (into / "marvin.db.pre-migration").exists()
    assert eng.restore_assets(target, into) == (0, 2)  # a second pass finds everything in place


def test_restore_refuses_an_occupied_directory_without_force(settings, target, source, data_dir):
    eng.run_backup(settings, target, source, now=NOW)
    (data_dir / "marvin.dump").write_bytes(b"older")
    with pytest.raises(keys.BackupError, match="already has marvin.dump, .secret"):
        eng.run_restore(target, data_dir)


def test_forced_restore_moves_the_existing_dump_aside(settings, target, source, data_dir):
    eng.run_backup(settings, target, source, now=NOW)
    (data_dir / "marvin.dump").write_bytes(b"older")
    eng.run_restore(target, data_dir, force=True)
    assert (data_dir / "marvin.dump").read_bytes().startswith(b"PGDMP")
    assert any(p.name.startswith("marvin.dump.pre-restore-") and p.read_bytes() == b"older" for p in data_dir.iterdir())


def test_restore_rejects_a_tampered_object_and_leaves_the_directory_alone(settings, target, source, tmp_path):
    eng.run_backup(settings, target, source, now=NOW)
    (target.root / keys.pg_key(NOW)).write_bytes(b"not the dump")
    into = tmp_path / "restore"
    with pytest.raises(keys.BackupError, match="sha256 mismatch"):
        eng.run_restore(target, into, skip_config=True, assets=False)
    assert not (into / "marvin.dump").exists()


def test_restore_picks_the_newest_postgres_dump_and_ignores_the_legacy_family(settings, target, source, tmp_path):
    src = tmp_path / "legacy"
    src.write_bytes(b"x")
    target.put_file(keys.db_key(NOW + timedelta(days=1)), src)  # a legacy key newer than any dump
    eng.run_backup(settings, target, source, now=NOW - timedelta(days=1))
    eng.run_backup(settings, target, source, now=NOW)
    assert eng.latest_key(target, keys.PG_PREFIX) == keys.pg_key(NOW)
    into = tmp_path / "pg"
    eng.run_restore(target, into, assets=False)
    assert (into / "marvin.dump").read_bytes().startswith(b"PGDMP")


@pytest.mark.parametrize("kwargs", [{"engine": "sqlite"}, {"db": "sqlite/marvin-20261006T071500Z.db.gz"}])
def test_restoring_a_sqlite_backup_is_refused_with_the_way_forward(target, tmp_path, kwargs):
    into = tmp_path / "restore"
    with pytest.raises(ValueError, match="marvin.scripts.sqlite_to_postgres") as exc:
        eng.run_restore(target, into, **kwargs)
    assert "docs/manual/postgres.md" in str(exc.value)
    assert not into.exists()  # refused before touching anything


def test_list_backups_shows_named_database_and_config_keys_including_the_legacy_family(settings, target, source, tmp_path):
    src = tmp_path / "legacy"
    src.write_bytes(b"x")
    legacy = keys.db_key(NOW - timedelta(days=400))
    target.put_file(legacy, src)
    target.put_file("postgres/manual-copy.dump", src)  # not a key the engine named
    eng.run_backup(settings, target, source, now=NOW)
    assert [o.key for o in eng.list_backups(target)] == [legacy, keys.pg_key(NOW), keys.config_key(NOW)]


# --- the command line -----------------------------------------------------------------------------


def _cli(args, env, cwd):
    return subprocess.run([sys.executable, "-m", "marvin.scripts.backup", *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=120)


FAKE_PG_DUMP = """#!/bin/sh
for a in "$@"; do case "$a" in --file=*) printf 'PGDMP-fake-dump' > "${a#--file=}" ;; esac; done
"""
FAKE_PG_RESTORE = """#!/bin/sh
echo '1; 0 0 TABLE DATA public users marvin'
"""


@pytest.fixture
def cli_env(tmp_path, data_dir):
    base = tmp_path / "base"  # BASE_DIR: Marvin would create dev/ or tests/.temp here if it built its settings
    base.mkdir()
    bin_dir = tmp_path / "bin"  # pg_dump / pg_restore stand-ins, so the CLI runs where no postgresql-client is installed
    bin_dir.mkdir()
    for name, body in (("pg_dump", FAKE_PG_DUMP), ("pg_restore", FAKE_PG_RESTORE)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BACKUP_", "STORAGE_", "POSTGRES_", "DB_ENGINE", "TESTING", "DATA_DIR", "PG"))}
    env.update(
        {
            "PYTHONPATH": str(REPO_SRC),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "BASE_DIR": str(base),
            "BACKUP_DATA_DIR": str(data_dir),
            # Nothing listens on port 1: recording the run fails fast ("NOT recorded") and the exit code is unaffected.
            "POSTGRES_SERVER": "127.0.0.1",
            "POSTGRES_PORT": "1",
            "POSTGRES_USER": "marvin",
            "POSTGRES_DB": "marvin",
        }
    )
    return env


def test_cli_refuses_a_target_on_the_data_volume(cli_env, tmp_path):
    nas = tmp_path / "nas"
    nas.mkdir()
    result = _cli(["run", "--target", "local"], {**cli_env, "BACKUP_LOCAL_ROOT": str(nas)}, tmp_path)
    assert result.returncode == 2 and "same filesystem" in result.stdout


def test_cli_needs_a_known_target(cli_env, tmp_path):
    assert _cli(["run"], cli_env, tmp_path).returncode == 2
    result = _cli(["list", "--target", "r2"], cli_env, tmp_path)
    assert result.returncode == 2 and "unknown backup target 'r2'" in result.stdout


@pytest.mark.skipif(not Path("/dev/shm").is_dir(), reason="needs a second filesystem (/dev/shm)")
def test_cli_backs_up_and_restores_without_building_marvins_settings(cli_env, tmp_path):
    import shutil
    import tempfile

    nas = Path(tempfile.mkdtemp(dir="/dev/shm", prefix="marvin-nas-"))
    try:
        env = {**cli_env, "BACKUP_LOCAL_ROOT": str(nas), "BACKUP_KEEP_DAILY": "3"}
        run = _cli(["run", "--target", "local", "--name", "nas"], env, tmp_path)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "backup[nas] ok" in run.stdout
        listed = _cli(["list", "--target", "local"], env, tmp_path)
        assert listed.returncode == 0 and "postgres/marvin-" in listed.stdout and "config/marvin-config-" in listed.stdout
        into = tmp_path / "restored"
        restored = _cli(["restore", "--target", "local", "--into", str(into)], env, tmp_path)
        assert restored.returncode == 0, restored.stdout + restored.stderr
        assert (into / "marvin.dump").read_bytes() == b"PGDMP-fake-dump" and (into / "assets" / "b.txt").read_text() == "hello"
        assert list((tmp_path / "base").iterdir()) == []  # no dev/data, no tests/.temp: settings never built
    finally:
        shutil.rmtree(nas, ignore_errors=True)


def test_cli_refuses_the_retired_sqlite_engine_naming_the_way_forward(cli_env, tmp_path):
    for command in (["list", "--target", "local"], ["run", "--target", "local"]):
        result = _cli(command, {**cli_env, "BACKUP_DB_ENGINE": "sqlite", "BACKUP_LOCAL_ROOT": str(tmp_path)}, tmp_path)
        assert result.returncode == 2 and "sqlite_to_postgres" in result.stdout + result.stderr
