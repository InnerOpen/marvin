"""Admin → Alerts: which platform events reach people outside Marvin, and how.

Email to super admins is built in, and so is push to the devices of those who turned it on (when the server
has Web Push); any message-capable integration action on one of the platform's own channels (Apprise first —
``/connections``) can be added as a route. Saving is audited as ``platform_settings_changed`` (platform
scope, always audited); each channel has a test button. See services/platform_alerts.py and
services/platform_connections.py.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.platform_alerts import (
    PlatformAlertDelivery,
    PlatformAlertEmailRead,
    PlatformAlertKindRead,
    PlatformAlertPushRead,
    PlatformAlertRouteRead,
    PlatformAlertsRead,
    PlatformAlertsUpdate,
    PlatformAlertTarget,
    PlatformAlertTestRequest,
    PlatformAlertTestResult,
    PlatformConnectionConfigField,
    PlatformConnectionCreate,
    PlatformConnectionProvider,
    PlatformConnectionRead,
    PlatformConnectionUpdate,
)
from marvin.services import alerting, platform_connections, web_push
from marvin.services import platform_alerts as alerts
from marvin.services.event_bus_service.event_types import EventOperation, EventPlatformSettingsChangedData, EventTypes

router = APIRouter(prefix="/alerts")


@controller(router)
class AdminPlatformAlertsController(BaseAdminController):
    def _read(self) -> PlatformAlertsRead:
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        settings = alerts.load(self.session)
        last = alerts.statuses(self.session)
        available = alerts.targets(self.session)
        by_key = {t.key: t for t in available}

        routes = []
        for route in settings.routes:
            target = by_key.get((route.integration_id, route.action))
            routes.append(
                PlatformAlertRouteRead(
                    id=route.id,
                    integration_id=route.integration_id,
                    action=route.action,
                    args=route.args,
                    enabled=route.enabled,
                    label=alerting.route_label(target, route),
                    problem=alerting.route_problem(alerts.PLATFORM, target),
                    last_delivery=PlatformAlertDelivery.from_status(last.get(route.id)),
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
                last_delivery=PlatformAlertDelivery.from_status(last.get(alerts.EMAIL_CHANNEL)),
            ),
            push=PlatformAlertPushRead(
                configured=web_push.configured(),
                enabled=settings.push_enabled,
                people=sorted(
                    (u.full_name or u.username or u.email or "?")
                    for u in web_push.push_ready_users(self.session, alerts.PLATFORM.push_people(self.session), alerts.PLATFORM.push_category)
                ),
                last_delivery=PlatformAlertDelivery.from_status(last.get(alerts.PUSH_CHANNEL)),
            ),
            routes=routes,
            targets=[PlatformAlertTarget.from_target(t) for t in available],
            connections=self._connections(settings),
            providers=self._providers(),
            integrations_available=INTEGRATIONS_AVAILABLE,
        )

    def _connections(self, settings) -> list[PlatformConnectionRead]:
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        message_slugs = {p.slug: p for p in platform_connections.message_providers()}
        found = []
        for c in platform_connections.load(self.session):
            provider = message_slugs.get(c.provider)
            actions = alerting.message_actions_of(provider) if provider is not None and INTEGRATIONS_AVAILABLE else []
            found.append(
                PlatformConnectionRead(
                    id=c.id,
                    provider=c.provider,
                    provider_name=getattr(provider, "name", None) or c.provider,
                    name=c.name,
                    enabled=c.enabled,
                    config=c.config,
                    has_credential=bool(c.secret_ref),
                    available=provider is not None,
                    needs_route_inputs=bool(actions) and all(a.required for a in actions),
                    routes=sum(1 for r in settings.routes if r.integration_id == c.id),
                )
            )
        return found

    def _providers(self) -> list[PlatformConnectionProvider]:
        found = []
        for p in platform_connections.message_providers():
            credential = (getattr(p, "credentials", None) or (None,))[0]
            props = (getattr(p, "config_schema", None) or {}).get("properties") or {}
            required = set((getattr(p, "config_schema", None) or {}).get("required") or ())
            found.append(
                PlatformConnectionProvider(
                    slug=p.slug,
                    name=getattr(p, "name", p.slug),
                    description=getattr(p, "description", "") or "",
                    credential_label=credential.label if credential else None,
                    credential_help=credential.help if credential else "",
                    credential_required=bool(credential and credential.required),
                    config_fields=[
                        PlatformConnectionConfigField(
                            key=k, label=(v or {}).get("title") or k, required=k in required, description=(v or {}).get("description") or ""
                        )
                        for k, v in props.items()
                        if (v or {}).get("type", "string") == "string"
                    ],
                )
            )
        return found

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
                push=data.push.model_dump() if data.push is not None else None,
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

    # ── platform channels (connections) ─────────────────────────────────────────

    def _channel_error(self, e: Exception) -> HTTPException:
        if isinstance(e, LookupError):
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    @router.post("/connections", response_model=PlatformAlertsRead, status_code=status.HTTP_201_CREATED, summary="Admin: Add a Platform Channel")
    def create_connection(self, data: PlatformConnectionCreate) -> PlatformAlertsRead:
        """Add a platform channel: an installed plugin that can send messages (Apprise first), with its credential
        (Apprise: the notification URLs, one per line — stored as a platform secret, never returned). Audited."""
        try:
            conn = platform_connections.create(
                self.session,
                provider=data.provider,
                name=data.name,
                config=data.config,
                credential=data.credential.get_secret_value() if data.credential else None,
            )
        except platform_connections.PlatformConnectionError as e:
            self.session.rollback()
            raise self._channel_error(e) from e
        self._announce([f"Channel added: {conn.name} ({conn.provider})"], setting=platform_connections.KEY)
        return self._read()

    @router.put("/connections/{connection_id}", response_model=PlatformAlertsRead, summary="Admin: Change a Platform Channel")
    def update_connection(self, connection_id: UUID4, data: PlatformConnectionUpdate) -> PlatformAlertsRead:
        """Rename, turn on or off, change the settings of, or rotate the credential of a platform channel. Audited."""
        before = platform_connections.get(self.session, str(connection_id))
        try:
            conn = platform_connections.update(
                self.session,
                str(connection_id),
                name=data.name,
                enabled=data.enabled,
                config=data.config,
                credential=data.credential.get_secret_value() if data.credential else None,
            )
        except (LookupError, platform_connections.PlatformConnectionError) as e:
            self.session.rollback()
            raise self._channel_error(e) from e
        changes = []
        if before and before.name != conn.name:
            changes.append(f"Channel renamed: {before.name} → {conn.name}")
        if before and before.enabled != conn.enabled:
            changes.append(f"Channel {conn.name}: {'on' if conn.enabled else 'off'}")
        if before and before.config != conn.config:
            changes.append(f"Channel {conn.name}: settings changed")
        if data.credential and data.credential.get_secret_value().strip():
            changes.append(f"Channel {conn.name}: credential changed")
        self._announce(changes, setting=platform_connections.KEY)
        return self._read()

    @router.delete("/connections/{connection_id}", response_model=PlatformAlertsRead, summary="Admin: Remove a Platform Channel")
    def delete_connection(self, connection_id: UUID4) -> PlatformAlertsRead:
        """Remove a platform channel, its credential and the alert routes that used it. Audited."""
        settings = alerts.load(self.session)
        try:
            conn = platform_connections.delete(self.session, str(connection_id))
        except LookupError as e:
            raise self._channel_error(e) from e
        changes = [f"Channel removed: {conn.name} ({conn.provider})"]
        dropped = [r for r in settings.routes if r.integration_id == conn.id]
        if dropped:
            settings.routes = [r for r in settings.routes if r.integration_id != conn.id]
            alerts.save(self.session, settings)
            changes.append(f"{len(dropped)} route(s) that used it removed")
        self._announce(changes, setting=platform_connections.KEY)
        return self._read()

    @router.post(
        "/connections/{connection_id}/test", response_model=PlatformAlertTestResult, summary="Admin: Send a Test Alert Through a Platform Channel"
    )
    def test_connection(self, connection_id: UUID4) -> PlatformAlertTestResult:
        """Send "Test alert from Marvin admin" through the channel's message action, even one that's turned off. A
        channel whose action needs more than the message (a channel name…) is tested through a route instead."""
        cid = str(connection_id)
        target = next((t for t in alerts.targets(self.session) if t.integration_id == cid), None)
        if target is None:
            if platform_connections.get(self.session, cid) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such channel.")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This channel's plugin isn't installed or no longer sends messages."
            )
        if target.action.required:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{target.integration_name} needs {', '.join(target.action.required)}: add a route for it, then test the route.",
            )
        name = getattr(self.user, "full_name", None) or getattr(self.user, "username", None)
        route = alerting.Route(id=cid, integration_id=cid, action=target.action.key, args={})
        delivery = alerting.send_route(
            alerts.PLATFORM, self.session, route, alerting.trial_message(alerts.PLATFORM, self.session, target.integration_name, name)
        )
        self.logger.info(f"Platform channels: test of {target.integration_name!r} by {name}: {delivery.outcome} — {delivery.detail}")
        return PlatformAlertTestResult(channel=cid, delivery=PlatformAlertDelivery.model_validate(delivery.status(None, True)))

    def _announce(self, changes: list[str], setting: str | None = None) -> None:
        """platform_settings_changed (platform scope, always audited). No workspace: a platform setting."""
        if not changes:
            return
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(f"Platform alerts changed by {name}: {'; '.join(changes)}")
        self.event_bus.dispatch(
            integration_id="platform_settings",
            group_id=None,
            event_type=EventTypes.platform_settings_changed,
            document_data=EventPlatformSettingsChangedData(
                operation=EventOperation.update, setting=setting or alerts.SETTINGS_KEY, changes=changes, changed_by_name=name
            ),
            message=("Platform alerts: " + "; ".join(changes))[:1000],
            user_id=self.user.id,
            entity_type="platform_settings",
        )
