"""System email template → event type mapping and virtual subscription."""

from dataclasses import dataclass
from typing import Any

# Maps template_type → event settings for the 3 system email templates.
# The listener uses this to fire system templates without a stored subscription row.
SYSTEM_TEMPLATE_EVENT_MAP: dict[str, dict] = {
    "invitation": {
        "label": "invitation email",
        "event_type": "invitation_sent",
        "recipient_type": "event_field",
        "recipient_field": "email_address",
    },
    "password_reset": {
        "label": "password reset email",
        "event_type": "user_password_reset_requested",
        "recipient_type": "event_field",
        "recipient_field": "email_address",
    },
    "welcome": {
        "label": "welcome email",
        "event_type": "user_signup",
        "recipient_type": "event_field",
        "recipient_field": "email_address",
    },
}

# Reverse lookup: event_type → template_type
_EVENT_TO_TEMPLATE_TYPE: dict[str, str] = {v["event_type"]: k for k, v in SYSTEM_TEMPLATE_EVENT_MAP.items()}


def get_template_type_for_event(event_type_name: str) -> str | None:
    """Return the system template_type for a given event type name, or None."""
    return _EVENT_TO_TEMPLATE_TYPE.get(event_type_name)


@dataclass
class VirtualEmailSubscription:
    """System template subscription — not stored in DB, created at listener time."""

    template_id: Any
    event_type: str
    recipient_type: str
    recipient_field: str | None = None
    recipient_email: str | None = None
    group_id: Any = None
    enabled: bool = True
    id: Any = None
