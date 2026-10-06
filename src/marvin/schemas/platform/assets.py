"""Asset schemas."""

from typing import Annotated, Any, Literal

from pydantic import UUID4, AliasChoices, ConfigDict, Field, StringConstraints, field_serializer, field_validator, model_validator

from marvin.schemas._marvin import _MarvinModel


class AssetUploadRequest(_MarvinModel):
    """Skinny schema for asset upload - client provides editorial metadata only."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """URL-friendly slug for the asset."""
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Name of the asset."""
    alt_text: str | None = None
    """Alt text for accessibility."""
    description: str | None = None
    """Optional description of the asset."""
    metadata_json: dict | None = Field(default=None, validation_alias=AliasChoices("metadata", "metadata_json"))
    """Optional asset metadata."""

    model_config = ConfigDict(from_attributes=True)


class AssetCreateInternal(_MarvinModel):
    """Internal schema for creating asset database record with all fields."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

    original_filename: str
    filename: str
    extension: str

    file_path: str | None = None
    file_size: int
    mime_type: str
    asset_type: Literal["image", "document", "video", "audio", "archive", "svg", "other"]
    checksum: str

    width: int | None = None
    height: int | None = None
    orientation: int | None = None

    storage_provider: str
    storage_key: str
    public_url: str | None = None

    alt_text: str | None = None
    description: str | None = None
    metadata_json: dict | None = Field(default=None, validation_alias=AliasChoices("metadata", "metadata_json"))

    model_config = ConfigDict(from_attributes=True)


class AssetUpdate(_MarvinModel):
    """Schema for updating editable asset fields."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    alt_text: str | None = Field(default=None, validation_alias=AliasChoices("alt_text", "altText"))
    description: str | None = None
    metadata_json: dict | None = Field(default=None, validation_alias=AliasChoices("metadata", "metadata_json"))
    tag_ids: list[UUID4] | None = Field(default=None, validation_alias=AliasChoices("tag_ids", "tagIds"))
    """Existing tag IDs to replace this asset's tags (resolve typed names via POST /tags first)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AssetCreate(_MarvinModel):
    """Legacy schema for backwards compatibility - prefer AssetCreateInternal."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """URL-friendly slug for the asset."""
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Name of the asset."""
    file_path: Annotated[str, StringConstraints(min_length=1)]
    """Path to the file in storage."""
    file_size: int
    """Size of the file in bytes."""
    mime_type: str
    """MIME type of the file."""
    width: int | None = None
    """Width in pixels (for images)."""
    height: int | None = None
    """Height in pixels (for images)."""
    alt_text: str | None = None
    """Alt text for accessibility."""
    description: str | None = None
    """Optional description of the asset."""
    metadata_json: dict | None = Field(default=None, validation_alias=AliasChoices("metadata", "metadata_json"))
    """Optional asset metadata."""

    model_config = ConfigDict(from_attributes=True)


class AssetSummary(_MarvinModel):
    """Summary schema for an asset."""

    id: UUID4
    """Unique identifier."""
    slug: str
    """URL-friendly slug."""
    name: str
    """Name of the asset."""
    mime_type: str
    """MIME type of the file."""
    alt_text: str | None = None
    """Alt text for accessibility."""

    model_config = ConfigDict(from_attributes=True)


class AssetRead(AssetSummary):
    """Full schema for reading an asset."""

    original_filename: str
    filename: str
    extension: str

    file_size: int
    """Size of the file in bytes."""
    asset_type: Literal["image", "document", "video", "audio", "archive", "svg", "other"]
    checksum: str

    width: int | None = None
    """Width in pixels."""
    height: int | None = None
    """Height in pixels."""
    orientation: int | None = None

    storage_provider: str
    storage_key: str
    public_url: str | None = None

    description: str | None = None
    """Optional description."""
    metadata_json: dict | None = Field(default=None, validation_alias=AliasChoices("metadata_json"))
    """Optional asset metadata."""
    uploaded_by: UUID4
    """ID of user who uploaded the asset."""
    tags: list[str] = []
    """Tag slugs applied to this asset (shared vocabulary)."""
    suggestion_json: dict | None = Field(
        default=None,
        description="Pending AI-proposed changes staged for review (write-back)",
        serialization_alias="suggestionJson",
    )

    @field_validator("tags", mode="before")
    @classmethod
    def _tag_slugs(cls, value: Any) -> list[str]:
        # `obj.tags` is the ORM Tag relationship; the schema field is a list of slug strings.
        if not value:
            return []
        return [getattr(t, "slug", t) for t in value]

    @field_validator("metadata_json", mode="before")
    @classmethod
    def validate_metadata(cls, value: Any) -> dict | None:
        """Ensure metadata is a dict, not SQLAlchemy MetaData."""
        if value is None:
            return None
        if hasattr(value, "__class__") and value.__class__.__name__ == "MetaData":
            return None
        if not isinstance(value, dict):
            return None
        return value

    @field_serializer("metadata_json")
    def serialize_metadata(self, value: dict | None, _info) -> dict | None:
        """Ensure metadata is serialized as dict."""
        return value if isinstance(value, dict) else None

    @model_validator(mode="after")
    def compute_public_url(self) -> "AssetRead":
        if not self.storage_key:
            return self
        try:
            from marvin.services.storage.provider_factory import provider_for

            self.public_url = provider_for(self).get_public_url(self.storage_key)
        except Exception:
            pass  # retain DB value as degraded fallback if provider config is broken
        return self

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AssetPlacement(_MarvinModel):
    """How an asset is used by a specific entry."""

    role: str | None = None
    """Role for this entry, such as hero, featured, support, inline, or download."""
    position: int = 0
    """Display order for this entry."""
    placement_metadata: dict | None = Field(
        default=None,
        validation_alias=AliasChoices("placement_metadata", "metadata_json"),
    )
    """Optional placement metadata."""

    @field_validator("placement_metadata", mode="before")
    @classmethod
    def validate_placement_metadata(cls, value: Any) -> dict | None:
        """Ensure placement_metadata is a dict, not SQLAlchemy MetaData."""
        if value is None:
            return None
        # If it's a SQLAlchemy MetaData object, return None instead
        if hasattr(value, "__class__") and value.__class__.__name__ == "MetaData":
            return None
        # If it's not a dict, try to convert or return None
        if not isinstance(value, dict):
            return None
        return value

    model_config = ConfigDict(from_attributes=True)


class EntryAssetRead(AssetRead, AssetPlacement):
    """Asset metadata plus entry-specific placement details."""

    model_config = ConfigDict(from_attributes=True)
