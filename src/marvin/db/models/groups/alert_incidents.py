"""``workspace_alert_incidents`` — what keeps a workspace's notifications to one per incident.

A workflow or scheduled task that keeps failing sends one alert, not one per run: its first failure opens
a row (``key`` = ``automation:<id>`` / ``scheduled_task:<id>``, unique per workspace, so two failures at once
open it once), later failures only count on it, and its next success deletes it and sends one "working
again" note through ``channels`` — the channels the alert went out through, whatever the settings say by
then. Integration alerts keep their own incidents (``integration_alerts``). See services/workspace_alerts.py.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import DateTime
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class WorkspaceAlertIncidentModel(SqlAlchemyBase, BaseMixins):
    """An open incident: something failing that has alerted once and will send a note when it works again."""

    __tablename__ = "workspace_alert_incidents"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups")
    key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    """What is failing: ``automation:<id>`` or ``scheduled_task:<id>``."""
    kind: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """The alert kind that opened it (``workflow_failed`` …)."""
    subject: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Its name when it failed, for the "working again" note."""
    count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channels: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    """The channels the alert went out through (``email``, route ids)."""

    __table_args__ = (sa.UniqueConstraint("group_id", "key", name="uq_workspace_alert_incidents_key"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
