"""Schemas for Admin → Platform alerts (/api/admin/alerts): which platform events reach people outside
Marvin, and how — email to super admins, or a message-capable integration action on a connection in the
platform workspace. See services/platform_alerts.py."""

from datetime import datetime
from typing import Any, Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class PlatformAlertDelivery(_MarvinModel):
    """A channel's last delivery (an alert or a test)."""

    at: datetime
    outcome: Literal["sent", "failed", "skipped"]
    detail: str
    event_type: str | None = None
    """The event that was sent; None for a test."""
    test: bool = False


class PlatformAlertKindRead(_MarvinModel):
    key: str
    label: str
    description: str
    event_type: str
    enabled: bool
    default: bool


class PlatformAlertEmailRead(_MarvinModel):
    enabled: bool
    recipients: list[str] | None = None
    """None: every super admin with an email address."""
    super_admin_emails: list[str] = Field(default_factory=list)
    """Who "every super admin" is right now."""
    smtp_ready: bool
    """Platform SMTP is configured; without it email alerts are recorded as not sent."""
    last_delivery: PlatformAlertDelivery | None = None


class PlatformAlertActionInput(_MarvinModel):
    """One of an action's own inputs the admin fills (the message itself is Marvin's)."""

    key: str
    label: str
    description: str = ""
    required: bool = False


class PlatformAlertTarget(_MarvinModel):
    """A message-capable action on a connection in the platform workspace."""

    integration_id: UUID4
    integration_name: str
    provider: str
    provider_name: str
    connection_enabled: bool
    action: str
    action_label: str
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


class PlatformWorkspaceRef(_MarvinModel):
    id: UUID4
    name: str
    slug: str | None = None


class PlatformAlertsRead(_MarvinModel):
    types: list[PlatformAlertKindRead]
    email: PlatformAlertEmailRead
    routes: list[PlatformAlertRouteRead]
    targets: list[PlatformAlertTarget]
    """What a new route can use: every message-capable action in the platform workspace."""
    platform_workspace: PlatformWorkspaceRef | None = None
    """Where routes' connections live; None when it can't be found (routes are then unavailable)."""
    integrations_available: bool
    """The integrations framework is installed."""


class PlatformAlertEmailUpdate(_MarvinModel):
    enabled: bool = True
    recipients: list[str] | None = None


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
    routes: list[PlatformAlertRouteUpdate] = Field(default_factory=list)


class PlatformAlertTestRequest(_MarvinModel):
    channel: str
    """``email``, or a saved route's id."""


class PlatformAlertTestResult(_MarvinModel):
    channel: str
    delivery: PlatformAlertDelivery
