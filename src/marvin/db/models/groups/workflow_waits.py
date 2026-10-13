"""``workflow_waits`` — a workflow run waiting at a Wait step until a time (services/automation/waits.py).

The run parks at the step as it does at an Approval step: everything it needs to go on is kept here (``snapshot``: the
event, the entry, the run's inputs, the earlier steps' outputs, the target row), its execution ends ``waiting``, and the
minutely sweep resumes it from the next step at ``resume_at`` in a new execution (``resumed_execution_id``). Status:
waiting, resumed, or cancelled (the workflow was switched off or its Wait step removed, or its entry went to the Trash meanwhile).
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

__all__ = ["WAIT_STATUSES", "WAIT_WAITING", "WorkflowWaitModel"]

WAIT_WAITING = "waiting"
WAIT_STATUSES = (WAIT_WAITING, "resumed", "cancelled")


class WorkflowWaitModel(SqlAlchemyBase, BaseMixins):
    """One workflow run waiting (or done waiting) at a Wait step."""

    __tablename__ = "workflow_waits"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True)
    """The run that parked."""
    resumed_execution_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True)
    """The run that went on at resume_at."""
    step_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    step_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    target_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    resume_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=WAIT_WAITING, index=True)
    snapshot: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    entry_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Why it didn't go on (cancelled)."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
