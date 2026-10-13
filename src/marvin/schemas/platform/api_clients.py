"""API Client schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import UUID4, ConfigDict, Field, StringConstraints

from marvin.schemas._marvin import _MarvinModel


class APIClientCreate(_MarvinModel):
    """Schema for creating a new API client."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Name of the API client."""
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """URL-friendly slug. Auto-generated from name if not provided."""
    description: str | None = None
    """Optional description of what this API client is used for."""
    permissions: dict | None = Field(
        default_factory=lambda: {
            "read:published_entries": True,
            "read:collections": True,
            "read:assets": True,
        }
    )
    """Permissions JSON. Default allows reading published entries, collections, and assets."""

    model_config = ConfigDict(from_attributes=True)


class APIClientUpdate(_MarvinModel):
    """Schema for updating an API client."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """New name for the API client."""
    description: str | None = None
    """Updated description."""
    permissions: dict | None = None
    """Updated permissions JSON."""
    enabled: bool | None = None
    """Whether the API client is enabled."""

    model_config = ConfigDict(from_attributes=True)


class APIClientSummary(_MarvinModel):
    """Summary schema for an API client."""

    id: UUID4
    """Unique identifier."""
    name: str
    """Name of the API client."""
    slug: str
    """URL-friendly slug."""
    description: str | None = None
    """Description of the API client."""
    enabled: bool
    """Whether the API client is enabled."""

    model_config = ConfigDict(from_attributes=True)


class APIClientRead(APIClientSummary):
    """Full schema for reading an API client."""

    group_id: UUID4
    """The workspace this API client belongs to."""
    permissions: dict
    """Permissions JSON."""
    last_used_at: datetime | None = None
    """When the token was last used."""
    created_at: datetime | None = None
    """When the API client was created."""
    update_at: datetime | None = None
    """When the API client was last updated."""
    revoked_at: datetime | None = None
    """When the API client was revoked."""

    model_config = ConfigDict(from_attributes=True)


class APIClientWithToken(_MarvinModel):
    """Response when creating or rotating an API client token - includes plaintext token ONCE."""

    id: UUID4
    """Unique identifier."""
    group_id: UUID4
    """The workspace this API client belongs to."""
    name: str
    """Display name."""
    slug: str
    """URL-friendly slug."""
    description: str | None = None
    """Description of the API client."""
    permissions: dict
    """Permissions JSON."""
    token: str
    """IMPORTANT: This is shown ONCE. Store it securely. Format: marvin_sk_..."""
    enabled: bool
    """Whether the API client is enabled."""
    created_at: datetime | None = None
    """When the API client was created."""

    model_config = ConfigDict(from_attributes=True)
