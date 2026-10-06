"""
Workspace audit settings: which event types the Event Log records.

Reading and changing the settings is ADMIN/OWNER (the gate every workspace-management route uses); any member
may read which types are left out, which is what the Event Log page tells everyone. Security events are locked:
always audited, refused here with a 409. A change is itself recorded as `workspace_settings_changed`, a locked
type, so switching auditing off always leaves a trace.
"""

from fastapi import APIRouter, HTTPException, status

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin, require_workspace_role
from marvin.schemas.group.audit_settings import AuditEventSetting, AuditExcludedEvent, AuditSettingsUpdate
from marvin.services.events import audit_settings

router = APIRouter(prefix="/groups/audit-settings")


@controller(router)
class AuditSettingsController(BaseUserController):
    def _settings(self) -> list[AuditEventSetting]:
        overrides = audit_settings.read_overrides(self.session, self.group_id)
        return [AuditEventSetting.model_validate(s, from_attributes=True) for s in audit_settings.settings(overrides)]

    @router.get("", response_model=list[AuditEventSetting], summary="List every event type's audit setting")
    def get_audit_settings(self):
        """Every catalog event type: its default, what this workspace records, and whether it's locked."""
        require_workspace_admin(self.user, self.group_id)
        return self._settings()

    @router.get("/excluded", response_model=list[AuditExcludedEvent], summary="List the event types the Event Log leaves out")
    def get_excluded_event_types(self):
        """The event types this workspace's Event Log does not record. Any member."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.VIEWER)
        overrides = audit_settings.read_overrides(self.session, self.group_id)
        return [AuditExcludedEvent.model_validate(s, from_attributes=True) for s in audit_settings.excluded(overrides)]

    @router.patch("", response_model=list[AuditEventSetting], summary="Change event types' audit settings")
    def update_audit_settings(self, data: AuditSettingsUpdate):
        """Record (`true`) or skip (`false`) event types, or put them back to the default (`null`). Types left
        out keep their setting. An unknown type is a 422; a locked (security) type a 409; nothing is saved then."""
        require_workspace_admin(self.user, self.group_id)
        try:
            _, changed = audit_settings.apply_changes(self.session, self.group_id, data.overrides)
        except audit_settings.UnknownEventTypes as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        except audit_settings.LockedEventTypes as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

        if changed:
            from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceSettingsData

            self.event_bus.dispatch(
                integration_id="audit_settings",
                group_id=self.group_id,
                event_type=EventTypes.workspace_settings_changed,
                document_data=EventWorkspaceSettingsData(
                    operation=EventOperation.update,
                    workspace_id=self.group_id,
                    changed_fields=["audit_overrides"],
                ),
                message=f"Audit settings changed: {audit_settings.describe(changed)}",
                user_id=self.user.id,
                entity_id=self.group_id,
                entity_type="workspace",
            )
        return self._settings()
