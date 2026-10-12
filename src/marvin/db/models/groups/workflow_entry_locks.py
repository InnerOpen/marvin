"""``workflow_entry_locks`` — one workflow running on one entry at a time (services/automation/engine.py ``_entry_turn``).

Two runs of the same workflow on the same entry — a retry and a fresh run, the same event handled twice, a re-list
pressed again — must not interleave: both would read the entry as it was and act on it (Square listed a piece twice).
A run takes its turn by holding this row (``holder``) until ``lease_until``; the next one waits, then re-reads the
entry and re-checks the workflow's conditions. A lease that ran out (a crashed worker) is taken over.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

__all__ = ["WorkflowEntryLockModel"]


class WorkflowEntryLockModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workflow_entry_locks"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    automation_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="CASCADE"), nullable=False)
    entry_id: Mapped[GUID] = mapped_column(GUID, nullable=False)
    holder: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)

    __table_args__ = (sa.UniqueConstraint("automation_id", "entry_id", name="uq_workflow_entry_locks_turn"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
