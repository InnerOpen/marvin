"""
The Events hub's reads: what sends each event type and what reacts to it, in the current workspace
(services/events/connections.py).

Workspace OWNER/ADMIN only, like the Events catalog page these feed: they name the workspace's workflows,
webhooks, email subscriptions and integration actions, which only admins can list. Platform-scope event types
aren't a workspace's (404 here); the admin Events page has their view (/api/admin/event-types/…).
"""

from fastapi import APIRouter, HTTPException, Query, status

from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.platform.event_connections import EventConnectionCounts, EventConnections

router = APIRouter(prefix="/event-types")


@controller(router)
class EventConnectionsController(BaseUserController):
    def _visible(self):
        """The caller's view of the Event Log (other members' AI runs are hidden below ADMIN)."""
        from marvin.services.ai.executions import user_sees_every_run, visible_events_clause

        return visible_events_clause(sees_all=user_sees_every_run(self.user, self.group_id), user_id=self.user.id)

    @router.get("/connections", response_model=list[EventConnectionCounts], summary="How connected each event type is")
    def summary(self) -> list[EventConnectionCounts]:
        """Every workspace event type, in catalog order: how many things send it and react to it, and when the
        Event Log last recorded one."""
        from marvin.services.events import connections

        require_workspace_admin(self.user, self.group_id)
        return connections.summary(self.session, self.group_id, visible=self._visible())

    @router.get("/{event_type}/connections", response_model=EventConnections, summary="What sends an event type and what reacts to it")
    def detail(self, event_type: str, limit: int = Query(10, ge=1, le=50)) -> EventConnections:
        """One event type: what sends it (Marvin itself, workflows, incoming webhooks, scheduled tasks), what
        happens (workflows, integration actions, emails, webhooks — switched-off ones too — and the built-in
        reactions), its newest `limit` events and the chain it's part of. 404 for an unknown or platform type."""
        from marvin.services.events import connections

        require_workspace_admin(self.user, self.group_id)
        entry = connections.workspace_entry(event_type)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event type {event_type} not found.")
        return connections.detail(self.session, self.group_id, entry, limit=limit, visible=self._visible())
