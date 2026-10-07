"""Schemas for Settings → Automation → Notifications (/api/groups/notifications): which of the workspace's
events reach people outside Marvin, and how. See services/workspace_alerts.py."""

from typing import Any

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.alerts import AlertDelivery, AlertKindRead, AlertTarget


class NotificationEmailRead(_MarvinModel):
    enabled: bool
    recipients: list[str] | None = None
    """None: every owner and admin of the workspace with an email address."""
    kinds: list[str] | None = None
    """The kinds email takes; None: every kind that is on."""
    admin_emails: list[str] = Field(default_factory=list)
    """Who "every owner and admin" is right now."""
    smtp_ready: bool
    """The workspace or the platform has SMTP set up; without it email notifications are recorded as not sent."""
    last_delivery: AlertDelivery | None = None


class NotificationRouteRead(_MarvinModel):
    id: str
    integration_id: UUID4
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    kinds: list[str] | None = None
    """The kinds it takes; None: every kind that is on."""
    label: str
    """"Connection → Action", or what's left of it when the connection is gone."""
    problem: str | None = None
    """Why it can't send right now (connection gone or turned off, plugin uninstalled)."""
    last_delivery: AlertDelivery | None = None


class WorkspaceNotificationsRead(_MarvinModel):
    types: list[AlertKindRead]
    email: NotificationEmailRead
    routes: list[NotificationRouteRead]
    targets: list[AlertTarget]
    """What a new route can use: every message-capable action on the workspace's connections."""
    integrations_available: bool
    """The integrations framework is installed."""
    integration_reminder_hours: int
    """An open integration alert is sent again after this many hours; 0 = never."""


class NotificationEmailUpdate(_MarvinModel):
    enabled: bool = True
    recipients: list[str] | None = None
    kinds: list[str] | None = None


class NotificationRouteUpdate(_MarvinModel):
    id: str | None = None
    """An existing route's id (keeps its last delivery); omit for a new one."""
    integration_id: UUID4
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    kinds: list[str] | None = None


class WorkspaceNotificationsUpdate(_MarvinModel):
    types: dict[str, bool] = Field(default_factory=dict)
    """Kind key → on/off; a kind left out keeps its current setting."""
    email: NotificationEmailUpdate = Field(default_factory=NotificationEmailUpdate)
    routes: list[NotificationRouteUpdate] = Field(default_factory=list)
    integration_reminder_hours: int | None = Field(default=None, ge=0, le=24 * 30)
    """None keeps the current window."""


class NotificationTestResult(_MarvinModel):
    channel: str
    delivery: AlertDelivery
