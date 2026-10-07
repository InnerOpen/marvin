"""Where integration alerts go — the "Integration alerts" panel on Settings → Integrations.

The bell always gets ``integration_attention_needed`` / ``_resolved`` (they are audited events). Beyond
that the panel writes ordinary subscription rows for ``integration_attention_needed``, the same rows
the Events page manages:

  * email to the workspace's owners and admins — an ``email_event_subscriptions`` row pointing at the
    "Integration Alert" system template;
  * a chat / notification connection — an ``integration_event_subscriptions`` row running its
    ``send_message`` (Slack) or ``notify`` (Apprise) action with the alert's ready-made text.

Turning a route off disables its row instead of deleting it: an alert that is still open records the
rows it went out through, and its "resolved" notice goes back through them (see
``errors.resolved_channel_rows``). No row is written for the resolved event itself.

Which actions can carry an alert is read from the provider's own metadata, never from a list of names
(``message_actions``): an action declaring the ``notify`` capability, or any action of a ``notify``-category
provider, whose input schema has a string body field. Platform alerts (services/platform_alerts.py) use
the same discovery and the same argument shape.
"""

from dataclasses import dataclass, field

from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
from marvin.db.models.groups.integrations import IntegrationModel

from .errors import NEEDED

TEMPLATE_TYPE = "integration_alert"

MESSAGE_CAPABILITY = "notify"
"""The capability (and provider category) that says "this sends a message / notification"."""
BODY_FIELDS = ("text", "body", "message", "content")
"""Input names, in preference order, that carry a message's text."""
TITLE_FIELDS = ("title", "subject")
"""Input names that carry its title, when the action takes one separately."""


@dataclass(frozen=True)
class MessageAction:
    """A provider action that can carry an alert, and where the alert goes in its input."""

    key: str
    label: str
    body_field: str
    title_field: str | None = None
    inputs: dict = field(default_factory=dict)
    """The action's other inputs (JSON-schema properties) — a channel, a priority — filled by whoever routes to it."""
    required: tuple[str, ...] = ()
    """Which of ``inputs`` the action requires."""

    def args(self, title: str, body: str) -> dict:
        """The alert as this action's arguments: title and body apart when it takes both, else one text."""
        if self.title_field:
            return {self.title_field: title, self.body_field: body}
        return {self.body_field: f"*{title}*\n{body}"}


def _string_field(props: dict, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in props and (props[name] or {}).get("type", "string") == "string"), None)


def message_actions(provider) -> list[MessageAction]:
    """The provider's actions that can carry a message, in the order it declares them: those declaring the
    ``notify`` capability, or any action of a ``notify``-category provider, with a string body input."""
    notify_provider = getattr(provider, "category", None) == MESSAGE_CAPABILITY
    found: list[MessageAction] = []
    for action in getattr(provider, "actions", ()) or ():
        if not (notify_provider or getattr(action, "capability", None) == MESSAGE_CAPABILITY):
            continue
        schema = getattr(action, "input_schema", None) or {}
        props = schema.get("properties") or {}
        body = _string_field(props, BODY_FIELDS)
        if body is None:
            continue
        title = _string_field(props, TITLE_FIELDS)
        carried = {body, title}
        inputs = {k: v for k, v in props.items() if k not in carried}
        required = tuple(k for k in schema.get("required") or () if k in inputs)
        found.append(MessageAction(key=action.key, label=action.label, body_field=body, title_field=title, inputs=inputs, required=required))
    return found


def _template_args(action: MessageAction) -> dict:
    """A workspace alert's subscription args: the alert event's title and summary as ``{{placeholders}}``."""
    return action.args("{{title}}", "{{summary}}")


def _system_template_id(session):
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    row = (
        session.query(EmailTemplateModel.id).filter(EmailTemplateModel.group_id.is_(None), EmailTemplateModel.template_type == TEMPLATE_TYPE).first()
    )
    return row[0] if row else None


def _notify_action(provider_key: str) -> MessageAction | None:
    """The provider's first alert-carrying action needing nothing but the message, if it has one (and is
    installed). A workspace route has no other arguments to give it."""
    try:
        from . import get_provider

        provider = get_provider(provider_key)
    except Exception:  # noqa: BLE001 — not installed: it can't carry alerts
        return None
    return next((action for action in message_actions(provider) if not action.required), None)


def _targets(session, group_id) -> list[tuple[IntegrationModel, MessageAction]]:
    rows = session.query(IntegrationModel).filter_by(group_id=group_id, enabled=True).order_by(IntegrationModel.name).all()
    return [(row, action) for row in rows if (action := _notify_action(row.provider))]


def _email_rows(session, group_id, template_id) -> list:
    if template_id is None:
        return []
    return session.query(EmailEventSubscriptionModel).filter_by(group_id=group_id, event_type=NEEDED, template_id=template_id).all()


def get_routing(session, group_id) -> dict:
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()
    enabled_subs = {
        (row.integration_id, row.action)
        for row in session.query(IntegrationEventSubscriptionModel).filter_by(group_id=group_id, event_type=NEEDED, enabled=True).all()
    }
    return {
        "email_admins": any(row.enabled for row in _email_rows(session, group_id, _system_template_id(session))),
        "targets": [
            {
                "integration_id": row.id,
                "name": row.name,
                "provider": row.provider,
                "action": action.key,
                "enabled": (row.id, action.key) in enabled_subs,
            }
            for row, action in _targets(session, group_id)
        ],
        "reminder_hours": getattr(prefs, "integration_alert_reminder_hours", 24) if prefs is not None else 24,
    }


def set_routing(session, group_id, *, email_admins: bool, integration_ids: list, reminder_hours: int) -> dict:
    """Write the routing: enable/disable (or create) the subscription rows, and the reminder window.
    Raises ValueError for a connection that can't carry alerts."""
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    targets = {row.id: action for row, action in _targets(session, group_id)}
    wanted = {str(i) for i in integration_ids}
    unknown = wanted - {str(i) for i in targets}
    if unknown:
        raise ValueError(f"These connections can't carry alerts: {', '.join(sorted(unknown))}")

    template_id = _system_template_id(session)
    if email_admins and template_id is None:
        raise ValueError("The Integration Alert email template is missing; restart Marvin to seed it.")
    email_rows = _email_rows(session, group_id, template_id)
    for row in email_rows:
        row.enabled = email_admins and row.recipient_type == "admins"
    if email_admins and not any(row.recipient_type == "admins" for row in email_rows):
        session.add(
            EmailEventSubscriptionModel(
                session=session, group_id=group_id, template_id=template_id, event_type=NEEDED, recipient_type="admins", enabled=True
            )
        )

    existing = {
        (row.integration_id, row.action): row
        for row in session.query(IntegrationEventSubscriptionModel).filter_by(group_id=group_id, event_type=NEEDED).all()
    }
    for integration_id, action in targets.items():
        on = str(integration_id) in wanted
        row = existing.get((integration_id, action.key))
        if row is not None:
            row.enabled = on
        elif on:
            session.add(
                IntegrationEventSubscriptionModel(
                    session=session,
                    group_id=group_id,
                    integration_id=integration_id,
                    event_type=NEEDED,
                    action=action.key,
                    args=_template_args(action),
                    enabled=True,
                )
            )

    prefs = session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()
    if prefs is not None:
        prefs.integration_alert_reminder_hours = reminder_hours
    session.commit()
    return get_routing(session, group_id)
