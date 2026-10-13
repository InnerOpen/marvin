"""Tag schemas.

A tag is a lightweight, group-scoped label from a shared vocabulary (see the ``Tags`` model).
Unlike collections, tags are created on the fly as users type them: ``POST /tags`` is
find-or-create by slug, so resolving a typed name to a stable id is a single call.
"""

from datetime import datetime
from typing import Annotated

from pydantic import UUID4, ConfigDict, StringConstraints

from marvin.schemas._marvin import _MarvinModel


class TagCreate(_MarvinModel):
    """Schema for creating (or finding) a tag.

    ``POST /tags`` is find-or-create by slug within the workspace, so posting a name that
    already exists returns the existing tag rather than erroring.
    """

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Display form as first typed ("Chore Coat"). The slug is derived from it if omitted."""
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """URL-friendly identity ("chore-coat"). Auto-generated from name if not provided."""
    color: str | None = None
    """Optional color code for UI display (e.g., '#FF5733')."""

    model_config = ConfigDict(from_attributes=True)


class TagUpdate(_MarvinModel):
    """Schema for renaming/recoloring a tag. The slug is stable and not updated here."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """New display name."""
    color: str | None = None
    """New color code."""

    model_config = ConfigDict(from_attributes=True)


class TagSummary(_MarvinModel):
    """Summary schema for a tag."""

    id: UUID4
    """Unique identifier."""
    name: str
    """Display name."""
    slug: str
    """URL-friendly identity — what smart-collection rules and the publish API match on."""
    color: str | None = None
    """Optional color code."""
    entry_count: int | None = None
    """Number of entries carrying this tag (populated by the list endpoint)."""
    usage_count: int | None = None
    """Total things carrying this tag — entries + assets + resources (populated by the list endpoint)."""
    created_at: datetime | None = None
    """Timestamp when the tag was created."""
    update_at: datetime | None = None
    """Timestamp when the tag was last updated."""

    model_config = ConfigDict(from_attributes=True)


class TagRead(TagSummary):
    """Full schema for reading a tag."""

    group_id: UUID4
    """The workspace/group this tag belongs to."""

    model_config = ConfigDict(from_attributes=True)
