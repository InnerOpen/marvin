"""Remote MCP, slice 1: the `remote_mcp` platform switch and the OAuth discovery metadata it guards.

Off by default: every `/.well-known/oauth-*` address answers 404, exactly as it did before the routes existed. On,
the metadata names PUBLIC_API_URL as the issuer whatever host the request came in on, and `/mcp` under it as the
resource. The shapes are checked against the `mcp` SDK's own models, which is what MCP clients parse them with.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

from marvin.app import app
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole
from marvin.services import platform_policy as pp

PUBLIC = "https://api-dev.iwobble.com"
WELL_KNOWN = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
)


@pytest.fixture(autouse=True)
def _fresh_policy(db_session, monkeypatch):
    from marvin.services.platform_settings import PlatformSettingsService

    svc = PlatformSettingsService(db_session)
    saved = svc.get(pp.REMOTE_MCP_KEY)
    svc.set(pp.REMOTE_MCP_KEY, {})
    env = get_app_settings()
    monkeypatch.setattr(env, "MCP_REMOTE_ENABLED", False)
    monkeypatch.setattr(env, "PUBLIC_API_URL", PUBLIC)
    pp.clear_cache()
    yield env
    svc.set(pp.REMOTE_MCP_KEY, saved or {})
    pp.clear_cache()


@pytest.fixture
def client():
    return TestClient(app)


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
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _switch_on(db_session):
    pp.save_remote_mcp(db_session, {"enabled": True})


# ── Off by default ───────────────────────────────────────────────────────────


def test_off_by_default_every_metadata_address_is_404(client):
    assert pp.remote_mcp().enabled is False
    for path in WELL_KNOWN:
        res = client.get(path)
        assert res.status_code == 404 and res.json() == {"detail": "Not Found"}, path


def test_the_routes_are_not_in_the_openapi_document():
    paths = app.openapi()["paths"]
    assert not [p for p in paths if "well-known" in p or p.startswith("/oauth")]


# ── On ───────────────────────────────────────────────────────────────────────


def test_authorization_server_metadata_names_the_public_api_as_issuer(db_session, client):
    _switch_on(db_session)
    res = client.get("/.well-known/oauth-authorization-server", headers={"host": "marvin-api-marvin-dev.apps.ocp4.iwobble.com"})
    assert res.status_code == 200
    meta = res.json()
    assert meta["issuer"] == PUBLIC  # no trailing slash, whatever host asked
    assert meta["authorization_endpoint"] == f"{PUBLIC}/oauth/authorize"
    assert meta["token_endpoint"] == f"{PUBLIC}/oauth/token"
    assert meta["registration_endpoint"] == f"{PUBLIC}/oauth/register"
    assert meta["revocation_endpoint"] == f"{PUBLIC}/oauth/revoke"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert {"client_secret_basic", "client_secret_post", "none"} <= set(meta["token_endpoint_auth_methods_supported"])
    assert meta["scopes_supported"] == ["marvin:read", "marvin:write"]
    assert meta["authorization_response_iss_parameter_supported"] is True
    assert "client_id_metadata_document_supported" not in meta  # until CIMD exists
    OAuthMetadata.model_validate(meta)


def test_protected_resource_metadata_points_mcp_at_the_issuer(db_session, client):
    _switch_on(db_session)
    for path in WELL_KNOWN[1:]:
        meta = client.get(path).json()
        assert meta == {
            "resource": f"{PUBLIC}/mcp",
            "authorization_servers": [PUBLIC],
            "scopes_supported": ["marvin:read", "marvin:write"],
            "bearer_methods_supported": ["header"],
            "resource_name": "Marvin",
        }
        ProtectedResourceMetadata.model_validate(meta)


def test_no_registration_endpoint_when_clients_may_not_register(db_session, client):
    pp.save_remote_mcp(db_session, {"enabled": True, "allow_dynamic_registration": False})
    assert "registration_endpoint" not in client.get("/.well-known/oauth-authorization-server").json()


def test_the_environment_can_switch_it_on_and_an_admin_off_again(db_session, client, _fresh_policy):
    _fresh_policy.MCP_REMOTE_ENABLED = True
    pp.clear_cache()
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200
    pp.save_remote_mcp(db_session, {"enabled": False})
    assert pp.remote_mcp().enabled is False
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404


def test_production_without_a_public_api_url_stays_off(db_session, client, _fresh_policy, monkeypatch):
    monkeypatch.setattr(_fresh_policy, "PRODUCTION", True)
    monkeypatch.setattr(_fresh_policy, "PUBLIC_API_URL", "")
    with pytest.raises(pp.PolicyError, match="PUBLIC_API_URL"):
        _switch_on(db_session)
    _fresh_policy.MCP_REMOTE_ENABLED = True  # switched on by the environment: still refuses to run
    pp.clear_cache()
    assert pp.remote_mcp().enabled is False
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404


def test_development_without_a_public_api_url_uses_the_request_origin(db_session, client, _fresh_policy, monkeypatch):
    monkeypatch.setattr(_fresh_policy, "PRODUCTION", False)
    monkeypatch.setattr(_fresh_policy, "PUBLIC_API_URL", "")
    _switch_on(db_session)
    assert client.get("/.well-known/oauth-authorization-server").json()["issuer"] == "http://testserver"


# ── The policy and its admin API ─────────────────────────────────────────────


def test_lifetimes_follow_the_environment_until_an_admin_sets_them(db_session):
    policy = pp.remote_mcp()
    assert (policy.access_token_minutes, policy.refresh_token_days, policy.grant_max_days) == (60, 30, 180)
    pp.save_remote_mcp(db_session, {"MCP_ACCESS_TOKEN_MINUTES": 15, "MCP_GRANT_MAX_DAYS": 180})
    view = pp.remote_mcp_view(db_session)
    by_key = {f["key"]: f for f in view["fields"]}
    assert by_key["MCP_ACCESS_TOKEN_MINUTES"]["value"] == 15 and by_key["MCP_ACCESS_TOKEN_MINUTES"]["overridden"]
    assert not by_key["MCP_GRANT_MAX_DAYS"]["overridden"]  # equal to the environment's: stored as cleared
    assert pp.remote_mcp().access_token_minutes == 15
    pp.save_remote_mcp(db_session, {"MCP_ACCESS_TOKEN_MINUTES": None})
    assert pp.remote_mcp().access_token_minutes == 60


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"MCP_ACCESS_TOKEN_MINUTES": 1}, "between 5 and 1440"),
        ({"MCP_REFRESH_TOKEN_DAYS": 200}, "can't be longer"),
        ({"extra_redirect_uris": ["http://example.com/cb"]}, "not an https URI"),
        ({"extra_redirect_uris": ["https://exa mple.com/cb"]}, "not an https URI"),
        ({"extra_redirect_uris": [f"https://e{i}.com/cb" for i in range(21)]}, "At most 20"),
        ({"TOKEN_TIME": 5}, "not a remote MCP setting"),
    ],
)
def test_bad_values_are_refused(db_session, values, message):
    with pytest.raises(pp.PolicyError, match=message):
        pp.save_remote_mcp(db_session, values)


def test_extra_redirect_uris_are_kept_exact_or_as_prefixes(db_session):
    uris = ["https://example.com/oauth/callback", "https://tools.example.com:8443/cb*", "https://example.com/oauth/callback"]
    pp.save_remote_mcp(db_session, {"extra_redirect_uris": uris})
    assert pp.remote_mcp().extra_redirect_uris == ("https://example.com/oauth/callback", "https://tools.example.com:8443/cb*")


def test_the_admin_api_reads_and_saves_the_policy(db_session, admin):
    res = admin.get("/api/admin/platform-policy/remote-mcp")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is False and body["issuer"] == PUBLIC and body["resource"] == f"{PUBLIC}/mcp"
    assert [f["key"] for f in body["fields"]] == ["MCP_ACCESS_TOKEN_MINUTES", "MCP_REFRESH_TOKEN_DAYS", "MCP_GRANT_MAX_DAYS"]

    res = admin.put(
        "/api/admin/platform-policy/remote-mcp",
        json={"enabled": True, "values": {"MCP_ACCESS_TOKEN_MINUTES": 30}, "extraRedirectUris": ["https://example.com/cb"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is True and body["extraRedirectUris"] == ["https://example.com/cb"]
    assert body["allowDynamicRegistration"] is True  # not sent: left as it was
    assert pp.remote_mcp().access_token_minutes == 30

    res = admin.put("/api/admin/platform-policy/remote-mcp", json={"values": {"MCP_ACCESS_TOKEN_MINUTES": 2}})
    assert res.status_code == 422 and "between 5 and 1440" in res.json()["detail"]


def test_the_admin_api_is_for_super_admins_only(db_session):
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
        c = TestClient(app)
        assert c.get("/api/admin/platform-policy/remote-mcp").status_code == 403
        assert c.put("/api/admin/platform-policy/remote-mcp", json={"enabled": True}).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
