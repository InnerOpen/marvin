"""Schemas for Admin → Alerts (/api/admin/alerts): which platform events reach people outside Marvin, and
how — email to super admins, push, or a message-capable integration action on one of the platform's own
channels (Apprise first). See services/platform_alerts.py and services/platform_connections.py."""

from typing import Any

from pydantic import UUID4, Field, SecretStr

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.alerts import AlertActionInput, AlertDelivery, AlertKindRead, AlertTarget, AlertTestRequest


class PlatformAlertDelivery(AlertDelivery):
    """A channel's last delivery (an alert or a test)."""


class PlatformAlertKindRead(AlertKindRead):
    pass


class PlatformAlertEmailRead(_MarvinModel):
    enabled: bool
    recipients: list[str] | None = None
    """None: every super admin with an email address."""
    super_admin_emails: list[str] = Field(default_factory=list)
    """Who "every super admin" is right now."""
    smtp_ready: bool
    """Platform SMTP is configured; without it email alerts are recorded as not sent."""
    last_delivery: PlatformAlertDelivery | None = None


class PlatformAlertPushRead(_MarvinModel):
    configured: bool
    """The server has Web Push (VAPID); without it push isn't a channel and the page hides it."""
    enabled: bool
    people: list[str] = Field(default_factory=list)
    """Who push reaches right now: super admins with a device and "Platform alerts" on."""
    last_delivery: PlatformAlertDelivery | None = None


class PlatformAlertActionInput(AlertActionInput):
    """One of an action's own inputs the admin fills (the message itself is Marvin's)."""


class PlatformAlertTarget(AlertTarget):
    """A message-capable action on a platform channel."""

    inputs: list[PlatformAlertActionInput] = Field(default_factory=list)


class PlatformAlertRouteRead(_MarvinModel):
    id: str
    integration_id: UUID4
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    label: str
    """"Connection → Action", or what's left of it when the connection is gone."""
    problem: str | None = None
    """Why it can't send right now (connection gone or turned off, plugin uninstalled)."""
    last_delivery: PlatformAlertDelivery | None = None


class PlatformConnectionConfigField(_MarvinModel):
    key: str
    label: str
    required: bool = False
    description: str = ""


class PlatformConnectionProvider(_MarvinModel):
    """An installed plugin that can carry a message — what a new platform channel can be."""

    slug: str
    name: str
    description: str = ""
    credential_label: str | None = None
    """What the provider's credential is called (for Apprise: its notification URLs); None: it takes none."""
    credential_help: str = ""
    credential_required: bool = False
    config_fields: list[PlatformConnectionConfigField] = Field(default_factory=list)
    """The plain-text settings its config takes, besides the credential."""


class PlatformConnectionRead(_MarvinModel):
    """A platform channel. The credential (Apprise URLs…) is never returned, only whether there is one."""

    id: UUID4
    provider: str
    provider_name: str
    name: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    has_credential: bool
    available: bool
    """Its plugin is installed and still sends messages."""
    needs_route_inputs: bool = False
    """Every message action of it needs more than the message (a channel…): add a route to test it."""
    routes: int = 0
    """How many alert routes use it."""


class PlatformConnectionCreate(_MarvinModel):
    provider: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    credential: SecretStr | None = None
    """Write-only: for Apprise, the notification URLs, one per line."""


class PlatformConnectionUpdate(_MarvinModel):
    name: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    credential: SecretStr | None = None
    """Write-only; blank keeps the saved one."""


class PlatformAlertsRead(_MarvinModel):
    types: list[PlatformAlertKindRead]
    email: PlatformAlertEmailRead
    push: PlatformAlertPushRead
    routes: list[PlatformAlertRouteRead]
    targets: list[PlatformAlertTarget]
    """What a new route can use: every message-capable action on a platform channel."""
    connections: list[PlatformConnectionRead] = Field(default_factory=list)
    """The platform's own channels, which routes use."""
    providers: list[PlatformConnectionProvider] = Field(default_factory=list)
    """What a new channel can be: installed plugins that send messages, Apprise first."""
    integrations_available: bool
    """The integrations framework is installed."""


class PlatformAlertEmailUpdate(_MarvinModel):
    enabled: bool = True
    recipients: list[str] | None = None


class PlatformAlertPushUpdate(_MarvinModel):
    enabled: bool = True


class PlatformAlertRouteUpdate(_MarvinModel):
    id: str | None = None
    """An existing route's id (keeps its last delivery); omit for a new one."""
    integration_id: UUID4
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PlatformAlertsUpdate(_MarvinModel):
    types: dict[str, bool] = Field(default_factory=dict)
    """Kind key → on/off; a kind left out keeps its current setting."""
    email: PlatformAlertEmailUpdate = Field(default_factory=PlatformAlertEmailUpdate)
    push: PlatformAlertPushUpdate | None = None
    """None keeps the current push setting."""
    routes: list[PlatformAlertRouteUpdate] = Field(default_factory=list)


class PlatformAlertTestRequest(AlertTestRequest):
    pass


class PlatformAlertTestResult(_MarvinModel):
    channel: str
    delivery: PlatformAlertDelivery
