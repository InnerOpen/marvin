"""Schemas for workspace integrations — credentialed connections to external services."""

from datetime import datetime
from uuid import UUID

from pydantic import UUID4, Field, SecretStr

from marvin.schemas._marvin import _MarvinModel


class IntegrationCreate(_MarvinModel):
    """Create a new integration instance."""

    provider: str  # registry key, e.g. "vercel_deploy"
    name: str  # user-facing label
    slug: str | None = None  # derived from name if omitted
    config: dict = Field(default_factory=dict)
    credential: SecretStr | None = None  # write-only; stored via the secret backend, never read back


class IntegrationUpdate(_MarvinModel):
    """Patch an integration. A present `credential` rotates the stored secret."""

    name: str | None = None
    enabled: bool | None = None
    config: dict | None = None
    credential: SecretStr | None = None


class IntegrationAttention(_MarvinModel):
    """An open alert on a connection — "Needs attention" on its card. One per error code, counted."""

    id: UUID4
    code: str
    message: str | None = None
    count: int = 1
    first_at: datetime | None = None
    last_at: datetime | None = None
    samples: list[dict] = Field(default_factory=list)
    """The last few failures: {at, message, action, entry_id, automation_slug, source}."""


class IntegrationRead(_MarvinModel):
    """An integration as returned by the API. Never carries the credential value."""

    id: UUID4
    provider: str
    name: str
    slug: str
    enabled: bool
    config: dict | None = None
    has_credential: bool = False  # whether a secret_ref is set — not the value
    credential_secret: str | None = None  # the workspace secret it reads (`{{SLUG}}`), when it isn't its own copy
    status: str
    last_checked_at: datetime | None = None
    last_error: str | None = None
    attention: list[IntegrationAttention] = Field(default_factory=list)
    """Open alerts (the connection needs attention); empty when it is healthy."""
    error_overrides: dict = Field(default_factory=dict)
    """An admin's adjustments to the provider's error policy: {code: {review?, notify?}}."""


class ProviderCredentialInfo(_MarvinModel):
    """A credential field a provider needs (drives the create form)."""

    key: str
    label: str
    help: str = ""
    required: bool = True


class ProviderEventInfo(_MarvinModel):
    """An event a provider can emit onto the bus."""

    key: str
    label: str
    description: str = ""


class ProviderActionInfo(_MarvinModel):
    """An action a provider exposes to automations."""

    key: str
    label: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    # Capability routing (present when the action advertises a standard capability kind).
    capability: str | None = None
    output_schema: dict = Field(default_factory=dict)
    priority: int = 0
    cost_hint: str | None = None
    requires_approval: bool = False
    error_policy: dict = Field(default_factory=dict)
    """This action's own error policy: {code: Handle.to_dict()} (SDK 0.5.0+)."""


class IntegrationProviderInfo(_MarvinModel):
    """A provider catalog entry — what the 'add integration' screen renders from."""

    slug: str
    name: str
    description: str = ""
    category: str
    icon: str = ""
    """Optional emoji the provider supplies; rendered as text, so a name or URL will not work."""
    has_logo: bool = False
    """Whether the provider ships a logo Marvin accepted (served by `GET …/providers/{slug}/logo`).
    False → show `icon`."""
    config_schema: dict = Field(default_factory=dict)
    credentials: list[ProviderCredentialInfo] = Field(default_factory=list)
    emits: list[ProviderEventInfo] = Field(default_factory=list)
    actions: list[ProviderActionInfo] = Field(default_factory=list)
    error_policy: dict | None = None
    """How the provider handles its errors — {"provider": {code: Handle}, "actions": {key: {code: Handle}}}
    (SDK 0.5.0+; None on an older SDK). Each Handle carries a human `summary`."""


class IntegrationPluginInfo(_MarvinModel):
    """One provider source (built-ins, or an installed plugin distribution) and how it loaded."""

    name: str
    source: str  # "builtin" | "entry_point"
    ok: bool
    slugs: list[str] = Field(default_factory=list)
    distribution: str | None = None
    version: str | None = None
    error: str | None = None


class IntegrationOptionsRequest(_MarvinModel):
    """Which action input to load options for. The input's `x-marvin-options` hint names the read
    action to run — the caller never picks the action or its args."""

    action_key: str
    input: str


class IntegrationOption(_MarvinModel):
    """One choice for an action input: the value stored, and what people see."""

    value: str | int | float | bool
    label: str


class IntegrationActionResult(_MarvinModel):
    """Result of running (or test-firing) a provider action."""

    ok: bool
    result: dict = Field(default_factory=dict)


class IntegrationCheckResult(_MarvinModel):
    """Result of a health check."""

    status: str
    last_error: str | None = None
    last_checked_at: datetime | None = None


class IntegrationEventSubscriptionCreate(_MarvinModel):
    """Wire an integration action to an event type."""

    integration_id: UUID4
    event_type: str
    action: str
    args: dict = Field(default_factory=dict)


class IntegrationEventSubscriptionUpdate(_MarvinModel):
    enabled: bool | None = None
    args: dict | None = None


class IntegrationEventSubscriptionRead(_MarvinModel):
    id: UUID4
    integration_id: UUID4
    integration_name: str | None = None  # convenience for the events UI
    provider: str | None = None
    event_type: str
    action: str
    args: dict | None = None
    enabled: bool
    source_integration_id: UUID4 | None = None
    """Read-only "installed by": the integration whose blueprint created this (null: made by a person)."""
    source_blueprint: str | None = None
    """Read-only: the slug of the blueprint that created this, if one did."""


class IntegrationErrorOverrides(_MarvinModel):
    """Per-connection adjustments to the provider's error policy. Only `review` and `notify` per code
    (or "*"); a code left out uses the provider's default."""

    overrides: dict[str, dict[str, bool]] = Field(default_factory=dict)


class IntegrationResolveResult(_MarvinModel):
    resolved: int


class AlertRoutingTarget(_MarvinModel):
    """A connection that can carry integration alerts (a chat or notification provider)."""

    integration_id: UUID4
    name: str
    provider: str
    action: str
    enabled: bool = False
    """Whether alerts currently go to it."""


class AlertRouting(_MarvinModel):
    """Where integration alerts go besides the bell (which always gets them)."""

    email_admins: bool = False
    """Email the workspace's owners and admins (the "Integration Alert" system template)."""
    targets: list[AlertRoutingTarget] = Field(default_factory=list)
    reminder_hours: int = 24
    """An open alert is announced again after this many hours; 0 = never."""


class AlertRoutingUpdate(_MarvinModel):
    email_admins: bool = False
    integration_ids: list[UUID4] = Field(default_factory=list)
    """The connections alerts go to (each must be one of the routing's targets)."""
    reminder_hours: int = Field(default=24, ge=0, le=24 * 30)


# ---- Alerts & health page ---------------------------------------------------------------------------


class IntegrationAlertRead(_MarvinModel):
    """One connection alert, open or resolved, with how long it was open and how it ended."""

    id: UUID
    integration_id: UUID
    integration_name: str | None = None
    integration_slug: str
    provider: str
    provider_name: str
    code: str
    message: str | None = None
    """The latest failure's message (redacted when it was stored)."""
    count: int
    status: str
    """open | resolved"""
    first_at: datetime | None = None
    last_at: datetime | None = None
    notified_at: datetime | None = None
    """When the alert was last announced (the open, or the latest reminder)."""
    remind_after: datetime | None = None
    """An open alert is announced again on its next failure after this; None while reminders are off."""
    reminder_hours: int = 0
    resolved_at: datetime | None = None
    resolution: str | None = None
    """manual | check | action"""
    resolved_by_name: str | None = None
    open_seconds: int | None = None
    """How long it stayed open (resolved alerts only)."""


class IntegrationAlertPage(_MarvinModel):
    items: list[IntegrationAlertRead]
    page: int
    per_page: int
    total: int


class IntegrationRetryRead(_MarvinModel):
    """A failed workflow step that is waiting to be retried (or running right now)."""

    id: UUID
    status: str
    """pending | parked (waits for the connection to recover) | running"""
    automation_id: UUID
    automation_name: str | None = None
    automation_enabled: bool = True
    """A disabled workflow's retries wait until it is enabled again."""
    entry_id: UUID | None = None
    entry_title: str | None = None
    entry_exists: bool = False
    integration_id: UUID | None = None
    integration_name: str | None = None
    integration_slug: str
    provider: str
    provider_name: str
    action: str
    code: str
    attempt: int
    """Retries made so far."""
    max_attempts: int
    next_attempt_at: datetime | None = None
    lease_until: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None


class HandledFailureRead(_MarvinModel):
    """A failed integration step that the provider's error policy took in hand."""

    id: UUID
    execution_id: UUID
    run_status: str
    is_retry: bool = False
    """The step ran in a retry run (the original failure has a row of its own)."""
    at: datetime | None = None
    automation_id: UUID | None = None
    automation_name: str | None = None
    entry_id: UUID | None = None
    entry_title: str | None = None
    entry_exists: bool = False
    integration_id: UUID | None = None
    integration_slug: str | None = None
    provider: str | None = None
    provider_name: str | None = None
    action: str | None = None
    code: str | None = None
    error: str | None = None
    outcome: str
    """What came of it, e.g. "retried, succeeded on retry 1" or "sent to review"."""
    retry_status: str | None = None
    """The retry chain's status now, when the policy started one and it is still on record."""


class HandledFailurePage(_MarvinModel):
    items: list[HandledFailureRead]
    page: int
    per_page: int
    total: int
    since: datetime


class IntegrationHealthRow(_MarvinModel):
    """One connection at a glance."""

    id: UUID
    name: str
    slug: str
    provider: str
    provider_name: str
    enabled: bool
    status: str
    """The last health check's result: ok | error | unconfigured | unavailable"""
    last_checked_at: datetime | None = None
    last_error: str | None = None
    last_success_at: datetime | None = None
    failures_7d: int = 0
    """Failed workflow steps through this connection in the last 7 days."""
    open_alerts: int = 0
    alert_codes: list[str] = Field(default_factory=list)
    live_retries: int = 0
