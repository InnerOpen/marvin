"""Off-site backup script (marvin.scripts.offsite_backup): key naming, retention, the incremental asset
decision, and backup/restore round trips against an in-memory S3 double (no network, no moto)."""

import gzip
import hashlib
import io
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from marvin.scripts import offsite_backup as ob


class FakeS3:
    """The subset of the boto3 S3 client the script calls, kept in memory."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.puts: list[str] = []

    def put_object(self, Bucket, Key, Body, Metadata, ContentType=None):  # noqa: N803 - boto3 signature
        self.objects[Key] = (Body.read(), dict(Metadata))
        self.puts.append(Key)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803
        contents = [
            {"Key": k, "Size": len(d), "ETag": f'"{hashlib.md5(d).hexdigest()}"'}
            for k, (d, _) in sorted(self.objects.items())
            if k.startswith(Prefix)
        ]
        yield {"Contents": contents} if contents else {}

    def get_object(self, Bucket, Key):  # noqa: N803
        data, meta = self.objects[Key]
        return {"Body": io.BytesIO(data), "Metadata": meta}

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)
        return {}


def _make_db(path: Path, rows: int = 50) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    conn.executemany("INSERT INTO users (email) VALUES (?)", [(f"u{i}@example.com",) for i in range(rows)])
    conn.commit()
    conn.close()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "assets" / "ws1").mkdir(parents=True)
    _make_db(d / "marvin.db")
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
def s3() -> FakeS3:
    return FakeS3()


@pytest.fixture
def bucket(s3: FakeS3) -> ob.Bucket:
    return ob.Bucket(s3, "marvin-backups")


@pytest.fixture
def settings(data_dir: Path) -> ob.Settings:
    return ob.Settings(endpoint="http://minio", bucket="marvin-backups", region="auto", data_dir=data_dir, engine="sqlite")


NOW = datetime(2026, 10, 6, 7, 15, 0, tzinfo=UTC)


# --- key naming ----------------------------------------------------------------------------------


def test_key_names_are_utc_stamped_and_parse_back():
    est = NOW.astimezone(datetime.now().astimezone().tzinfo)
    assert ob.db_key(est) == "sqlite/marvin-20261006T071500Z.db.gz"
    assert ob.config_key(NOW) == "config/marvin-config-20261006T071500Z.tar.gz"
    assert ob.asset_key("ws1/a.png") == "assets/ws1/a.png"
    assert ob.key_timestamp(ob.db_key(NOW)) == NOW
    assert ob.key_timestamp(ob.config_key(NOW)) == NOW


@pytest.mark.parametrize(
    "key",
    ["sqlite/marvin.db.gz", "sqlite/manual-copy.db.gz", "assets/ws1/a.png", "sqlite/marvin-20261006.db.gz", "config/marvin-20261006T071500Z.db.gz"],
)
def test_foreign_keys_have_no_timestamp(key):
    assert ob.key_timestamp(key) is None


# --- retention -----------------------------------------------------------------------------------


def _nightly(days: int, start: datetime = NOW) -> list[str]:
    return [ob.db_key(start - timedelta(days=i)) for i in range(days)]


def test_retention_keeps_14_daily_plus_8_weekly():
    keys = _nightly(120)
    kept = ob.select_retained(keys)
    daily = set(keys[:14])
    assert daily <= kept
    weekly = kept - daily
    # The 8 newest ISO weeks are covered; the ones not already inside the 14 days add one key each.
    weeks = {ob.key_timestamp(k).isocalendar()[:2] for k in kept}
    assert len(weeks) == 8
    assert all(ob.key_timestamp(k) < ob.key_timestamp(keys[13]) for k in weekly)
    assert len(kept) == 14 + len(weekly) and 5 <= len(weekly) <= 7
    assert set(ob.select_expired(keys)) == set(keys) - kept
    # The newest backup of each kept week is the one kept (a Sunday, the last day of an ISO week).
    assert all(ob.key_timestamp(k).isoweekday() == 7 for k in weekly)


def test_retention_counts_days_with_backups_not_calendar_days():
    keys = _nightly(3, NOW) + _nightly(3, NOW - timedelta(days=200))
    assert ob.select_expired(keys) == []


def test_retention_keeps_only_the_newest_backup_of_a_day():
    morning, evening = NOW.replace(hour=3), NOW.replace(hour=20)
    keys = [ob.db_key(morning), ob.db_key(evening)]
    assert ob.select_expired(keys) == [ob.db_key(morning)]


def test_retention_never_expires_keys_it_did_not_name():
    keys = _nightly(60) + ["sqlite/before-cutover.db.gz", "sqlite/marvin.db.gz"]
    expired = ob.select_expired(keys)
    assert expired
    assert "sqlite/before-cutover.db.gz" not in expired and "sqlite/marvin.db.gz" not in expired


# --- incremental asset decision -----------------------------------------------------------------


def test_asset_upload_decision(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"content")
    md5 = hashlib.md5(b"content").hexdigest()
    assert ob.asset_needs_upload(f, None) is True
    assert ob.asset_needs_upload(f, ob.RemoteObject("k", 999, f'"{md5}"')) is True
    assert ob.asset_needs_upload(f, ob.RemoteObject("k", 7, f'"{md5}"')) is False
    assert ob.asset_needs_upload(f, ob.RemoteObject("k", 7, '"' + "0" * 32 + '"')) is True
    # A multipart ETag is not an MD5: same size counts as unchanged.
    assert ob.asset_needs_upload(f, ob.RemoteObject("k", 7, '"abc123-2"')) is False


# --- backup ------------------------------------------------------------------------------------


def test_backup_uploads_db_config_and_assets(settings, bucket, s3):
    report = ob.run_backup(settings, bucket, now=NOW)
    assert report.failures == []
    assert set(s3.objects) == {
        "sqlite/marvin-20261006T071500Z.db.gz",
        "config/marvin-config-20261006T071500Z.tar.gz",
        "assets/ws1/a.png",
        "assets/b.txt",
    }
    data, meta = s3.objects["sqlite/marvin-20261006T071500Z.db.gz"]
    assert meta["sha256"] == hashlib.sha256(data).hexdigest()
    assert meta["db-sha256"] == hashlib.sha256(gzip.decompress(data)).hexdigest()
    assert report.assets_uploaded == 2 and report.assets_unchanged == 0
    assert "offsite-backup ok" in report.summary(1.0, False)


def test_second_backup_uploads_only_changed_assets(settings, bucket, s3, data_dir):
    ob.run_backup(settings, bucket, now=NOW)
    s3.puts.clear()
    report = ob.run_backup(settings, bucket, now=NOW + timedelta(days=1))
    assert report.assets_uploaded == 0 and report.assets_unchanged == 2
    assert not [k for k in s3.puts if k.startswith("assets/")]

    (data_dir / "assets" / "b.txt").write_text("HELLO")  # same size, new content
    (data_dir / "assets" / "new.txt").write_text("n")
    report = ob.run_backup(settings, bucket, now=NOW + timedelta(days=2))
    assert report.assets_uploaded == 2 and report.assets_unchanged == 1


def test_backup_never_deletes_remote_assets(settings, bucket, s3, data_dir):
    ob.run_backup(settings, bucket, now=NOW)
    (data_dir / "assets" / "b.txt").unlink()
    ob.run_backup(settings, bucket, now=NOW + timedelta(days=1))
    assert "assets/b.txt" in s3.objects


def test_dry_run_uploads_and_deletes_nothing(settings, bucket, s3):
    old = ob.db_key(NOW - timedelta(days=400))
    s3.objects[old] = (b"x", {})
    for k in _nightly(30, NOW - timedelta(days=1)):
        s3.objects[k] = (b"x", {})
    before = dict(s3.objects)
    report = ob.run_backup(settings, bucket, dry_run=True, now=NOW)
    assert s3.objects == before and report.failures == []
    assert report.pruned > 0 and report.assets_uploaded == 2
    assert "DRY RUN" in report.summary(1.0, True)


def test_backup_prunes_old_snapshots(settings, bucket, s3):
    for k in _nightly(60, NOW - timedelta(days=1)):
        s3.objects[k] = (b"x", {})
    report = ob.run_backup(settings, bucket, now=NOW)
    remaining = [k for k in s3.objects if k.startswith("sqlite/")]
    assert ob.db_key(NOW) in remaining
    assert len(remaining) == len(ob.select_retained(remaining)) < 61
    assert report.pruned == 61 - len(remaining)


def test_integrity_failure_aborts_db_upload_but_not_the_rest(settings, bucket, s3, monkeypatch):
    stale = _nightly(60, NOW - timedelta(days=1))
    for k in stale:
        s3.objects[k] = (b"x", {})

    def broken(path):
        raise ob.BackupError(f"integrity_check failed on {path.name}: ['row 3 missing from index']")

    monkeypatch.setattr(ob, "check_integrity", broken)
    report = ob.run_backup(settings, bucket, now=NOW)
    assert ob.db_key(NOW) not in s3.objects
    # A failed database backup prunes nothing from sqlite/ ...
    assert all(k in s3.objects for k in stale)
    # ... while the config archive and assets still go up, and the run reports failure.
    assert ob.config_key(NOW) in s3.objects and "assets/b.txt" in s3.objects
    assert any(f.startswith("database: integrity_check failed") for f in report.failures)
    assert "FAILED" in report.summary(1.0, False)


def test_check_integrity_rejects_a_corrupt_file(tmp_path: Path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    with pytest.raises(ob.BackupError):
        ob.check_integrity(bad)


def test_postgres_without_a_connection_is_a_reported_failure_not_a_silent_skip(settings, bucket, s3):
    settings.engine = "postgres"
    report = ob.run_backup(settings, bucket, now=NOW)
    assert not [k for k in s3.objects if k.startswith(("sqlite/", "postgres/"))]
    assert any("POSTGRES_SERVER" in f for f in report.failures)
    assert ob.config_key(NOW) in s3.objects  # assets and config are still protected


PG_ENV = {"PGHOST": "marvin-dev-pg-rw", "PGPORT": "5432", "PGUSER": "marvin", "PGPASSWORD": "pg-pass-do-not-print", "PGDATABASE": "marvin"}


class FakePg:
    """Stands in for subprocess.run of pg_dump / pg_restore --list."""

    def __init__(self, returncode: int = 0, tables: int = 3) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.returncode = returncode
        self.tables = tables

    def __call__(self, args, env, capture_output, text, timeout, check):
        self.calls.append((list(args), dict(env)))
        if args[0] == "pg_dump":
            if self.returncode == 0:
                Path(next(a.split("=", 1)[1] for a in args if a.startswith("--file="))).write_bytes(b"PGDMP" + b"x" * 64)
            return subprocess.CompletedProcess(args, self.returncode, "", "pg_dump: error: connection refused")
        listing = "\n".join(f"{i}; 0 0 TABLE DATA public t{i} marvin" for i in range(self.tables))
        return subprocess.CompletedProcess(args, 0, listing, "")


def test_postgres_dump_is_uploaded_verified_and_pruned(settings, bucket, s3, monkeypatch):
    settings.engine, settings.pg_env = "postgres", PG_ENV
    fake = FakePg()
    monkeypatch.setattr(ob.subprocess, "run", fake)
    for i in range(1, 120):  # four months of nightly dumps: the oldest fall outside 14 daily + 8 weekly
        s3.objects[ob.pg_key(NOW - timedelta(days=i))] = (b"old", {})
    old = ob.pg_key(NOW - timedelta(days=119))
    keep_sqlite = ob.db_key(NOW - timedelta(days=400))  # the other engine's family is not this run's to prune
    s3.objects[keep_sqlite] = (b"old", {})

    report = ob.run_backup(settings, bucket, now=NOW)

    assert report.failures == []
    key = ob.pg_key(NOW)
    assert key == "postgres/marvin-20261006T071500Z.dump"
    data, meta = s3.objects[key]
    assert meta[ob.META_SHA256] == hashlib.sha256(data).hexdigest()
    assert old not in s3.objects and keep_sqlite in s3.objects
    assert [c[0][0] for c in fake.calls] == ["pg_dump", "pg_restore"]
    for args, env in fake.calls:
        assert env["PGPASSWORD"] == PG_ENV["PGPASSWORD"]  # the password travels in the environment...
        assert not any(PG_ENV["PGPASSWORD"] in a for a in args)  # ...never on the command line
    assert "--format=custom" in fake.calls[0][0]
    assert PG_ENV["PGPASSWORD"] not in report.summary(1.0, False)


def test_postgres_dump_failure_uploads_nothing(settings, bucket, s3, monkeypatch):
    settings.engine, settings.pg_env = "postgres", PG_ENV
    monkeypatch.setattr(ob.subprocess, "run", FakePg(returncode=1))
    report = ob.run_backup(settings, bucket, now=NOW)
    assert not [k for k in s3.objects if k.startswith("postgres/")]
    assert any("connection refused" in f for f in report.failures)


def test_postgres_empty_dump_is_refused(settings, bucket, s3, monkeypatch):
    settings.engine, settings.pg_env = "postgres", PG_ENV
    monkeypatch.setattr(ob.subprocess, "run", FakePg(tables=0))
    report = ob.run_backup(settings, bucket, now=NOW)
    assert not [k for k in s3.objects if k.startswith("postgres/")]
    assert any("no table data" in f for f in report.failures)


def test_missing_pg_dump_binary_says_what_to_install(settings, bucket, monkeypatch):
    settings.engine, settings.pg_env = "postgres", PG_ENV

    def missing(*a, **kw):
        raise FileNotFoundError("pg_dump")

    monkeypatch.setattr(ob.subprocess, "run", missing)
    report = ob.run_backup(settings, bucket, now=NOW)
    assert any("postgresql-client" in f for f in report.failures)


def test_restore_fetches_a_postgres_dump_without_loading_it(settings, bucket, s3, monkeypatch, tmp_path):
    settings.engine, settings.pg_env = "postgres", PG_ENV
    monkeypatch.setattr(ob.subprocess, "run", FakePg())
    ob.run_backup(settings, bucket, now=NOW)
    target = tmp_path / "restore"
    ob.run_restore(bucket, target, engine="postgres")
    assert (target / "marvin.dump").read_bytes() == s3.objects[ob.pg_key(NOW)][0]
    assert not (target / "marvin.db").exists()
    assert (target / ".secret").read_text() == "s3cr3t-installation-key"


def test_prefix_keeps_an_environment_to_itself(settings, s3):
    s3.objects["sqlite/marvin-20200101T000000Z.db.gz"] = (b"prod", {})  # another environment's backup
    s3.objects["config/marvin-config-20200101T000000Z.tar.gz"] = (b"prod", {})
    dev = ob.Bucket(s3, "marvin-backups", "dev/")
    report = ob.run_backup(settings, dev, now=NOW)
    assert report.failures == []
    ours = sorted(k for k in s3.objects if k.startswith("dev/"))
    assert f"dev/{ob.db_key(NOW)}" in ours and f"dev/{ob.config_key(NOW)}" in ours
    assert all(k.startswith(("dev/", "sqlite/marvin-2020", "config/marvin-config-2020")) for k in s3.objects)
    assert "sqlite/marvin-20200101T000000Z.db.gz" in s3.objects  # never pruned from under the prefix
    assert ob.db_key(NOW) in dev.list("sqlite/")  # keys come back relative to the prefix


@pytest.mark.parametrize(("raw", "expected"), [("", ""), (None, ""), ("dev", "dev/"), ("/dev/", "dev/"), ("a/b", "a/b/")])
def test_normalize_prefix(raw, expected):
    assert ob.normalize_prefix(raw) == expected


def test_settings_from_env_maps_postgres_connection_and_prefix():
    env = {
        "BACKUP_S3_ENDPOINT": "e",
        "BACKUP_S3_BUCKET": "b",
        "AWS_ACCESS_KEY_ID": "k",
        "AWS_SECRET_ACCESS_KEY": "s",
        "BACKUP_S3_PREFIX": "dev",
        "DB_ENGINE": "postgres",
        "POSTGRES_SERVER": "h",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "pw-do-not-print",
        "POSTGRES_DB": "d",
    }
    s = ob.Settings.from_env(env)
    assert s.prefix == "dev/" and s.engine == "postgres"
    assert s.pg_env == {"PGHOST": "h", "PGPORT": "5432", "PGUSER": "u", "PGPASSWORD": "pw-do-not-print", "PGDATABASE": "d"}
    assert "pw-do-not-print" not in repr(s)


def test_key_families_do_not_cross():
    assert ob.key_timestamp(ob.pg_key(NOW)) == NOW
    assert ob.key_timestamp("postgres/marvin-20261006T071500Z.db.gz") is None
    assert ob.key_timestamp("sqlite/marvin-20261006T071500Z.dump") is None
    assert ob.db_prefix("postgres") == "postgres/" and ob.db_prefix("sqlite") == "sqlite/"


def test_settings_from_env_names_missing_variables_without_values():
    with pytest.raises(ob.BackupError) as err:
        ob.Settings.from_env({"BACKUP_S3_BUCKET": "b", "AWS_SECRET_ACCESS_KEY": "do-not-print"})
    msg = str(err.value)
    assert "BACKUP_S3_ENDPOINT" in msg and "AWS_ACCESS_KEY_ID" in msg and "do-not-print" not in msg
    s = ob.Settings.from_env({"BACKUP_S3_ENDPOINT": "e", "BACKUP_S3_BUCKET": "b", "AWS_ACCESS_KEY_ID": "i", "AWS_SECRET_ACCESS_KEY": "k"})
    assert (s.region, s.data_dir, s.engine) == ("auto", Path("/app/data"), "sqlite")


# --- restore -----------------------------------------------------------------------------------


def test_restore_round_trip(settings, bucket, data_dir, tmp_path):
    ob.run_backup(settings, bucket, now=NOW)
    target = tmp_path / "restored"
    ob.run_restore(bucket, target)
    conn = sqlite3.connect(target / "marvin.db")
    assert conn.execute("SELECT count(*) FROM users").fetchone() == (50,)
    conn.close()
    assert (target / ".secret").read_bytes() == (data_dir / ".secret").read_bytes()
    assert (target / ".secret").stat().st_mode & 0o077 == 0
    assert (target / "scheduler_state.json").read_text() == '{"last": 1}'
    assert (target / "assets" / "ws1" / "a.png").read_bytes() == (data_dir / "assets" / "ws1" / "a.png").read_bytes()
    assert not (target / ".temp").exists() and not (target / "marvin.db.pre-migration").exists()


def test_restore_refuses_an_occupied_target_without_force(settings, bucket, data_dir):
    ob.run_backup(settings, bucket, now=NOW)
    with pytest.raises(ob.BackupError, match="--force"):
        ob.run_restore(bucket, data_dir)
    # Assets alone may be restored into a live directory (nothing is replaced).
    ob.run_restore(bucket, data_dir, skip_db=True, skip_config=True)


def test_forced_restore_moves_existing_db_and_wal_aside(settings, bucket, data_dir):
    ob.run_backup(settings, bucket, now=NOW)
    (data_dir / "marvin.db-wal").write_bytes(b"stale wal")
    ob.run_restore(bucket, data_dir, force=True)
    names = sorted(p.name for p in data_dir.iterdir())
    assert not (data_dir / "marvin.db-wal").exists()
    assert any(n.startswith("marvin.db-wal.pre-restore-") for n in names)
    assert any(n.startswith("marvin.db.pre-restore-") for n in names)
    assert any(n.startswith(".secret.pre-restore-") for n in names)
    ob.check_integrity(data_dir / "marvin.db")


def test_restore_rejects_a_tampered_object_and_leaves_target_alone(settings, bucket, s3, tmp_path):
    ob.run_backup(settings, bucket, now=NOW)
    key = ob.db_key(NOW)
    data, meta = s3.objects[key]
    s3.objects[key] = (gzip.compress(b"not the database"), meta)
    target = tmp_path / "restored"
    with pytest.raises(ob.BackupError, match="sha256 mismatch"):
        ob.run_restore(bucket, target)
    assert not (target / "marvin.db").exists()


def test_restore_picks_the_newest_backup(settings, bucket, s3, data_dir, tmp_path):
    ob.run_backup(settings, bucket, now=NOW - timedelta(days=1))
    conn = sqlite3.connect(data_dir / "marvin.db")
    conn.execute("INSERT INTO users (email) VALUES ('late@example.com')")
    conn.commit()
    conn.close()
    ob.run_backup(settings, bucket, now=NOW)
    ob.run_restore(bucket, tmp_path / "r", assets=False)
    conn = sqlite3.connect(tmp_path / "r" / "marvin.db")
    assert conn.execute("SELECT count(*) FROM users").fetchone() == (51,)
    conn.close()


# --- hourly retention for postgres/ ---------------------------------------------------------------


def test_postgres_retention_keeps_48_hourly_14_daily_8_weekly():
    hours = [NOW - timedelta(hours=h) for h in range(24 * 70)]  # ten weeks of hourly dumps
    keys = [ob.pg_key(ts) for ts in hours]
    keep = ob.select_retained(keys, keep_hourly=ob.KEEP_HOURLY)

    assert {ob.pg_key(ts) for ts in hours[:48]} <= keep  # every one of the last 48 hours
    assert ob.pg_key(hours[48]) not in keep  # the 49th hour is only an hour (not a day's newest)
    newest_per_day = {}
    for ts in hours:  # newest first
        newest_per_day.setdefault(ts.date(), ob.pg_key(ts))
    assert set(list(newest_per_day.values())[:14]) <= keep
    assert list(newest_per_day.values())[14] not in keep or ob.key_timestamp(list(newest_per_day.values())[14]).weekday() == 6
    assert ob.pg_key(hours[-1]) not in keep  # ten weeks back: outside 8 weekly
    assert 48 < len(keep) <= 48 + 14 + 8


def test_prune_applies_the_hourly_rule_to_postgres_only(s3, bucket):
    for h in range(30):  # 30 hourly backups across two UTC days
        ts = NOW - timedelta(hours=h)
        s3.objects[ob.pg_key(ts)] = (b"x", {})
        s3.objects[ob.db_key(ts)] = (b"x", {})
    report = ob.Report()
    ob.prune(bucket, ob.PG_PREFIX, report, dry_run=False)
    ob.prune(bucket, ob.DB_PREFIX, report, dry_run=False)
    assert len([k for k in s3.objects if k.startswith("postgres/")]) == 30  # all within 48 hours
    assert len([k for k in s3.objects if k.startswith("sqlite/")]) == 2  # newest per day
    assert report.pruned == 28


# --- configurable retention (BACKUP_KEEP_*) -------------------------------------------------------


def test_retention_defaults_are_todays_counts():
    s = ob.Settings.from_env({"BACKUP_S3_ENDPOINT": "e", "BACKUP_S3_BUCKET": "b", "AWS_ACCESS_KEY_ID": "i", "AWS_SECRET_ACCESS_KEY": "k"})
    assert s.retention == ob.Retention(hourly=48, daily=14, weekly=8)
    assert ob.Retention.from_env({"BACKUP_KEEP_DAILY": ""}) == ob.Retention()  # empty = unset


def test_retention_from_env_overrides_each_count():
    env = {"BACKUP_KEEP_HOURLY": "24", "BACKUP_KEEP_DAILY": "7", "BACKUP_KEEP_WEEKLY": "0"}
    assert ob.Retention.from_env(env) == ob.Retention(hourly=24, daily=7, weekly=0)
    assert ob.Retention.from_env({"BACKUP_KEEP_DAILY": "30"}) == ob.Retention(hourly=48, daily=30, weekly=8)


@pytest.mark.parametrize("raw", ["-1", "seven", "1.5"])
def test_retention_from_env_rejects_bad_counts(raw):
    with pytest.raises(ob.BackupError, match="BACKUP_KEEP_WEEKLY"):
        ob.Retention.from_env({"BACKUP_KEEP_WEEKLY": raw})


def test_retention_never_drops_the_daily_rule():
    # daily=0 (with hourly/weekly off) would prune the backup the run just uploaded.
    with pytest.raises(ob.BackupError, match="daily >= 1"):
        ob.Retention.from_env({"BACKUP_KEEP_DAILY": "0"})


def test_custom_retention_keeps_24_hourly_7_daily_no_weekly(s3, bucket):
    hours = [NOW - timedelta(hours=h) for h in range(24 * 21)]  # three weeks of hourly dumps
    for ts in hours:
        s3.objects[ob.pg_key(ts)] = (b"x", {})
        s3.objects[ob.config_key(ts)] = (b"x", {})
    retention = ob.Retention(hourly=24, daily=7, weekly=0)
    report = ob.Report()
    ob.prune(bucket, ob.PG_PREFIX, report, dry_run=False, retention=retention)
    ob.prune(bucket, ob.CONFIG_PREFIX, report, dry_run=False, retention=retention)

    newest_per_day = {}
    for ts in hours:  # newest first
        newest_per_day.setdefault(ts.date(), ts)
    last_7_days = list(newest_per_day.values())[:7]

    pg = {k for k in s3.objects if k.startswith("postgres/")}
    assert pg == {ob.pg_key(ts) for ts in hours[:24]} | {ob.pg_key(ts) for ts in last_7_days}
    # config/ has no hourly rule: just the newest of each of the last 7 days, nothing weekly.
    assert {k for k in s3.objects if k.startswith("config/")} == {ob.config_key(ts) for ts in last_7_days}


def test_run_backup_prunes_with_the_settings_retention(settings, bucket, s3):
    for d in range(1, 10):  # nine older daily snapshots
        s3.objects[ob.db_key(NOW - timedelta(days=d))] = (b"x", {})
    settings.retention = ob.Retention(daily=3, weekly=0)
    ob.run_backup(settings, bucket, now=NOW)
    assert sorted(k for k in s3.objects if k.startswith("sqlite/")) == sorted(ob.db_key(NOW - timedelta(days=d)) for d in range(3))
