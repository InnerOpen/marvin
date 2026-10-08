"""Settings → Automation → Notifications: which of the workspace's events reach people outside Marvin, and how.

Email to the workspace's owners and admins is built in, and so is push to the devices of those who turned it
on (when the server has Web Push); any message-capable integration action on one of the
workspace's connections can be added as a route, each taking every kind or only some. Workspace ADMIN/OWNER
only. Saving is audited as ``workspace_settings_changed``; each channel has a test button. See
services/workspace_alerts.py.
"""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.alerts import AlertDelivery, AlertKindRead, AlertTarget, AlertTestRequest
from marvin.schemas.group.notifications import (
    NotificationEmailRead,
    NotificationPushRead,
    NotificationRouteRead,
    NotificationTestResult,
    WorkspaceNotificationsRead,
    WorkspaceNotificationsUpdate,
)
from marvin.services import alerting, web_push, workspace_alerts
from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceSettingsData

router = APIRouter(prefix="/groups/notifications")


def _names(users) -> list[str]:
    return sorted((getattr(u, "full_name", None) or u.username or u.email or "?") for u in users)


@controller(router)
class WorkspaceNotificationsController(BaseUserController):
    @property
    def _scope(self) -> workspace_alerts.WorkspaceScope:
        return workspace_alerts.WorkspaceScope(self.group_id)

    def _read(self) -> WorkspaceNotificationsRead:
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        scope = self._scope
        settings = alerting.load(scope, self.session)
        last = alerting.statuses(scope, self.session)
        workspace = scope.workspace(self.session)
        available = alerting.targets(self.session, workspace)
        by_key = {t.key: t for t in available}
        routes = []
        for route in settings.routes:
            target = by_key.get((route.integration_id, route.action))
            routes.append(
                NotificationRouteRead(
                    id=route.id,
                    integration_id=route.integration_id,
                    action=route.action,
                    args=route.args,
                    enabled=route.enabled,
                    kinds=route.kinds,
                    label=alerting.route_label(target, route),
                    problem=alerting.route_problem(scope, workspace, target),
                    last_delivery=AlertDelivery.from_status(last.get(route.id)),
                )
            )
        return WorkspaceNotificationsRead(
            types=[
                AlertKindRead(
                    key=k.key,
                    label=k.label,
                    description=k.description,
                    event_type=k.event_type,
                    enabled=settings.types[k.key],
                    default=k.default,
                    push=k.push,
                )
                for k in scope.kinds
            ],
            email=NotificationEmailRead(
                enabled=settings.email_enabled,
                recipients=settings.recipients,
                kinds=settings.email_kinds,
                admin_emails=workspace_alerts.admin_emails(self.session, self.group_id),
                smtp_ready=workspace_alerts.smtp_ready(self.session, self.group_id),
                last_delivery=AlertDelivery.from_status(last.get(alerting.EMAIL_CHANNEL)),
            ),
            push=NotificationPushRead(
                configured=web_push.configured(),
                enabled=settings.push_enabled,
                kinds=settings.push_kinds,
                people=_names(web_push.push_ready_users(self.session, scope.push_people(self.session), scope.push_category)),
                last_delivery=AlertDelivery.from_status(last.get(alerting.PUSH_CHANNEL)),
            ),
            routes=routes,
            targets=[AlertTarget.from_target(t) for t in available],
            integrations_available=INTEGRATIONS_AVAILABLE,
            integration_reminder_hours=workspace_alerts.reminder_hours(self.session, self.group_id),
        )

    @router.get("", response_model=WorkspaceNotificationsRead, summary="Get the workspace's notification settings")
    def get_notifications(self) -> WorkspaceNotificationsRead:
        require_workspace_admin(self.user, self.group_id)
        return self._read()

    @router.put("", response_model=WorkspaceNotificationsRead, summary="Replace the workspace's notification settings")
    def update_notifications(self, data: WorkspaceNotificationsUpdate) -> WorkspaceNotificationsRead:
        require_workspace_admin(self.user, self.group_id)
        scope = self._scope
        old = alerting.load(scope, self.session)
        try:
            new = alerting.validate(
                scope,
                self.session,
                types=data.types,
                email_enabled=data.email.enabled,
                recipients=data.email.recipients,
                email_kinds=data.email.kinds,
                push=data.push.model_dump() if data.push is not None else None,
                routes=[r.model_dump(mode="json") for r in data.routes],
            )
        except alerting.InvalidAlertSettings as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        changes = alerting.describe_changes(scope, self.session, old, new)
        hours = data.integration_reminder_hours
        if hours is not None and hours != workspace_alerts.reminder_hours(self.session, self.group_id):
            workspace_alerts.set_reminder_hours(self.session, self.group_id, hours)
            changes.append(f"Integration alert reminders: {f'every {hours} h' if hours else 'never'}")
        alerting.save(scope, self.session, new)
        if changes:
            self._announce(changes)
        return self._read()

    @router.post("/test", response_model=NotificationTestResult, summary="Send a test notification")
    def test_channel(self, data: AlertTestRequest) -> NotificationTestResult:
        require_workspace_admin(self.user, self.group_id)
        name = getattr(self.user, "full_name", None) or getattr(self.user, "username", None)
        try:
            result = workspace_alerts.send_test(self.session, self.group_id, data.channel, by=name)
        except LookupError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        self.logger.info(f"Workspace notifications: test of {data.channel!r} by {name}: {result['outcome']} — {result['detail']}")
        return NotificationTestResult(channel=data.channel, delivery=AlertDelivery.model_validate(result))

    def _announce(self, changes: list[str]) -> None:
        """workspace_settings_changed: what changed, by name — never a route's arguments."""
        self.event_bus.dispatch(
            integration_id="notifications",
            group_id=self.group_id,
            event_type=EventTypes.workspace_settings_changed,
            document_data=EventWorkspaceSettingsData(operation=EventOperation.update, workspace_id=self.group_id, changed_fields=["notifications"]),
            message=("Notifications: " + "; ".join(changes))[:1000],
            user_id=self.user.id,
            entity_id=self.group_id,
            entity_type="workspace",
        )
