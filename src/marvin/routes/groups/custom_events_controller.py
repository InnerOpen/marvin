"""
A workspace's own events: register `custom.<name>` events with the fields their payload carries.

Registered events are sent by a workflow's Emit event step, started on by a workflow's event trigger and named by
webhook, email and integration subscriptions like any other event (services/events/custom_events.py). Reading and
changing them is ADMIN/OWNER, the gate the Events pages and the workflow builder use. A change is recorded as
`workspace_settings_changed`. An event a workflow still names can't be removed (409).
"""

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import ValidationError

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.group.custom_events import CustomEventDefinition, CustomEventRead, CustomEventSave
from marvin.services.events import custom_events

router = APIRouter(prefix="/groups/custom-events")


@controller(router)
class CustomEventsController(BaseUserController):
    def _read(self) -> list[CustomEventRead]:
        events = custom_events.read(self.session, self.group_id)
        types = [custom_events.event_type_of(e.name) for e in events]
        used = custom_events.usage(self.session, self.group_id, types)
        return [CustomEventRead(**e.model_dump(), event_type=t, used_by=used[t]) for e, t in zip(events, types, strict=True)]

    def _record(self, message: str) -> None:
        from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceSettingsData

        self.event_bus.dispatch(
            integration_id="custom_events",
            group_id=self.group_id,
            event_type=EventTypes.workspace_settings_changed,
            document_data=EventWorkspaceSettingsData(operation=EventOperation.update, workspace_id=self.group_id, changed_fields=["custom_events"]),
            message=message,
            user_id=self.user.id,
            entity_id=self.group_id,
            entity_type="workspace",
        )

    @router.get("", response_model=list[CustomEventRead], summary="List the workspace's custom events")
    def list_custom_events(self):
        """The registered events, by name, with their fields and the workflows that name each."""
        require_workspace_admin(self.user, self.group_id)
        return self._read()

    @router.put("/{name}", response_model=CustomEventRead, summary="Register or change a custom event")
    def save_custom_event(self, name: str, data: CustomEventSave):
        """Register `custom.<name>` (`name` is the slug after the prefix) or replace the one of that name: its title,
        description and fields. 422 for a bad name or field; 409 past the workspace's limit."""
        require_workspace_admin(self.user, self.group_id)
        try:
            definition = CustomEventDefinition(name=name, **data.model_dump())
            saved, created = custom_events.save(self.session, self.group_id, definition)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[{"msg": err["msg"], "loc": err["loc"]} for err in e.errors()]
            ) from e
        except custom_events.CustomEventError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        event_type = custom_events.event_type_of(saved.name)
        self._record(f"Custom event {event_type} {'registered' if created else 'changed'}")
        return next(e for e in self._read() if e.event_type == event_type)

    @router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a custom event")
    def delete_custom_event(self, name: str):
        """Unregister it. 404 if there is none of that name; 409 while a workflow still starts on it or sends it. What
        the Event Log recorded stays; a subscription that names it just never fires again."""
        require_workspace_admin(self.user, self.group_id)
        try:
            gone = custom_events.remove(self.session, self.group_id, name.removeprefix(custom_events.PREFIX))
        except KeyError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No custom event {name}.") from e
        except custom_events.CustomEventInUse as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        self._record(f"Custom event {custom_events.event_type_of(gone.name)} removed")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
