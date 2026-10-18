# ruff: noqa: F811, F401 — the `client` / `on` / `ws` fixtures are imported, then named as parameters
"""Remote MCP: a connector pinned to one workspace, `/mcp/w/<workspace-slug>`.

Its own OAuth resource: metadata at `/.well-known/oauth-protected-resource/mcp/w/<slug>`, a consent page that offers
that workspace only, and a token that works at that URL (and at the same workspace's renamed slug) and nowhere else.
`/mcp` keeps working as before.
"""

import json

import pytest
from mcp.shared.auth import ProtectedResourceMetadata

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import platform_policy
from tests.test_remote_mcp_oauth import (
    ISSUER,
    REDIRECT,
    _authorize,
    _basic,
    _code,
    _connect,
    _consent,
    _mcp,
    _pkce,
    _ref,
    _register,
    _rpc_body,
    client,
    on,
    ws,
)


def _slug(db_session, w) -> str:
    from marvin.db.models.groups import Groups

    return db_session.get(Groups, w.gid).slug


def _url(slug) -> str:
    return f"{ISSUER}/mcp/w/{slug}"


def _join(db_session, user, other, role=WorkspaceRole.OWNER) -> None:
    """Make `user` a member of `other`'s workspace too."""
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    db_session.add(WorkspaceMembers(session=db_session, user_id=user.uid, group_id=other.gid, workspace_role=role))
    db_session.commit()


def _post(client, path, token, method="initialize", params=None, session=None, rpc_id=1):
    headers = {"Accept": "application/json, text/event-stream", **({"Authorization": f"Bearer {token}"} if token else {})}
    if session:
        headers["mcp-session-id"] = session
    message = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}
    if method == "initialize":
        message["params"] = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}
    return client.post(path, json=message, headers=headers)


def _pinned_tokens(client, user, slug, *, workspace=None, access="read", send_resource=True):
    """Sign in through a workspace's own URL (the `resource` the client read from that URL's metadata)."""
    reg = _register(client)
    verifier, challenge = _pkce()
    res = _authorize(client, reg, challenge, resource=_url(slug))
    code = _code(_consent(client, _ref(res), user, access=access, workspace=workspace))
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier}
    if send_resource:
        form["resource"] = _url(slug)
    out = client.post("/oauth/token", data=form, headers=_basic(reg))
    assert out.status_code == 200, out.text
    return reg, out.json()


# ── metadata ─────────────────────────────────────────────────────────────────


def test_a_workspace_url_has_its_own_resource_metadata(client, on):
    res = client.get("/.well-known/oauth-protected-resource/mcp/w/mash-and-burn")
    assert res.status_code == 200
    meta = ProtectedResourceMetadata.model_validate(res.json())  # what MCP clients parse it with
    assert str(meta.resource) == _url("mash-and-burn") and [str(s).rstrip("/") for s in meta.authorization_servers] == [ISSUER]
    assert client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == f"{ISSUER}/mcp"  # unchanged
    assert client.get("/.well-known/oauth-protected-resource/mcp/w/Mash-And-Burn").json()["resource"] == _url("mash-and-burn")  # lower-cased
    assert client.get("/.well-known/oauth-protected-resource/mcp/w/-bad").status_code == 404
    assert client.get("/.well-known/oauth-protected-resource/mcp/w/has.dot").status_code == 404


def test_the_metadata_does_not_say_whether_a_workspace_exists(client, on, ws, db_session):
    real = _slug(db_session, ws())
    for slug in (real, f"{real}-nope"):  # a real slug and a made-up one answer alike
        assert client.get(f"/.well-known/oauth-protected-resource/mcp/w/{slug}").json()["resource"] == _url(slug)


def test_workspace_urls_are_404_while_the_switch_is_off(client, monkeypatch):
    off = platform_policy.RemoteMcpPolicy(False, 60, 30, 180, (), True)
    monkeypatch.setattr(platform_policy, "remote_mcp", lambda: off)
    assert client.get("/.well-known/oauth-protected-resource/mcp/w/x").status_code == 404
    assert client.post("/mcp/w/x", json={}).status_code == 404


def test_a_workspace_url_challenges_with_its_own_metadata(client, on):
    res = _post(client, "/mcp/w/mash-and-burn", None)
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == f'Bearer resource_metadata="{ISSUER}/.well-known/oauth-protected-resource/mcp/w/mash-and-burn"'
    assert _post(client, "/mcp/w/mash-and-burn", "marvin_at_nope").status_code == 401  # a slug that doesn't exist answers the same
    assert _post(client, "/mcp/w/-bad", None).status_code == 404


# ── authorize and consent ────────────────────────────────────────────────────


def test_only_this_servers_resources_are_taken(client, on):
    reg = _register(client)
    for resource in ("https://evil.example/mcp/w/x", f"{ISSUER}/mcp/w/", f"{ISSUER}/mcp/w/a/b", f"{ISSUER}/mcp/x/y", f"{ISSUER}/mcp/w/-x"):
        res = _authorize(client, reg, _pkce()[1], resource=resource)
        assert res.status_code == 302 and "error=invalid_target" in res.headers["location"], resource


def test_consent_for_a_workspace_url_offers_that_workspace_only(client, on, ws, db_session):
    me, other = ws("Mine"), ws("Other")
    _join(db_session, me, other)
    reg = _register(client)
    auth = {"Authorization": f"Bearer {me.jwt}"}

    pinned = client.get(
        f"/api/oauth/requests/{_ref(_authorize(client, reg, _pkce()[1], resource=_url(_slug(db_session, other))))}", headers=auth
    ).json()
    assert pinned["pinned"] is True and [w["id"] for w in pinned["workspaces"]] == [str(other.gid)]

    general = client.get(f"/api/oauth/requests/{_ref(_authorize(client, reg, _pkce()[1]))}", headers=auth).json()
    assert general["pinned"] is False and {w["id"] for w in general["workspaces"]} == {str(me.gid), str(other.gid)}


def test_the_consent_form_can_not_move_a_pinned_connector_to_another_workspace(client, on, ws, db_session):
    me, other = ws("Mine"), ws("Other")
    _join(db_session, me, other)
    ref = _ref(_authorize(client, _register(client), _pkce()[1], resource=_url(_slug(db_session, other))))
    assert _consent(client, ref, me, workspace=me.gid).status_code == 403
    assert _consent(client, ref, me, workspace=other.gid).status_code == 200


def test_a_non_member_or_a_missing_workspace_gets_nothing_to_approve(client, on, ws, db_session):
    me, stranger = ws("Mine"), ws("Stranger")
    auth = {"Authorization": f"Bearer {me.jwt}"}
    reg = _register(client)
    for slug in (_slug(db_session, stranger), "no-such-workspace"):
        ref = _ref(_authorize(client, reg, _pkce()[1], resource=_url(slug)))
        assert client.get(f"/api/oauth/requests/{ref}", headers=auth).json()["workspaces"] == []  # the same answer for both
        assert _consent(client, ref, me, workspace=me.gid).status_code == 403


# ── audience binding ─────────────────────────────────────────────────────────


def test_a_workspace_token_works_at_its_own_url_only(client, on, ws, db_session):
    me, other = ws("Mine"), ws("Other")
    _join(db_session, me, other)
    mine, theirs = _slug(db_session, me), _slug(db_session, other)
    _reg, tokens = _pinned_tokens(client, me, mine)
    token = tokens["access_token"]

    res = _post(client, f"/mcp/w/{mine}", token)
    assert res.status_code == 200 and _rpc_body(res)["result"]["serverInfo"]["name"] == "Marvin"
    assert _post(client, f"/mcp/w/{mine.upper()}", token).status_code == 200  # the slug is case-insensitive
    assert _post(client, "/mcp", token).status_code == 401  # not the general URL
    assert _post(client, f"/mcp/w/{theirs}", token).status_code == 401  # not another workspace, though its user is a member there


def test_a_general_token_does_not_work_at_a_workspace_url(client, on, ws, db_session):
    me = ws("Mine")
    _reg, tokens = _connect(client, me)
    assert _post(client, "/mcp", tokens["access_token"]).status_code == 200
    assert _post(client, f"/mcp/w/{_slug(db_session, me)}", tokens["access_token"]).status_code == 401


def test_a_workspace_token_is_for_that_workspace_even_when_the_client_leaves_out_resource_at_the_token_step(client, on, ws, db_session):
    me = ws("Mine")
    slug = _slug(db_session, me)
    _reg, tokens = _pinned_tokens(client, me, slug, send_resource=False)
    assert _post(client, f"/mcp/w/{slug}", tokens["access_token"]).status_code == 200


def test_the_token_step_refuses_a_different_resource_than_authorize(client, on, ws, db_session):
    me, other = ws("Mine"), ws("Other")
    _join(db_session, me, other)
    reg = _register(client)
    verifier, challenge = _pkce()
    code = _code(_consent(client, _ref(_authorize(client, reg, challenge, resource=_url(_slug(db_session, me)))), me))
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "code_verifier": verifier,
        "resource": _url(_slug(db_session, other)),
    }
    out = client.post("/oauth/token", data=form, headers=_basic(reg))
    assert out.status_code == 400 and out.json()["error"] == "invalid_target"


def test_a_refreshed_workspace_token_keeps_its_audience(client, on, ws, db_session):
    me = ws("Mine")
    slug = _slug(db_session, me)
    reg, tokens = _pinned_tokens(client, me, slug)
    fresh = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, headers=_basic(reg)).json()
    assert _post(client, f"/mcp/w/{slug}", fresh["access_token"]).status_code == 200
    assert _post(client, "/mcp", fresh["access_token"]).status_code == 401


def test_a_session_opened_at_one_url_can_not_be_read_from_another_without_a_token(client, on, ws, db_session):
    me, other = ws("Mine"), ws("Other")
    _join(db_session, me, other)
    mine, theirs = _slug(db_session, me), _slug(db_session, other)
    _reg, tokens = _pinned_tokens(client, me, mine)
    init = _post(client, f"/mcp/w/{mine}", tokens["access_token"])
    session = init.headers["mcp-session-id"]
    for path in ("/mcp", f"/mcp/w/{theirs}"):
        assert client.delete(path, headers={"mcp-session-id": session}).status_code == 401, path


def test_a_workspace_connection_works_in_its_workspace_and_lists_as_pinned(client, on, ws, db_session):
    me = ws("Mine")
    slug = _slug(db_session, me)
    _reg, tokens = _pinned_tokens(client, me, slug)
    token = tokens["access_token"]
    init = _post(client, f"/mcp/w/{slug}", token)
    session = init.headers["mcp-session-id"]
    assert _post(client, f"/mcp/w/{slug}", token, "notifications/initialized", session=session, rpc_id=None).status_code in (200, 202)
    overview = _rpc_body(_post(client, f"/mcp/w/{slug}", token, "tools/call", {"name": "workspace_overview", "arguments": {}}, session, 2))["result"]
    assert not overview.get("isError") and json.loads(overview["content"][0]["text"])
    apps = client.get("/api/users/self/connected-apps", headers={"Authorization": f"Bearer {me.jwt}"}).json()
    assert [a["pinned"] for a in apps] == [True]
    # a general connection (the other kind) is not marked
    _connect(client, me)
    assert sorted(a["pinned"] for a in client.get("/api/users/self/connected-apps", headers={"Authorization": f"Bearer {me.jwt}"}).json()) == [
        False,
        True,
    ]


# ── renames ──────────────────────────────────────────────────────────────────


def test_a_renamed_workspace_keeps_resolving_for_its_connectors(client, on, ws, db_session):
    from marvin.db.models.groups import Groups
    from marvin.services.group.workspace_rename import rename_workspace

    me = ws("Mine")
    old = _slug(db_session, me)
    _reg, tokens = _pinned_tokens(client, me, old)
    token = tokens["access_token"]

    rename_workspace(db_session, db_session.get(Groups, me.gid), name="Mine renamed", slug=f"{old}-renamed")
    db_session.commit()
    new = f"{old}-renamed"

    assert _post(client, f"/mcp/w/{old}", token).status_code == 200  # the old address still works
    assert _post(client, f"/mcp/w/{new}", token).status_code == 200  # and so does the new one, with the same token
    # a new sign-in at the old address still lands in this workspace
    ref = _ref(_authorize(client, _register(client), _pkce()[1], resource=_url(old)))
    view = client.get(f"/api/oauth/requests/{ref}", headers={"Authorization": f"Bearer {me.jwt}"}).json()
    assert [w["id"] for w in view["workspaces"]] == [str(me.gid)]


def test_a_slug_another_workspace_now_has_does_not_inherit_the_token(client, on, ws, db_session):
    """If a slug ends up naming a different workspace, a token minted for the first one is refused there (it is bound
    to the workspace, not to the string)."""
    from marvin.db.models.groups import Groups

    me, other = ws("Mine"), ws("Other")
    _join(db_session, me, other)
    old = _slug(db_session, me)
    _reg, tokens = _pinned_tokens(client, me, old)
    db_session.get(Groups, me.gid).slug = f"{old}-moved"
    db_session.flush()
    db_session.get(Groups, other.gid).slug = old  # (a rename flow forbids this; the check must hold anyway)
    db_session.commit()
    assert _post(client, f"/mcp/w/{old}", tokens["access_token"]).status_code == 401


def test_losing_membership_ends_a_workspace_connection(client, on, ws, db_session):
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    me = ws("Mine")
    slug = _slug(db_session, me)
    _reg, tokens = _pinned_tokens(client, me, slug)
    db_session.query(WorkspaceMembers).filter(WorkspaceMembers.user_id == me.uid).delete()
    db_session.commit()
    assert _post(client, f"/mcp/w/{slug}", tokens["access_token"]).status_code == 401


# the plain /mcp flow is covered by test_remote_mcp_oauth.py and test_remote_mcp_server.py (unchanged); this keeps a
# direct check next to the new routes that the two URLs are separate resources.
def test_mcp_and_workspace_urls_are_separate_resources(client, on, ws, db_session):
    me = ws("Mine")
    _reg, general = _connect(client, me)
    _reg2, pinned = _pinned_tokens(client, me, _slug(db_session, me))
    assert general["access_token"] != pinned["access_token"]
    assert _mcp(client, general["access_token"]).status_code == 200
    assert _mcp(client, pinned["access_token"]).status_code == 401


@pytest.mark.parametrize("path", ["/mcp/w/", "/mcp/w"])
def test_bare_workspace_prefix_is_not_a_connector(client, on, path):
    assert client.post(path, json={}).status_code in (404, 405)
