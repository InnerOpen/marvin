"""Which integration actions can carry an alert — for the alerts that go past the bell: Settings → Automation
→ Notifications (services/workspace_alerts.py) and Admin → Platform alerts (services/platform_alerts.py), both
through services/alerting.py.

Read from the provider's own metadata, never from a list of names (``message_actions``): an action declaring
the ``notify`` capability, or any action of a ``notify``-category provider, whose input schema has a string
body field. The alert goes into that field (and a title field when the action takes one); the action's other
inputs — a channel, a priority — are the route's arguments.
"""

from dataclasses import dataclass, field

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
