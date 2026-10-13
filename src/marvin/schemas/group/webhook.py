"""
This module defines Pydantic schemas for managing group-specific webhook
configurations within the Marvin application.
"""

import datetime
import enum
from typing import Any

from pydantic import UUID4, ConfigDict, HttpUrl, ValidationInfo, field_validator, model_validator

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas._marvin.datetime_parser import parse_datetime as marvin_parse_datetime
from marvin.schemas.response.pagination import PaginationBase
from marvin.services.event_bus_service.event_types import WebhookMode  # noqa: F401 — re-exported for API consumers


class WebhookMethod(str, enum.Enum):
    GET = "GET"
    POST = "POST"


class WebhookCreate(_MarvinModel):
    """
    Schema for creating a new webhook configuration.
    Includes fields for enabling the webhook, naming it, specifying the target URL,
    HTTP method, type, and an optional scheduled time for execution.
    """

    enabled: bool = True
    name: str
    url: HttpUrl
    method: WebhookMethod = WebhookMethod.POST
    webhook_type: WebhookMode = WebhookMode.generic
    scheduled_time: datetime.datetime | None = None
    headers: dict[str, str] | None = None
    subscribed_events: list[str] | None = None
    custom_payload: dict | None = None

    @field_validator("url", mode="before")
    @classmethod
    def validate_webhook_url(cls, v: Any) -> Any:
        """Block SSRF targets in production. Localhost/private IPs allowed when PRODUCTION=False."""
        from marvin.core.config import get_app_settings

        if get_app_settings().PRODUCTION:
            import ipaddress
            from urllib.parse import urlparse

            url_str = str(v)
            parsed = urlparse(url_str)
            hostname = parsed.hostname or ""
            blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}
            if hostname in blocked_hosts:
                raise ValueError("Webhook URL cannot target localhost or internal addresses in production")
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise ValueError("Webhook URL cannot target private IP ranges in production")
            except ValueError as e:
                if "cannot target" in str(e):
                    raise
                # Not an IP address — hostname is fine
        return v

    @field_validator("scheduled_time", mode="before")
    @classmethod
    def validate_scheduled_time(cls, v: Any, info: ValidationInfo) -> datetime.datetime | None:
        if v is None or v == "":
            return None
        if isinstance(v, datetime.datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=datetime.UTC)
            return v.astimezone(datetime.UTC)
        try:
            parsed_dt = marvin_parse_datetime(v)
            return parsed_dt.astimezone(datetime.UTC)
        except (ValueError, TypeError, AttributeError):
            pass
        raise ValueError(f"Invalid format for scheduled_time: '{v}'. Expected ISO datetime string or datetime object.")


class WebhookSave(WebhookCreate):
    group_id: UUID4
    headers_json: dict[str, str] | None = None
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _sync_headers_to_headers_json(self) -> "WebhookSave":
        """Copy headers → headers_json so auto_init finds the ORM column name."""
        if self.headers is not None and self.headers_json is None:
            self.headers_json = self.headers
        return self


class WebhookUpdate(WebhookCreate):
    group_id: UUID4


class WebhookRead(WebhookUpdate):
    id: UUID4
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("url", mode="before")
    @classmethod
    def validate_webhook_url(cls, v: Any) -> Any:
        """Reads accept whatever is already stored — the SSRF block is write-only.

        WebhookCreate rejects localhost/private URLs when creating a webhook in production (SSRF
        protection at delivery time). But a row that already holds such a URL — created in dev, or
        before the rule — must stay readable, or every response embedding it 500s in production:
        GroupRead carries `list[WebhookRead]`, so one localhost webhook takes out the whole group
        read. Read models must be total over persisted data, so this overrides the inherited
        validator to a pass-through.
        """
        return v

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Bridge headers_json → headers from ORM layer."""
        if hasattr(obj, "headers_json") and obj.headers_json and not getattr(obj, "headers", None):
            obj.headers = obj.headers_json
        return super().model_validate(obj, **kwargs)


class WebhookPagination(PaginationBase):
    """
    Schema for paginated responses containing a list of webhook configurations.
    """

    items: list[WebhookRead]
    """The list of webhook configurations for the current page, serialized as `WebhookRead`."""


class WebhookExecutionLogRead(_MarvinModel):
    """Schema for reading a webhook execution log entry."""

    id: UUID4
    webhook_id: UUID4
    group_id: UUID4
    executed_at: datetime.datetime
    status: str
    http_status_code: int | None = None
    error_message: str | None = None
    retry_attempt: int = 0
    request_payload: dict | None = None
    response_body: str | None = None

    model_config = ConfigDict(from_attributes=True)
