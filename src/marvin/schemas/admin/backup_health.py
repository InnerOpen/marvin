"""Schemas for Admin → Backup health (/api/admin/backup-health): the backup targets as their runs report
them. Nothing here is a credential (see db/models/platform/backup_runs.py)."""

from datetime import datetime
from typing import Any

from pydantic import UUID4

from marvin.schemas._marvin import _MarvinModel


class BackupRunRead(_MarvinModel):
    id: UUID4
    target_name: str
    target_type: str
    status: str
    """ok, partial (the database was saved, another step failed), failed, or missed (written by the
    backend: no successful run in time)."""
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    db_engine: str | None = None
    db_key: str | None = None
    db_bytes: int | None = None
    db_gz_bytes: int | None = None
    config_items: int | None = None
    assets_uploaded: int | None = None
    assets_uploaded_bytes: int | None = None
    assets_unchanged: int | None = None
    pruned: int | None = None
    failures: int = 0
    error_summary: str | None = None
    host: str | None = None
    """The pod that ran it: `oc logs <host>` while the Job is kept."""
    notified_at: datetime | None = None


class BackupTargetRead(_MarvinModel):
    name: str
    type: str
    state: str
    """ok, partial, failed, overdue, or unknown (no schedule recorded, so nothing to compare with)."""
    schedule: str | None = None
    time_zone: str | None = None
    schedule_error: str | None = None
    """Why next run / overdue can't be worked out (no schedule recorded, or one this reader can't parse)."""
    interval_seconds: int | None = None
    keep_hourly: int | None = None
    keep_daily: int | None = None
    keep_weekly: int | None = None
    location: str | None = None
    settings: dict[str, Any] = {}
    """Its non-secret settings as the latest run read them."""
    last_run: BackupRunRead | None = None
    last_success: BackupRunRead | None = None
    first_seen: datetime | None = None
    next_run_at: datetime | None = None
    due_by: datetime | None = None
    """A successful run must start before this, or the target is overdue."""
    overdue: bool = False
    overdue_since: datetime | None = None
    """When the current overdue incident was reported (backup_failed, reason overdue)."""


class BackupHealthRead(_MarvinModel):
    now: datetime
    targets: list[BackupTargetRead]
    runs: list[BackupRunRead]
    """The newest runs, all targets (or the one asked for), newest first."""
