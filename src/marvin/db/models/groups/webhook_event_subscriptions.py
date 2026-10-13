"""Outgoing webhook ⇄ event connections.

One row = "when ``event_type`` fires in the webhook's workspace, POST to webhook ``webhook_id``" —
the same shape as ``email_event_subscriptions`` and ``integration_event_subscriptions``, so "what
reacts to event X" is one query across all three. Only event-driven webhooks act on these rows.
The webhook API still reads and writes the list as ``subscribedEvents``
(``GroupWebhooksModel.subscribed_events``).
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.guid import GUID


class WebhookEventSubscriptionModel(SqlAlchemyBase, BaseMixins):
    """Binds an outgoing webhook to an event type. Built through the webhook's ``subscribed_events``
    (plain keyword constructor — the setter has no session to hand to auto_init)."""

    __tablename__ = "webhook_event_subscriptions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    webhook_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("webhook_urls.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    """The event name this webhook fires on (e.g. 'webhook_triggered')."""

    __table_args__ = (sa.UniqueConstraint("webhook_id", "event_type", name="uq_webhook_event_subscriptions_webhook_event"),)
