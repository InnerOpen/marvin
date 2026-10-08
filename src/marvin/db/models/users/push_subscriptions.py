"""``push_subscriptions`` — the browsers and phones a user turned Web Push on in (Profile → Notifications).

One row per push endpoint (a browser profile's subscription with a push service, unique across users: the
latest user to subscribe on a device owns it). ``p256dh``/``auth`` are the browser's keys the payload is
encrypted to. The sender (services/web_push.py) stamps ``last_used_at``/``last_success_at``, counts
consecutive failures in ``failure_count`` and deletes a row the push service says is gone (404/410).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .users import Users


class PushSubscriptionModel(SqlAlchemyBase, BaseMixins):
    """One device's Web Push subscription."""

    __tablename__ = "push_subscriptions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    user_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user: Mapped[Optional["Users"]] = orm.relationship("Users", back_populates="push_subscriptions")
    endpoint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """The push service URL messages are posted to."""
    p256dh: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    auth: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    label: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    """What the user calls the device ("Pixel 8 · Chrome"); defaults from the user agent."""
    last_used_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """The last time a message was sent to it, whatever came of it."""
    last_success_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    failure_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    """Failed sends since the last success."""

    __table_args__ = (sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
