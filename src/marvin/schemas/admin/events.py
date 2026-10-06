"""Schemas for the platform's Events page (admin: /api/admin/events): platform-scope events across workspaces."""

from datetime import datetime

from pydantic import UUID4

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.platform.event_connections import EventReaction, EventSender, EventTypeRef, WorkspaceEventReactions
from marvin.schemas.response.pagination import PaginationBase


class AdminEventSummary(_MarvinModel):
    """A platform event as the admin Events page lists it, with the names a super admin needs to read it."""

    event_id: UUID4
    event_type: str
    event_name: str
    """The catalog's display name for the type ("New User Signup")."""
    occurred_at: datetime
    message_title: str
    message_body: str | None = None
    workspace_id: UUID4 | None = None
    """The workspace the event was dispatched with (kept as context: the new user's workspace, the workspace
    created or switched to). None for an event with no workspace."""
    workspace_name: str | None = None
    workspace_slug: str | None = None
    user_id: UUID4 | None = None
    """Who the event is about: the user who acted or, when nobody signed in did (a sign-up), the account it
    names."""
    user_name: str | None = None
    user_email: str | None = None
    entity_id: UUID4 | None = None
    entity_type: str | None = None


class AdminEventRead(AdminEventSummary):
    """A platform event with its full payload."""

    integration_id: str
    correlation_id: str | None = None
    event_data: dict


class AdminEventPagination(PaginationBase):
    """One page of platform events, newest first."""

    items: list[AdminEventSummary]


class AdminEventType(_MarvinModel):
    """A platform-scope event type, for the Events page's filter."""

    event_type: str
    name: str
    description: str
    category: str


class AdminEventConnections(_MarvinModel):
    """A platform event type's story across the platform: what sends it, what happens (built in, plus each
    workspace's own subscriptions, grouped by workspace), and its newest events in any workspace."""

    event_type: str
    name: str
    description: str
    category: str
    senders: list[EventSender]
    reactions: list[EventReaction]
    """Built-in reactions and the system email template the type sends, if any."""
    workspaces: list[WorkspaceEventReactions]
    """Workspaces with their own reactions to it (workflows, integration actions, emails, webhooks)."""
    recent: list[AdminEventSummary]
    leads_to: list[EventTypeRef]
    caused_by: list[EventTypeRef]
