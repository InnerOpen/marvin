"""A stored webhook with a localhost URL must stay readable in production.

WebhookCreate blocks localhost/private URLs when a webhook is *created* in production — SSRF
protection at delivery time. That validator is inherited all the way down to WebhookRead, so once a
row held such a URL (created in dev, or before the rule), *reading* it in production raised a
ValidationError. GroupRead embeds `list[WebhookRead]`, so a single localhost webhook 500'd the whole
group read — which took out GET /api/admin/groups and every page that loads groups. Reads must be
total over persisted data; the SSRF block is write-only.
"""

import uuid

import pytest
from pydantic import ValidationError

from marvin.core.config import get_app_settings
from marvin.schemas.group.webhook import WebhookCreate, WebhookRead


@pytest.fixture
def production_mode(monkeypatch):
    """Force PRODUCTION=True for the duration of a test (the validator only fires then)."""
    settings = get_app_settings()
    monkeypatch.setattr(settings, "PRODUCTION", True)
    yield


def _read_payload(**overrides) -> dict:
    payload = {
        "id": uuid.uuid4(),
        "group_id": uuid.uuid4(),
        "name": "inbox",
        "url": "https://example.com/hook",
    }
    payload.update(overrides)
    return payload


def test_read_accepts_a_stored_localhost_url_in_production(production_mode):
    """The regression: this used to raise, taking GroupRead down with it."""
    webhook = WebhookRead(**_read_payload(url="http://localhost:8083/hook"))

    assert str(webhook.url).startswith("http://localhost:8083")


def test_read_accepts_a_private_ip_url_in_production(production_mode):
    webhook = WebhookRead(**_read_payload(url="http://10.0.0.5/hook"))

    assert "10.0.0.5" in str(webhook.url)


def test_read_still_accepts_a_public_url(production_mode):
    webhook = WebhookRead(**_read_payload(url="https://hooks.example.com/x"))

    assert "hooks.example.com" in str(webhook.url)


def test_write_still_blocks_localhost_in_production(production_mode):
    """The SSRF guard must remain on the write path — the fix only relaxes reads."""
    with pytest.raises(ValidationError):
        WebhookCreate(name="x", url="http://localhost:8083/hook")


def test_write_still_blocks_private_ip_in_production(production_mode):
    with pytest.raises(ValidationError):
        WebhookCreate(name="x", url="http://192.168.1.10/hook")


def test_write_allows_public_url_in_production(production_mode):
    webhook = WebhookCreate(name="x", url="https://hooks.example.com/x")

    assert "hooks.example.com" in str(webhook.url)


def test_group_read_serializes_a_localhost_webhook_in_production(production_mode):
    """The actual failure path: GroupRead embeds list[WebhookRead] and used to 500 here."""
    from marvin.schemas.group.group import GroupRead

    group = GroupRead(
        id=uuid.uuid4(),
        name="Test Workspace",
        slug="test-workspace",
        webhooks=[WebhookRead(**_read_payload(url="http://localhost:8083/hook"))],
    )

    # mode="json" is what the API actually serializes with — it renders HttpUrl as a string.
    assert group.model_dump(mode="json")["webhooks"][0]["url"].startswith("http://localhost:8083")
