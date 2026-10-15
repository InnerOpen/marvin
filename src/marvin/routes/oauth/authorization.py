"""The remote MCP server's OAuth endpoints (root level, outside /api; 404 while the platform switch is off):

- POST /oauth/register: dynamic client registration (RFC 7591), 10/h per IP.
- GET /oauth/authorize: validate, store the request pending, send the browser to the consent page on the UI host.
- POST /oauth/token: authorization_code (PKCE S256) and refresh_token (rotating).
- POST /oauth/revoke: RFC 7009.
- /mcp: checks the bearer token; until the MCP transport lands (slice 3) it answers initialize with no tools.

Every rejection is logged at warning (a silent 401 costs hours: BrainMCP). No route sets a cookie.
"""

from __future__ import annotations

import base64
import html
import json
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.services.mcp_remote import limits
from marvin.services.mcp_remote import oauth as svc
from marvin.services.mcp_remote.policy import issuer, resource_url

logger = get_logger(__name__)
router = APIRouter()
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
MCP_PROTOCOL = "2025-06-18"


def _on(request: Request):
    """(issuer, policy) while remote MCP is on; 404 otherwise."""
    from marvin.services.platform_policy import remote_mcp

    policy = remote_mcp()
    issuer_url = issuer(request) if policy.enabled else None
    if not issuer_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return issuer_url, policy


def _ip(request: Request) -> str:
    from marvin.services.security.login_throttle import login_client_ip

    return login_client_ip(request)


def _error(e: svc.OAuthError, headers: dict | None = None) -> JSONResponse:
    logger.warning("remote MCP: %s %s", e.error, e.description)
    return JSONResponse(e.body(), status_code=e.status, headers={**NO_STORE, **(headers or {})})


def _limited(e: limits.RateLimited) -> JSONResponse:
    return JSONResponse(
        {"error": "slow_down", "error_description": "Too many requests"}, status_code=429, headers={"Retry-After": str(e.retry_after)}
    )


async def _form(request: Request) -> dict:
    return {k: str(v) for k, v in (await request.form()).items()}


def _basic(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip()).decode()
        client_id, _, secret = raw.partition(":")
        return unquote(client_id), unquote(secret)  # RFC 6749 §2.3.1: form-encoded before base64
    except Exception:  # noqa: BLE001
        raise svc.OAuthError("invalid_client", "malformed Basic credentials", 401) from None


# ── registration ─────────────────────────────────────────────────────────────


@router.post("/oauth/register")
async def register(request: Request) -> Response:
    _issuer, policy = _on(request)
    if not policy.allow_dynamic_registration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    ip = _ip(request)
    try:
        limits.check("register", ip)
    except limits.RateLimited as e:
        return _limited(e)
    limits.hit("register", ip)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error(svc.OAuthError("invalid_client_metadata", "the body must be JSON"))
    if not isinstance(body, dict):
        return _error(svc.OAuthError("invalid_client_metadata", "the body must be a JSON object"))
    with session_context() as session:
        try:
            out = svc.register_client(session, body, ip=ip, extra_redirect_uris=policy.extra_redirect_uris)
        except svc.OAuthError as e:
            return _error(e)
    return JSONResponse(out, status_code=201, headers=NO_STORE)


# ── authorize ────────────────────────────────────────────────────────────────


def _error_page(e: svc.OAuthError) -> HTMLResponse:
    logger.warning("remote MCP authorize refused (no redirect): %s %s", e.error, e.description)
    body = (
        "<!doctype html><meta charset='utf-8'><title>Can't connect to Marvin</title>"
        "<body style='font-family:system-ui;max-width:36rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1>Can't connect to Marvin</h1><p>{html.escape(e.description or e.error)}</p>"
        "<p>Start the connection again from your app.</p></body>"
    )
    return HTMLResponse(body, status_code=400, headers={"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'"})


@router.get("/oauth/authorize")
def authorize(request: Request) -> Response:
    from marvin.core.config import get_app_settings

    issuer_url, _policy = _on(request)
    ip = _ip(request)
    try:
        limits.check("authorize", ip)
    except limits.RateLimited as e:
        return _limited(e)
    limits.hit("authorize", ip)
    params = dict(request.query_params)
    with session_context() as session:
        try:
            pending = svc.start_authorization(session, params, ip=ip, resource=resource_url(issuer_url))
        except svc.AuthorizeError as e:
            if not e.redirect_uri:
                return _error_page(e)
            logger.warning("remote MCP authorize refused: %s %s", e.error, e.description)
            back = svc._with_query(e.redirect_uri, {"error": e.error, "error_description": e.description, "state": e.state, "iss": issuer_url})
            return RedirectResponse(back, status_code=302)
    ui = (get_app_settings().BASE_URL or "").rstrip("/")
    return RedirectResponse(f"{ui}/oauth/consent?req={pending.ref}", status_code=302)


# ── token and revoke ─────────────────────────────────────────────────────────


@router.post("/oauth/token")
async def token(request: Request) -> Response:
    _issuer, policy = _on(request)
    ip = _ip(request)
    try:
        limits.check("token_failure", ip)
    except limits.RateLimited as e:
        return _limited(e)
    form = await _form(request)
    with session_context() as session:
        try:
            client = svc.authenticate_client(session, basic=_basic(request), form=form)
            grant_type = form.get("grant_type")
            if grant_type == "authorization_code":
                out = svc.exchange_code(session, client, form, policy=policy)
            elif grant_type == "refresh_token":
                out = svc.refresh(
                    session,
                    client,
                    form,
                    policy=policy,
                    on_reuse=lambda grant: limits.announce("mcp_token_reuse_detected", session, grant, reason="reuse_detected"),
                )
            else:
                raise svc.OAuthError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token")
        except svc.OAuthError as e:
            limits.hit("token_failure", ip)
            return _error(e, {"WWW-Authenticate": 'Basic realm="marvin"'} if e.status == 401 else None)
    return JSONResponse(out, headers=NO_STORE)


@router.post("/oauth/revoke")
async def revoke(request: Request) -> Response:
    _on(request)
    form = await _form(request)
    with session_context() as session:
        try:
            client = svc.authenticate_client(session, basic=_basic(request), form=form)
        except svc.OAuthError as e:
            return _error(e, {"WWW-Authenticate": 'Basic realm="marvin"'})
        grant = svc.revoke_token(session, client, form.get("token") or "")
        if grant is not None:
            limits.announce("mcp_connection_revoked", session, grant, reason="client")
    return Response(status_code=200, headers=NO_STORE)


# ── /mcp (the token check; tools arrive with slice 3) ────────────────────────


def _challenge(issuer_url: str, *, invalid: bool) -> Response:
    meta = f"{issuer_url}/.well-known/oauth-protected-resource/mcp"
    value = f'Bearer resource_metadata="{meta}"' + (', error="invalid_token"' if invalid else "")
    return JSONResponse({"error": "invalid_token" if invalid else "unauthorized"}, status_code=401, headers={"WWW-Authenticate": value})


def _rpc(result_or_error: dict, rpc_id) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, **result_or_error})


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"])
async def mcp(request: Request) -> Response:
    issuer_url, _policy = _on(request)
    header = request.headers.get("authorization") or ""
    bearer = header[7:].strip() if header.lower().startswith("bearer ") else ""
    with session_context() as session:
        grant = svc.verify_access_token(
            session,
            bearer,
            resource=resource_url(issuer_url),
            on_revoke=lambda g, reason: limits.announce("mcp_connection_revoked", session, g, reason=reason),
        )
        if grant is None:
            logger.warning("remote MCP: /mcp refused (%s)", "bad token" if bearer else "no token")
            return _challenge(issuer_url, invalid=bool(bearer))
        grant.last_used_at = svc._now()
        grant.last_ip = _ip(request)[:64]
        grant.last_user_agent = (request.headers.get("user-agent") or "")[:300] or None
        session.commit()
    if request.method != "POST":
        return Response(status_code=405, headers={"Allow": "POST"})
    try:
        message = await request.json()
    except json.JSONDecodeError:
        return _rpc({"error": {"code": -32700, "message": "Parse error"}}, None)
    if not isinstance(message, dict):
        return _rpc({"error": {"code": -32600, "message": "Invalid request"}}, None)
    method, rpc_id = message.get("method"), message.get("id")
    if rpc_id is None:  # a notification (e.g. notifications/initialized)
        return Response(status_code=202)
    if method == "initialize":
        from marvin import __version__

        asked = (message.get("params") or {}).get("protocolVersion") or MCP_PROTOCOL
        return _rpc(
            {
                "result": {
                    "protocolVersion": asked,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "Marvin", "version": __version__},
                    "instructions": "Marvin's tools arrive in the next release; this connection is signed in.",
                }
            },
            rpc_id,
        )
    if method == "tools/list":
        return _rpc({"result": {"tools": []}}, rpc_id)
    if method == "ping":
        return _rpc({"result": {}}, rpc_id)
    return _rpc({"error": {"code": -32601, "message": f"Method not found: {method}"}}, rpc_id)
