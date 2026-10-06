"""Schemas for the Events hub: what sends an event type and what reacts to it, in one workspace
(services/events/connections.py). Read-only; nothing here carries a URL, header, token, args or address."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.platform.event_log import EventLogSummary

ReactionKind = Literal["workflow", "integration_action", "email", "webhook", "builtin"]
SenderKind = Literal["marvin", "workflow", "incoming_webhook", "scheduled_task"]


class InstalledBy(_MarvinModel):
    """The integration whose blueprint created a workflow, task, incoming webhook or integration action."""

    integration_id: UUID4
    name: str
    provider: str
    blueprint: str | None = None


class EventReaction(_MarvinModel):
    """One thing that runs when the event happens."""

    kind: ReactionKind
    id: UUID4 | None = None
    """The workflow, integration action subscription, email subscription (or system template) or outgoing webhook.
    None for a built-in reaction."""
    name: str
    enabled: bool
    """Whether the event bus runs it now. A switched-off one is listed too, as False."""
    detail: str | None = None
    """What it does or listens to beyond the type: an integration's action, who an email goes to, a workflow's
    target (the incoming webhook slug, or the workflow a chained / on-error trigger waits for)."""
    trigger_type: str | None = None
    """A workflow's trigger type (event, incoming_webhook, chained, on_error)."""
    managed_at: str | None = None
    """The admin page where it's edited."""
    installed_by: InstalledBy | None = None


class EventSender(_MarvinModel):
    """One thing that sends the event: Marvin itself (a line from the catalog) or a row in this workspace."""

    kind: SenderKind
    id: UUID4 | None = None
    name: str
    enabled: bool
    detail: str | None = None
    """Which step or task sends it ("Emit event step", "Entry step: publish", "Request Site Rebuild task")."""
    via_workflow_id: UUID4 | None = None
    """For an incoming webhook: the workflow it starts, which sends the event."""
    via_workflow_name: str | None = None
    managed_at: str | None = None
    installed_by: InstalledBy | None = None


class EventTypeRef(_MarvinModel):
    event_type: str
    name: str


class EventConnections(_MarvinModel):
    """An event type's whole story in one workspace: what sends it, what happens, and when it last did."""

    event_type: str
    name: str
    description: str
    category: str
    senders: list[EventSender]
    reactions: list[EventReaction]
    audited: bool
    """Whether this workspace's Event Log records the type: when False, an empty `recent` means "not recorded",
    not "never happened"."""
    recent: list[EventLogSummary]
    """The newest Event Log rows of this type, newest first."""
    leads_to: list[EventTypeRef]
    """Event types this one causes through Marvin's own code (catalog)."""
    caused_by: list[EventTypeRef]
    """Event types that cause this one (the catalog's `leads_to`, reversed)."""


class EventConnectionCounts(_MarvinModel):
    """One row of the Events catalog: how connected an event type is, in both directions."""

    event_type: str
    senders: int
    """Marvin's own senders plus the workspace's workflows, incoming webhooks and scheduled tasks that send it."""
    reactions: int
    """Workflows, integration actions, emails and webhooks on it, switched-off ones included."""
    active_reactions: int
    """Those of `reactions` the event bus runs now."""
    builtin_reactions: int
    last_occurred_at: datetime | None = None
    """When the workspace's Event Log last recorded one."""


class WorkspaceEventReactions(_MarvinModel):
    workspace_id: UUID4
    workspace_name: str | None = None
    workspace_slug: str | None = None
    reactions: list[EventReaction]
