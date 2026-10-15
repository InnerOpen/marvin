"""Remote MCP slice 2: the OAuth authorization server, consent and connected apps (tasks/mcp-oauth-plan.md §6.2).

Driven through the real app with a real user and a signed-in session (a JWT), the way claude.ai or Claude Code would:
register → authorize → consent → code → token → /mcp → refresh → revoke.
"""

import base64
import hashlib
import secrets
import uuid
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.security import create_access_token
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import platform_policy
from marvin.services.mcp_remote import limits
from marvin.services.mcp_remote import oauth as svc

REDIRECT = "http://127.0.0.1:53682/cb"
ISSUER = "http://testserver"
RESOURCE = f"{ISSUER}/mcp"


@pytest.fixture
def on(monkeypatch):
    """Remote MCP switched on, rate limits fresh, events captured."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    policy = platform_policy.RemoteMcpPolicy(True, 60, 30, 180, (), True)
    monkeypatch.setattr(platform_policy, "remote_mcp", lambda: policy)
    limits.reset()
    sent = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
    return SimpleNamespace(policy=policy, events=sent)


def _workspace(db_session, label, role: WorkspaceRole | None):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"{label} {marker}", slug=f"{label.lower()}-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid, group_id=gid, full_name=f"{label} User", username=f"u-{marker}", email=f"u-{marker}@x.test",
            auth_method="MARVIN", is_superuser=False, platform_role="NONE", admin=False, password="x",
        )
    )  # fmt: skip
    if role is not None:
        db_session.add(WorkspaceMembers(session=db_session, user_id=uid, group_id=gid, workspace_role=role))
    db_session.commit()
    return SimpleNamespace(gid=gid, uid=uid, jwt=create_access_token({"sub": str(uid)}))


@pytest.fixture
def ws(db_session):
    made = []

    def make(label="Mcp", role=WorkspaceRole.OWNER):
        w = _workspace(db_session, label, role)
        made.append(w)
        return w

    yield make
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel, OAuthClientModel, OAuthGrantModel, OAuthTokenModel
    from marvin.db.models.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    db_session.rollback()
    for w in made:
        grants = [g for (g,) in db_session.query(OAuthGrantModel.id).filter(OAuthGrantModel.user_id == w.uid)]
        db_session.query(OAuthTokenModel).filter(OAuthTokenModel.grant_id.in_(grants)).delete(synchronize_session=False)
        db_session.query(OAuthAuthorizationRequestModel).filter(OAuthAuthorizationRequestModel.user_id == w.uid).delete(synchronize_session=False)
        db_session.query(OAuthGrantModel).filter(OAuthGrantModel.user_id == w.uid).delete(synchronize_session=False)
        db_session.query(WorkspaceMembers).filter(WorkspaceMembers.user_id == w.uid).delete()
        db_session.query(Users).filter(Users.id == w.uid).delete()
        db_session.query(Groups).filter(Groups.id == w.gid).delete()
    db_session.query(OAuthAuthorizationRequestModel).filter(OAuthAuthorizationRequestModel.user_id.is_(None)).delete(synchronize_session=False)
    db_session.query(OAuthClientModel).filter(OAuthClientModel.client_name.like("Test %")).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def _register(client, **body):
    res = client.post("/oauth/register", json={"client_name": "Test Claude", "redirect_uris": [REDIRECT], **body})
    assert res.status_code == 201, res.text
    return res.json()


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _authorize(client, reg, challenge, **params):
    query = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT, "state": "s-1", "code_challenge": challenge,
             "code_challenge_method": "S256", "resource": RESOURCE, **params}  # fmt: skip
    return client.get("/oauth/authorize", params={k: v for k, v in query.items() if v is not None})


def _ref(res) -> str:
    assert res.status_code == 302, res.text
    location = res.headers["location"]
    assert "/oauth/consent?req=" in location
    return parse_qs(urlsplit(location).query)["req"][0]


def _consent(client, ref, user, *, access="read", workspace=None, nonce=None, decision="approve"):
    auth = {"Authorization": f"Bearer {user.jwt}"}
    view = client.get(f"/api/oauth/requests/{ref}", headers=auth)
    assert view.status_code == 200, view.text
    body = {"consentNonce": nonce or view.json()["consentNonce"], "workspaceId": str(workspace or user.gid), "access": access}
    return client.post(f"/api/oauth/requests/{ref}/{decision}", json=body, headers=auth)


def _code(res) -> str:
    assert res.status_code == 200, res.text
    q = parse_qs(urlsplit(res.json()["redirectTo"]).query)
    assert q["state"] == ["s-1"] and q["iss"] == [ISSUER]
    return q["code"][0]


def _basic(reg) -> dict:
    raw = f"{reg['client_id']}:{reg['client_secret']}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _connect(client, user, *, access="read", reg=None):
    reg = reg or _register(client)
    verifier, challenge = _pkce()
    code = _code(_consent(client, _ref(_authorize(client, reg, challenge)), user, access=access))
    tokens = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier},
                         headers=_basic(reg))  # fmt: skip
    assert tokens.status_code == 200, tokens.text
    return reg, tokens.json()


def _mcp(client, token, method="initialize", rpc_id=1):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": {}}, headers=headers)


# ── the whole flow ───────────────────────────────────────────────────────────


def test_a_client_signs_in_reaches_mcp_refreshes_and_is_revoked(client, on, ws, db_session):
    from marvin.services.event_bus_service.event_types import EventTypes

    owner = ws()
    reg, tokens = _connect(client, owner)
    assert tokens["access_token"].startswith("marvin_at_") and tokens["refresh_token"].startswith("marvin_rt_")
    assert tokens["scope"] == "marvin:read" and tokens["expires_in"] == 3600

    init = _mcp(client, tokens["access_token"])
    assert init.status_code == 200 and init.json()["result"]["serverInfo"]["name"] == "Marvin"
    assert _mcp(client, tokens["access_token"], "tools/list").json()["result"]["tools"] == []

    fresh = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, headers=_basic(reg))
    assert fresh.status_code == 200 and fresh.json()["refresh_token"] != tokens["refresh_token"]

    apps = client.get("/api/users/self/connected-apps", headers={"Authorization": f"Bearer {owner.jwt}"}).json()
    assert [(a["clientName"], a["redirectHost"], a["access"]) for a in apps] == [("Test Claude", "127.0.0.1:53682", "read")]
    assert client.post(f"/api/users/self/connected-apps/{apps[0]['id']}/revoke", headers={"Authorization": f"Bearer {owner.jwt}"}).status_code == 200
    assert _mcp(client, fresh.json()["access_token"]).status_code == 401

    kinds = [e["event_type"] for e in on.events]
    assert kinds == [EventTypes.mcp_connection_authorized, EventTypes.mcp_connection_revoked]
    payload = on.events[0]["document_data"].model_dump_json()
    assert "marvin_at_" not in payload and "marvin_rt_" not in payload and reg["client_secret"] not in payload


def test_mcp_without_a_good_token_points_at_the_metadata(client, on):
    res = _mcp(client, None)
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == f'Bearer resource_metadata="{ISSUER}/.well-known/oauth-protected-resource/mcp"'
    bad = _mcp(client, "marvin_at_not-a-token")
    assert bad.status_code == 401 and 'error="invalid_token"' in bad.headers["www-authenticate"]
    assert _mcp(client, "marvin_tk_a-personal-token").status_code == 401  # personal tokens don't work here


def test_everything_is_404_while_the_switch_is_off(client, monkeypatch):
    off = platform_policy.RemoteMcpPolicy(False, 60, 30, 180, (), True)
    monkeypatch.setattr(platform_policy, "remote_mcp", lambda: off)
    assert client.post("/oauth/register", json={}).status_code == 404
    assert client.get("/oauth/authorize").status_code == 404
    assert client.post("/oauth/token").status_code == 404
    assert client.post("/mcp", json={}).status_code == 404
    assert client.get("/api/oauth/requests/x").status_code in (401, 404)


# ── registration and authorize ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "uri, ok",
    [
        ("https://claude.ai/api/mcp/auth_callback", True),
        ("http://localhost:33418/callback", True),
        ("http://[::1]:9/x", True),
        ("https://evil.example/cb", False),
        ("http://claude.ai/api/mcp/auth_callback", False),
    ],
)
def test_only_allowed_redirect_uris_register(client, on, uri, ok):
    res = client.post("/oauth/register", json={"client_name": "Test X", "redirect_uris": [uri]})
    assert (res.status_code == 201) is ok, res.text
    if ok:
        assert "client_secret" in res.json()


def test_an_unknown_client_or_redirect_gets_a_page_never_a_redirect(client, on):
    _verifier, challenge = _pkce()
    res = client.get("/oauth/authorize", params={"client_id": "marvin_oc_nope", "redirect_uri": "https://evil.example/cb", "response_type": "code"})
    assert res.status_code == 400 and "location" not in res.headers and "Can't connect" in res.text
    reg = _register(client)
    res = _authorize(client, reg, challenge, redirect_uri="http://127.0.0.1:1/other")
    assert res.status_code == 400 and "location" not in res.headers


@pytest.mark.parametrize(
    "params, error",
    [
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": None}, "invalid_request"),
        ({"resource": "https://elsewhere.example/mcp"}, "invalid_target"),
        ({"scope": "admin"}, "invalid_scope"),
    ],
)
def test_bad_requests_go_back_to_the_client_with_the_error(client, on, params, error):
    _verifier, challenge = _pkce()
    res = _authorize(client, _register(client), challenge, **params)
    assert res.status_code == 302
    q = parse_qs(urlsplit(res.headers["location"]).query)
    assert q["error"] == [error] and q["state"] == ["s-1"] and res.headers["location"].startswith(REDIRECT)


def test_authorize_sets_no_cookie(client, on):
    _verifier, challenge = _pkce()
    res = _authorize(client, _register(client), challenge)
    assert res.status_code == 302 and "set-cookie" not in res.headers


# ── consent ──────────────────────────────────────────────────────────────────


def test_consent_needs_a_session_not_a_personal_token(client, on, ws):
    _verifier, challenge = _pkce()
    ref = _ref(_authorize(client, _register(client), challenge))
    assert client.get(f"/api/oauth/requests/{ref}", headers={"Authorization": "Bearer marvin_tk_something"}).status_code == 403
    long_jwt = create_access_token({"sub": str(ws().uid), "long_token": True, "id": 1})
    assert client.get(f"/api/oauth/requests/{ref}", headers={"Authorization": f"Bearer {long_jwt}"}).status_code == 403


def test_consent_refuses_other_workspaces_low_roles_wrong_nonces_and_old_requests(client, on, ws, db_session):
    from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel

    viewer, stranger = ws("Viewer", WorkspaceRole.VIEWER), ws("Other")
    reg = _register(client)

    def fresh_ref():
        return _ref(_authorize(client, reg, _pkce()[1]))

    assert _consent(client, fresh_ref(), viewer, workspace=stranger.gid).status_code == 403  # not a member
    assert _consent(client, fresh_ref(), viewer, access="write").status_code == 403  # write needs EDITOR
    assert _consent(client, fresh_ref(), viewer, nonce="forged").status_code == 403
    ref = fresh_ref()
    db_session.query(OAuthAuthorizationRequestModel).filter_by(ref_lookup=svc._hash(ref)).update({"expires_at": svc._now() - timedelta(minutes=1)})
    db_session.commit()
    auth = {"Authorization": f"Bearer {viewer.jwt}"}
    assert (
        client.post(f"/api/oauth/requests/{ref}/approve", json={"consentNonce": "x", "workspaceId": str(viewer.gid)}, headers=auth).status_code == 410
    )
    assert _code(_consent(client, fresh_ref(), viewer))  # read-only works for a viewer


def test_deny_sends_access_denied_and_a_second_approve_is_harmless(client, on, ws):
    owner = ws()
    reg = _register(client)
    denied = _consent(client, _ref(_authorize(client, reg, _pkce()[1])), owner, decision="deny")
    q = parse_qs(urlsplit(denied.json()["redirectTo"]).query)
    assert q["error"] == ["access_denied"] and q["state"] == ["s-1"]

    ref = _ref(_authorize(client, reg, _pkce()[1]))
    auth = {"Authorization": f"Bearer {owner.jwt}"}
    nonce = client.get(f"/api/oauth/requests/{ref}", headers=auth).json()["consentNonce"]
    body = {"consentNonce": nonce, "workspaceId": str(owner.gid), "access": "read"}
    assert client.post(f"/api/oauth/requests/{ref}/approve", json=body, headers=auth).json()["redirectTo"]
    again = client.post(f"/api/oauth/requests/{ref}/approve", json=body, headers=auth).json()
    assert again == {"redirectTo": None, "already": True}


def test_a_workspace_that_turned_off_mcp_can_not_be_chosen(client, on, ws, db_session):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    owner = ws()
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=owner.gid, invocation_sources={"mcp": False}))
    db_session.commit()
    try:
        res = _consent(client, _ref(_authorize(client, _register(client), _pkce()[1])), owner)
        assert res.status_code == 403 and "external MCP hosts" in res.json()["detail"]
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=owner.gid).delete()
        db_session.commit()


# ── tokens ───────────────────────────────────────────────────────────────────


def test_a_code_works_once_and_a_second_use_revokes_what_it_issued(client, on, ws):
    owner = ws()
    reg = _register(client)
    verifier, challenge = _pkce()
    code = _code(_consent(client, _ref(_authorize(client, reg, challenge)), owner))
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier}
    first = client.post("/oauth/token", data=form, headers=_basic(reg))
    assert first.status_code == 200
    second = client.post("/oauth/token", data=form, headers=_basic(reg))
    assert second.status_code == 400 and second.json()["error"] == "invalid_grant"
    assert _mcp(client, first.json()["access_token"]).status_code == 401


def test_pkce_secret_and_redirect_must_all_match(client, on, ws):
    owner = ws()
    reg = _register(client)
    verifier, challenge = _pkce()
    code = _code(_consent(client, _ref(_authorize(client, reg, challenge)), owner))
    base = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier}
    assert client.post("/oauth/token", data={**base, "code_verifier": "wrong" * 10}, headers=_basic(reg)).json()["error"] == "invalid_grant"
    wrong_secret = client.post("/oauth/token", data=base, headers=_basic({**reg, "client_secret": "marvin_cs_wrong"}))
    assert wrong_secret.status_code == 401 and wrong_secret.headers["www-authenticate"].startswith("Basic")
    assert client.post("/oauth/token", data={**base, "redirect_uri": "http://127.0.0.1:9/x"}, headers=_basic(reg)).json()["error"] == "invalid_grant"
    posted = client.post("/oauth/token", data={**base, "client_id": reg["client_id"], "client_secret": reg["client_secret"]})
    assert posted.status_code == 200  # client_secret_post works too


def test_a_public_client_signs_in_with_pkce_alone(client, on, ws):
    reg = _register(client, token_endpoint_auth_method="none")
    assert "client_secret" not in reg
    verifier, challenge = _pkce()
    code = _code(_consent(client, _ref(_authorize(client, reg, challenge)), ws()))
    res = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier, "client_id": reg["client_id"]},
    )
    assert res.status_code == 200, res.text


def test_a_reused_refresh_token_inside_the_grace_is_refused_after_it_revokes_the_grant(client, on, ws, db_session):
    from marvin.db.models.platform.oauth import OAuthTokenModel
    from marvin.services.event_bus_service.event_types import EventTypes

    reg, tokens = _connect(client, ws())
    form = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
    rotated = client.post("/oauth/token", data=form, headers=_basic(reg)).json()

    retry = client.post("/oauth/token", data=form, headers=_basic(reg))
    assert retry.json()["error"] == "invalid_grant" and _mcp(client, rotated["access_token"]).status_code == 200  # a retry race

    db_session.query(OAuthTokenModel).filter_by(token_lookup=svc._hash(tokens["refresh_token"])).update(
        {"rotated_at": svc._now() - timedelta(seconds=svc.REUSE_GRACE_SECONDS + 5)}
    )
    db_session.commit()
    stolen = client.post("/oauth/token", data=form, headers=_basic(reg))
    assert stolen.json()["error"] == "invalid_grant" and _mcp(client, rotated["access_token"]).status_code == 401
    assert EventTypes.mcp_token_reuse_detected in [e["event_type"] for e in on.events]


def test_a_refresh_can_not_widen_the_scope_and_revoke_ends_the_grant(client, on, ws):
    reg, tokens = _connect(client, ws())
    wider = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "scope": "marvin:write"},
                        headers=_basic(reg))  # fmt: skip
    assert wider.json()["error"] == "invalid_scope"
    assert client.post("/oauth/revoke", data={"token": tokens["refresh_token"]}, headers=_basic(reg)).status_code == 200
    assert _mcp(client, tokens["access_token"]).status_code == 401


def test_losing_the_membership_disconnects_the_app(client, on, ws, db_session):
    from marvin.db.models.users.workspace_members import WorkspaceMembers
    from marvin.services.event_bus_service.event_types import EventTypes

    owner = ws()
    _reg, tokens = _connect(client, owner)
    db_session.query(WorkspaceMembers).filter_by(user_id=owner.uid).delete()
    db_session.commit()
    assert _mcp(client, tokens["access_token"]).status_code == 401
    revoked = [e for e in on.events if e["event_type"] == EventTypes.mcp_connection_revoked]
    assert revoked and revoked[0]["document_data"].reason == "membership_lost"


def test_write_needs_an_editor_and_shows_on_the_grant(client, on, ws):
    editor = ws("Editor", WorkspaceRole.EDITOR)
    _reg, tokens = _connect(client, editor, access="write")
    assert tokens["scope"] == "marvin:read marvin:write"


def test_super_admins_list_and_revoke_any_connected_app(client, on, ws, db_session):
    from marvin.db.models.users import Users

    owner, admin = ws(), ws("Admin")
    db_session.query(Users).filter_by(id=admin.uid).update({"platform_role": "SUPER_ADMIN", "is_superuser": True})
    db_session.commit()
    _reg, tokens = _connect(client, owner)
    assert client.get("/api/admin/connected-apps", headers={"Authorization": f"Bearer {owner.jwt}"}).status_code == 403
    rows = client.get("/api/admin/connected-apps", headers={"Authorization": f"Bearer {admin.jwt}"}).json()
    mine = next(r for r in rows if r["userId"] == str(owner.uid))
    assert (
        client.post(f"/api/admin/connected-apps/{mine['id']}/revoke", headers={"Authorization": f"Bearer {admin.jwt}"}).json()["revokedReason"]
        == "admin"
    )
    assert _mcp(client, tokens["access_token"]).status_code == 401


def test_registration_is_rate_limited(client, on):
    for _ in range(limits.LIMITS["register"][0]):
        _register(client)
    res = client.post("/oauth/register", json={"client_name": "Test Y", "redirect_uris": [REDIRECT]})
    assert res.status_code == 429 and int(res.headers["retry-after"]) > 0


def test_the_mcp_events_are_platform_audit_events():
    from marvin.services.events.event_catalog import CATALOG_BY_TYPE

    for name in ("mcp_connection_authorized", "mcp_connection_revoked", "mcp_token_reuse_detected"):
        entry = CATALOG_BY_TYPE[name]
        assert (entry.scope, entry.audit_locked, entry.category) == ("platform", True, "Security")


def test_a_dev_refresh_revokes_copied_connected_apps(client, on, ws, db_session):
    from marvin.db.db_setup import engine
    from marvin.scripts.refresh_dev import revoke_copied_mcp_grants

    _reg, tokens = _connect(client, ws())
    with engine.begin() as conn:
        assert revoke_copied_mcp_grants(conn) >= 1
    assert _mcp(client, tokens["access_token"]).status_code == 401
