"""Form schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import UUID4, ConfigDict, Field, StringConstraints, field_validator

from marvin.schemas._marvin import _MarvinModel

FORM_STATUSES = {
    "draft",
    "published",
    "archived",
}


class FormFieldDefinition(_MarvinModel):
    """Field definition for form schema."""

    key: str
    label: str
    type: str
    required: bool = False
    placeholder: str | None = None
    validation: dict | None = None
    options: list[str] | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        valid_types = {"text", "email", "textarea", "select", "checkbox", "radio", "tel", "url", "number"}
        if value not in valid_types:
            raise ValueError(f"type must be one of: {', '.join(sorted(valid_types))}")
        return value


class FormSchemaDefinition(_MarvinModel):
    """Schema definition for forms."""

    fields: list[FormFieldDefinition]


class FormCreate(_MarvinModel):
    """Schema for creating a form."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    description: str | None = None
    status: str = "draft"
    form_schema: dict = Field(default_factory=dict, serialization_alias="schemaJson")
    settings_json: dict | None = Field(default=None, serialization_alias="settingsJson")
    metadata_json: dict | None = Field(default=None, serialization_alias="metadataJson")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in FORM_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(FORM_STATUSES))}")
        return value

    @field_validator("form_schema")
    @classmethod
    def validate_schema(cls, value: dict) -> dict:
        if value:
            FormSchemaDefinition.model_validate(value)
        return value

    model_config = ConfigDict(from_attributes=True)


class FormUpdate(_MarvinModel):
    """Schema for updating a form."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    description: str | None = None
    status: str | None = None
    form_schema: dict | None = Field(default=None, serialization_alias="schemaJson")
    settings_json: dict | None = Field(default=None, serialization_alias="settingsJson")
    metadata_json: dict | None = Field(default=None, serialization_alias="metadataJson")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in FORM_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(FORM_STATUSES))}")
        return value

    @field_validator("form_schema")
    @classmethod
    def validate_schema(cls, value: dict | None) -> dict | None:
        if value:
            FormSchemaDefinition.model_validate(value)
        return value

    model_config = ConfigDict(from_attributes=True)


class FormRead(_MarvinModel):
    """Schema for reading a form."""

    id: UUID4
    group_id: UUID4 = Field(serialization_alias="groupId")
    slug: str
    name: str
    description: str | None
    # validation_alias reads from the ORM attribute (Forms.schema_json) under from_attributes —
    # without it, model_validate(orm_obj) looked for `form_schema`/`formSchema`, found neither on the
    # ORM row, and 500'd the admin form endpoints. serialization keeps the camelCase `schemaJson`.
    form_schema: dict = Field(validation_alias="schema_json", serialization_alias="schemaJson")
    settings_json: dict | None = Field(serialization_alias="settingsJson")
    metadata_json: dict | None = Field(serialization_alias="metadataJson")
    status: str
    submissions_count: int = Field(serialization_alias="submissionsCount")
    last_submission_at: datetime | None = Field(serialization_alias="lastSubmissionAt")
    created_at: datetime | None = Field(serialization_alias="createdAt")
    update_at: datetime | None = Field(serialization_alias="updateAt")

    model_config = ConfigDict(from_attributes=True)
