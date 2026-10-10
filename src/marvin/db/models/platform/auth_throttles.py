"""Failed sign-ins (and password-reset requests) counted per account name and per client IP.

One row per (scope, key): how many failures since the window opened, and — once there are too many —
until when that key is refused. Keyed by the name typed, not a user id, so an account that doesn't
exist is throttled exactly like one that does (the answer never reveals which). See
services/security/login_throttle.py.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class AuthThrottleModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "auth_throttles"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    scope: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    """What is counted: "login:account", "login:ip", "reset:email" or "reset:ip"."""
    key: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    """The account name typed (lowercased), the email, or the client IP."""
    count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")
    window_start: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)

    __table_args__ = (sa.UniqueConstraint("scope", "key", name="uq_auth_throttles_scope_key"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
