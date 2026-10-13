"""Database model for email event subscriptions."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column, validates

from marvin.db.models import BaseMixins, SqlAlchemyBase
from marvin.db.models._model_utils.auto_init import auto_init
from marvin.db.models._model_utils.guid import GUID


class EmailEventSubscriptionModel(SqlAlchemyBase, BaseMixins):
    """Links an email template to an event type for a workspace.

    Each row means: when `event_type` fires in `group_id`, render `template_id`
    and send to the resolved recipient.
    """

    __tablename__ = "email_event_subscriptions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)

    group_id: Mapped[GUID] = mapped_column(
        GUID,
        sa.ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[GUID] = mapped_column(
        GUID,
        sa.ForeignKey("email_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)

    # "event_field" → pull address from event data field named recipient_field
    # "admins"      → send to all workspace admin users
    # "specific"    → send to literal address in recipient_email
    recipient_type: Mapped[str] = mapped_column(sa.String, nullable=False, default="admins")
    recipient_field: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    @validates("event_type")
    def _canonical_event_type(self, _key: str, value: str) -> str:
        """An old event name is stored as the event it stands for (site_build_* → site_deployment_*)."""
        from marvin.services.events.event_catalog import canonical_event_type

        return canonical_event_type(value) if value else value

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
