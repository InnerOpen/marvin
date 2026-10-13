"""One row per run of a backup target (``python -m marvin.scripts.backup run``), written by the backup job
itself at the end of the run, whatever its outcome, plus the ``missed`` rows the backend's health check
adds when a target goes quiet.

The backup CronJobs run beside the backend and the backend can't see Kubernetes, so this table is how it
learns about them: the job writes the row with plain DB-API calls (``services/backup_engine/recorder.py``,
which must stay free of Marvin's settings and SQLAlchemy), and the backend reads it for Admin → Backup
health, the ``backup_completed`` / ``backup_failed`` events and overdue detection
(``services/backup_health``). Nothing here is ever a credential: ``location`` is the target's own
``describe()``, ``settings_json`` holds only its non-secret settings, and ``error_summary`` is scrubbed of
anything that looks like a key before it is written.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
"""The database was backed up, another step (config, assets, prune) failed."""
STATUS_FAILED = "failed"
"""The database wasn't backed up, or the target couldn't be opened."""
STATUS_MISSED = "missed"
"""Written by the backend, not a job: no successful run within the target's overdue window."""
STATUSES = (STATUS_OK, STATUS_PARTIAL, STATUS_FAILED, STATUS_MISSED)


class BackupRunModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "backup_runs"
    __table_args__ = (sa.Index("ix_backup_runs_target_started", "target_name", "started_at"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    target_name: Mapped[str] = mapped_column(sa.String(63), nullable=False)
    """The chart's ``backup.targets[].name`` (``--name``), e.g. ``r2``."""
    target_type: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    """``local`` or a plugin's target slug (``--target``), e.g. ``s3``."""
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    schedule: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """The CronJob's schedule (BACKUP_SCHEDULE), e.g. ``0 * * * *``."""
    time_zone: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """The zone the schedule is read in (BACKUP_TIME_ZONE); empty means the cluster's, UTC."""
    keep_hourly: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    keep_daily: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    keep_weekly: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    location: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    """The target's ``describe()``, e.g. ``s3://marvin-backups (….r2.cloudflarestorage.com)``."""
    settings_json: Mapped[dict | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    """The target's non-secret settings as the job read them (bucket, endpoint, region, prefix, …)."""

    db_engine: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    db_key: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    db_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    db_gz_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    config_items: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    assets_uploaded: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    assets_uploaded_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    assets_unchanged: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    pruned: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    failures: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    host: Mapped[str | None] = mapped_column(sa.String(63), nullable=True)
    """The pod that ran it (HOSTNAME), for ``oc logs``."""

    notified_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """When the backend dispatched this run's event (backup_completed / backup_failed); None until then."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
