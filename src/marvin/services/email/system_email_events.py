"""System template → event type mapping and virtual subscription.

Marvin's own emails a workspace template can replace. The password-reset email isn't one of them: its link is a live
credential for an account the workspace doesn't own, so it's always the platform's own template, sent by
PasswordResetService through the platform's own sender (a workspace template could carry the link anywhere — an
``<img src="…{{reset_url}}">`` leaks it without a click — and a workspace SMTP profile would relay it).
"""

from dataclasses import dataclass
from typing import Any

# Maps template_type → event settings for the system email templates a workspace may replace.
# The listener uses this to fire system templates without a stored subscription row.
SYSTEM_TEMPLATE_EVENT_MAP: dict[str, dict] = {
    "invitation": {
        "label": "invitation email",
        "event_type": "invitation_sent",
        "recipient_type": "event_field",
        "recipient_field": "email_address",
        # The link isn't in the event (any member reads an event's payload); the sender adds it.
        "link_variable": ("invitation_url", "Link for the recipient to accept the invite"),
    },
    "welcome": {
        "label": "welcome email",
        "event_type": "user_signup",
        "recipient_type": "event_field",
        "recipient_field": "email_address",
    },
}

SENT_DIRECTLY: frozenset[str] = frozenset({"invitation"})
"""System emails that carry a live link, so they're sent by the code that mints it (EmailService.send_invitation),
never through the event bus: the email listener leaves them out, and their event carries no link."""

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


def system_email_route(session, group_id, event_type: str) -> list[VirtualEmailSubscription] | None:
    """Marvin's own email for `event_type` in a workspace: the workspace's enabled connections of its own enabled
    template of the system type (they replace Marvin's), else Marvin's enabled system template. Always to the event's
    own address (the mapping's recipient), never to a connection's own recipients: replacing Marvin's email changes
    what it says, not who gets it. None when the event has no system email or nothing sends it (then the workspace's
    other subscriptions do, as services/events/connections.py `_runs` lists them)."""
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    template_type = get_template_type_for_event(event_type)
    if template_type is None:
        return None
    mapping = SYSTEM_TEMPLATE_EVENT_MAP[template_type]

    def route(template_id, sub_group_id=None, sub_id=None) -> VirtualEmailSubscription:
        return VirtualEmailSubscription(
            template_id=template_id,
            event_type=event_type,
            recipient_type=mapping["recipient_type"],
            recipient_field=mapping.get("recipient_field"),
            recipient_email=mapping.get("recipient_email"),
            group_id=sub_group_id,
            id=sub_id,
        )

    if group_id:
        connected = (
            session.query(EmailEventSubscriptionModel)
            .join(EmailTemplateModel, EmailTemplateModel.id == EmailEventSubscriptionModel.template_id)
            .filter(
                EmailEventSubscriptionModel.group_id == group_id,
                EmailEventSubscriptionModel.event_type == event_type,
                EmailEventSubscriptionModel.enabled.is_(True),
                EmailTemplateModel.group_id == group_id,
                EmailTemplateModel.template_type == template_type,
                EmailTemplateModel.enabled.is_(True),
            )
            .all()
        )
        if connected:
            return [route(sub.template_id, sub.group_id, sub.id) for sub in connected]

    system = (
        session.query(EmailTemplateModel).filter(EmailTemplateModel.group_id.is_(None), EmailTemplateModel.template_type == template_type).first()
    )
    if system is not None and system.enabled:
        return [route(system.id)]
    return None
