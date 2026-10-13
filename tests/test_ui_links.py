"""ui_links: absolute only when FRONTEND_URL is configured, else root-relative; reviewLink is copy-ready."""

from marvin.core.config import get_app_settings
from marvin.services.ui_links import entry_edit_url, entry_review_link, ui_base_url


def test_default_frontend_url_means_relative_links(monkeypatch):
    settings = get_app_settings()
    monkeypatch.setattr(settings, "FRONTEND_URL", type(settings).model_fields["FRONTEND_URL"].default)
    assert ui_base_url() is None
    assert entry_edit_url("abc") == "/workspace/entries/abc"
    assert entry_review_link("abc") == "[Review the draft](/workspace/entries/abc)"


def test_configured_frontend_url_makes_links_absolute(monkeypatch):
    settings = get_app_settings()
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://marvin.example.com/")
    assert ui_base_url() == "https://marvin.example.com"
    assert entry_edit_url("abc") == "https://marvin.example.com/workspace/entries/abc"
    assert entry_review_link("abc", "Review the entry") == "[Review the entry](https://marvin.example.com/workspace/entries/abc)"
