"""``workflow_email_sends`` — the emails an Email step has sent, so the same send is never made twice.

An Email step (services/automation/actions/email.py) claims a row here, keyed on its run's event, its place in the
workflow and the person it writes to (or on the step's own ``once_per``), before it sends. The same event handled
twice, a retry and a run pressed again find the claim and send nothing; a send that fails gives the claim back, so a
retry can still send it. It holds who was written to and what for — never the message.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

__all__ = ["WorkflowEmailSendModel"]


class WorkflowEmailSendModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workflow_email_sends"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    send_key: Mapped[str] = mapped_column(sa.String(400), nullable=False)
    workflow_slug: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "send_key", name="uq_workflow_email_sends_key"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
