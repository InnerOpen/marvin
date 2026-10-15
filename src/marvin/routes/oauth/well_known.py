"""OAuth discovery for the remote MCP server: authorization server metadata (RFC 8414) and protected resource
metadata (RFC 9728). An MCP client reads them after `/mcp` answers 401."""

from fastapi import APIRouter, HTTPException, Request, status

from marvin.services.mcp_remote.policy import authorization_server_metadata, issuer, protected_resource_metadata

router = APIRouter(prefix="/.well-known")


def _issuer_or_404(request: Request) -> tuple[str, object]:
    from marvin.services.platform_policy import remote_mcp

    policy = remote_mcp()
    issuer_url = issuer(request) if policy.enabled else None
    if not issuer_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return issuer_url, policy


@router.get("/oauth-authorization-server")
def oauth_authorization_server(request: Request) -> dict:
    issuer_url, policy = _issuer_or_404(request)
    return authorization_server_metadata(issuer_url, allow_dynamic_registration=policy.allow_dynamic_registration)


@router.get("/oauth-protected-resource")
@router.get("/oauth-protected-resource/mcp")
def oauth_protected_resource(request: Request) -> dict:
    issuer_url, _policy = _issuer_or_404(request)
    return protected_resource_metadata(issuer_url)
