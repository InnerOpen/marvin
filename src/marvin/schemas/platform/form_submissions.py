"""Form submission schemas."""

from datetime import datetime

from pydantic import UUID4, ConfigDict, Field

from marvin.schemas._marvin import _MarvinModel


class FormSubmissionCreate(_MarvinModel):
    """Schema for creating a form submission."""

    data_json: dict = Field(serialization_alias="dataJson")

    model_config = ConfigDict(from_attributes=True)


class FormSubmissionRead(_MarvinModel):
    """Schema for reading a form submission."""

    id: UUID4
    form_id: UUID4 = Field(serialization_alias="formId")
    group_id: UUID4 = Field(serialization_alias="groupId")
    data_json: dict = Field(serialization_alias="dataJson")
    metadata_json: dict | None = Field(serialization_alias="metadataJson")
    status: str
    ip_address: str | None = Field(serialization_alias="ipAddress")
    user_agent: str | None = Field(serialization_alias="userAgent")
    referrer: str | None
    submitted_at: datetime = Field(serialization_alias="submittedAt")
    processed_at: datetime | None = Field(serialization_alias="processedAt")

    model_config = ConfigDict(from_attributes=True)
