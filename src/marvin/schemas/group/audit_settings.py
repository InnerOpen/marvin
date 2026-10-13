"""Per-workspace audit settings (services/events/audit_settings.py)."""

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel


class AuditEventSetting(_MarvinModel):
    """One catalog event type and whether this workspace's Event Log records it."""

    event_type: str
    name: str
    category: str
    default_audited: bool
    """The catalog default."""
    audited: bool
    """What this workspace records: the override if there is one, otherwise the default."""
    locked: bool
    """A security event: always audited, can't be changed."""


class AuditExcludedEvent(_MarvinModel):
    """An event type this workspace's Event Log does not record."""

    event_type: str
    name: str
    category: str


class AuditSettingsUpdate(_MarvinModel):
    """Overrides to merge: `{event_type: true | false}` to record or skip a type, `null` for its default.
    Types left out keep their current setting."""

    overrides: dict[str, bool | None] = Field(default_factory=dict)
