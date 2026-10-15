"""The remote MCP's /api routes: what the consent page calls, and connected apps.

- /api/oauth/requests/{ref} (GET, approve, deny): only a signed-in session may approve (a session JWT from the browser),
  never a personal API token, so a script holding one can't mint itself an MCP grant (plan §6.1 item 8).
- /api/users/self/connected-apps: the caller's grants, and Revoke.
- /api/admin/connected-apps: every grant, and Revoke (super admins).
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import UUID4

from marvin.core.config import get_app_settings
from marvin.core.dependencies.dependencies import ALGORITHM, get_current_superuser, get_current_user, oauth2_scheme_soft_fail
from marvin.db.db_setup import generate_session, session_context
from marvin.schemas._marvin import _MarvinModel
from marvin.services.mcp_remote import limits
from marvin.services.mcp_remote import oauth as svc
from marvin.services.mcp_remote.policy import issuer

router = APIRouter(prefix="/api")


class ConsentWorkspace(_MarvinModel):
    id: str
    name: str
    slug: str
    can_write: bool
    mcp_allowed: bool


class ConsentRequestRead(_MarvinModel):
    status: str
    client_name: str
    """What the app calls itself: unverified."""
    redirect_host: str
    """Where the approval is sent back to: the verified fact."""
    wants_write: bool
    consent_nonce: str | None = None
    workspaces: list[ConsentWorkspace] = []


class ConsentDecision(_MarvinModel):
    consent_nonce: str | None = None
    workspace_id: str | None = None
    access: str = "read"


class ConsentResult(_MarvinModel):
    redirect_to: str | None = None
    already: bool = False


class ConnectedAppRead(_MarvinModel):
    id: str
    client_name: str
    redirect_host: str
    access: str
    workspace_id: str
    workspace: str
    user_id: str
    user: str
    created_at: object | None = None
    last_used_at: object | None = None
    revoked_at: object | None = None
    revoked_reason: str | None = None


async def session_user(request: Request, token: str | None = Depends(oauth2_scheme_soft_fail), session=Depends(generate_session)):
    """The signed-in user, from a session (the browser's JWT), refusing personal API tokens and long-lived JWTs."""
    settings = get_app_settings()
    raw = token or request.cookies.get(settings.AUTH_COOKIE_NAME, "") or ""
    refused = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approving an MCP app needs a signed-in session, not an API token.")
    if raw.startswith(settings.SECURITY_TOKEN_PREFIX_USER):
        raise refused
    try:
        if jwt.decode(raw, settings.SECRET, algorithms=[ALGORITHM]).get("long_token") is not None:
            raise refused
    except jwt.PyJWTError:
        pass  # get_current_user answers 401
    return await get_current_user(request, token, session)


def _http(e: svc.OAuthError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.description or e.error)


def _issuer_or_404(request: Request) -> str:
    """The OAuth issuer (it goes back to the client as ``iss``) while remote MCP is on; 404 otherwise."""
    from marvin.services.platform_policy import remote_mcp

    issuer_url = issuer(request) if remote_mcp().enabled else None
    if not issuer_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remote MCP is off")
    return issuer_url


# ── consent ──────────────────────────────────────────────────────────────────


@router.get("/oauth/requests/{ref}", response_model=ConsentRequestRead, include_in_schema=False)
def get_request(ref: str, request: Request, user=Depends(session_user)) -> ConsentRequestRead:
    _issuer_or_404(request)
    with session_context() as session:
        try:
            return ConsentRequestRead.model_validate(svc.consent_view(session, ref, user))
        except svc.OAuthError as e:
            raise _http(e) from None


@router.post("/oauth/requests/{ref}/approve", response_model=ConsentResult, include_in_schema=False)
def approve(ref: str, data: ConsentDecision, request: Request, user=Depends(session_user)) -> ConsentResult:
    issuer_url = _issuer_or_404(request)
    with session_context() as session:
        try:
            out = svc.approve(
                session,
                ref,
                user,
                workspace_id=data.workspace_id,
                access=data.access,
                nonce=data.consent_nonce,
                issuer=issuer_url,
            )
        except svc.OAuthError as e:
            raise _http(e) from None
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick a workspace") from None
        if out.get("grant") is not None:
            limits.announce("mcp_connection_authorized", session, out["grant"])
    return ConsentResult(redirect_to=out.get("redirect_to"), already=bool(out.get("already")))


@router.post("/oauth/requests/{ref}/deny", response_model=ConsentResult, include_in_schema=False)
def deny(ref: str, data: ConsentDecision, request: Request, user=Depends(session_user)) -> ConsentResult:
    issuer_url = _issuer_or_404(request)
    with session_context() as session:
        try:
            out = svc.deny(session, ref, user, nonce=data.consent_nonce, issuer=issuer_url)
        except svc.OAuthError as e:
            raise _http(e) from None
    return ConsentResult(redirect_to=out["redirect_to"])


# ── connected apps ───────────────────────────────────────────────────────────


@router.get("/users/self/connected-apps", response_model=list[ConnectedAppRead], summary="List My Connected MCP Apps")
def my_connected_apps(user=Depends(get_current_user)) -> list[ConnectedAppRead]:
    """The MCP apps (claude.ai, ChatGPT, Claude Code…) the caller let use Marvin, still connected."""
    with session_context() as session:
        return [ConnectedAppRead.model_validate(g) for g in svc.list_grants(session, user_id=user.id)]


@router.post("/users/self/connected-apps/{grant_id}/revoke", response_model=ConnectedAppRead, summary="Disconnect One of My MCP Apps")
def revoke_my_app(grant_id: UUID4, user=Depends(get_current_user)) -> ConnectedAppRead:
    """Revoke the app's access at once: its tokens stop working; it has to be approved again to reconnect."""
    from marvin.db.models.platform.oauth import OAuthGrantModel

    with session_context() as session:
        grant = session.get(OAuthGrantModel, grant_id)
        if grant is None or str(grant.user_id) != str(user.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        was_live = grant.revoked_at is None
        grant = svc.revoke_grant(session, grant.id, reason="user")
        if was_live:
            limits.announce("mcp_connection_revoked", session, grant, reason="user")
        return ConnectedAppRead.model_validate(svc.grant_view(session, grant))


@router.get("/admin/connected-apps", response_model=list[ConnectedAppRead], summary="Admin: List Connected MCP Apps")
def all_connected_apps(include_revoked: bool = False, _admin=Depends(get_current_superuser)) -> list[ConnectedAppRead]:
    """Every user's connected MCP apps (and, with include_revoked, the revoked ones and why)."""
    with session_context() as session:
        return [ConnectedAppRead.model_validate(g) for g in svc.list_grants(session, include_revoked=include_revoked)]


@router.post("/admin/connected-apps/{grant_id}/revoke", response_model=ConnectedAppRead, summary="Admin: Disconnect an MCP App")
def admin_revoke_app(grant_id: UUID4, _admin=Depends(get_current_superuser)) -> ConnectedAppRead:
    with session_context() as session:
        from marvin.db.models.platform.oauth import OAuthGrantModel

        grant = session.get(OAuthGrantModel, grant_id)
        if grant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        was_live = grant.revoked_at is None
        grant = svc.revoke_grant(session, grant.id, reason="admin")
        if was_live:
            limits.announce("mcp_connection_revoked", session, grant, reason="admin")
        return ConnectedAppRead.model_validate(svc.grant_view(session, grant))
