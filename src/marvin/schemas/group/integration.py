"""Schemas for workspace integrations — credentialed connections to external services."""

from datetime import datetime

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


class IntegrationRead(_MarvinModel):
    """An integration as returned by the API. Never carries the credential value."""

    id: UUID4
    provider: str
    name: str
    slug: str
    enabled: bool
    config: dict | None = None
    has_credential: bool = False  # whether a secret_ref is set — not the value
    status: str
    last_checked_at: datetime | None = None
    last_error: str | None = None


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


class IntegrationProviderInfo(_MarvinModel):
    """A provider catalog entry — what the 'add integration' screen renders from."""

    slug: str
    name: str
    description: str = ""
    category: str
    icon: str = ""
    """Optional emoji the provider supplies; rendered as text, so a name or URL will not work."""
    config_schema: dict = Field(default_factory=dict)
    credentials: list[ProviderCredentialInfo] = Field(default_factory=list)
    emits: list[ProviderEventInfo] = Field(default_factory=list)
    actions: list[ProviderActionInfo] = Field(default_factory=list)


class IntegrationPluginInfo(_MarvinModel):
    """One provider source (built-ins, or an installed plugin distribution) and how it loaded."""

    name: str
    source: str  # "builtin" | "entry_point"
    ok: bool
    slugs: list[str] = Field(default_factory=list)
    distribution: str | None = None
    version: str | None = None
    error: str | None = None


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
