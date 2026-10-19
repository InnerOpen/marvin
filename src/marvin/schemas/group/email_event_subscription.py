"""Pydantic schemas for email event subscriptions."""

from datetime import datetime
from enum import Enum

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class RecipientType(str, Enum):
    event_field = "event_field"
    admins = "admins"
    specific = "specific"


class EmailEventSubscriptionCreate(_MarvinModel):
    group_id: UUID4 | None = None  # injected by controller from session
    template_id: UUID4
    event_type: str
    recipient_type: RecipientType = RecipientType.admins
    recipient_field: str | None = Field(None, description="Snake-case field name from event data, e.g. invitee_email")
    recipient_email: str | None = Field(None, description="Literal email address for recipient_type=specific")
    enabled: bool = True


class EmailEventSubscriptionRead(_MarvinModel):
    id: UUID4
    group_id: UUID4
    template_id: UUID4
    event_type: str
    recipient_type: RecipientType
    recipient_field: str | None
    recipient_email: str | None
    enabled: bool
    created_at: datetime
    update_at: datetime

    model_config = {"from_attributes": True}
