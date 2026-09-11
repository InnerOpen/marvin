"""SQLAlchemy model for per-workspace *incoming* webhooks (ingress event source).

Where `GroupWebhooksModel` sends data OUT to an external URL, an incoming webhook is the mirror:
an external system POSTs to a tokened Marvin URL, and the receiver drops an `incoming_webhook`
event onto the event bus carrying the request payload. Whatever is subscribed — user-configured
automations, Flavor A reaction listeners, the audit log — then reacts. The webhook itself is a
dumb, reusable ingress; it is not bound to any one automation (many can react to the same webhook).

The `token` is the credential: no login/session. It is minted explicitly by an admin (null until
then), rotatable, and revocable. The receiver looks the webhook up by this unique token.
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


class WorkspaceIncomingWebhookModel(SqlAlchemyBase, BaseMixins):
    """A tokened ingress endpoint. A POST to its URL emits an `incoming_webhook` event.

    Deny-by-default: an incoming webhook only accepts requests when `enabled` is true AND a `token`
    has been minted. Managed by ADMIN/OWNER. Automations reference it by `slug` in a trigger.
    """

    __tablename__ = "workspace_incoming_webhooks"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="incoming_webhooks")

    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    # The secret credential. Null = no access minted yet. Unique so the receiver can resolve by it.
    token: Mapped[str | None] = mapped_column(sa.String, nullable=True, unique=True, index=True)

    # Optional HMAC verification: when `signing_secret_ref` names a workspace secret, every request must
    # carry `<signature_header>: sha256=<hex HMAC-SHA256 of the raw body>` computed with that secret
    # (the Buttondown / GitHub / Stripe-style scheme). The URL token alone stays the credential otherwise.
    signing_secret_ref: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    signature_header: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    # Observability — surfaced in the management UI so an admin can confirm deliveries land.
    received_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_incoming_webhooks_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
