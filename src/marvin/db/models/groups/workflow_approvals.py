"""``workflow_approvals`` — a workflow run waiting at an Approval step (services/automation/approvals.py).

The run parks at the step: everything it needs to go on is kept here (``snapshot``: the event, the entry, the earlier
steps' outputs, the target row), the run's execution ends ``waiting``, and approvers at ``min_role`` are told. A
decision — approve or deny by a person, or ``expired`` by the hourly sweep — resumes the run from the next step in a
new execution (``resumed_execution_id``) with ``steps.<id>.output.decision``. ``entry_version`` is the entry's
``update_at`` when it parked: an approval of an entry that has changed since becomes ``stale``, so nothing a person
approved is applied to content they didn't see.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

__all__ = ["APPROVAL_STATUSES", "APPROVAL_PENDING", "WorkflowApprovalModel"]

APPROVAL_PENDING = "pending"
APPROVAL_STATUSES = (APPROVAL_PENDING, "approved", "denied", "expired", "stale")


class WorkflowApprovalModel(SqlAlchemyBase, BaseMixins):
    """One workflow run waiting for (or decided by) a person at an Approval step."""

    __tablename__ = "workflow_approvals"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True)
    """The run that parked."""
    resumed_execution_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True)
    """The run that went on after the decision."""
    step_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    step_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    target_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    min_role: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    """Who may decide: a member at this workspace role or above (services/ai/operations/base ROLE_*)."""
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=APPROVAL_PENDING, index=True)
    snapshot: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    entry_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True, index=True)
    entry_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)
    decided_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # An approval with choices: what was offered (labels), and the one picked on approval.
    choices: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    choice: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
