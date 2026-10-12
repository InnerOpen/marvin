"""``push_action_tokens`` — the one-tap Approve / Deny an approval push carries (services/push_actions.py).

One row per approval push: the token itself is never stored, only its SHA-256 (``token_hash``). It decides
exactly one approval — an AI run's park (``thread_id`` and the park it was minted for, ``parked_at``) or a waiting
workflow run (``workflow_approval_id``) — for exactly one user,
once (``used_at``), until ``expires_at``. Deleted with the user or the thread; expired rows are swept when the
next one is minted.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class PushActionTokenModel(SqlAlchemyBase, BaseMixins):
    """A single-use, short-lived token to approve or deny one parked AI approval from its notification."""

    __tablename__ = "push_action_tokens"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    user_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("ai_threads.id", ondelete="CASCADE"), nullable=True, index=True)
    """The root conversation an AI approval is decided on (the push's approval id) — or None for a workflow's."""
    workflow_approval_id: Mapped[GUID | None] = mapped_column(
        GUID, sa.ForeignKey("workflow_approvals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    """The waiting workflow run it decides (services/automation/approvals.py) — set instead of ``thread_id``."""
    parked_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """The park it was minted for (``pending_json.parked_at``): a later park of the same thread is another approval."""
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)

    __table_args__ = (sa.UniqueConstraint("token_hash", name="uq_push_action_tokens_token_hash"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
