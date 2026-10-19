"""The remote MCP server's OAuth 2.1 authorization server (plan §2, §6.1): clients, pending requests, consent, codes,
tokens, grants.

- Every secret is opaque (256 bits) and stored only as a SHA-256 hash: client secrets, the pending request's ref, the
  consent nonce, codes, access and refresh tokens. Prefixes (``marvin_oc_`` …) let secret scanners find a leaked one;
  none starts with the personal token's ``marvin_tk_`` or the site client's ``marvin_sk_``, so none works on /api.
- The pending request travels by URL ref, never by cookie, and lives in the database, so an MCP client that fetches
  /oauth/authorize with its own HTTP client, or a deploy in the middle of a sign-in, doesn't lose it (BrainMCP).
- A grant is one approval ("connected app"): a user, ONE workspace, a scope, a resource. Tokens hang off it; revoking
  it (user, admin, membership lost, token reuse, a dev refresh) kills them all.
- Refresh tokens rotate on every use. A rotated one presented again inside REUSE_GRACE_SECONDS is refused quietly (a
  client retrying); after that it means a copy is in someone else's hands: the grant is revoked and
  ``mcp_token_reuse_detected`` sent. A code used twice revokes what it issued (RFC 6749 §4.1.2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from marvin.core.root_logger import get_logger

from . import redirects
from .policy import SCOPE_READ, SCOPE_WRITE, SCOPES, canonical_resource, pinned_slug, resource_url

logger = get_logger(__name__)

PREFIX_CLIENT, PREFIX_SECRET, PREFIX_CODE, PREFIX_ACCESS, PREFIX_REFRESH = "marvin_oc_", "marvin_cs_", "marvin_ac_", "marvin_at_", "marvin_rt_"
REQUEST_MINUTES = 30
CODE_MINUTES = 5
REUSE_GRACE_SECONDS = 30
AUTH_METHODS = ("client_secret_basic", "client_secret_post", "none")
GRANT_TYPES = ("authorization_code", "refresh_token")
ROLE_EDITOR = 3
MAX_CLIENT_NAME = 200


class OAuthError(Exception):
    """An OAuth error response: ``error`` code, a safe description, the HTTP status."""

    def __init__(self, error: str, description: str = "", status: int = 400) -> None:
        super().__init__(f"{error}: {description}")
        self.error, self.description, self.status = error, description, status

    def body(self) -> dict:
        return {"error": self.error, **({"error_description": self.description} if self.description else {})}


class AuthorizeError(OAuthError):
    """An error at /oauth/authorize. With ``redirect_uri`` set (the client and redirect URI were valid), it is sent
    back to the client; without, it is shown as a page and never redirected (plan §6.1 item 1)."""

    def __init__(self, error: str, description: str = "", *, redirect_uri: str | None = None, state: str | None = None) -> None:
        super().__init__(error, description)
        self.redirect_uri, self.state = redirect_uri, state


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """A stored time as UTC-aware (the columns hand back either, depending on the driver)."""
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _new(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def _with_query(uri: str, params: dict) -> str:
    parts = urlsplit(uri)
    query = "&".join(p for p in (parts.query, urlencode({k: v for k, v in params.items() if v is not None})) if p)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _scopes(raw: str | None) -> list[str]:
    asked = [s for s in (raw or "").split() if s]
    return asked or list(SCOPES)


# ── clients (RFC 7591) ───────────────────────────────────────────────────────


def register_client(session, body: dict, *, ip: str | None, extra_redirect_uris=()) -> dict:
    """Dynamic client registration. The secret is returned once and stored hashed."""
    from marvin.db.models.platform.oauth import OAuthClientModel

    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris:
        raise OAuthError("invalid_redirect_uri", "redirect_uris is required")
    for uri in uris:
        if not redirects.allowed(uri, extra_redirect_uris):
            raise OAuthError("invalid_redirect_uri", f"redirect URI not allowed: {str(uri)[:200]}")
    method = body.get("token_endpoint_auth_method") or "client_secret_basic"
    if method not in AUTH_METHODS:
        raise OAuthError("invalid_client_metadata", f"token_endpoint_auth_method must be one of {', '.join(AUTH_METHODS)}")
    grant_types = body.get("grant_types") or list(GRANT_TYPES)
    if not isinstance(grant_types, list) or "authorization_code" not in grant_types or any(g not in GRANT_TYPES for g in grant_types):
        raise OAuthError("invalid_client_metadata", "grant_types must include authorization_code (and may include refresh_token)")
    if body.get("response_types") not in (None, ["code"]):
        raise OAuthError("invalid_client_metadata", "response_types must be [code]")
    name = " ".join(str(body.get("client_name") or "MCP client").split())[:MAX_CLIENT_NAME] or "MCP client"
    client_id = _new(PREFIX_CLIENT)[:64]
    secret = None if method == "none" else _new(PREFIX_SECRET)

    def short(key: str, limit: int) -> str | None:
        value = body.get(key)
        return str(value)[:limit] if value else None

    client = OAuthClientModel(
        session=session,
        client_id=client_id,
        client_secret_hash=_hash(secret) if secret else None,
        token_endpoint_auth_method=method,
        redirect_uris=list(uris),
        grant_types=list(grant_types),
        client_name=name,
        client_uri=short("client_uri", 500),
        logo_uri=short("logo_uri", 500),
        software_id=short("software_id", 100),
        software_version=short("software_version", 100),
        registered_ip=(ip or "")[:64] or None,
    )
    session.add(client)
    session.commit()
    logger.info("remote MCP: client registered (%s, %s, %d redirect URI(s))", name, method, len(uris))
    out = {
        "client_id": client_id,
        "client_id_issued_at": int(datetime.now(UTC).timestamp()),
        "redirect_uris": list(uris),
        "grant_types": list(grant_types),
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "client_name": name,
    }
    if secret:
        out |= {"client_secret": secret, "client_secret_expires_at": 0}
    return out


def _client(session, client_id: str | None):
    from marvin.db.models.platform.oauth import OAuthClientModel

    if not client_id:
        return None
    return session.query(OAuthClientModel).filter_by(client_id=str(client_id)[:64]).one_or_none()


def authenticate_client(session, *, basic: tuple[str, str] | None, form: dict):
    """The client of a /oauth/token or /oauth/revoke request, by HTTP Basic or by form fields. A confidential client
    may use either (RFC 6749 §2.3.1); ``none`` only for a client registered as public. Raises 401 invalid_client."""
    client_id, secret = basic if basic else (form.get("client_id"), form.get("client_secret"))
    client = _client(session, client_id)
    if client is None:
        logger.warning("remote MCP: invalid_client (unknown client_id)")
        raise OAuthError("invalid_client", "unknown client", 401)
    if client.token_endpoint_auth_method == "none":
        if secret:
            logger.warning("remote MCP: invalid_client (a public client sent a secret)")
            raise OAuthError("invalid_client", "this client has no secret", 401)
        return client
    if not secret or not client.client_secret_hash or not hmac.compare_digest(_hash(str(secret)), client.client_secret_hash):
        logger.warning("remote MCP: invalid_client (wrong or missing secret for %s)", client.client_name)
        raise OAuthError("invalid_client", "client authentication failed", 401)
    return client


# ── authorize → consent ──────────────────────────────────────────────────────


@dataclass
class PendingRequest:
    ref: str
    """The opaque value the consent page URL carries (``?req=``)."""


def start_authorization(session, params: dict, *, ip: str | None, issuer: str) -> PendingRequest:
    """Validate an authorization request and store it pending. Errors before the client and redirect URI are
    known-good carry no redirect_uri (shown as a page); later ones go back to the client. The resource is `<issuer>/mcp`
    or a workspace's own `<issuer>/mcp/w/<slug>` (its slug is looked up at consent, where only a signed-in user sees
    the answer)."""
    from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel

    client = _client(session, params.get("client_id"))
    if client is None:
        raise AuthorizeError("invalid_client", "unknown client_id")
    redirect_uri = params.get("redirect_uri") or (client.redirect_uris[0] if len(client.redirect_uris or []) == 1 else None)
    if not redirect_uri or redirect_uri not in (client.redirect_uris or []):
        raise AuthorizeError("invalid_request", "redirect_uri isn't one this client registered")
    state = params.get("state")

    def back(error: str, description: str) -> AuthorizeError:
        return AuthorizeError(error, description, redirect_uri=redirect_uri, state=state)

    if params.get("response_type") != "code":
        raise back("unsupported_response_type", "response_type must be code")
    challenge, method = params.get("code_challenge"), params.get("code_challenge_method")
    if not challenge or method != "S256" or not (43 <= len(challenge) <= 128):
        raise back("invalid_request", "PKCE with code_challenge_method=S256 is required")
    resource = canonical_resource(issuer, params.get("resource") or resource_url(issuer))
    if resource is None:
        raise back("invalid_target", "unknown resource")
    scopes = _scopes(params.get("scope"))
    if any(s not in SCOPES for s in scopes):
        raise back("invalid_scope", f"scopes are {', '.join(SCOPES)}")
    ref = _new()
    session.add(
        OAuthAuthorizationRequestModel(
            session=session,
            ref_lookup=_hash(ref),
            client_fk=client.id,
            redirect_uri=redirect_uri,
            state=(state or None) and str(state)[:1000],
            code_challenge=challenge,
            requested_scope=" ".join(scopes),
            resource=resource,
            consent_nonce_hash=_hash(_new()),  # replaced when the consent page loads
            expires_at=_now() + timedelta(minutes=REQUEST_MINUTES),
            created_ip=(ip or "")[:64] or None,
        )
    )
    session.commit()
    return PendingRequest(ref=ref)


def _pending(session, ref: str):
    from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel

    row = session.query(OAuthAuthorizationRequestModel).filter_by(ref_lookup=_hash(str(ref or ""))).one_or_none()
    if row is None:
        raise OAuthError("not_found", "This sign-in request doesn't exist. Start again from your app.", 404)
    return row


def _memberships(session, user_id) -> list[tuple[Any, str, str, int]]:
    """(group id, name, slug, numeric role) of the user's real memberships (super admins get no others)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    rows = (
        session.query(Groups.id, Groups.name, Groups.slug, WorkspaceMembers.workspace_role)
        .join(WorkspaceMembers, WorkspaceMembers.group_id == Groups.id)
        .filter(WorkspaceMembers.user_id == user_id)
        .order_by(Groups.name)
        .all()
    )
    return [(gid, name, slug, WORKSPACE_ROLE_HIERARCHY.get(role, 0)) for gid, name, slug, role in rows]


def member_role(session, user_id, group_id) -> int:
    return next((role for gid, _n, _s, role in _memberships(session, user_id) if str(gid) == str(group_id)), 0)


def _mcp_allowed(session, group_id) -> bool:
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.operations.base import source_allowed

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    return source_allowed(settings.invocation_sources if settings else None, "mcp")


def _pinned_group(session, issuer: str, resource: str):
    """The workspace a pinned resource names (its current slug or a former one), or None."""
    from marvin.services.group.workspace_rename import find_group_by_slug

    slug = pinned_slug(issuer, resource)
    return find_group_by_slug(session, slug) if slug else None


def consent_view(session, ref: str, user, *, issuer: str) -> dict:
    """What the consent page shows, and a fresh consent nonce for its form (only its hash is kept). A request for a
    workspace's own URL offers that workspace only (none when the user isn't a member, or it doesn't exist: the page
    can't tell them apart, which keeps slugs from being probed)."""
    from marvin.db.models.platform.oauth import OAuthClientModel

    row = _pending(session, ref)
    client = session.get(OAuthClientModel, row.client_fk)
    expired = row.status == "pending" and _aware(row.expires_at) < _now()
    nonce = None
    if row.status == "pending" and not expired:
        nonce = _new()
        row.consent_nonce_hash = _hash(nonce)
        session.commit()
    asked = row.requested_scope.split()
    pinned = pinned_slug(issuer, row.resource) is not None
    pinned_group = _pinned_group(session, issuer, row.resource) if pinned else None
    return {
        "pinned": pinned,
        "status": "expired" if expired else row.status,
        "client_name": client.client_name if client else "Unknown app",
        "redirect_host": redirects.host_of(row.redirect_uri),
        "wants_write": SCOPE_WRITE in asked,
        "consent_nonce": nonce,
        "workspaces": [
            {"id": str(gid), "name": name, "slug": slug, "can_write": role >= ROLE_EDITOR, "mcp_allowed": _mcp_allowed(session, gid)}
            for gid, name, slug, role in _memberships(session, user.id)
            if not pinned or (pinned_group is not None and gid == pinned_group.id)
        ],
    }


def _usable_pending(session, ref: str, nonce: str | None):
    row = _pending(session, ref)
    if row.status != "pending":
        return row
    if _aware(row.expires_at) < _now():
        row.status = "expired"
        session.commit()
        raise OAuthError("expired", "This sign-in request expired. Start again from your app.", 410)
    if not nonce or not hmac.compare_digest(_hash(str(nonce)), row.consent_nonce_hash):
        raise OAuthError("forbidden", "This approval page is out of date. Reload it and try again.", 403)
    return row


def approve(session, ref: str, user, *, workspace_id, access: str, nonce: str | None, issuer: str) -> dict:
    """Approve a pending request: create the grant and a single-use code. Returns ``{"redirect_to"}`` (None when it
    was already approved: the code was already sent)."""
    from marvin.db.models.platform.oauth import OAuthClientModel, OAuthGrantModel

    row = _usable_pending(session, ref, nonce)
    if row.status == "approved" and str(row.user_id) == str(user.id):
        return {"redirect_to": None, "already": True}
    if row.status != "pending":
        raise OAuthError("forbidden", f"This sign-in request was already {row.status}.", 403)
    if pinned_slug(issuer, row.resource) is not None:  # the connector's own URL names the workspace; the form can't change it
        pinned = _pinned_group(session, issuer, row.resource)
        if pinned is None or (workspace_id and str(workspace_id) != str(pinned.id)):
            raise OAuthError("forbidden", "You aren't a member of the workspace this connector is for.", 403)
        workspace_id = pinned.id
    role = member_role(session, user.id, workspace_id)
    if role <= 0:
        raise OAuthError("forbidden", "You aren't a member of that workspace.", 403)
    if not _mcp_allowed(session, workspace_id):
        raise OAuthError("forbidden", "That workspace has turned off AI from external MCP hosts.", 403)
    if access not in ("read", "write"):
        raise OAuthError("invalid_request", "access must be read or write")
    if access == "write" and (role < ROLE_EDITOR or SCOPE_WRITE not in row.requested_scope.split()):
        raise OAuthError("forbidden", "Read & write needs the Editor role, and an app that asked for it.", 403)
    scope = f"{SCOPE_READ} {SCOPE_WRITE}" if access == "write" else SCOPE_READ
    client = session.get(OAuthClientModel, row.client_fk)
    grant = OAuthGrantModel(
        session=session,
        user_id=user.id,
        group_id=uuid.UUID(str(workspace_id)),
        client_fk=row.client_fk,
        scope=scope,
        resource=row.resource,
        client_name_snapshot=client.client_name if client else "MCP client",
        redirect_host=redirects.host_of(row.redirect_uri)[:200],
    )
    session.add(grant)
    session.flush()
    code = _new(PREFIX_CODE)
    row.status, row.user_id, row.group_id, row.granted_scope, row.grant_id = "approved", user.id, grant.group_id, scope, grant.id
    row.code_lookup, row.code_expires_at = _hash(code), _now() + timedelta(minutes=CODE_MINUTES)
    session.commit()
    return {"redirect_to": _with_query(row.redirect_uri, {"code": code, "state": row.state, "iss": issuer}), "grant": grant}


def deny(session, ref: str, user, *, nonce: str | None, issuer: str) -> dict:
    row = _usable_pending(session, ref, nonce)
    if row.status != "pending":
        raise OAuthError("forbidden", f"This sign-in request was already {row.status}.", 403)
    row.status, row.user_id = "denied", user.id
    session.commit()
    return {"redirect_to": _with_query(row.redirect_uri, {"error": "access_denied", "state": row.state, "iss": issuer})}


# ── tokens ───────────────────────────────────────────────────────────────────


def _issue(session, grant, *, access_minutes: int, refresh_days: int) -> dict:
    from marvin.db.models.platform.oauth import OAuthTokenModel

    access, refresh = _new(PREFIX_ACCESS), _new(PREFIX_REFRESH)
    now = _now()
    refresh_row = OAuthTokenModel(
        session=session, grant_id=grant.id, kind="refresh", token_lookup=_hash(refresh), expires_at=now + timedelta(days=refresh_days)
    )
    session.add(
        OAuthTokenModel(
            session=session, grant_id=grant.id, kind="access", token_lookup=_hash(access), expires_at=now + timedelta(minutes=access_minutes)
        )
    )
    session.add(refresh_row)
    session.flush()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": access_minutes * 60,
        "refresh_token": refresh,
        "scope": grant.scope,
        "_refresh_row": refresh_row,
    }


def _public(tokens: dict) -> dict:
    return {k: v for k, v in tokens.items() if not k.startswith("_")}


def exchange_code(session, client, form: dict, *, policy, issuer: str) -> dict:
    """authorization_code: a single-use, 5-minute code bound to the client, the redirect URI and the PKCE challenge."""
    from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel, OAuthGrantModel

    code = form.get("code") or ""
    row = session.query(OAuthAuthorizationRequestModel).filter_by(code_lookup=_hash(code)).one_or_none() if code else None
    if row is None or str(row.client_fk) != str(client.id):
        raise OAuthError("invalid_grant", "unknown code")
    if row.code_used_at is not None:
        if row.grant_id:
            revoke_grant(session, row.grant_id, reason="code_reuse")
        logger.warning("remote MCP: an authorization code was used twice; its grant is revoked")
        raise OAuthError("invalid_grant", "code already used")
    if row.code_expires_at is None or _aware(row.code_expires_at) < _now():
        raise OAuthError("invalid_grant", "code expired")
    if form.get("redirect_uri", row.redirect_uri) != row.redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri doesn't match")
    verifier = form.get("code_verifier") or ""
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    if not verifier or not hmac.compare_digest(expected, row.code_challenge):
        raise OAuthError("invalid_grant", "PKCE verification failed")
    if form.get("resource") and canonical_resource(issuer, form["resource"]) != row.resource:
        raise OAuthError("invalid_target", "unknown resource")
    grant = session.get(OAuthGrantModel, row.grant_id) if row.grant_id else None
    if grant is None or grant.revoked_at is not None:
        raise OAuthError("invalid_grant", "the approval was revoked")
    row.code_used_at = _now()
    tokens = _issue(session, grant, access_minutes=policy.access_token_minutes, refresh_days=policy.refresh_token_days)
    client.last_used_at = _now()
    session.commit()
    return _public(tokens)


def refresh(session, client, form: dict, *, policy, on_reuse=None) -> dict:
    """refresh_token: rotate. A rotated token presented again after the grace revokes the grant (``on_reuse`` is
    told, to send the event); inside the grace it is refused without revoking (a client's retry race)."""
    from marvin.db.models.platform.oauth import OAuthGrantModel, OAuthTokenModel

    token = form.get("refresh_token") or ""
    row = session.query(OAuthTokenModel).filter_by(token_lookup=_hash(token), kind="refresh").one_or_none() if token else None
    grant = session.get(OAuthGrantModel, row.grant_id) if row else None
    if row is None or grant is None or str(grant.client_fk) != str(client.id):
        raise OAuthError("invalid_grant", "unknown refresh token")
    if grant.revoked_at is not None:
        raise OAuthError("invalid_grant", "the approval was revoked")
    if row.rotated_at is not None:
        if (_now() - _aware(row.rotated_at)).total_seconds() > REUSE_GRACE_SECONDS:
            revoke_grant(session, grant.id, reason="reuse_detected")
            logger.warning("remote MCP: a rotated refresh token was used again; grant %s revoked", grant.id)
            if on_reuse:
                on_reuse(grant)
        raise OAuthError("invalid_grant", "refresh token already used")
    if _aware(row.expires_at) < _now():
        raise OAuthError("invalid_grant", "refresh token expired")
    if grant.created_at and _now() - _aware(grant.created_at) > timedelta(days=policy.grant_max_days):
        raise OAuthError("invalid_grant", "this approval is too old: sign in again")
    asked = form.get("scope")
    if asked and any(s not in grant.scope.split() for s in asked.split()):
        raise OAuthError("invalid_scope", "a refresh can't widen the scope")
    tokens = _issue(session, grant, access_minutes=policy.access_token_minutes, refresh_days=policy.refresh_token_days)
    row.rotated_at, row.replaced_by = _now(), tokens["_refresh_row"].id
    client.last_used_at = _now()
    session.commit()
    return _public(tokens)


def revoke_token(session, client, token: str):
    """RFC 7009: revoke the grant behind one of this client's tokens and return it. Unknown or foreign tokens:
    nothing, quietly (None)."""
    from marvin.db.models.platform.oauth import OAuthGrantModel, OAuthTokenModel

    row = session.query(OAuthTokenModel).filter_by(token_lookup=_hash(token or "")).one_or_none()
    grant = session.get(OAuthGrantModel, row.grant_id) if row else None
    if grant is not None and str(grant.client_fk) == str(client.id) and grant.revoked_at is None:
        return revoke_grant(session, grant.id, reason="client")
    return None


def serves_resource(session, grant, resource: str, issuer: str) -> bool:
    """Whether a grant's token may be used at `resource` (the URL the request came to). A grant for `<issuer>/mcp`
    works there only. One for a workspace's own URL works only at a workspace URL that now names that same workspace
    (the slug may have been renamed: a former slug still counts), never at `/mcp` or another workspace's URL."""
    slug = pinned_slug(issuer, resource)
    if slug is None:
        return canonical_resource(issuer, resource) == grant.resource
    if pinned_slug(issuer, grant.resource) is None:
        return False
    group = _pinned_group(session, issuer, resource)
    return group is not None and str(group.id) == str(grant.group_id)


def verify_access_token(session, token: str, *, resource: str, issuer: str, on_revoke=None):
    """The grant an access token at /mcp stands for, or None: unexpired, unrevoked, issued for this resource (see
    `serves_resource`), and its user still a member of the workspace (else the grant is revoked as membership_lost)."""
    from marvin.db.models.platform.oauth import OAuthGrantModel, OAuthTokenModel

    if not token or not token.startswith(PREFIX_ACCESS):
        return None
    row = session.query(OAuthTokenModel).filter_by(token_lookup=_hash(token), kind="access").one_or_none()
    if row is None or _aware(row.expires_at) < _now():
        return None
    grant = session.get(OAuthGrantModel, row.grant_id)
    if grant is None or grant.revoked_at is not None or not serves_resource(session, grant, resource, issuer):
        return None
    if member_role(session, grant.user_id, grant.group_id) <= 0:
        revoke_grant(session, grant.id, reason="membership_lost")
        if on_revoke:
            on_revoke(grant, "membership_lost")
        return None
    return grant


# ── grants (connected apps) ──────────────────────────────────────────────────


def revoke_grant(session, grant_id, *, reason: str) -> Any:
    """Revoke a grant and delete its tokens. Returns the grant (None if unknown); revoking twice is harmless."""
    from marvin.db.models.platform.oauth import OAuthGrantModel, OAuthTokenModel

    grant = session.get(OAuthGrantModel, uuid.UUID(str(grant_id)))
    if grant is None:
        return None
    if grant.revoked_at is None:
        grant.revoked_at, grant.revoked_reason = _now(), reason[:64]
    session.query(OAuthTokenModel).filter(OAuthTokenModel.grant_id == grant.id).delete()
    session.commit()
    return grant


def grant_view(session, grant) -> dict:
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    group = session.get(Groups, grant.group_id)
    user = session.get(Users, grant.user_id)
    return {
        "id": str(grant.id),
        "client_name": grant.client_name_snapshot,
        "redirect_host": grant.redirect_host,
        "scope": grant.scope,
        "access": "write" if SCOPE_WRITE in grant.scope.split() else "read",
        "workspace_id": str(grant.group_id),
        "workspace": group.name if group else "?",
        "pinned": "/mcp/w/" in grant.resource,
        "user_id": str(grant.user_id),
        "user": (user.full_name or user.username) if user else "?",
        "created_at": grant.created_at,
        "last_used_at": grant.last_used_at,
        "revoked_at": grant.revoked_at,
        "revoked_reason": grant.revoked_reason,
    }


def list_grants(session, *, user_id=None, include_revoked: bool = False) -> list[dict]:
    from marvin.db.models.platform.oauth import OAuthGrantModel

    q = session.query(OAuthGrantModel)
    if user_id is not None:
        q = q.filter(OAuthGrantModel.user_id == user_id)
    if not include_revoked:
        q = q.filter(OAuthGrantModel.revoked_at.is_(None))
    return [grant_view(session, g) for g in q.order_by(OAuthGrantModel.created_at.desc()).all()]
