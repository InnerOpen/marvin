"""Collection schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import UUID4, AliasChoices, ConfigDict, Field, StringConstraints, field_validator

from marvin.schemas._marvin import _MarvinModel
from marvin.services.entry_listing import check_listed_rule


def _checked_rules(rules: dict | None) -> dict | None:
    """The ``smart_rules`` validator: ``listed`` (any | listed | unlisted) is the one rule key whose value is checked on save;
    the other keys are read leniently by ``matches_rules`` (services/collections/smart_collections.py)."""
    check_listed_rule(rules)
    return rules


class CollectionCreate(_MarvinModel):
    """Schema for creating a new collection."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Name of the collection."""
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """URL-friendly slug for the collection. Auto-generated from name if not provided."""
    description: str | None = None
    """Optional description of the collection."""
    sort_order: int = 0
    """Display order for UI (lower numbers first)."""
    icon: str | None = None
    """Optional icon identifier for UI display."""
    color: str | None = None
    """Optional color code for UI display (e.g., '#FF5733')."""
    is_smart: bool = False
    """Whether this is a smart collection based on rules."""
    smart_rules: dict | None = None
    """Optional rules for smart collections."""
    target_type: str = "entry"
    """Which entity type this collection groups: 'entry' (default), 'asset', or 'resource'."""
    is_public: bool = True
    """Whether this collection is exposed via the publish API."""
    metadata_json: dict | None = None
    """Custom metadata for this collection."""
    entry_ids: list[UUID4] | None = None
    """Optional list of entry IDs to add to this collection."""

    model_config = ConfigDict(from_attributes=True)

    _check_rules = field_validator("smart_rules")(_checked_rules)


class CollectionUpdate(_MarvinModel):
    """Schema for updating a collection."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """Name of the collection."""
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """URL-friendly slug for the collection."""
    description: str | None = None
    """Optional description of the collection."""
    sort_order: int | None = None
    """Display order for UI."""
    icon: str | None = None
    """Optional icon identifier."""
    color: str | None = None
    """Optional color code."""
    is_smart: bool | None = None
    """Whether this is a smart collection based on rules."""
    smart_rules: dict | None = None
    """Optional rules for smart collections."""
    target_type: str | None = None
    """Which entity type this collection groups: 'entry', 'asset', or 'resource'."""
    is_public: bool | None = None
    """Whether this collection is exposed via the publish API."""
    in_sidebar: bool | None = None
    """Whether the app sidebar lists this collection under Collections."""
    metadata_json: dict | None = None
    """Custom metadata for this collection."""
    entry_ids: list[UUID4] | None = None
    """Optional list of entry IDs to replace existing entries in this collection."""

    model_config = ConfigDict(from_attributes=True)

    _check_rules = field_validator("smart_rules")(_checked_rules)


class CollectionSummary(_MarvinModel):
    """Summary schema for a collection."""

    id: UUID4
    """Unique identifier."""
    name: str
    """Name of the collection."""
    slug: str
    """URL-friendly slug."""
    description: str | None = None
    """Optional description."""
    sort_order: int
    """Display order."""
    icon: str | None = None
    """Optional icon identifier."""
    color: str | None = None
    """Optional color code."""
    is_smart: bool
    """Whether this is a smart collection."""
    target_type: str = "entry"
    """Which entity type this collection groups: 'entry', 'asset', or 'resource'."""
    is_system: bool = False
    """System workflow collection — locked from edit/delete and internal-only."""
    is_public: bool = True
    """Whether this collection is exposed via the publish API."""
    in_sidebar: bool = True
    """Whether the app sidebar lists this collection under Collections."""
    entry_count: int | None = None
    """Number of entries in this collection (populated by the list endpoint)."""
    created_at: datetime | None = None
    """Timestamp when the collection was created."""
    update_at: datetime | None = None
    """Timestamp when the collection was last updated."""

    model_config = ConfigDict(from_attributes=True)


class CollectionRead(CollectionSummary):
    """Full schema for reading a collection."""

    group_id: UUID4
    """The workspace/group this collection belongs to."""
    smart_rules: dict | None = None
    """Optional rules for smart collections."""
    metadata_json: dict | None = None
    """Custom metadata for this collection."""
    source_integration_id: UUID4 | None = None
    """Read-only "installed by": the integration whose blueprint created this (null: made by a person)."""
    source_blueprint: str | None = None
    """Read-only: the slug of the blueprint that created this, if one did."""
    source_integration_name: str | None = None
    """Read-only: that integration's name (the sidebar groups its collections under it)."""
    source_integration_provider: str | None = None
    """Read-only: that integration's provider slug (the sidebar shows its logo on the group)."""
    source_integration_icon: str | None = None
    """Read-only: the provider's emoji, for when it ships no logo."""
    source_integration_has_logo: bool = False
    """Read-only: whether the provider ships a logo (served by GET /api/groups/integrations/providers/{slug}/logo)."""

    model_config = ConfigDict(from_attributes=True)


class UpdateEntryCollectionRequest(_MarvinModel):
    """Schema for updating junction fields on an entry-collection relationship."""

    role: str | None = None
    metadata_json: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class EntryCollectionRead(_MarvinModel):
    """Collection summary with entry-specific placement details."""

    id: UUID4
    name: str
    slug: str
    icon: str | None = None
    color: str | None = None
    role: str | None = None
    placement_metadata: dict | None = Field(
        default=None,
        validation_alias=AliasChoices("placement_metadata", "metadata_json"),
    )
    sort_order: int = 0

    @field_validator("placement_metadata", mode="before")
    @classmethod
    def validate_placement_metadata(cls, value: Any) -> dict | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        return value

    model_config = ConfigDict(from_attributes=True)


class SmartRulesPreviewRequest(_MarvinModel):
    """Unsaved smart-collection rules to evaluate against the workspace."""

    target_type: Literal["entry", "asset", "resource"] = "entry"
    """Which kind of item the rules select."""
    smart_rules: dict | None = None
    """The rules, in the same shape as ``CollectionCreate.smart_rules``."""
    limit: int = Field(default=10, ge=0, le=50)
    """How many matching items to list (newest first); ``total`` counts them all."""

    _check_rules = field_validator("smart_rules")(_checked_rules)


class SmartRulesPreviewItem(_MarvinModel):
    """One item the rules match."""

    id: UUID4
    label: str
    slug: str | None = None
    type: str


class SmartRulesPreview(_MarvinModel):
    """What a smart collection with these rules would contain if saved now."""

    total: int
    """Every match, not just the listed ones."""
    items: list[SmartRulesPreviewItem]
    """The first ``limit`` matches, newest first."""
    ignored_keys: list[str] = []
    """Keys in the rules this target type doesn't read (e.g. a workflow query's ``entry_type``)."""
    note: str | None = None
    """Why nothing can match, when that's knowable (e.g. an empty rule set)."""
