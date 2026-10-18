"""``workflow_step_idempotency`` — the calls a webhook or integration step has made under an ``idempotency_key``.

A step with an ``idempotency_key`` (services/automation/idempotency.py) claims a row here before it calls out, keyed on
its workflow, where it calls and the key's resolved text. The same key again within the window finds the row and calls
nothing: it reuses the recorded ``output``. A call that fails gives the claim back, so a retry still makes it. A claim
that is never completed (a crashed worker) runs out on its own. It holds a hash of the key, never the key's text.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

__all__ = ["IDEMPOTENCY_CLAIMED", "IDEMPOTENCY_DONE", "WorkflowStepIdempotencyModel"]

IDEMPOTENCY_CLAIMED = "claimed"
IDEMPOTENCY_DONE = "done"


class WorkflowStepIdempotencyModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workflow_step_idempotency"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """sha256 of the workflow, the destination and the key's text."""
    workflow_slug: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    destination: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    """Where the step calls: ``webhook:<id or url>`` or ``integration:<slug>.<action>`` — to read the table by."""
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=IDEMPOTENCY_CLAIMED)
    output: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """What the call returned, reused by a duplicate (None for a claim in flight, or an output too large to keep)."""
    expires_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)
    """A claim in flight: when it may be taken over. A completed call: the end of its window."""

    __table_args__ = (sa.UniqueConstraint("group_id", "key_hash", name="uq_workflow_step_idempotency_key"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
