"""
The admin Events page's Events hub view (super admin): what sends a platform event type and what reacts to it.

Platform events (sign-ups, backups, …; `CatalogEntry.scope == "platform"`) aren't a workspace's, so the workspace
connections API leaves them out. Here: Marvin's own senders, the built-in reactions and system email, each
workspace's own subscriptions grouped by workspace, and the newest events across every workspace.
"""

from fastapi import APIRouter, HTTPException, Query, status

from marvin.routes._base import BaseAdminController, controller
from marvin.routes.admin.events_controller import summaries
from marvin.schemas.admin.events import AdminEventConnections

router = APIRouter(prefix="/event-types")


@controller(router)
class AdminEventConnectionsController(BaseAdminController):
    @router.get("/{event_type}/connections", response_model=AdminEventConnections, summary="What sends a platform event type and what reacts to it")
    def detail(self, event_type: str, limit: int = Query(10, ge=1, le=50)) -> AdminEventConnections:
        """A platform event type's senders, reactions (platform-wide, then by workspace) and newest `limit` events in
        any workspace. 404 for an unknown type or a workspace one (the workspace API has those)."""
        from marvin.services.events import connections
        from marvin.services.events.event_catalog import get_catalog_entry

        entry = get_catalog_entry(event_type)
        if entry is None or entry.scope != "platform":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Platform event type {event_type} not found.")
        senders, reactions, workspaces = connections.platform_detail(self.session, entry)
        rows, _ = self.repos.event_log.page_platform_events(event_type=event_type, page=1, per_page=limit)
        return AdminEventConnections(
            event_type=entry.event_type,
            name=entry.name,
            description=entry.description,
            category=entry.category,
            senders=senders,
            reactions=reactions,
            workspaces=workspaces,
            recent=summaries(self.session, rows),
            leads_to=connections.leads_to(event_type),
            caused_by=connections.caused_by(event_type),
        )
