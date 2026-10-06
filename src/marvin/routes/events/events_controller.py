"""
This module defines the FastAPI controller that lists the event types a workspace
can subscribe to (webhooks, integration actions, email), with their data contracts.
"""

from fastapi import APIRouter

from marvin.routes._base import MarvinCrudRoute  # Custom route class for CRUD-like routes
from marvin.routes._base.base_controllers import BaseUserController  # Base controller for user-authenticated routes
from marvin.routes._base.controller import controller  # Decorator for class-based views

# All routes here will be under /event.
router = APIRouter(prefix="/event", route_class=MarvinCrudRoute)


@controller(router)
class EventTypesController(BaseUserController):
    """Lists subscribable event types. Requires user authentication."""

    @router.get("/types", summary="List subscribable event types with data contracts")
    def list_event_types(self) -> list[dict]:
        """
        Returns event types available for subscription with their data contracts —
        what variables each event provides for use in templates and notifications.
        Only returns events in the catalog (user-subscribable subset of all EventTypes).
        """
        # Only the workspace's own: platform events (sign-ups, workspaces, platform tokens, security, backups;
        # scope == "platform") belong to the admin Events page, so no workspace list or picker offers them.
        from marvin.services.events.event_catalog import CATALOG, CATEGORIES

        by_category: dict[str, list] = {c: [] for c in CATEGORIES}
        by_category["Other"] = []

        from marvin.services.events.payload_schemas import get_payload_example

        for entry in CATALOG:
            if not entry.enabled or entry.scope == "platform":
                continue  # internal/disabled events and the platform's own aren't offered to a workspace
            cat = entry.category if entry.category in by_category else "Other"
            by_category[cat].append(
                {
                    "value": entry.event_type,
                    "label": entry.name,
                    "description": entry.description,
                    "category": entry.category,
                    "enabled": entry.enabled,
                    "variables": [{"slug": v.slug, "description": v.description, "example": v.example, "type": v.type} for v in entry.variables],
                    "payloadExample": get_payload_example(entry.event_type),
                }
            )

        return [entry for cat in CATEGORIES for entry in by_category.get(cat, [])]
