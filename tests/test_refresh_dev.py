"""Refreshing marvin-dev from production's newest backup (scripts/refresh_dev.py, `task dev:refresh`): the guards
that keep it off production's database, the asset top-up, and the order of the steps."""

import io
from pathlib import Path

import pytest
from marvin_integration_sdk.storage.memory import MemoryBackupTarget, MemoryStorageProvider

from marvin.scripts import refresh_dev


class _Source:
    def describe(self):
        return "s3://marvin-backups"


DEV_ENV = {"BACKUP_S3_BUCKET": "marvin-backups-dev", "POSTGRES_SERVER": "marvin-dev-pg-rw"}


@pytest.mark.parametrize(
    "env, source, host, refused",
    [
        (DEV_ENV, "marvin-backups", "marvin-dev-pg-rw", None),
        ({"BACKUP_S3_BUCKET": "marvin-backups", "POSTGRES_SERVER": "marvin-pg-rw"}, "marvin-backups", "marvin-pg-rw", "production job"),
        (DEV_ENV, "marvin-backups", "marvin-pg-rw", "does not match"),
        ({"POSTGRES_SERVER": "marvin-dev-pg-rw"}, "marvin-backups", "marvin-dev-pg-rw", "BACKUP_S3_BUCKET is not set"),
    ],
)
def test_it_only_replaces_the_database_it_was_told_to_and_never_from_its_own_bucket(env, source, host, refused):
    reason = refresh_dev.refuse_unless_safe(env, source, host)
    assert reason is None if refused is None else refused in reason


def _put(target, key: str, data: bytes, tmp_path: Path) -> None:
    path = tmp_path / "upload"
    path.write_bytes(data)
    target.put_file(key, path)


def test_assets_dev_lacks_are_copied_and_ones_it_has_are_left_alone(tmp_path, monkeypatch):
    source = MemoryBackupTarget()
    _put(source, "assets/ws/new.png", b"new", tmp_path)
    _put(source, "assets/ws/old.png", b"prod copy", tmp_path)
    dev = MemoryStorageProvider()
    dev.put("ws/old.png", io.BytesIO(b"dev copy"), "image/png")
    monkeypatch.setattr(refresh_dev.engine, "open_asset_sources", lambda settings, env: ([dev], []))

    copied, present = refresh_dev.copy_missing_assets(source, None, {}, tmp_path)

    assert (copied, present) == (1, 1)
    assert dev.get("ws/new.png").read() == b"new"
    assert dev.get("ws/old.png").read() == b"dev copy"  # nothing overwritten, nothing deleted


def test_a_refused_run_touches_nothing(monkeypatch):
    monkeypatch.setattr("os.environ", {"BACKUP_S3_BUCKET": "marvin-backups", "POSTGRES_SERVER": "marvin-pg-rw"})
    monkeypatch.setattr(refresh_dev, "restore_database", lambda *a: pytest.fail("restored a database it should have refused"))
    assert refresh_dev.main(["--source-bucket", "marvin-backups", "--confirm-db-host", "marvin-pg-rw"]) == 2


def test_the_steps_run_in_order_and_assets_can_be_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr("os.environ", dict(DEV_ENV))
    monkeypatch.setattr(refresh_dev.engine, "open_target", lambda slug, env=None: calls.append(("source", env["BACKUP_S3_BUCKET"])) or _Source())
    monkeypatch.setattr(refresh_dev, "restore_database", lambda source, settings, work: calls.append("restore") or "postgres/marvin-x.dump")
    monkeypatch.setattr(refresh_dev, "pause", lambda settings: calls.append("pause") or [])
    monkeypatch.setattr(refresh_dev, "copy_missing_assets", lambda *a: calls.append("assets") or (0, 0))

    assert refresh_dev.main(["--source-bucket", "marvin-backups", "--confirm-db-host", "marvin-dev-pg-rw"]) == 0
    assert calls == [("source", "marvin-backups"), "restore", "pause", "assets"]
    calls.clear()
    assert refresh_dev.main(["--source-bucket", "marvin-backups", "--confirm-db-host", "marvin-dev-pg-rw", "--skip-assets"]) == 0
    assert "assets" not in calls


def test_a_failed_restore_fails_the_job_before_anything_is_paused(monkeypatch):
    monkeypatch.setattr("os.environ", dict(DEV_ENV))
    monkeypatch.setattr(refresh_dev.engine, "open_target", lambda slug, env=None: _Source())

    def broken(*a):
        raise refresh_dev.BackupError("pg_restore failed (1): …")

    monkeypatch.setattr(refresh_dev, "restore_database", broken)
    monkeypatch.setattr(refresh_dev, "pause", lambda settings: pytest.fail("paused after a failed restore"))
    assert refresh_dev.main(["--source-bucket", "marvin-backups", "--confirm-db-host", "marvin-dev-pg-rw"]) == 1
