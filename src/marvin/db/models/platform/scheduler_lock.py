"""Leader-election lease for the scheduler.

Every API process starts the scheduler in its lifespan, so running more than one replica ran the
minutely callbacks more than once per minute — duplicate webhook deliveries and duplicate
scheduled-task triggers. This table holds a single row that exactly one process owns at a time:
whoever holds an unexpired lease runs the callbacks, everyone else skips the tick.

A row rather than a Postgres advisory lock so the mechanism works on SQLite too, which is what
development and single-container deployments run on.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from marvin.db.models import BaseMixins, SqlAlchemyBase

# The table holds exactly one row, addressed by this constant.
SCHEDULER_LOCK_ID = "scheduler"


class SchedulerLockModel(SqlAlchemyBase, BaseMixins):
    """The scheduler's single leadership lease."""

    __tablename__ = "scheduler_lock"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    """Always SCHEDULER_LOCK_ID — the singleton row's key."""

    holder_id: Mapped[str] = mapped_column(String, nullable=False)
    """Identifies the process currently holding the lease. Regenerated per process start."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """
    When the lease lapses. The holder pushes this forward on every tick; if it dies, the row is
    claimable again once this passes, so leadership recovers without anyone intervening.
    """

    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """When the current holder first took the lease. Useful for spotting leadership flapping."""
