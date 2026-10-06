"""Integration ⇄ event connections.

One row = "when ``event_type`` fires in this workspace, run integration ``integration_id``'s
``action`` with ``args``." This is the same subscribe-to-an-event pattern webhooks, notifications,
and email templates use — the event bus fans out to an IntegrationEventListener that runs these.
"""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID
from .._model_utils.installed_by import InstalledByMixin

if TYPE_CHECKING:
    from .groups import Groups
    from .integrations import IntegrationModel


class IntegrationEventSubscriptionModel(SqlAlchemyBase, BaseMixins, InstalledByMixin):
    """Binds an integration action to an event type."""

    __tablename__ = "integration_event_subscriptions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = relationship("Groups", back_populates="integration_event_subscriptions", single_parent=True)

    integration_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    integration: Mapped[Optional["IntegrationModel"]] = relationship("IntegrationModel", foreign_keys=[integration_id])

    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """The event name this connection fires on (e.g. 'entry-published')."""

    action: Mapped[str] = mapped_column(String, nullable=False)
    """Which provider action to run (e.g. 'send_message')."""

    args: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """Action arguments, may contain {{field}} placeholders filled from the event."""

    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
