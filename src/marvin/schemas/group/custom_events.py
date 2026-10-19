"""A workspace's own events (services/events/custom_events.py): what it registers and what the API returns."""

import re
from typing import Literal

from pydantic import Field, field_validator

from marvin.schemas._marvin import _MarvinModel

PREFIX = "custom."
FIELD_TYPES = ("string", "number", "boolean", "date")
MAX_EVENTS = 50
MAX_FIELDS = 12
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SLUG_HINT = "start with a letter and use lowercase letters, digits and underscores only (40 characters at most)"

FieldType = Literal["string", "number", "boolean", "date"]


class CustomEventField(_MarvinModel):
    """One value an event carries, in `payload.<key>` (a workflow reads `${event.payload.<key>}`)."""

    key: str
    type: FieldType = "string"
    description: str | None = Field(default=None, max_length=200)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SLUG.match(value):
            raise ValueError(f"A field key must {_SLUG_HINT}.")
        return value


class CustomEventDefinition(_MarvinModel):
    """An event the workspace registers: `custom.<name>` with the fields its payload carries."""

    name: str
    """The slug after `custom.`; `custom.` in front of it is accepted and dropped."""
    title: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    fields: list[CustomEventField] = Field(default_factory=list, max_length=MAX_FIELDS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip().lower().removeprefix(PREFIX)
        if not _SLUG.match(value):
            raise ValueError(f"An event name is `custom.` and a slug that must {_SLUG_HINT}.")
        return value

    @field_validator("title", "description")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("fields")
    @classmethod
    def _unique_keys(cls, fields: list[CustomEventField]) -> list[CustomEventField]:
        keys = [f.key for f in fields]
        if len(set(keys)) != len(keys):
            raise ValueError("Each field needs its own key.")
        return fields


class CustomEventSave(_MarvinModel):
    """The body of PUT /groups/custom-events/{name}: everything but the name, which is in the path."""

    title: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    fields: list[CustomEventField] = Field(default_factory=list, max_length=MAX_FIELDS)


class CustomEventRead(CustomEventDefinition):
    event_type: str
    """The full event name, `custom.<name>`."""
    used_by: list[str] = Field(default_factory=list)
    """Names of the workflows that start on it or send it."""
