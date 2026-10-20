"""Which integration actions can carry an alert — for the alerts that go past the bell: Settings → Automation
→ Notifications (services/workspace_alerts.py) and Admin → Platform alerts (services/platform_alerts.py), both
through services/alerting.py.

Read from the provider's own metadata, never from a list of names (``message_actions``): an action declaring
the ``notify`` capability, or any action of a ``notify``-category provider, whose input schema has a string
body field. The alert goes into that field (and a title field when the action takes one); the action's other
inputs — a channel, a priority — are the route's arguments.
"""

from dataclasses import dataclass, field

from .social import SOCIAL_DELETE_COMMENT, SOCIAL_MESSAGE, SOCIAL_POST, SOCIAL_REPLY, SOCIAL_REPOST

MESSAGE_CAPABILITY = "notify"
"""The capability (and provider category) that says "this sends a message / notification"."""
GATED_CAPABILITIES = frozenset({SOCIAL_POST, SOCIAL_REPLY, SOCIAL_MESSAGE, SOCIAL_REPOST, SOCIAL_DELETE_COMMENT})
"""Capabilities that speak or destroy in public (post, reply, message, repost, delete a comment), so their actions always
need a person's approval. Capability routing (a step that
names the capability) skips an approval-gated action — nobody is there to approve an unattended run — except for these,
which it accepts once the run is past an Approval step (``approved``). Marvin treats every action declaring one as gated,
whether or not the plugin said ``requires_approval``."""
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


def capabilities_of(provider) -> set[str]:
    """The capabilities a provider offers to unattended callers (a workflow step): those its actions declare — an
    approval-gated action's only for a capability that is gated by design (``social.post`` and the engagement ones, usable after
    an Approval step) — and ``notify`` when it has a message action: what a recipe's ``{"capability": …}`` prerequisite is matched against."""
    found = {
        a.capability
        for a in getattr(provider, "actions", ()) or ()
        if getattr(a, "capability", None) and (a.capability in GATED_CAPABILITIES or not getattr(a, "requires_approval", False))
    }
    if any(not _needs_approval(provider, m.key) for m in message_actions(provider)):
        found.add(MESSAGE_CAPABILITY)
    return found


def capability_action(provider, capability: str, args: dict, *, approved: bool = False) -> tuple[str, dict] | None:
    """For a step that names a capability instead of an action: the provider's action for it and the step's
    arguments in that action's terms, or None when the provider has none. ``notify`` takes the standard ``title``
    and ``body`` and maps them onto the message action's own fields (Slack's ``text``, Apprise's ``body``…); any
    other argument passes through. Other capabilities pass the arguments as they are. An approval-gated action is
    skipped, except for a capability in ``GATED_CAPABILITIES`` when the run is ``approved`` (past an Approval step)."""
    if capability == MESSAGE_CAPABILITY:
        action = next((m for m in message_actions(provider) if not _needs_approval(provider, m.key)), None)
        if action is None:
            return None
        title, body = str(args.get("title") or ""), str(args.get("body") or "")
        rest = {k: v for k, v in args.items() if k not in ("title", "body")}
        carried = action.args(title, body) if title else {action.body_field: body}
        return action.key, {**rest, **carried}
    for declared in getattr(provider, "actions", ()) or ():
        if getattr(declared, "capability", None) == capability and (not needs_approval(declared) or (approved and capability in GATED_CAPABILITIES)):
            return declared.key, dict(args)
    return None


def needs_approval(action) -> bool:
    """Whether a person must approve a run before this provider action runs: it says so (``requires_approval``), or it
    declares a capability that publishes publicly (``GATED_CAPABILITIES``)."""
    return bool(getattr(action, "requires_approval", False) or getattr(action, "capability", None) in GATED_CAPABILITIES)


def _needs_approval(provider, key: str) -> bool:
    return any(getattr(a, "key", None) == key and needs_approval(a) for a in getattr(provider, "actions", ()) or ())
