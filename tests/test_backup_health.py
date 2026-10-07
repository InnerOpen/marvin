"""Backup health: every run of a backup target records itself in `backup_runs` (ok, partial, failed — a
target that can't even be opened included), the backend announces runs as backup_completed / backup_failed,
notices a target that went quiet (overdue: once per incident, cleared by the next successful run), and
shows it all on Admin → Backup health and the super admin's activity bell. Plus the small cron reader the
schedule needs, the plain-language error mapping, and the masked settings on Admin → Storage."""

import io
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from marvin_integration_sdk.storage import Setting, StorageConfigError, StoragePlugin
from marvin_integration_sdk.storage.memory import MemoryBackupTarget, MemoryStorageProvider
from sqlalchemy.orm import Session

from marvin.db.models.platform.backup_runs import BackupRunModel
from marvin.db.models.users.roles import PlatformRole
from marvin.scripts import backup as backup_cli
from marvin.services import backup_health
from marvin.services.backup_engine import recorder
from marvin.services.backup_health import cron
from marvin.services.storage import healthcheck as hc
from tests.test_storage_providers import _EP, entry_points  # noqa: F401  (fixture)

NOW = datetime(2026, 10, 7, 16, 5, tzinfo=UTC)


# --------------------------------------------------------------------------------------------------
# Cron
# --------------------------------------------------------------------------------------------------


def test_cron_hourly_next_run_and_interval():
    s = cron.parse("0 * * * *", "America/New_York")
    assert s.next_after(datetime(2026, 10, 7, 15, 0, tzinfo=UTC)) == datetime(2026, 10, 7, 16, 0, tzinfo=UTC)
    assert s.next_after(datetime(2026, 10, 7, 15, 59, 30, tzinfo=UTC)) == datetime(2026, 10, 7, 16, 0, tzinfo=UTC)
    assert s.interval(NOW) == timedelta(hours=1)


def test_cron_daily_in_a_time_zone_and_across_dst():
    s = cron.parse("30 2 * * *", "America/New_York")
    # 02:30 EDT is 06:30 UTC
    assert s.next_after(datetime(2026, 10, 7, 12, 0, tzinfo=UTC)) == datetime(2026, 10, 8, 6, 30, tzinfo=UTC)
    assert s.interval(NOW) == timedelta(hours=24)
    # Clocks go back on 1 Nov 2026: that day is 25 hours long, and the longest gap is what counts.
    assert s.interval(datetime(2026, 10, 30, 12, tzinfo=UTC)) == timedelta(hours=25)


def test_cron_fields_lists_ranges_steps_and_day_rules():
    s = cron.parse("*/15 9-17 * * 1-5")
    assert s.minutes == {0, 15, 30, 45} and s.hours == set(range(9, 18)) and s.weekdays == {1, 2, 3, 4, 5}
    # Saturday 2026-10-10 → the next weekday morning, Monday 09:00 UTC
    assert s.next_after(datetime(2026, 10, 10, 12, tzinfo=UTC)) == datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    # Both day fields restricted: either matches (the 1st, or any Sunday)
    either = cron.parse("0 0 1 * 0")
    assert either.next_after(datetime(2026, 10, 2, tzinfo=UTC)) == datetime(2026, 10, 4, tzinfo=UTC)  # a Sunday
    assert cron.parse("@daily").next_after(NOW) == datetime(2026, 10, 8, tzinfo=UTC)
    assert cron.parse("0 0 * * 7").weekdays == {0}


@pytest.mark.parametrize("bad", ["", "* * *", "61 * * * *", "0 0 * JAN *", "*/0 * * * *", "5-1 * * * *"])
def test_cron_refuses_what_it_cannot_read(bad):
    with pytest.raises(ValueError):
        cron.parse(bad)


def test_cron_refuses_an_unknown_zone():
    with pytest.raises(ValueError):
        cron.parse("0 * * * *", "Mars/Olympus")


def test_overdue_window():
    assert backup_health.overdue_window(timedelta(hours=1)) == timedelta(hours=2) + backup_health.GRACE
    assert backup_health.overdue_window(timedelta(hours=24)) == timedelta(hours=26) + backup_health.GRACE


# --------------------------------------------------------------------------------------------------
# Plain-language errors and scrubbing
# --------------------------------------------------------------------------------------------------


def _client_error(code: str, status: int = 400, op: str = "PutObject"):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": f"{code} message"}, "ResponseMetadata": {"HTTPStatusCode": status}}, op)


@pytest.mark.parametrize(
    ("exc", "message", "code"),
    [
        (lambda: _client_error("InvalidAccessKeyId", 403), hc.KEY_INVALID, "InvalidAccessKeyId"),
        (lambda: _client_error("Unauthorized", 401), hc.KEY_INVALID, "Unauthorized"),
        (lambda: _client_error("SignatureDoesNotMatch", 403), hc.KEY_INVALID, "SignatureDoesNotMatch"),
        (lambda: _client_error("AccessDenied", 403), hc.KEY_NO_ACCESS, "AccessDenied"),
        (lambda: _client_error("NoSuchBucket", 404), hc.NO_BUCKET, "NoSuchBucket"),
        (lambda: _client_error("", 403, "HeadObject"), hc.REFUSED, "HTTP 403"),
        (lambda: _client_error("403", 403, "HeadObject"), hc.REFUSED, "HTTP 403"),
        (lambda: _client_error("", 401, "HeadObject"), hc.KEY_INVALID, "HTTP 401"),
    ],
)
def test_explain_maps_s3_error_codes(exc, message, code):
    why = hc.explain(exc())
    assert (why.message, why.code) == (message, code)
    assert str(why) == f"{message} ({code})"


def test_explain_maps_network_and_config_errors():
    from botocore.exceptions import ConnectTimeoutError, EndpointConnectionError

    assert hc.explain(EndpointConnectionError(endpoint_url="https://nope.invalid")).message == hc.UNREACHABLE
    assert hc.explain(ConnectTimeoutError(endpoint_url="https://slow.example")).message == hc.TIMED_OUT
    import socket

    assert hc.explain(socket.gaierror(-2, "Name or service not known")).message == hc.UNREACHABLE
    assert hc.explain(StorageConfigError("missing setting(s): BACKUP_S3_BUCKET")).message == "settings: missing setting(s): BACKUP_S3_BUCKET"
    try:
        try:
            raise _client_error("InvalidAccessKeyId", 403)
        except Exception as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert hc.explain(outer).message == hc.KEY_INVALID  # found down the chain
    plain = hc.explain(ValueError("first line\nsecond line"))
    assert (plain.message, plain.code) == ("first line / second line", None)


def test_scrub_removes_credentials():
    env = {"AWS_SECRET_ACCESS_KEY": "fake-secret-value-one", "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE1234", "BACKUP_S3_BUCKET": "marvin-backups"}
    text = "failed with key AKIAEXAMPLE1234 and secret fake-secret-value-one at postgres://marvin:hunter22@db:5432/marvin in marvin-backups"
    out = hc.scrub(text, env)
    assert "AKIAEXAMPLE1234" not in out and "fake-secret-value" not in out and "hunter22" not in out
    assert "postgres://****@db:5432/marvin" in out and "marvin-backups" in out  # a bucket isn't a credential
    assert len(hc.scrub("x" * 5000)) == hc.MAX_TEXT


# --------------------------------------------------------------------------------------------------
# The check (list / put / get / delete) through a provider and a target, against moto's S3
# --------------------------------------------------------------------------------------------------


class Boto3Target(MemoryBackupTarget):
    """A minimal S3 backup target over a boto3 client (the real one lives in marvin-storage-s3)."""

    slug = "s3test"

    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def put_file(self, key, path, metadata=None, content_type=None):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=Path(path).read_bytes(), Metadata=dict(metadata or {}))

    def get(self, key, dest):
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        Path(dest).write_bytes(obj["Body"].read())
        return obj.get("Metadata", {})

    def list(self, prefix):
        from marvin_integration_sdk.storage import TargetObject

        out = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return {o["Key"]: TargetObject(o["Key"], o["Size"]) for o in out.get("Contents", [])}

    def delete(self, keys):
        for k in keys:
            self.client.delete_object(Bucket=self.bucket, Key=k)

    def describe(self):
        return f"s3://{self.bucket} (moto)"


class Boto3Provider(MemoryStorageProvider):
    """A minimal asset provider over a boto3 client, enough for check_provider."""

    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def iter_keys(self, prefix=""):
        out = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        yield from (o["Key"] for o in out.get("Contents", []))

    def put(self, key, data, content_type, metadata=None):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data.read(), ContentType=content_type)

    def get(self, key):
        return io.BytesIO(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)
        return True


@pytest.fixture
def s3(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    for var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="marvin-backups")
        yield client


def _keys(client, bucket="marvin-backups"):
    return [o["Key"] for o in client.list_objects_v2(Bucket=bucket).get("Contents", [])]


def test_check_target_round_trip_leaves_nothing_behind(s3):
    result = hc.check_target(Boto3Target(s3, "marvin-backups"))
    assert result.ok, result.lines()
    assert [s.name for s in result.steps] == ["list", "put", "get", "delete"]
    assert result.key.startswith(hc.HEALTHCHECK_PREFIX) and result.location == "s3://marvin-backups (moto)"
    assert _keys(s3) == []


def test_check_provider_round_trip_leaves_nothing_behind(s3):
    result = hc.check_provider(Boto3Provider(s3, "marvin-backups"), "s3://marvin-backups")
    assert result.ok, result.lines()
    assert _keys(s3) == []


def test_check_reports_a_missing_bucket(s3):
    result = hc.check_target(Boto3Target(s3, "no-such-bucket"))
    assert not result.ok
    steps = {s.name: s for s in result.steps}
    assert steps["put"].error == hc.NO_BUCKET and steps["put"].code == "NoSuchBucket"
    assert steps["get"].error == "skipped: the put failed"


def test_check_reports_a_revoked_key(s3):
    import boto3
    from moto.core import set_initial_no_auth_action_count

    @set_initial_no_auth_action_count(0)
    def run():
        revoked = boto3.client("s3", region_name="us-east-1", aws_access_key_id="AKIAREVOKED0000", aws_secret_access_key="gone")
        return hc.check_target(Boto3Target(revoked, "marvin-backups"))

    result = run()
    assert not result.ok
    put = next(s for s in result.steps if s.name == "put")
    assert (put.error, put.code) == (hc.KEY_INVALID, "InvalidAccessKeyId")


def test_check_with_a_key_that_cannot_access_the_bucket(s3):
    import boto3
    from moto.core import set_initial_no_auth_action_count

    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_user(UserName="scoped")
    key = iam.create_access_key(UserName="scoped")["AccessKey"]  # no policy: may do nothing

    @set_initial_no_auth_action_count(0)
    def run():
        scoped = boto3.client("s3", region_name="us-east-1", aws_access_key_id=key["AccessKeyId"], aws_secret_access_key=key["SecretAccessKey"])
        return hc.check_target(Boto3Target(scoped, "marvin-backups"))

    put = next(s for s in run().steps if s.name == "put")
    assert (put.error, put.code) == (hc.KEY_NO_ACCESS, "AccessDenied")


def test_check_reports_an_unreachable_endpoint(monkeypatch):
    import boto3
    from botocore.config import Config

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    client = boto3.client(
        "s3",
        region_name="auto",
        endpoint_url="https://marvin-healthcheck.invalid",
        config=Config(retries={"max_attempts": 1}, connect_timeout=2, read_timeout=2),
    )
    result = hc.check_target(Boto3Target(client, "marvin-backups"))
    assert not result.ok and {s.error for s in result.steps if s.name != "get"} == {hc.UNREACHABLE}


def test_the_s3_plugin_against_moto(s3):
    plugin = pytest.importorskip("marvin_storage_s3")
    from marvin_storage_s3.provider import S3StorageProvider
    from marvin_storage_s3.target import S3BackupTarget

    target = S3BackupTarget.from_config({"BACKUP_S3_BUCKET": "marvin-backups", "BACKUP_S3_REGION": "us-east-1"})
    assert hc.check_target(target).ok
    provider = S3StorageProvider.from_config({"STORAGE_S3_BUCKET": "marvin-backups", "STORAGE_S3_REGION": "us-east-1"})
    assert hc.check_provider(provider).ok
    assert _keys(s3) == [] and plugin


# --------------------------------------------------------------------------------------------------
# Recording runs (the job side)
# --------------------------------------------------------------------------------------------------


def _runs_db(data_dir: Path) -> Path:
    """DATA_DIR/marvin.db with the backup_runs table (and a little data for the snapshot to copy)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    db = data_dir / "marvin.db"
    eng = sa.create_engine(f"sqlite:///{db}")
    BackupRunModel.__table__.create(eng)
    eng.dispose()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    conn.execute("INSERT INTO users (email) VALUES ('a@example.com')")
    conn.commit()
    conn.close()
    (data_dir / ".secret").write_text("installation-secret")
    return db


def _read_runs(db: Path) -> list[BackupRunModel]:
    eng = sa.create_engine(f"sqlite:///{db}")
    with Session(eng) as s:
        rows = s.query(BackupRunModel).order_by(BackupRunModel.started_at).all()
        s.expunge_all()
    eng.dispose()
    return rows


def test_recorder_columns_match_the_model():
    model = {c.name for c in BackupRunModel.__table__.columns}
    assert set(recorder.COLUMNS) == model - {"notified_at"}  # notified_at is the backend's


def test_record_run_writes_a_row_the_backend_reads(tmp_path):
    db = _runs_db(tmp_path / "data")
    started = datetime(2026, 10, 7, 15, 0, 3, tzinfo=UTC)
    rec = recorder.RunRecord(
        target_name="r2",
        target_type="s3",
        status="ok",
        started_at=started,
        finished_at=started + timedelta(seconds=8.7),
        schedule="0 * * * *",
        time_zone="America/New_York",
        retention=(48, 30, 8),
        location="s3://marvin-backups (abc.r2.cloudflarestorage.com)",
        settings={"BACKUP_S3_BUCKET": "marvin-backups"},
        db_engine="postgres",
        db_key="postgres/marvin-20261007T150003Z.dump",
        db_bytes=7_400_000,
        config_items=3,
        assets_uploaded=0,
        assets_unchanged=516,
        pruned=2,
        host="marvin-backup-r2-29321940-abcde",
    )
    assert recorder.record_run(rec, {"DB_ENGINE": "sqlite", "BACKUP_DATA_DIR": str(db.parent)})
    (row,) = _read_runs(db)
    assert isinstance(row.id, uuid.UUID) and row.status == "ok" and row.started_at == started
    assert row.duration_seconds == pytest.approx(8.7) and row.settings_json == {"BACKUP_S3_BUCKET": "marvin-backups"}
    assert (row.keep_hourly, row.keep_daily, row.keep_weekly) == (48, 30, 8) and row.notified_at is None
    assert row.host == "marvin-backup-r2-29321940-abcde" and row.assets_unchanged == 516


def test_record_run_on_postgres(db_session):
    """The job's psycopg2 INSERT into the real (migrated) table: the Postgres CI job, or DB_ENGINE=postgres."""
    from marvin.db.db_setup import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("needs the suite on Postgres (DB_ENGINE=postgres)")
    url = engine.url
    env = {
        "DB_ENGINE": "postgres",
        "POSTGRES_SERVER": url.host or "localhost",
        "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_USER": url.username or "",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_DB": url.database or "",
    }
    name = f"pg-{uuid.uuid4().hex[:8]}"
    rec = recorder.RunRecord(name, "s3", "partial", NOW, NOW + timedelta(seconds=3), settings={"BACKUP_S3_BUCKET": "b"}, retention=(48, 30, 8))
    try:
        assert recorder.record_run(rec, env)
        row = db_session.query(BackupRunModel).filter_by(target_name=name).one()
        assert row.status == "partial" and row.started_at == NOW and row.settings_json == {"BACKUP_S3_BUCKET": "b"}
        assert isinstance(row.id, uuid.UUID) and row.keep_weekly == 8
    finally:
        db_session.query(BackupRunModel).filter_by(target_name=name).delete()
        db_session.commit()


def test_record_run_never_creates_a_database_or_raises(tmp_path, caplog):
    rec = recorder.RunRecord("r2", "s3", "failed", NOW, NOW)
    assert not recorder.record_run(rec, {"DB_ENGINE": "sqlite", "BACKUP_DATA_DIR": str(tmp_path)})
    assert not (tmp_path / "marvin.db").exists()
    assert "NOT recorded" in caplog.text
    assert not recorder.record_run(rec, {"DB_ENGINE": "postgres"})  # no connection settings
    assert not recorder.record_run(rec, {"DB_ENGINE": "oracle"})


def test_target_settings_leave_out_secrets_and_keys(entry_points):  # noqa: F811
    env = {
        "BACKUP_LOCAL_ROOT": "/backup-target",
        "BACKUP_DATA_DIR": "/app/data",
        "BACKUP_PREFIX": "prod/",
        "AWS_SECRET_ACCESS_KEY": "nope",
    }

    class KeyedTarget(MemoryBackupTarget):
        settings = (
            Setting("X_BUCKET", "Bucket", required=True),
            Setting("X_ACCESS_KEY_ID", "Access key"),
            Setting("X_SECRET", "Secret", secret=True),
        )

    entry_points.append(_EP("keyed", StoragePlugin(slug="keyed", name="Keyed", target=KeyedTarget)))
    assert recorder.target_settings("local", env) == {"BACKUP_LOCAL_ROOT": "/backup-target", "BACKUP_DATA_DIR": "/app/data", "BACKUP_PREFIX": "prod/"}
    got = recorder.target_settings("keyed", {"X_BUCKET": "b", "X_ACCESS_KEY_ID": "AKIA1234", "X_SECRET": "s"})
    assert got == {"X_BUCKET": "b"}
    assert recorder.target_settings("nosuch", {}) == {}


# The CLI's run(): every outcome is recorded.


class SharedMemoryTarget(MemoryBackupTarget):
    """One store for every instance (the CLI builds its own), and a switch to make writes fail like R2 does
    with a revoked key."""

    slug = "memtest"
    store: dict = {}
    fail_with: Exception | None = None

    @classmethod
    def from_config(cls, config):
        t = cls()
        t.objects = cls.store
        return t

    def put_file(self, key, path, metadata=None, content_type=None):
        if SharedMemoryTarget.fail_with is not None:
            raise SharedMemoryTarget.fail_with
        return super().put_file(key, path, metadata, content_type)

    def list(self, prefix):
        if SharedMemoryTarget.fail_with is not None:
            raise SharedMemoryTarget.fail_with
        return super().list(prefix)


@pytest.fixture
def job(entry_points, tmp_path, monkeypatch):  # noqa: F811
    entry_points.append(_EP("memtest", StoragePlugin(slug="memtest", name="Memory", target=SharedMemoryTarget)))
    SharedMemoryTarget.store, SharedMemoryTarget.fail_with = {}, None
    data = tmp_path / "data"
    db = _runs_db(data)
    env = {
        "DB_ENGINE": "sqlite",
        "BACKUP_DATA_DIR": str(data),
        "BACKUP_SCHEDULE": "0 * * * *",
        "BACKUP_TIME_ZONE": "America/New_York",
        "BACKUP_KEEP_HOURLY": "48",
        "STORAGE_PROVIDER": "local",
        "HOSTNAME": "marvin-backup-r2-1-xyz",
        "AWS_SECRET_ACCESS_KEY": "fake-secret-value-two",
    }
    yield SimpleNamespace(env=env, db=db)
    SharedMemoryTarget.fail_with = None


def test_run_records_a_successful_run(job):
    assert backup_cli.run("memtest", "r2", env=job.env) == 0
    (row,) = _read_runs(job.db)
    assert (row.target_name, row.target_type, row.status, row.failures) == ("r2", "memtest", "ok", 0)
    assert (row.schedule, row.time_zone, row.keep_hourly) == ("0 * * * *", "America/New_York", 48)
    assert row.db_key.startswith("sqlite/") and row.db_bytes > 0 and row.config_items == 1
    assert row.host == "marvin-backup-r2-1-xyz" and row.error_summary is None and row.location


def test_run_records_a_failed_run_when_the_key_is_revoked(job):
    SharedMemoryTarget.fail_with = _client_error("InvalidAccessKeyId", 403)
    assert backup_cli.run("memtest", "r2", env=job.env) == 1
    (row,) = _read_runs(job.db)
    assert row.status == "failed" and row.db_key is None and row.failures >= 2
    assert row.error_summary.startswith("database, config: " + hc.KEY_INVALID) and row.error_summary.count("InvalidAccessKeyId") == 1


def test_run_records_a_target_that_cannot_be_opened(job):
    assert backup_cli.run("nosuch", "nas", env=job.env) == 2
    (row,) = _read_runs(job.db)
    assert (row.target_name, row.status) == ("nas", "failed")
    assert row.error_summary.startswith("target: ") and "unknown backup target 'nosuch'" in row.error_summary


def test_run_records_partial_when_only_assets_fail(job):
    env = {**job.env, "BACKUP_ASSET_PROVIDERS": "nosuch"}
    assert backup_cli.run("memtest", "r2", env=env) == 1
    (row,) = _read_runs(job.db)
    assert row.status == "partial" and row.db_key and "assets from nosuch" in row.error_summary


def test_run_never_records_a_secret(job):
    secret = job.env["AWS_SECRET_ACCESS_KEY"]
    SharedMemoryTarget.fail_with = RuntimeError(f"signature mismatch for {secret}")
    backup_cli.run("memtest", "r2", env=job.env)
    (row,) = _read_runs(job.db)
    assert secret not in (row.error_summary or "") and "****" in row.error_summary
    assert secret not in json.dumps(row.settings_json or {})


def test_failures_with_the_same_reason_are_folded():
    why = hc.KEY_INVALID + " (InvalidAccessKeyId)"
    got = backup_cli.summarize_failures([f"database: {why}", f"config: {why}", f"assets: {why}", "asset ws/a.png: AccessDenied"])
    assert got == f"database, config, assets: {why}; asset ws/a.png: AccessDenied"
    assert backup_cli.summarize_failures([f"s{i}: e{i}" for i in range(7)]).endswith("; and 2 more")


def test_a_dry_run_is_not_recorded(job):
    assert backup_cli.run("memtest", "r2", dry_run=True, env=job.env) == 0
    assert _read_runs(job.db) == []


def test_test_command_checks_a_target(job, monkeypatch, capsys):
    monkeypatch.setattr("os.environ", {**job.env})
    assert backup_cli.main(["test", "--target", "memtest", "--name", "r2"]) == 0
    out = capsys.readouterr().out
    assert "put" in out and "delete" in out and "FAILED" not in out
    assert SharedMemoryTarget.store == {}  # nothing left behind
    assert _read_runs(job.db) == []  # a test records nothing
    SharedMemoryTarget.fail_with = _client_error("AccessDenied", 403)
    assert backup_cli.main(["test", "--target", "memtest", "--name", "r2"]) == 1
    assert hc.KEY_NO_ACCESS in capsys.readouterr().out


# --------------------------------------------------------------------------------------------------
# The backend: target health, announcements, overdue detection
# --------------------------------------------------------------------------------------------------


class _Bus:
    def __init__(self):
        self.events: list[dict] = []

    def dispatch(self, **kw):
        self.events.append(kw)


@pytest.fixture
def runs(db_session):
    """A clean backup_runs table, and a helper adding a job's run."""
    db_session.query(BackupRunModel).delete()
    db_session.commit()

    def add(name="r2", status="ok", at=NOW, schedule="0 * * * *", tz="America/New_York", notified=True, **kw):
        row = BackupRunModel(
            session=db_session,
            target_name=name,
            target_type=kw.pop("target_type", "s3"),
            status=status,
            started_at=at.replace(tzinfo=None),
            finished_at=(at + timedelta(seconds=9)).replace(tzinfo=None),
            duration_seconds=9.0,
            schedule=schedule,
            time_zone=tz,
            keep_hourly=48,
            keep_daily=30,
            keep_weekly=8,
            location="s3://marvin-backups (r2)",
            settings_json={"BACKUP_S3_BUCKET": "marvin-backups"},
            failures=0 if status == "ok" else 2,
            notified_at=at.replace(tzinfo=None) if notified else None,
            **kw,
        )
        db_session.add(row)
        db_session.commit()
        return row

    yield add
    db_session.query(BackupRunModel).delete()
    db_session.commit()


def test_target_health_ok_with_next_run(db_session, runs):
    runs(at=NOW - timedelta(minutes=5))
    (t,) = backup_health.all_targets(db_session, NOW)
    assert (t.name, t.type, t.state, t.overdue) == ("r2", "s3", "ok", False)
    assert t.next_run_at == datetime(2026, 10, 7, 17, 0, tzinfo=UTC) and t.interval == timedelta(hours=1)
    assert t.due_by == NOW - timedelta(minutes=5) + timedelta(hours=2) + backup_health.GRACE
    assert t.retention == (48, 30, 8) and t.settings == {"BACKUP_S3_BUCKET": "marvin-backups"}


def test_target_health_failing_then_overdue(db_session, runs):
    runs(at=NOW - timedelta(hours=1, minutes=5))  # 15:00 ok
    runs(status="failed", at=NOW - timedelta(minutes=5), error_summary="database: " + hc.KEY_INVALID)  # 16:00 failed
    (t,) = backup_health.all_targets(db_session, NOW)
    assert t.state == "failed" and not t.overdue and t.last_run.status == "failed" and t.last_success.status == "ok"
    later = NOW + timedelta(hours=1, minutes=11)  # 17:16, still no success since 15:00
    (t,) = backup_health.all_targets(db_session, later)
    assert t.state == "overdue" and t.overdue


def test_a_target_without_a_schedule_is_never_overdue(db_session, runs):
    runs(at=NOW - timedelta(days=3), schedule=None, tz=None)
    (t,) = backup_health.all_targets(db_session, NOW)
    assert t.state == "ok" and not t.overdue and "BACKUP_SCHEDULE" in t.schedule_error


def test_announce_runs_sends_completed_and_failed_once(db_session, runs):
    ok = runs(at=NOW - timedelta(hours=1), notified=False, db_bytes=7_400_000)
    bad = runs(status="partial", at=NOW - timedelta(minutes=5), notified=False, error_summary="assets: " + hc.KEY_NO_ACCESS)
    runs(name="old", status="failed", at=NOW - timedelta(days=3), notified=False)  # from before the backend was up: not announced
    bus = _Bus()
    assert backup_health.announce_runs(db_session, bus, NOW) == 2
    kinds = [(e["event_type"].name, e["document_data"].reason) for e in bus.events]
    assert kinds == [("backup_completed", "completed"), ("backup_failed", "partial")]
    first = bus.events[0]
    assert first["group_id"] is None and first["entity_id"] == ok.id and first["document_data"].backup_size == "7.4 MB"
    assert bus.events[1]["document_data"].error_message == "assets: " + hc.KEY_NO_ACCESS and bad.notified_at is not None
    assert backup_health.announce_runs(db_session, _Bus(), NOW) == 0  # all marked


def test_failed_runs_alert_once_per_incident_and_recovery_once(db_session, runs):
    """backoffLimit: 2 retries a failing run, so one bad hour records three failed runs: one alert. The ok
    run that ends the incident says recovered; the next failure is a new incident."""
    runs(at=NOW - timedelta(hours=2))  # the last ok run, already announced
    for minutes, status in ((60, "failed"), (58, "failed"), (55, "partial")):
        runs(status=status, at=NOW - timedelta(minutes=minutes), notified=False, error_summary="database: " + hc.KEY_INVALID)
    bus = _Bus()
    assert backup_health.announce_runs(db_session, bus, NOW) == 1
    (event,) = bus.events
    assert (event["event_type"].name, event["document_data"].reason) == ("backup_failed", "failed")
    assert event["message"] == "Backup r2: failed"
    assert db_session.query(BackupRunModel).filter(BackupRunModel.notified_at.is_(None)).count() == 0  # retries marked, not sent

    # Still failing an hour later: the same incident, no second alert.
    runs(status="failed", at=NOW + timedelta(minutes=5), notified=False)
    assert backup_health.announce_runs(db_session, bus, NOW + timedelta(minutes=10)) == 0

    # Recovery: said once; the next ok run is an ordinary completed.
    runs(at=NOW + timedelta(hours=1, minutes=5), notified=False)
    runs(at=NOW + timedelta(hours=2, minutes=5), notified=False)
    assert backup_health.announce_runs(db_session, bus, NOW + timedelta(hours=2, minutes=10)) == 2
    sent = [(e["event_type"].name, e["document_data"].reason, e["message"]) for e in bus.events[1:]]
    assert sent == [("backup_completed", "recovered", "Backup r2: recovered"), ("backup_completed", "completed", "Backup r2: ok")]

    # Failing again is a new incident: a new alert.
    runs(status="failed", at=NOW + timedelta(hours=3, minutes=5), notified=False)
    assert backup_health.announce_runs(db_session, bus, NOW + timedelta(hours=3, minutes=10)) == 1
    assert (bus.events[-1]["event_type"].name, bus.events[-1]["document_data"].reason) == ("backup_failed", "failed")


def test_incidents_are_per_target_and_overdue_counts_toward_recovery(db_session, runs):
    runs(name="r2", status="failed", at=NOW - timedelta(minutes=30), notified=True)  # r2's incident is open
    runs(name="nas", status="failed", at=NOW - timedelta(minutes=20), notified=False, target_type="local")
    runs(name="quiet", status="missed", at=NOW - timedelta(hours=1), notified=True)  # only an overdue marker
    runs(name="quiet", status="failed", at=NOW - timedelta(minutes=15), notified=False)
    runs(name="quiet", at=NOW - timedelta(minutes=10), notified=False)
    bus = _Bus()
    assert backup_health.announce_runs(db_session, bus, NOW) == 3
    sent = [(e["document_data"].target_name, e["document_data"].reason) for e in bus.events]
    # nas has nothing to do with r2's incident; quiet's overdue marker was announced on its own, so its
    # first failed run still alerts (it carries the error), and its ok run ends the incident.
    assert sent == [("nas", "failed"), ("quiet", "failed"), ("quiet", "recovered")]


def test_overdue_is_reported_once_per_incident_and_clears(db_session, runs):
    runs(at=NOW - timedelta(hours=3))  # last success 13:05
    runs(status="failed", at=NOW - timedelta(hours=1), error_summary="database: " + hc.KEY_INVALID)
    bus = _Bus()
    assert backup_health.check(db_session, bus, NOW).overdue == ["r2"]
    (event,) = bus.events
    data = event["document_data"]
    assert event["event_type"].name == "backup_failed" and data.reason == "overdue" and data.status == "missed"
    assert "no successful run since 2026-10-07 13:05 UTC" in data.error_message and hc.KEY_INVALID in data.error_message
    assert data.last_success_at == NOW - timedelta(hours=3)
    missed = db_session.query(BackupRunModel).filter_by(status="missed").one()
    assert missed.notified_at is not None and missed.target_type == "s3"

    # Same incident: no second alert, even a while later and with more failures.
    runs(status="failed", at=NOW + timedelta(minutes=55))
    assert backup_health.check(db_session, bus, NOW + timedelta(hours=2)).overdue == []
    (t,) = backup_health.all_targets(db_session, NOW + timedelta(hours=2))
    assert t.overdue and t.overdue_since == NOW and t.last_run.status == "failed"  # a missed marker isn't a run

    # A successful run ends it; going quiet again is a new incident.
    runs(at=NOW + timedelta(hours=2, minutes=55))
    (t,) = backup_health.all_targets(db_session, NOW + timedelta(hours=3))
    assert (t.state, t.overdue, t.overdue_since) == ("ok", False, None)
    assert backup_health.check(db_session, bus, NOW + timedelta(hours=3)).overdue == []
    assert backup_health.check(db_session, bus, NOW + timedelta(hours=6)).overdue == ["r2"]
    assert len(bus.events) == 2


def test_a_target_that_never_succeeded_is_overdue_from_its_first_run(db_session, runs):
    runs(name="nas-nightly", status="failed", at=NOW - timedelta(hours=27), schedule="30 2 * * *", target_type="local")
    bus = _Bus()
    assert backup_health.check(db_session, bus, NOW).overdue == ["nas-nightly"]
    assert "since the target was first seen" in bus.events[0]["document_data"].error_message


def test_daily_target_gets_26_hours(db_session, runs):
    runs(name="nas-nightly", at=NOW - timedelta(hours=26), schedule="30 2 * * *", target_type="local")
    assert backup_health.check(db_session, _Bus(), NOW).overdue == []
    assert backup_health.check(db_session, _Bus(), NOW + backup_health.GRACE + timedelta(minutes=1)).overdue == ["nas-nightly"]


def test_old_runs_are_pruned(db_session, runs):
    runs(at=NOW - timedelta(days=91))
    runs(at=NOW - timedelta(days=1))
    assert backup_health.prune_runs(db_session, NOW) == 1
    assert db_session.query(BackupRunModel).count() == 1


def test_the_scheduler_task_never_raises(monkeypatch):
    import importlib

    task = importlib.import_module("marvin.services.scheduler.tasks.check_backup_health")

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(backup_health, "check", boom)
    task.check_backup_health()  # logged, not raised


# --------------------------------------------------------------------------------------------------
# Events: platform scope, no workspace, the real bus
# --------------------------------------------------------------------------------------------------


def test_backup_events_are_sent_platform_scope_and_audit_locked():
    from marvin.services.events.event_catalog import HIDDEN_EVENT_TYPES, get_catalog_entry, is_platform_event

    for name in ("backup_completed", "backup_failed"):
        entry = get_catalog_entry(name)
        assert is_platform_event(name) and entry.audit_locked and entry.sent_by and name not in HIDDEN_EVENT_TYPES
        assert {"target_name", "reason", "location"} <= {v.slug for v in entry.variables}
    assert "backup_started" in HIDDEN_EVENT_TYPES  # still never sent


def test_check_writes_platform_events_without_a_workspace(db_session, runs):
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    run = runs(status="failed", at=datetime.now(UTC) - timedelta(minutes=2), notified=False, error_summary="database: " + hc.KEY_INVALID)
    backup_health.check(db_session, EventBusService(bg_tasks=None))
    db_session.expire_all()
    row = db_session.query(EventLogModel).filter(EventLogModel.event_type == "backup_failed", EventLogModel.entity_id == run.id).one()
    assert row.workspace_id is None
    doc = row.event_data.get("documentData") or row.event_data.get("document_data")
    assert doc["targetName" if "targetName" in doc else "target_name"] == "r2"


def test_an_overdue_target_reaches_the_event_log(db_session, runs):
    """The missed marker is committed before the event is dispatched: the event log writes on its own
    connection, which SQLite refuses ("database is locked") while another write is pending."""
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    runs(name="quiet", at=datetime.now(UTC) - timedelta(hours=5))
    assert backup_health.check(db_session, EventBusService(bg_tasks=None)).overdue == ["quiet"]
    db_session.expire_all()
    missed = db_session.query(BackupRunModel).filter_by(target_name="quiet", status="missed").one()
    row = db_session.query(EventLogModel).filter(EventLogModel.event_type == "backup_failed", EventLogModel.entity_id == missed.id).one()
    assert row.workspace_id is None and missed.notified_at is not None


def test_a_workspace_email_subscription_never_gets_a_platform_backup_event(db_session):
    """The repository scopes by group only when it has one: with no workspace, every workspace's
    subscription to the type would match. A platform event has none."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.email_templates import EmailTemplateModel
    from marvin.services.event_bus_service.event_bus_listener import EmailEventListener
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventTypes

    gid, tid = uuid.uuid4(), uuid.uuid4()
    g = Groups(session=db_session, name=f"Mail {gid.hex[:6]}", slug=f"mail-{gid.hex[:6]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(EmailTemplateModel.__table__).values(
            id=tid, template_type="custom", group_id=gid, name="Backup alert", subject="{{ message_title }}", enabled=True
        )
    )
    db_session.execute(
        sa.insert(EmailEventSubscriptionModel.__table__).values(
            id=uuid.uuid4(), group_id=gid, template_id=tid, event_type="backup_failed", recipient_type="admins", enabled=True
        )
    )
    db_session.commit()
    try:
        event = Event(
            message=EventBusMessage(title="Backup Failed"),
            event_type=EventTypes.backup_failed,
            integration_id="backup_health",
            document_data=None,
            workspace_id=None,
        )
        assert EmailEventListener(None).get_subscribers(event) == []
        assert EmailEventListener(gid).get_subscribers(event)  # the workspace's own scope still finds it
    finally:
        db_session.execute(sa.delete(EmailEventSubscriptionModel.__table__).where(EmailEventSubscriptionModel.__table__.c.group_id == gid))
        db_session.execute(sa.delete(EmailTemplateModel.__table__).where(EmailTemplateModel.__table__.c.id == tid))
        db_session.query(Groups).filter(Groups.id == gid).delete()
        db_session.commit()


# --------------------------------------------------------------------------------------------------
# Admin API: Backup health, the bell's platform feed, Storage settings and Test connection
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def admin():
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    def _as(role=PlatformRole.SUPER_ADMIN):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            group_id=None,
            active_group_id=None,
            platform_role=role,
            is_superuser=False,
            admin=True,
            full_name="Ada Admin",
            username="ada",
        )
        return TestClient(app)

    yield _as
    app.dependency_overrides.pop(get_current_user, None)


def test_backup_health_api(db_session, runs, admin):
    now = datetime.now(UTC)
    runs(at=now - timedelta(hours=1, minutes=30))
    runs(status="failed", at=now - timedelta(minutes=30), error_summary="database: " + hc.KEY_INVALID, host="pod-1")
    runs(name="nas-nightly", at=now - timedelta(hours=40), schedule="30 2 * * *", target_type="local")
    res = admin().get("/api/admin/backup-health")
    assert res.status_code == 200, res.text
    body = res.json()
    targets = {t["name"]: t for t in body["targets"]}
    assert targets["r2"]["state"] == "failed" and targets["r2"]["lastRun"]["errorSummary"].endswith(hc.KEY_INVALID)
    assert targets["r2"]["lastSuccess"]["status"] == "ok" and targets["r2"]["intervalSeconds"] == 3600
    assert targets["r2"]["nextRunAt"] and targets["r2"]["dueBy"] and targets["r2"]["keepHourly"] == 48
    assert targets["nas-nightly"]["state"] == "overdue" and targets["nas-nightly"]["overdue"]
    assert [r["status"] for r in body["runs"]][:2] == ["failed", "ok"] and body["runs"][0]["host"] == "pod-1"
    assert len(admin().get("/api/admin/backup-health", params={"target": "nas-nightly"}).json()["runs"]) == 1
    assert admin(PlatformRole.NONE).get("/api/admin/backup-health").status_code == 403


def test_the_platform_feed_carries_backup_failures_for_the_bell(db_session, runs, admin):
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    since = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    run = runs(status="failed", at=datetime.now(UTC) - timedelta(minutes=1), notified=False, error_summary="database: " + hc.KEY_INVALID)
    backup_health.check(db_session, EventBusService(bg_tasks=None))
    res = admin().get("/api/admin/events/feed", params={"since": since})
    assert res.status_code == 200, res.text
    (event,) = [e for e in res.json()["events"] if e["eventType"] == "backup_failed" and e["entityId"] == str(run.id)]
    assert event["workspaceId"] is None and event["detail"].endswith(hc.KEY_INVALID)
    assert admin(PlatformRole.NONE).get("/api/admin/events/feed").status_code == 403


@pytest.fixture
def storage_platform(entry_points, monkeypatch, tmp_path):  # noqa: F811
    from marvin.services.storage import provider_factory
    from tests.test_storage_providers import _settings

    settings = _settings(
        STORAGE_PROVIDER="local",
        STORAGE_LOCAL_ROOT=tmp_path / "assets",
        STORAGE_S3_BUCKET=None,
        STORAGE_S3_ACCESS_KEY="AKIAEXAMPLEKEY99",
        STORAGE_S3_SECRET_KEY="fake-secret-value-three",
    )
    monkeypatch.setattr(provider_factory, "_settings", lambda: settings)
    provider_factory.reset_provider_cache()
    yield SimpleNamespace(root=tmp_path / "assets")
    provider_factory.reset_provider_cache()


def test_setting_values_mask_secrets_and_key_ids():
    from marvin.services.storage.admin import setting_values

    declared = (
        Setting("B", "Bucket", required=True),
        Setting("R", "Region", default="auto"),
        Setting("X_ACCESS_KEY_ID", "Access key ID"),
        Setting("X_SECRET", "Secret", secret=True),
        Setting("E", "Endpoint"),
    )
    got = {v["env"]: v for v in setting_values(declared, {"B": "marvin-assets", "X_ACCESS_KEY_ID": "AKIAEXAMPLEKEY99", "X_SECRET": "s3cr3t"})}
    assert (got["B"]["value"], got["B"]["is_set"]) == ("marvin-assets", True)
    assert (got["R"]["value"], got["R"]["is_set"]) == ("auto", False)  # the default in effect
    assert (got["X_ACCESS_KEY_ID"]["value"], got["X_ACCESS_KEY_ID"]["secret"]) == ("…EY99", True)
    assert (got["X_SECRET"]["value"], got["X_SECRET"]["secret"]) == ("****", True)
    assert got["E"]["value"] is None


def test_admin_storage_shows_settings_masked_and_backup_targets(db_session, runs, admin, storage_platform):
    runs(at=datetime.now(UTC) - timedelta(minutes=10))
    res = admin().get("/api/admin/storage")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "fake-secret-value-three" not in res.text and "AKIAEXAMPLEKEY99" not in res.text
    providers = {p["slug"]: p for p in body["providers"]}
    local = {s["env"]: s for s in providers["local"]["settings"]}
    assert local["STORAGE_LOCAL_ROOT"]["value"] == str(storage_platform.root)
    s3 = {s["env"]: s for s in providers["s3"]["settings"]}
    assert s3["STORAGE_S3_SECRET_KEY"]["value"] == "****" and s3["STORAGE_S3_ACCESS_KEY"]["value"] == "…EY99"
    (target,) = body["backupTargets"]
    assert (target["name"], target["type"], target["state"]) == ("r2", "s3", "ok")
    assert target["settings"] == [
        {"env": "BACKUP_S3_BUCKET", "label": "BACKUP_S3_BUCKET", "value": "marvin-backups", "isSet": True, "secret": False, "help": ""}
    ]


def test_test_connection_on_the_local_provider(admin, storage_platform):
    res = admin().post("/api/admin/storage/providers/local/test")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and [s["name"] for s in body["steps"]] == ["list", "put", "get", "delete"]
    assert body["key"].startswith(hc.HEALTHCHECK_PREFIX)
    assert not [p for p in storage_platform.root.rglob("*") if p.is_file()]  # nothing left behind


def test_test_connection_reports_an_unconfigured_provider_and_refuses_an_unknown_one(admin, storage_platform):
    res = admin().post("/api/admin/storage/providers/s3/test")
    assert res.status_code == 200, res.text
    body = res.json()
    assert not body["ok"] and body["steps"][0]["name"] == "settings" and "STORAGE_S3_BUCKET" in body["steps"][0]["error"]
    assert admin().post("/api/admin/storage/providers/nosuch/test").status_code == 404
    assert admin(PlatformRole.NONE).post("/api/admin/storage/providers/local/test").status_code == 403


def test_test_connection_maps_a_revoked_key(admin, storage_platform, entry_points, s3):  # noqa: F811
    import boto3
    from moto.core import set_initial_no_auth_action_count

    class RevokedProvider(Boto3Provider):
        slug = "revoked"
        settings = ()

        @classmethod
        def from_config(cls, config):
            client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="AKIAREVOKED0000", aws_secret_access_key="gone")
            return Boto3Provider(client, "marvin-backups")

    entry_points.append(_EP("revoked", StoragePlugin(slug="revoked", name="Revoked", provider=RevokedProvider)))

    @set_initial_no_auth_action_count(0)
    def run():
        return admin().post("/api/admin/storage/providers/revoked/test").json()

    body = run()
    assert not body["ok"]
    put = next(s for s in body["steps"] if s["name"] == "put")
    assert (put["error"], put["code"]) == (hc.KEY_INVALID, "InvalidAccessKeyId")
