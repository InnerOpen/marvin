"""Admin → Platform alerts: which platform events reach people outside Marvin, and how.

Email to super admins is built in; any message-capable integration action on a connection in the
platform workspace can be added as a route. Saving is audited as ``platform_settings_changed`` (platform
scope, always audited); each channel has a test button. See services/platform_alerts.py.
"""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.platform_alerts import (
    PlatformAlertActionInput,
    PlatformAlertDelivery,
    PlatformAlertEmailRead,
    PlatformAlertKindRead,
    PlatformAlertRouteRead,
    PlatformAlertsRead,
    PlatformAlertsUpdate,
    PlatformAlertTarget,
    PlatformAlertTestRequest,
    PlatformAlertTestResult,
    PlatformWorkspaceRef,
)
from marvin.services import platform_alerts as alerts
from marvin.services.event_bus_service.event_types import EventOperation, EventPlatformSettingsChangedData, EventTypes

router = APIRouter(prefix="/alerts")


def _delivery(raw: dict | None) -> PlatformAlertDelivery | None:
    try:
        return PlatformAlertDelivery.model_validate(raw) if raw else None
    except ValueError:
        return None


def _target(t: alerts.Target) -> PlatformAlertTarget:
    action = t.action
    return PlatformAlertTarget(
        integration_id=t.integration_id,
        integration_name=t.integration_name,
        provider=t.provider,
        provider_name=t.provider_name,
        connection_enabled=t.connection_enabled,
        action=action.key,
        action_label=action.label,
        inputs=[
            PlatformAlertActionInput(
                key=key,
                label=(prop or {}).get("title") or key,
                description=(prop or {}).get("description") or "",
                required=key in action.required,
            )
            for key, prop in action.inputs.items()
        ],
    )


@controller(router)
class AdminPlatformAlertsController(BaseAdminController):
    def _read(self) -> PlatformAlertsRead:
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        settings = alerts.load(self.session)
        last = alerts.statuses(self.session)
        workspace = alerts._platform_workspace(self.session)
        available = alerts.targets(self.session, workspace)
        by_key = {t.key: t for t in available}

        routes = []
        for route in settings.routes:
            target = by_key.get((route.integration_id, route.action))
            problem = None
            if workspace is None:
                problem = "There's no platform workspace to send through."
            elif target is None:
                problem = "The connection is gone from the platform workspace, its plugin isn't installed, or the action no longer sends messages."
            elif not target.connection_enabled:
                problem = f"{target.integration_name} is turned off in the platform workspace."
            routes.append(
                PlatformAlertRouteRead(
                    id=route.id,
                    integration_id=route.integration_id,
                    action=route.action,
                    args=route.args,
                    enabled=route.enabled,
                    label=f"{target.integration_name} → {target.action.label}" if target else f"(missing connection) → {route.action}",
                    problem=problem,
                    last_delivery=_delivery(last.get(route.id)),
                )
            )
        return PlatformAlertsRead(
            types=[
                PlatformAlertKindRead(
                    key=k.key, label=k.label, description=k.description, event_type=k.event_type, enabled=settings.types[k.key], default=k.default
                )
                for k in alerts.KINDS
            ],
            email=PlatformAlertEmailRead(
                enabled=settings.email_enabled,
                recipients=settings.recipients,
                super_admin_emails=alerts.super_admin_emails(self.session),
                smtp_ready=alerts.smtp_ready(),
                last_delivery=_delivery(last.get(alerts.EMAIL_CHANNEL)),
            ),
            routes=routes,
            targets=[_target(t) for t in available],
            platform_workspace=PlatformWorkspaceRef(id=workspace.id, name=workspace.name, slug=getattr(workspace, "slug", None))
            if workspace
            else None,
            integrations_available=INTEGRATIONS_AVAILABLE,
        )

    @router.get("", response_model=PlatformAlertsRead, summary="Admin: Get Platform Alert Settings")
    def get_alerts(self) -> PlatformAlertsRead:
        """Which platform events alert, and where they go besides the bell."""
        return self._read()

    @router.put("", response_model=PlatformAlertsRead, summary="Admin: Replace Platform Alert Settings")
    def update_alerts(self, data: PlatformAlertsUpdate) -> PlatformAlertsRead:
        """Replace the alert types, the email channel and the integration routes (audited)."""
        old = alerts.load(self.session)
        try:
            new = alerts.validate(
                self.session,
                types=data.types,
                email_enabled=data.email.enabled,
                recipients=data.email.recipients,
                routes=[r.model_dump(mode="json") for r in data.routes],
            )
        except alerts.InvalidAlertSettings as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        changes = alerts.describe_changes(self.session, old, new)
        alerts.save(self.session, new)
        if changes:
            self._announce(changes)
        return self._read()

    @router.post("/test", response_model=PlatformAlertTestResult, summary="Admin: Send a Test Platform Alert")
    def test_channel(self, data: PlatformAlertTestRequest) -> PlatformAlertTestResult:
        """Send "Test alert from Marvin admin" through one saved channel (``email`` or a route id), even
        one that's turned off. The result is also its last delivery."""
        name = getattr(self.user, "full_name", None) or getattr(self.user, "username", None)
        try:
            result = alerts.send_test(self.session, data.channel, by=name)
        except LookupError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        self.logger.info(f"Platform alerts: test of {data.channel!r} by {name}: {result['outcome']} — {result['detail']}")
        return PlatformAlertTestResult(channel=data.channel, delivery=PlatformAlertDelivery.model_validate(result))

    def _announce(self, changes: list[str]) -> None:
        """platform_settings_changed (platform scope, always audited). No workspace: a platform setting."""
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(f"Platform alerts changed by {name}: {'; '.join(changes)}")
        self.event_bus.dispatch(
            integration_id="platform_settings",
            group_id=None,
            event_type=EventTypes.platform_settings_changed,
            document_data=EventPlatformSettingsChangedData(
                operation=EventOperation.update, setting=alerts.SETTINGS_KEY, changes=changes, changed_by_name=name
            ),
            message=("Platform alerts: " + "; ".join(changes))[:1000],
            user_id=self.user.id,
            entity_type="platform_settings",
        )
