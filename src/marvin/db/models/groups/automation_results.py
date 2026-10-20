"""``automation_results`` — what happened to the work Marvin handed to another system (Settings › Automation › Results;
services/automation_results.py).

One row per hand-off. An integration action that declares ``hands_off`` (marvin_integration_sdk.HandsOff) starts work somewhere
else and returns once it has *started*; the engine writes the row ``in_flight`` when the step succeeds and ``failed`` when the
call itself fails. The other side reports back, and the ``automation_result`` workflow step settles the row (by the run's id on
the other side, else the newest one in flight for that entry and connection); a report that matches no row is kept as a fresh
one rather than dropped. The words are Marvin's: the provider maps its own (``IntegrationProvider.result_status``).

``status`` is in_flight | succeeded | failed. A row still in flight 24 hours after it was sent shows as **No reply**: that is
computed from ``sent_at`` (services/automation_results.py), not a status, so a late reply still settles it normally.

``integration_id`` and ``entry_id`` are empty when a hand-off isn't about an entry, or a report names no known connection. The
row goes with the workspace, the connection and the entry. A daily system task (``prune_automation_results``) drops settled
rows after 30 days and unhandled ones (in flight, or failed and not dismissed) after 180.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import AwareDateTime
from .._model_utils.guid import GUID

__all__ = ["AutomationResultModel"]


class AutomationResultModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "automation_results"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("entries.id", ondelete="CASCADE"), nullable=True, index=True)
    """The entry the work was about; empty when a hand-off isn't about one."""
    integration_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True, index=True)
    """The connection the work went through; empty for a result no known connection reported."""
    workflow_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="SET NULL"), nullable=True)
    """The Marvin workflow whose step handed it off; empty for a result that arrived unannounced, and once that workflow is deleted."""
    action: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The provider action that handed it off (``trigger_workflow``); what Retry looks for in the workflow."""
    target: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """What was asked of the other side, as the provider names it (an n8n workflow's path)."""
    remote_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The run's id on the other side; what a reply settles the row by."""
    remote_url: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="in_flight", server_default="in_flight")
    """in_flight | succeeded | failed."""
    message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(AwareDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """When the other side finished (its own time when it said, else when Marvin heard); empty while in flight."""
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1, server_default="1")
    """1 for the first hand-off; a retry (the error policy's or a person's Retry) of the same one counts up."""
    dismissed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    """A failure a person has dealt with: it no longer asks for attention (and is pruned after 30 days like a settled one)."""
    dismissed_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        sa.Index("ix_automation_results_group_status", "group_id", "status"),
        sa.Index("ix_automation_results_group_sent", "group_id", "sent_at"),
        sa.Index("ix_automation_results_remote", "integration_id", "remote_id"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
