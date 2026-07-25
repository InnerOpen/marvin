"""Pydantic schemas for workspace SMTP profiles.

The password is write-only: accepted on create/update, never returned. Reads
expose a `has_password` boolean instead so the UI can show whether one is stored.
The password field also accepts a reference to an existing workspace secret —
`{{SLUG}}` or a bare uppercase `SLUG` — instead of a literal value.
"""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, ConfigDict, Field

from marvin.schemas._marvin import _MarvinModel

AuthStrategy = Literal["TLS", "SSL", "NONE"]

_PASSWORD_DESC = "Literal SMTP password, or a reference to an existing workspace secret as {{SLUG}} or a bare uppercase SLUG."


class SMTPProfileCreate(_MarvinModel):
    name: str
    host: str
    port: int = 587
    username: str | None = None
    password: str | None = Field(default=None, description=_PASSWORD_DESC)
    from_name: str | None = None
    from_email: str | None = None
    auth_strategy: AuthStrategy = "TLS"
    is_active: bool = False

    model_config = ConfigDict(from_attributes=True)


class SMTPProfileUpdate(_MarvinModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = Field(default=None, description=_PASSWORD_DESC)
    from_name: str | None = None
    from_email: str | None = None
    auth_strategy: AuthStrategy | None = None
    is_active: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class SMTPProfileRead(_MarvinModel):
    id: UUID4
    group_id: UUID4
    name: str
    host: str
    port: int
    username: str | None = None
    from_name: str | None = None
    from_email: str | None = None
    auth_strategy: str = "TLS"
    is_active: bool = False
    has_password: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SMTPProfileTestRequest(_MarvinModel):
    recipient_email: str


class SMTPProfileTestResult(_MarvinModel):
    success: bool
    message: str
