"""`/mcp` and `/mcp/w/<workspace-slug>`: the remote MCP server's HTTP endpoint (streamable HTTP, the MCP SDK's session
manager behind a token check). The second form is a connector pinned to one workspace: its own OAuth resource, so a
token for it works there and nowhere else (`oauth.serves_resource`).

Each request:
1. 404 while the platform switch is off (or there is no issuer);
2. a bearer access token resolves to its grant (`oauth.verify_access_token`: unexpired, unrevoked, for this resource,
   the user still a member), else 401 with `WWW-Authenticate: Bearer resource_metadata=…`;
3. the workspace still allows AI from external MCP hosts, else 403;
4. a request on an existing session must come from the grant that opened it (403). GET and DELETE on a live session
   may come without a token (ChatGPT's desktop client sends none on its event stream), as long as that grant is
   still good. POST always needs one;
5. the connection goes on the request state for the handlers (`server.py`), and the SDK takes over.

Sessions live in this process's memory (one backend process), so a deploy ends them: the SDK answers 404 for an
unknown session id and clients start a new one (MCP spec). One log line per request, never a token.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from marvin.core.root_logger import get_logger
from marvin.services.mcp_remote.policy import SCOPE_WRITE, SLUG_RE, issuer, resource_url, workspace_resource_url

logger = get_logger(__name__)

# The SSE library logs every chunk it streams at DEBUG, tool results included. A result can hold a one-time upload link, and
# a workspace's content besides, so that stream is not logged whatever the app's level.
logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)

SESSION_HEADER = "mcp-session-id"
SESSION_IDLE_SECONDS = 3600


def _challenge(issuer_url: str, *, invalid: bool, slug: str | None = None) -> Response:
    meta = f"{issuer_url}/.well-known/oauth-protected-resource/mcp" + (f"/w/{slug}" if slug else "")
    value = f'Bearer resource_metadata="{meta}"' + (', error="invalid_token"' if invalid else "")
    return JSONResponse({"error": "invalid_token" if invalid else "unauthorized"}, status_code=401, headers={"WWW-Authenticate": value})


class RemoteMcpTransport:
    """The ASGI app at /mcp. `running()` must be entered (the app's lifespan) before it serves anything."""

    def __init__(self) -> None:
        self._manager = None
        self._sessions: dict[str, tuple[UUID, float]] = {}  # session id → (grant id, last seen)

    @asynccontextmanager
    async def running(self):
        """Run a fresh SDK session manager (one can only run once, so a new one per lifespan)."""
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        from marvin.services.mcp_remote.server import server

        # Security settings left at None: DNS-rebinding protection guards cookie-less local servers; every
        # request here carries a bearer token, and the Host varies (public host, LAN route, tests).
        manager = StreamableHTTPSessionManager(app=server, json_response=False, stateless=False, session_idle_timeout=SESSION_IDLE_SECONDS)
        async with manager.run():
            self._manager, self._sessions = manager, {}
            try:
                yield
            finally:
                self._manager, self._sessions = None, {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        started = time.monotonic()
        status_box: dict = {}

        opens_session = SESSION_HEADER not in request.headers

        async def send_logged(message) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = message["status"]
                sid = _header(message.get("headers") or [], SESSION_HEADER)
                if opens_session and sid and "grant" in status_box:  # the SDK just started this session
                    self._sessions[sid] = (status_box["grant"], time.monotonic())
            await send(message)

        try:
            await self._handle(request, scope, receive, send_logged, status_box)
        finally:
            logger.info(
                "remote MCP %s %s → %s in %dms (auth=%s grant=%s session=%s ua=%s)",
                request.method,
                request.url.path[:100],
                status_box.get("status", "-"),
                (time.monotonic() - started) * 1000,
                "yes" if request.headers.get("authorization") else "no",
                status_box.get("grant", "-"),
                (request.headers.get(SESSION_HEADER) or "-")[:12],
                (request.headers.get("user-agent") or "-")[:80],
            )

    async def _handle(self, request: Request, scope: Scope, receive: Receive, send: Send, box: dict) -> None:
        from marvin.services.platform_policy import remote_mcp

        issuer_url = issuer(request) if remote_mcp().enabled else None
        slug = (scope.get("path_params") or {}).get("slug")  # set on /mcp/w/{slug}: the connector pinned to a workspace
        if slug is not None:
            slug = slug.lower()
        if not issuer_url or (slug is not None and not SLUG_RE.fullmatch(slug)):
            return await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
        resource = workspace_resource_url(issuer_url, slug) if slug else resource_url(issuer_url)
        if self._manager is None:
            return await JSONResponse({"detail": "The MCP server is starting"}, status_code=503)(scope, receive, send)

        header = request.headers.get("authorization") or ""
        bearer = header[7:].strip() if header.lower().startswith("bearer ") else ""
        session_id = request.headers.get(SESSION_HEADER)
        bound = self._live(session_id)

        if bearer:
            conn = await _connection_for_token(request, bearer, resource, issuer_url)
        elif bound is not None and request.method in ("GET", "DELETE"):
            conn = await _connection_for_grant(bound, resource, issuer_url)
        else:
            conn = None
        if conn is None:
            logger.warning("remote MCP: /mcp refused (%s)", "bad token" if bearer else "no token")
            return await _challenge(issuer_url, invalid=bool(bearer), slug=slug)(scope, receive, send)
        if isinstance(conn, Response):
            return await conn(scope, receive, send)
        box["grant"] = conn.grant_id
        if request.method == "POST":
            from marvin.services.mcp_remote import limits

            try:
                limits.check("mcp_request", str(conn.grant_id))
            except limits.RateLimited as e:
                body = {"error": "rate_limited", "error_description": "Too many requests from this connection; slow down."}
                return await JSONResponse(body, status_code=429, headers={"Retry-After": str(e.retry_after)})(scope, receive, send)
            limits.hit("mcp_request", str(conn.grant_id))
        if bound is not None and bound != conn.grant_id:
            logger.warning("remote MCP: session %s belongs to another connection", session_id[:12])
            return await JSONResponse({"error": "forbidden", "error_description": "This session belongs to another connection."}, status_code=403)(
                scope, receive, send
            )
        if session_id and bound is not None:
            self._sessions[session_id] = (bound, time.monotonic())
            if request.method == "DELETE":
                self._sessions.pop(session_id, None)

        scope.setdefault("state", {})["mcp_connection"] = conn
        self._prune()
        await self._manager.handle_request(scope, receive, send)

    def _live(self, session_id: str | None) -> UUID | None:
        entry = self._sessions.get(session_id or "")
        return entry[0] if entry else None

    def _prune(self) -> None:
        """Forget sessions the SDK has idled out (it drops them after SESSION_IDLE_SECONDS without a request)."""
        cutoff = time.monotonic() - SESSION_IDLE_SECONDS - 60
        for sid in [sid for sid, (_g, seen) in self._sessions.items() if seen < cutoff]:
            self._sessions.pop(sid, None)


def _header(headers, name: str) -> str | None:
    wanted = name.encode()
    for key, value in headers:
        if key.lower() == wanted:
            return value.decode()
    return None


def _connection(session, grant, request: Request | None):
    """The handlers' Connection for a valid grant, or a 403 response when the workspace turned MCP off."""
    from marvin.services.mcp_remote import oauth as svc
    from marvin.services.mcp_remote.server import Connection

    if not svc._mcp_allowed(session, grant.group_id):
        logger.warning("remote MCP: workspace %s has turned off AI from external MCP hosts", grant.group_id)
        return JSONResponse({"error": "forbidden", "error_description": "This workspace has turned off AI from external MCP hosts."}, status_code=403)
    if request is not None:
        from marvin.services.security.login_throttle import login_client_ip

        grant.last_used_at = svc._now()
        grant.last_ip = login_client_ip(request)[:64]
        grant.last_user_agent = (request.headers.get("user-agent") or "")[:300] or None
        session.commit()
    return Connection(grant_id=grant.id, user_id=grant.user_id, group_id=grant.group_id, can_write=SCOPE_WRITE in grant.scope.split())


async def _connection_for_token(request: Request, bearer: str, resource: str, issuer_url: str):
    import anyio

    from marvin.db.db_setup import session_context
    from marvin.services.mcp_remote import limits
    from marvin.services.mcp_remote import oauth as svc

    def check():
        with session_context() as session:
            grant = svc.verify_access_token(
                session,
                bearer,
                resource=resource,
                issuer=issuer_url,
                on_revoke=lambda g, reason: limits.announce("mcp_connection_revoked", session, g, reason=reason),
            )
            return None if grant is None else _connection(session, grant, request)

    return await anyio.to_thread.run_sync(check)


async def _connection_for_grant(grant_id: UUID, resource: str, issuer_url: str):
    """A tokenless GET/DELETE on a live session: its grant must still be unrevoked, serve the URL it came to and its
    user a member."""
    import anyio

    from marvin.db.db_setup import session_context
    from marvin.db.models.platform.oauth import OAuthGrantModel
    from marvin.services.mcp_remote import oauth as svc

    def check():
        with session_context() as session:
            grant = session.get(OAuthGrantModel, grant_id)
            if (
                grant is None
                or grant.revoked_at is not None
                or not svc.serves_resource(session, grant, resource, issuer_url)
                or svc.member_role(session, grant.user_id, grant.group_id) <= 0
            ):
                return None
            return _connection(session, grant, None)

    return await anyio.to_thread.run_sync(check)


transport = RemoteMcpTransport()
