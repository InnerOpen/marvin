"""Submission protection settings — spam controls for public submissions to submittable entry types.

Two layers share one shape. The platform admin sets concrete defaults (`SubmissionProtectionSettings`);
a workspace may override any field (`SubmissionProtectionOverride`, where ``None`` means "inherit the
platform default"). `resolve_submission_protection` merges them field by field at submit time.
"""

from typing import Literal

from pydantic import Field, field_validator

from marvin.schemas._marvin import _MarvinModel

SubmissionProtectionMode = Literal["off", "review", "reject"]

DEFAULT_SURGE_WINDOW_MINUTES = 10


def _normalize_domains(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        domain = raw.strip().lower().lstrip("@")
        if domain and domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out


class SubmissionProtectionSettings(_MarvinModel):
    """Concrete, fully-resolved settings (also the platform-default shape)."""

    mode: SubmissionProtectionMode = "review"
    """What to do with a suspicious submission: ``off`` (no checks), ``review`` (accept but land it as
    ``needs_review`` with the reasons recorded), ``reject`` (400)."""
    blocked_domains: list[str] = Field(default_factory=list)
    """Email domains that are always suspicious."""
    allowed_domains: list[str] = Field(default_factory=list)
    """When non-empty, only these email domains are accepted without flagging."""
    block_disposable_domains: bool = True
    """Flag well-known throwaway email providers (bundled preset)."""
    block_personal_domains: bool = False
    """Flag consumer webmail providers (gmail, yahoo, …). Useful for B2B-only forms."""
    capture_client_info: bool = True
    """Record the submitter's IP address, user agent and referer on the entry and in the event."""
    exempt_ips: list[str] = Field(default_factory=list)
    """IPs or CIDR ranges that skip every check (your office, monitoring, test rigs)."""
    surge_threshold: int | None = Field(default=None, ge=1)
    """Emit ``submission_surge_detected`` when one form receives this many submissions in the window."""
    surge_window_minutes: int = Field(default=DEFAULT_SURGE_WINDOW_MINUTES, ge=1)

    @field_validator("blocked_domains", "allowed_domains", mode="after")
    @classmethod
    def _clean_domains(cls, value: list[str]) -> list[str]:
        return _normalize_domains(value)

    @field_validator("exempt_ips", mode="after")
    @classmethod
    def _clean_ips(cls, value: list[str]) -> list[str]:
        return [v.strip() for v in value if v.strip()]


class SubmissionProtectionOverride(_MarvinModel):
    """Workspace-level override: every field optional, ``None`` inherits the platform default."""

    mode: SubmissionProtectionMode | None = None
    blocked_domains: list[str] | None = None
    allowed_domains: list[str] | None = None
    block_disposable_domains: bool | None = None
    block_personal_domains: bool | None = None
    capture_client_info: bool | None = None
    exempt_ips: list[str] | None = None
    surge_threshold: int | None = Field(default=None, ge=1)
    surge_window_minutes: int | None = Field(default=None, ge=1)

    @field_validator("blocked_domains", "allowed_domains", mode="after")
    @classmethod
    def _clean_domains(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalize_domains(value)


def resolve_submission_protection(platform: dict | None, workspace: dict | None) -> SubmissionProtectionSettings:
    """Merge a workspace override onto the platform defaults, field by field.

    Both inputs are the raw stored dicts (snake_case or camelCase keys — the models accept either).
    A workspace field set to ``None`` (or absent) inherits; anything else wins.
    """
    base = SubmissionProtectionSettings.model_validate(platform or {})
    if not workspace:
        return base
    override = SubmissionProtectionOverride.model_validate(workspace)
    merged = base.model_dump()
    merged.update({k: v for k, v in override.model_dump().items() if v is not None})
    return SubmissionProtectionSettings.model_validate(merged)


class SubmissionProtectionStatus(_MarvinModel):
    """What a workspace sees: the platform defaults, its own override, and the merged result."""

    platform_defaults: SubmissionProtectionSettings
    workspace_override: SubmissionProtectionOverride
    effective: SubmissionProtectionSettings
