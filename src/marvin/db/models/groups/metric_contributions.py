"""``metric_contributions`` — the events a Metric step has already counted, so the same event is never added twice.

A Metric step in ``add`` mode (services/automation/actions/metric.py) claims a row here — keyed on its run's event, the
workflow and the step — in the same transaction that raises the window's number. The same event handled twice (a
re-delivery, a retry, a run of the same trigger again) finds the claim and adds nothing; a write that fails rolls the
claim back with it, so a retry can still count. A claim goes with the observation it counted into (clearing a window
on the Metrics page starts its count over). It holds the key and the amount, never the event.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

__all__ = ["MetricContributionModel"]


class MetricContributionModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "metric_contributions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    observation_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("metric_observations.id", ondelete="CASCADE"), nullable=True, index=True)
    contribution_key: Mapped[str] = mapped_column(sa.String(400), nullable=False)
    """Workflow, step and the run's event (its correlation id) — one add per key."""
    amount: Mapped[float] = mapped_column(sa.Float, nullable=False)

    __table_args__ = (sa.UniqueConstraint("group_id", "contribution_key", name="uq_metric_contributions_key"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
