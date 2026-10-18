"""``metric_observations`` — what a workflow's Metric step recorded: a number for a metric, a variant and a window.

One row per (workspace, metric, variant, subject, window): the window is a day (``2026-10-18``), an ISO week
(``2026-W42``) or a month (``2026-10``), worked out in the workspace's time zone; ``variant`` and ``subject`` are free
labels ("" when the step names none). Recording the same key again replaces the value, so a run repeated for the same
window doesn't double-count (services/metrics.py). These are observations — numbers someone noted down — never a
statement of what caused them.
"""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

__all__ = ["MetricObservationModel"]


class MetricObservationModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "metric_observations"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    variant: Mapped[str] = mapped_column(sa.String(100), nullable=False, default="")
    subject: Mapped[str] = mapped_column(sa.String(100), nullable=False, default="")
    window_label: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    """The window as written: ``2026-10-18`` | ``2026-W42`` | ``2026-10``."""
    granularity: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """day | week | month."""
    window_start: Mapped[date] = mapped_column(sa.Date, nullable=False)
    """The window's first day (a week's Monday) — what a date range filters on."""
    value: Mapped[float] = mapped_column(sa.Float, nullable=False)
    automation_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="SET NULL"), nullable=True)
    """The workflow whose step recorded it (None once it is deleted, or for a dry-run-free manual write)."""

    __table_args__ = (
        sa.UniqueConstraint("group_id", "metric", "variant", "subject", "window_label", name="uq_metric_observations_key"),
        sa.Index("ix_metric_observations_metric_window", "group_id", "metric", "window_start"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
