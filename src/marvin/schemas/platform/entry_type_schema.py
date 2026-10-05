"""Entry type schema definition models for schema-driven content.

This module defines the field schema models that power Marvin's schema-driven
content system. Entry Types define schemas that specify what fields exist,
how they are edited, and validation rules.

The schema uses discriminated unions (via Pydantic's Literal types) to model
different field types, following Marvin's existing pattern from scheduled tasks
(schedule_type: Literal["cron", "interval", "once"]).
"""

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from marvin.schemas._marvin import _MarvinModel


class BaseFieldSchema(_MarvinModel):
    """Base schema for all field types.

    Defines common properties shared across all field types:
    - Identification (key, label)
    - Validation (required, default_value)
    - UI hints (placeholder, help_text, read_only)
    """

    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")]
    """Field identifier (used as key in data_json). Must be a valid Python identifier."""

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Display label shown to editors in the UI."""

    required: bool = Field(default=False)
    """Whether this field is mandatory. Validated when creating/updating entries."""

    default_value: Any | None = Field(default=None, alias="defaultValue")
    """Default value used when field is not provided."""

    placeholder: str | None = None
    """Placeholder text shown in empty inputs."""

    help_text: str | None = Field(default=None, alias="helpText")
    """Help text shown to editors to explain the field's purpose. Also fed to AI compose as
    context, so keep it useful for both a human filling the form and the model authoring the field."""

    ai_hint: str | None = Field(default=None, alias="aiHint")
    """Directive, AI-only authoring guidance for this field (e.g. desired length, voice, what to
    include). Layered on top of help_text in the compose prompt; not shown as form helper text."""

    read_only: bool = Field(default=False, alias="readOnly")
    """If true, field cannot be edited (useful for computed/system fields)."""


class TextFieldSchema(BaseFieldSchema):
    """Single-line text input field."""

    type: Literal["text"]
    min: int | None = Field(default=None, description="Minimum string length")
    max: int | None = Field(default=None, description="Maximum string length")
    pattern: str | None = Field(default=None, description="Regex pattern for validation")


class TextareaFieldSchema(BaseFieldSchema):
    """Multi-line plain text field."""

    type: Literal["textarea"]
    min: int | None = Field(default=None, description="Minimum string length")
    max: int | None = Field(default=None, description="Maximum string length")
    rows: int | None = Field(default=None, description="Number of visible rows")


class MarkdownFieldSchema(BaseFieldSchema):
    """Markdown editor field."""

    type: Literal["markdown"]
    auto_embed: bool = Field(default=True, alias="autoEmbed")
    """A supported media link (YouTube, Vimeo, Spotify, …) alone on its own line becomes a player on the
    site (published under the entry's ``embeds``). ``false`` keeps every link in this field a plain link."""


class NumberFieldSchema(BaseFieldSchema):
    """Numeric input field (integer or float)."""

    type: Literal["number"]
    min: float | None = None
    max: float | None = None
    step: float | None = Field(default=None, description="Increment step for number input")


class BooleanFieldSchema(BaseFieldSchema):
    """Boolean toggle/checkbox field."""

    type: Literal["boolean"]


class SelectFieldSchema(BaseFieldSchema):
    """Dropdown selection field with predefined options."""

    type: Literal["select"]
    options: list[str] = Field(..., description="Valid options for selection", min_length=1)
    multiple: bool = Field(default=False, description="Allow multiple selections")


class DateFieldSchema(BaseFieldSchema):
    """Date picker field (date only, no time)."""

    type: Literal["date"]


class DateTimeFieldSchema(BaseFieldSchema):
    """Date and time picker field."""

    type: Literal["datetime"]


class JsonFieldSchema(BaseFieldSchema):
    """Free-form JSON object field.

    Allows arbitrary JSON data (object, array, etc).
    Use sparingly - prefer structured fields when possible.
    """

    type: Literal["json"]


class EmbedFieldSchema(BaseFieldSchema):
    """A media player slot. Value is a supported media link (YouTube, Vimeo, Spotify, SoundCloud, …),
    published resolved under the entry's ``embeds``."""

    type: Literal["embed"]
    providers: list[str] | None = Field(default=None, description="Allowed provider keys (e.g. ['youtube', 'vimeo']); empty = any")

    @field_validator("providers")
    @classmethod
    def _known_providers(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        from marvin.services.media_embeds.providers import PROVIDERS

        unknown = [p for p in value if p not in PROVIDERS]
        if unknown:
            raise ValueError(f"Unknown media providers {unknown}; known: {sorted(PROVIDERS)}")
        return value


class AssetFieldSchema(BaseFieldSchema):
    """A single linked asset (image/file). Value is an asset id."""

    type: Literal["asset"]
    model_config = ConfigDict(extra="allow")


class AssetListFieldSchema(BaseFieldSchema):
    """Multiple linked assets. Value is a list of asset ids."""

    type: Literal["asset-list"]
    min: int | None = None
    max: int | None = None
    model_config = ConfigDict(extra="allow")


class ResourceFieldSchema(BaseFieldSchema):
    """A single linked resource. Value is a resource id."""

    type: Literal["resource"]
    model_config = ConfigDict(extra="allow")


class ResourceListFieldSchema(BaseFieldSchema):
    """Multiple linked resources. Value is a list of resource ids."""

    type: Literal["resource-list"]
    min: int | None = None
    max: int | None = None
    model_config = ConfigDict(extra="allow")


# Discriminated union of all field types. Asset/resource relationship fields are first-class
# here (they also render via the entry editor's sidebar pickers).
FieldSchema = Annotated[
    TextFieldSchema
    | TextareaFieldSchema
    | MarkdownFieldSchema
    | NumberFieldSchema
    | BooleanFieldSchema
    | SelectFieldSchema
    | DateFieldSchema
    | DateTimeFieldSchema
    | JsonFieldSchema
    | EmbedFieldSchema
    | AssetFieldSchema
    | AssetListFieldSchema
    | ResourceFieldSchema
    | ResourceListFieldSchema,
    Field(discriminator="type"),
]
"""
Discriminated union of all field schema types.

Pydantic automatically validates and deserializes to the correct field type
based on the 'type' field.

Note: Asset and Resource relationships are managed through the entry edit UI
sidebar, not through the schema system.
"""


class EntryTypeSchemaDefinition(_MarvinModel):
    """Entry type schema definition.

    Defines the structure of an Entry Type's content model:
    - What fields exist
    - Field types and validation rules
    - Default values
    - UI configuration

    This schema is stored in entry_types.schema_json and used to validate
    entries.data_json when creating/updating entries.

    Example:
        ```json
        {
            "fields": [
                {
                    "key": "body",
                    "label": "Content",
                    "type": "markdown",
                    "required": false
                },
                {
                    "key": "difficulty",
                    "label": "Difficulty",
                    "type": "select",
                    "options": ["beginner", "intermediate", "advanced"],
                    "defaultValue": "beginner"
                }
            ]
        }
        ```
    """

    fields: list[FieldSchema] = Field(default_factory=list)
    """List of field definitions for this entry type."""

    def get_field(self, key: str) -> FieldSchema | None:
        """Get a field definition by key.

        Args:
            key: The field key to search for

        Returns:
            The field schema if found, None otherwise
        """
        for field in self.fields:
            if field.key == key:
                return field
        return None

    def get_required_fields(self) -> list[FieldSchema]:
        """Get all required fields.

        Returns:
            List of field schemas marked as required
        """
        return [field for field in self.fields if field.required]

    def get_field_keys(self) -> set[str]:
        """Get all field keys defined in the schema.

        Returns:
            Set of field keys
        """
        return {field.key for field in self.fields}
