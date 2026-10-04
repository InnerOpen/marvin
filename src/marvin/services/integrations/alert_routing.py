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
"""

from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
from marvin.db.models.groups.integrations import IntegrationModel

from .errors import NEEDED

TEMPLATE_TYPE = "integration_alert"

NOTIFY_ACTIONS: dict[str, dict] = {
    "send_message": {"text": "*{{title}}*\n{{summary}}"},
    "notify": {"title": "{{title}}", "body": "{{summary}}"},
}
"""Provider actions that can carry an alert, with the args each gets (filled from the alert event)."""


def _system_template_id(session):
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    row = (
        session.query(EmailTemplateModel.id).filter(EmailTemplateModel.group_id.is_(None), EmailTemplateModel.template_type == TEMPLATE_TYPE).first()
    )
    return row[0] if row else None


def _notify_action(provider_key: str) -> str | None:
    """The provider's alert-carrying action, if it has one (and is installed)."""
    try:
        from . import get_provider

        provider = get_provider(provider_key)
    except Exception:  # noqa: BLE001 — not installed: it can't carry alerts
        return None
    keys = {getattr(a, "key", None) for a in getattr(provider, "actions", ()) or ()}
    return next((action for action in NOTIFY_ACTIONS if action in keys), None)


def _targets(session, group_id) -> list[tuple[IntegrationModel, str]]:
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
            {"integration_id": row.id, "name": row.name, "provider": row.provider, "action": action, "enabled": (row.id, action) in enabled_subs}
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
        row = existing.get((integration_id, action))
        if row is not None:
            row.enabled = on
        elif on:
            session.add(
                IntegrationEventSubscriptionModel(
                    session=session,
                    group_id=group_id,
                    integration_id=integration_id,
                    event_type=NEEDED,
                    action=action,
                    args=dict(NOTIFY_ACTIONS[action]),
                    enabled=True,
                )
            )

    prefs = session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()
    if prefs is not None:
        prefs.integration_alert_reminder_hours = reminder_hours
    session.commit()
    return get_routing(session, group_id)
