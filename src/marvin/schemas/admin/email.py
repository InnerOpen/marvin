"""
This module defines Pydantic schemas related to administrative email functionalities
within the Marvin application.

These schemas are used for request and response models in endpoints that
check email configuration status or send test emails.
"""

from typing import Literal

from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model for Marvin schemas


class EmailReady(_MarvinModel):
    """
    Schema indicating the readiness of the email (SMTP) service.
    """

    ready: bool  # True if the email service is configured and enabled, False otherwise.


class EmailSuccess(_MarvinModel):
    """
    Schema for the response when an email operation (like sending a test email) is attempted.
    Indicates success or failure and provides an error message if applicable.
    """

    success: bool  # True if the email operation was successful, False otherwise.
    error: str | None = None  # An optional error message if the operation failed.


class EmailTest(_MarvinModel):
    """Request body for sending a test email."""

    email: str
    subject: str | None = None
    message: str | None = None


class PlatformSMTPField(_MarvinModel):
    """One platform SMTP field: the value in force, the environment's, and which of the two it is."""

    value: str | None = None
    """What's in force (the port as text); None when set nowhere."""
    env_value: str | None = None
    """What the environment (`SMTP_*`) says, whether or not an admin overrode it."""
    source: Literal["admin", "env"] | None = None


class PlatformSMTPRead(_MarvinModel):
    """The platform SMTP server (Admin → Email): the environment's settings with the admin's per-field overrides."""

    ready: bool
    """Mail can go out through it."""
    problem: str | None = None
    """When it can't, why."""
    source: Literal["admin", "env"] | None = None
    """``admin`` when any field is an admin's, ``env`` when the environment alone is complete, else None."""
    host: PlatformSMTPField
    port: PlatformSMTPField
    username: PlatformSMTPField
    auth_strategy: PlatformSMTPField
    from_name: PlatformSMTPField
    from_email: PlatformSMTPField
    password_set: bool
    """A password is in force (the value itself is never returned)."""
    password_source: Literal["admin", "env"] | None = None
    password_missing: bool = False
    """The admin's saved password can't be read from the secret store: enter it again."""
    can_store_password: bool = True
    """False with `SECRET_BACKEND=env`: the operator sets `PLATFORM_SMTP_PASSWORD` in the environment instead."""
    env_available: bool
    """The environment alone is complete."""
    env_summary: str | None = None
    """The environment's server in a line, e.g. ``smtp.example.com:587 · TLS · Marvin <hi@example.com>``."""


class PlatformSMTPUpdate(_MarvinModel):
    """Replaces the admin's fields: a blank or missing one goes back to the environment's. The password is write-only
    and left alone when blank."""

    host: str | None = None
    port: int | None = None
    username: str | None = None
    auth_strategy: str | None = None
    """TLS, SSL or NONE."""
    from_name: str | None = None
    from_email: str | None = None
    password: str | None = None
    clear_password: bool = False
    """Remove the admin's password (the environment's, if any, applies again)."""
