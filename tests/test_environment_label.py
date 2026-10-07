"""ENVIRONMENT_LABEL: a short tag ("DEV", "STAGING") the UI badges a non-production instance with.

It is normalised on load, served on the public login-info endpoint (the login page and the layouts
read it before anyone signs in) and on the admin about endpoint. Empty means production: nothing shows.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user
from marvin.core.settings.settings import AppSettings
from marvin.db.models.users.roles import PlatformRole


def _settings(**kwargs) -> AppSettings:
    return AppSettings(SECRET="test", **kwargs)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   ", ""),
        (None, ""),
        ("dev", "DEV"),
        ("  Staging \n", "STAGING"),
        ("pr-123", "PR-123"),
        ("a-very-long-environment-name", "A-VERY-LONG-"),  # capped at 12 so the badge stays small
    ],
)
def test_label_is_stripped_upper_cased_and_capped(raw, expected):
    assert _settings(ENVIRONMENT_LABEL=raw).ENVIRONMENT_LABEL == expected


def test_label_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT_LABEL", " dev ")
    assert _settings().ENVIRONMENT_LABEL == "DEV"


def test_label_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT_LABEL", raising=False)
    assert _settings().ENVIRONMENT_LABEL == ""


@pytest.mark.parametrize("label", ["DEV", ""])
def test_login_info_is_public_and_carries_the_label(client: TestClient, monkeypatch, label):
    monkeypatch.setattr(get_app_settings(), "ENVIRONMENT_LABEL", label)
    res = client.get("/api/app/about/login-info")
    assert res.status_code == 200
    body = res.json()
    assert body["environmentLabel"] == label
    assert "isDemo" in body  # the label sits beside, and does not replace, demo mode


@pytest.fixture
def super_admin_client(monkeypatch):
    user = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        admin=True,
        is_superuser=True,
        platform_role=PlatformRole.SUPER_ADMIN,
        username="root",
        email="root@t.test",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    # The about payload asks GitHub for the latest release; keep the test offline.
    monkeypatch.setattr("marvin.routes.admin.about_controller.get_latest_version", lambda _url: "0.0.0")
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("label", ["STAGING", ""])
def test_admin_about_carries_the_label(super_admin_client: TestClient, monkeypatch, label):
    monkeypatch.setattr(get_app_settings(), "ENVIRONMENT_LABEL", label)
    res = super_admin_client.get("/api/admin/about")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["environmentLabel"] == label
    assert body["production"] is False and "demoStatus" in body
