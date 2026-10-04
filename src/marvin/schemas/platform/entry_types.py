"""Entry type schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import UUID4, AliasChoices, ConfigDict, Field, StringConstraints, field_validator

from marvin.core.root_logger import get_logger
from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe
from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition, RenderingDefinition
from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
from marvin.services.entry_urls import normalize_page_url_pattern

logger = get_logger(__name__)


class EntryTypeCreate(_MarvinModel):
    """Schema for creating an entry type."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    # Nullable with a None default (not `= 0` / `= False`) so the generated OpenAPI/SDK type
    # marks them optional: openapi-typescript treats a non-null default as "always present"
    # (→ required in TS). The repo's create() coalesces None back to the real defaults, so
    # runtime behavior is unchanged. Mirrors EntryTypeUpdate.
    sort_order: int | None = None
    is_system: bool | None = None
    is_rendered: bool | None = None
    content_schema: dict | None = Field(
        default=None,
        description="Entry type schema definition (EntryTypeSchemaDefinition)",
        serialization_alias="schemaJson",
        validation_alias=AliasChoices("schemaJson", "schema_json"),
    )
    rendering: dict | None = Field(
        default=None,
        description="Rendering configuration (RenderingDefinition)",
        serialization_alias="renderingJson",
        validation_alias=AliasChoices("renderingJson", "rendering_json"),
    )
    capabilities: dict | None = Field(
        default=None,
        description="Behavioral capabilities (CapabilitiesDefinition)",
        serialization_alias="capabilitiesJson",
        validation_alias=AliasChoices("capabilitiesJson", "capabilities_json"),
    )
    recipe: dict | None = Field(
        default=None,
        description="Authoring recipe (EntryTypeRecipe)",
        serialization_alias="recipeJson",
        validation_alias=AliasChoices("recipeJson", "recipe_json"),
    )
    page_url_pattern: str | None = Field(
        default=None,
        description="Where the site renders an entry of this type, e.g. /works/{slug}. Placeholders: {slug}, {id}, {entry_type}.",
    )

    @field_validator("content_schema")
    @classmethod
    def validate_content_schema(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        try:
            EntryTypeSchemaDefinition.model_validate(value)
        except Exception as e:
            logger.warning("Schema validation warning (unsupported field types will be preserved): %s", e)
        return value

    @field_validator("rendering")
    @classmethod
    def validate_rendering(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        RenderingDefinition.model_validate(value)
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        CapabilitiesDefinition.model_validate(value)
        return value

    @field_validator("recipe")
    @classmethod
    def validate_recipe(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        EntryTypeRecipe.model_validate(value)
        return value

    @field_validator("page_url_pattern")
    @classmethod
    def validate_page_url_pattern(cls, value: str | None) -> str | None:
        return normalize_page_url_pattern(value)

    model_config = ConfigDict(from_attributes=True)


class EntryTypeUpdate(_MarvinModel):
    """Schema for patching an entry type."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_system: bool | None = None
    is_rendered: bool | None = None
    content_schema: dict | None = Field(
        default=None,
        description="Entry type schema definition (EntryTypeSchemaDefinition)",
        serialization_alias="schemaJson",
        validation_alias=AliasChoices("schemaJson", "schema_json"),
    )
    rendering: dict | None = Field(
        default=None,
        description="Rendering configuration (RenderingDefinition)",
        serialization_alias="renderingJson",
        validation_alias=AliasChoices("renderingJson", "rendering_json"),
    )
    capabilities: dict | None = Field(
        default=None,
        description="Behavioral capabilities (CapabilitiesDefinition)",
        serialization_alias="capabilitiesJson",
        validation_alias=AliasChoices("capabilitiesJson", "capabilities_json"),
    )
    recipe: dict | None = Field(
        default=None,
        description="Authoring recipe (EntryTypeRecipe)",
        serialization_alias="recipeJson",
        validation_alias=AliasChoices("recipeJson", "recipe_json"),
    )
    page_url_pattern: str | None = Field(
        default=None,
        description="Where the site renders an entry of this type, e.g. /works/{slug}. Placeholders: {slug}, {id}, {entry_type}.",
    )

    @field_validator("content_schema")
    @classmethod
    def validate_content_schema(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        try:
            EntryTypeSchemaDefinition.model_validate(value)
        except Exception as e:
            logger.warning("Schema validation warning (unsupported field types will be preserved): %s", e)
        return value

    @field_validator("rendering")
    @classmethod
    def validate_rendering(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        RenderingDefinition.model_validate(value)
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        CapabilitiesDefinition.model_validate(value)
        return value

    @field_validator("recipe")
    @classmethod
    def validate_recipe(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        EntryTypeRecipe.model_validate(value)
        return value

    @field_validator("page_url_pattern")
    @classmethod
    def validate_page_url_pattern(cls, value: str | None) -> str | None:
        return normalize_page_url_pattern(value)

    model_config = ConfigDict(from_attributes=True)


class EntryTypeRead(_MarvinModel):
    """Schema for reading an entry type.

    System entry types have group_id=None and are globally available to all workspaces.
    Workspace-scoped entry types have a specific group_id.
    """

    id: UUID4
    group_id: UUID4 | None
    name: str
    slug: str
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    sort_order: int
    is_system: bool
    is_rendered: bool = False
    content_schema: dict | None = Field(
        default=None,
        description="Entry type schema definition (EntryTypeSchemaDefinition)",
        serialization_alias="schemaJson",
        validation_alias=AliasChoices("schemaJson", "schema_json"),
    )
    rendering: dict | None = Field(
        default=None,
        description="Rendering configuration (RenderingDefinition)",
        serialization_alias="renderingJson",
        validation_alias=AliasChoices("renderingJson", "rendering_json"),
    )
    capabilities: dict | None = Field(
        default=None,
        description="Behavioral capabilities (CapabilitiesDefinition)",
        serialization_alias="capabilitiesJson",
        validation_alias=AliasChoices("capabilitiesJson", "capabilities_json"),
    )
    recipe: dict | None = Field(
        default=None,
        description="Authoring recipe (EntryTypeRecipe)",
        serialization_alias="recipeJson",
        validation_alias=AliasChoices("recipeJson", "recipe_json"),
    )
    page_url_pattern: str | None = Field(
        default=None,
        description="Where the site renders an entry of this type, e.g. /works/{slug}. Placeholders: {slug}, {id}, {entry_type}.",
    )
    created_at: datetime | None = None
    update_at: datetime | None = None
    warnings: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


class EntryTypeSummary(EntryTypeRead):
    """Summary schema for an entry type."""

    pass
