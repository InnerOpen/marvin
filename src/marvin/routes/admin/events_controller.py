"""
The platform's Events page (super admin): platform-scope events across every workspace.

Platform events (sign-ups, workspaces created, edited or deleted by a platform admin, a user switching workspace,
personal tokens, platform security signals and backups; `CatalogEntry.scope == "platform"`) are stored with the
workspace they touched, like any event, but a workspace's Event Log leaves them out. This is where they're read.
"""

import math
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import UUID4

from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.users.users import Users
from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.events import AdminEventPagination, AdminEventRead, AdminEventSummary, AdminEventType
from marvin.services.events.event_catalog import CATALOG, CATEGORIES, get_catalog_entry, is_platform_event

router = APIRouter(prefix="/events")

MAX_PER_PAGE = 100


def _document(event_data) -> dict:
    doc = (event_data or {}).get("documentData") or (event_data or {}).get("document_data") or {}
    return doc if isinstance(doc, dict) else {}


def _subject_user_id(row: EventLogModel):
    """Who the event is about: whoever acted, else the account it names (a sign-up has no signed-in user)."""
    if row.user_id:
        return row.user_id
    return row.entity_id if row.entity_type == "user" else None


@controller(router)
class AdminEventsController(BaseAdminController):
    def _summaries(self, rows: list[EventLogModel], schema=AdminEventSummary) -> list:
        """The rows with their catalog name, workspace and user filled in: two lookups for the page, not per row."""
        group_ids = {r.workspace_id for r in rows if r.workspace_id}
        user_ids = {uid for r in rows if (uid := _subject_user_id(r))}
        groups = {g.id: g for g in self.session.query(Groups).filter(Groups.id.in_(group_ids)).all()} if group_ids else {}
        users = {u.id: u for u in self.session.query(Users).filter(Users.id.in_(user_ids)).all()} if user_ids else {}

        out = []
        for row in rows:
            entry = get_catalog_entry(row.event_type)
            group = groups.get(row.workspace_id)
            uid = _subject_user_id(row)
            user = users.get(uid)
            doc = _document(row.event_data)
            # A password reset names its account only in the payload.
            fallback_name = doc.get("username")
            fallback_email = doc.get("email")
            data = {
                "event_id": row.event_id,
                "event_type": row.event_type,
                "event_name": entry.name if entry else row.event_type,
                "occurred_at": row.occurred_at,
                "message_title": row.message_title,
                "message_body": row.message_body,
                "workspace_id": row.workspace_id,
                "workspace_name": group.name if group else None,
                "workspace_slug": group.slug if group else None,
                "user_id": uid,
                "user_name": (user.full_name or user.username) if user else (str(fallback_name) if fallback_name else None),
                "user_email": user.email if user else (str(fallback_email) if fallback_email else None),
                "entity_id": row.entity_id,
                "entity_type": row.entity_type,
            }
            if schema is AdminEventRead:
                data |= {"integration_id": row.integration_id, "correlation_id": row.correlation_id, "event_data": row.event_data or {}}
            out.append(schema.model_validate(data))
        return out

    @router.get("", response_model=AdminEventPagination, summary="List platform events")
    def list_events(
        self,
        event_type: str | None = None,
        workspace_id: UUID4 | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=MAX_PER_PAGE),
    ) -> AdminEventPagination:
        """Platform events across every workspace, newest first. Filter by type, workspace and date range (UTC).
        A type that isn't a platform event matches nothing."""
        rows, total = self.repos.event_log.page_platform_events(
            event_type=event_type,
            workspace_id=workspace_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )
        return AdminEventPagination(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=math.ceil(total / per_page) if total else 0,
            items=self._summaries(rows),
        )

    @router.get("/catalog", response_model=list[AdminEventType], summary="List platform event types")
    def list_event_types(self) -> list[AdminEventType]:
        """Every platform-scope event type, in category display order, for the Events page's filter."""

        def rank(category: str) -> int:
            return CATEGORIES.index(category) if category in CATEGORIES else len(CATEGORIES)

        entries = sorted((e for e in CATALOG if e.scope == "platform"), key=lambda e: rank(e.category))
        return [AdminEventType(event_type=e.event_type, name=e.name, description=e.description, category=e.category) for e in entries]

    @router.get("/{event_id}", response_model=AdminEventRead, summary="Get a platform event")
    def get_event(self, event_id: UUID4) -> AdminEventRead:
        """One platform event with its full payload. A workspace event is a 404 here: it's in its workspace's log."""
        row = self.session.query(EventLogModel).filter(EventLogModel.event_id == event_id).first()
        if row is None or not is_platform_event(row.event_type):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Platform event {event_id} not found.")
        return self._summaries([row], schema=AdminEventRead)[0]
