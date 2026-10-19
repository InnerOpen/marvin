"""Admin → Site Settings → Features Status reads `/api/admin/about/features-status`: each feature as it is in force,
and where that comes from — not the raw settings dump, which only knows the environment's defaults (it showed
"Mcp Remote: Disabled" on an install whose admin had switched remote MCP on)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole
from marvin.services import platform_policy as pp
from marvin.services import platform_smtp
from marvin.services.platform_settings import PlatformSettingsService

URL = "/api/admin/about/features-status"
PUBLIC = "https://api.example.com"
SMTP_ENV = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_NAME", "SMTP_FROM_EMAIL")


@pytest.fixture(autouse=True)
def world(db_session, monkeypatch):
    env = get_app_settings()
    touched = {"MCP_REMOTE_ENABLED", "PUBLIC_API_URL", "PRODUCTION", *SMTP_ENV}
    before = set(env.model_fields_set)
    svc = PlatformSettingsService(db_session)
    saved = svc.get(pp.REMOTE_MCP_KEY)
    svc.set(pp.REMOTE_MCP_KEY, {})
    monkeypatch.setattr(env, "MCP_REMOTE_ENABLED", False)
    monkeypatch.setattr(env, "PUBLIC_API_URL", PUBLIC)
    monkeypatch.setattr(env, "PRODUCTION", False)
    for name in SMTP_ENV:
        monkeypatch.setattr(env, name, None)
    platform_smtp.reset(db_session)
    pp.clear_cache()
    env.model_fields_set.difference_update(touched)  # "set by the environment" must start out unset, as on a bare install
    yield env
    svc.set(pp.REMOTE_MCP_KEY, saved or {})
    platform_smtp.reset(db_session)
    pp.clear_cache()
    env.model_fields_set.intersection_update(before)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def admin():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="00000000-0000-0000-0000-00000000a0a0",
        group_id=None,
        admin=True,
        is_superuser=True,
        username="platform-admin",
        full_name="Platform Admin",
        platform_role=PlatformRole.SUPER_ADMIN,
    )
    return TestClient(app)


def _row(client, key):
    res = client.get(URL)
    assert res.status_code == 200, res.text
    return next(r for r in res.json() if r["key"] == key)


def test_remote_mcp_switched_on_in_admin_while_the_environment_is_off(admin, db_session):
    pp.save_remote_mcp(db_session, {"enabled": True})
    row = _row(admin, "mcp_remote")
    assert row["enabled"] is True and row["source"] == "admin" and row["reason"] is None
    assert row["managePath"] == "/admin/site-settings#remote-mcp"


def test_remote_mcp_switched_on_by_the_environment_alone(admin, world):
    world.MCP_REMOTE_ENABLED = True
    pp.clear_cache()
    row = _row(admin, "mcp_remote")
    assert row["enabled"] is True and row["source"] == "environment"


def test_remote_mcp_off_by_default_says_so(admin):
    row = _row(admin, "mcp_remote")
    assert row["enabled"] is False and row["source"] == "default" and "MCP_REMOTE_ENABLED" in row["reason"]


def test_remote_mcp_switched_off_in_admin_over_an_environment_on(admin, db_session, world):
    world.MCP_REMOTE_ENABLED = True
    pp.save_remote_mcp(db_session, {"enabled": False})
    row = _row(admin, "mcp_remote")
    assert row["enabled"] is False and row["source"] == "admin" and "Admin" in row["reason"]


def test_remote_mcp_blocked_without_a_public_api_url_says_why(admin, world, monkeypatch):
    monkeypatch.setattr(world, "PRODUCTION", True)
    monkeypatch.setattr(world, "PUBLIC_API_URL", "")
    world.MCP_REMOTE_ENABLED = True  # switched on, but can't run
    pp.clear_cache()
    row = _row(admin, "mcp_remote")
    assert row["enabled"] is False and row["source"] == "environment" and "PUBLIC_API_URL" in row["reason"]
    assert pp.remote_mcp().enabled is False  # the card agrees with what the server does


def test_smtp_set_through_admin_fields_is_ready_from_admin(admin, db_session):
    assert _row(admin, "smtp")["enabled"] is False
    platform_smtp.save(
        db_session,
        {"host": "smtp.example.com", "port": 25, "auth_strategy": "NONE", "from_name": "Marvin", "from_email": "noreply@example.com"},
    )
    row = _row(admin, "smtp")
    assert row["enabled"] is True and row["source"] == "admin" and row["reason"] is None
    assert row["managePath"] == "/admin/email-settings"


def test_smtp_from_the_environment_alone(admin, world):
    for name, value in {
        "SMTP_HOST": "env.test",
        "SMTP_PORT": "25",
        "SMTP_FROM_NAME": "Env",
        "SMTP_FROM_EMAIL": "env@env.test",
    }.items():
        setattr(world, name, value)
    world.SMTP_AUTH_STRATEGY = "NONE"
    platform_smtp.clear_cache()
    row = _row(admin, "smtp")
    assert row["enabled"] is True and row["source"] == "environment"


def test_smtp_incomplete_says_what_is_missing(admin):
    row = _row(admin, "smtp")
    assert row["enabled"] is False and row["source"] == "default" and row["reason"]


def test_every_row_has_a_known_source_and_reasons_only_when_off(admin):
    rows = admin.get(URL).json()
    assert {r["key"] for r in rows} >= {"smtp", "mcp_remote", "ldap", "oidc", "openai", "web_push", "scheduler", "embeddings_builtin"}
    for r in rows:
        assert r["source"] in {"admin", "environment", "default"}
        assert r["enabled"] == (r["reason"] is None), r


def test_features_status_is_for_super_admins_only():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="00000000-0000-0000-0000-00000000b0b0",
        group_id=None,
        admin=True,
        is_superuser=False,
        username="ws-admin",
        full_name="Workspace Admin",
        platform_role=PlatformRole.NONE,
    )
    try:
        assert TestClient(app).get(URL).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
