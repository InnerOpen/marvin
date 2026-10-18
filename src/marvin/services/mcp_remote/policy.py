"""Where the remote MCP server lives and what its OAuth metadata says.

The issuer is `PUBLIC_API_URL` (the chart's `config.publicApiUrl`) and the protected resource is that plus `/mcp`.
Both stay the public host whatever host a request arrived on (the LAN `.apps` route, say), because a token is bound
to the resource it was issued for. A connector can also be pinned to one workspace: `/mcp/w/<workspace-slug>` is a
resource of its own (see `canonical_resource`), with metadata at `.well-known/oauth-protected-resource/mcp/w/<slug>`.
With no `PUBLIC_API_URL`, PRODUCTION keeps the server off (`platform_policy.remote_mcp`);
development takes the issuer from the request and says so in the log.
"""

from __future__ import annotations

import re

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

SCOPE_READ = "marvin:read"
SCOPE_WRITE = "marvin:write"
SCOPES = (SCOPE_READ, SCOPE_WRITE)
MCP_PATH = "/mcp"
WORKSPACE_PATH = "/mcp/w/"
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}")

_warned = False


def issuer(request) -> str | None:
    """The OAuth issuer: PUBLIC_API_URL, else (outside PRODUCTION) the request's own origin."""
    global _warned
    from marvin.core.config import get_app_settings

    env = get_app_settings()
    if env.PUBLIC_API_URL:
        return env.PUBLIC_API_URL
    if env.PRODUCTION:
        return None
    if not _warned:
        logger.warning("PUBLIC_API_URL is not set: the remote MCP issuer is taken from each request (development only)")
        _warned = True
    return str(request.base_url).rstrip("/")


def resource_url(issuer_url: str) -> str:
    return f"{issuer_url}{MCP_PATH}"


def workspace_resource_url(issuer_url: str, slug: str) -> str:
    return f"{issuer_url}{WORKSPACE_PATH}{slug}"


def canonical_resource(issuer_url: str, resource: str | None) -> str | None:
    """`resource` as this server names it, or None when it isn't one of its resources: `<issuer>/mcp` (the workspace is
    chosen at consent) or `<issuer>/mcp/w/<slug>` (pinned to a workspace; the slug lower-cased). Trailing slash ignored."""
    base = (resource or "").strip().rstrip("/")
    if base == resource_url(issuer_url):
        return base
    prefix = f"{issuer_url}{WORKSPACE_PATH}"
    if base.startswith(prefix):
        slug = base[len(prefix) :].lower()
        if SLUG_RE.fullmatch(slug):
            return f"{prefix}{slug}"
    return None


def pinned_slug(issuer_url: str, resource: str | None) -> str | None:
    """The workspace slug a resource is pinned to, or None (`/mcp`, or not ours)."""
    prefix = f"{issuer_url}{WORKSPACE_PATH}"
    canonical = canonical_resource(issuer_url, resource)
    return canonical[len(prefix) :] if canonical and canonical.startswith(prefix) else None


def authorization_server_metadata(issuer_url: str, *, allow_dynamic_registration: bool = True) -> dict:
    """RFC 8414 metadata. S256 is the only PKCE method; a confidential client may send its secret either way."""
    meta = {
        "issuer": issuer_url,
        "authorization_endpoint": f"{issuer_url}/oauth/authorize",
        "token_endpoint": f"{issuer_url}/oauth/token",
        "revocation_endpoint": f"{issuer_url}/oauth/revoke",
        "scopes_supported": list(SCOPES),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
        "revocation_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
        "authorization_response_iss_parameter_supported": True,
    }
    if allow_dynamic_registration:
        meta["registration_endpoint"] = f"{issuer_url}/oauth/register"
    return meta


def protected_resource_metadata(issuer_url: str, slug: str | None = None) -> dict:
    """RFC 9728 metadata for `/mcp` (or, with a slug, for that workspace's own URL): which authorization server issues
    its tokens."""
    return {
        "resource": workspace_resource_url(issuer_url, slug) if slug else resource_url(issuer_url),
        "authorization_servers": [issuer_url],
        "scopes_supported": list(SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "Marvin",
    }
