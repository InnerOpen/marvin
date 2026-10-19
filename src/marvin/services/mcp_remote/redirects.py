"""Which redirect URIs an MCP client may register and be sent back to (plan §6.1 item 1).

Built in: Claude's callbacks (claude.ai, claude.com), ChatGPT's connector callback, and the loopback addresses on any
port and path (Claude Code and other local clients run a callback server there). An admin can add exact https URIs, or
`https://host/path*` prefixes, in the remote MCP policy (`extra_redirect_uris`). Anything else is refused at
registration, and a redirect URI is re-checked against the client's registered list (exact match) at authorize.
"""

from __future__ import annotations

from urllib.parse import urlsplit

BUILT_IN = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "https://chatgpt.com/connector_platform_oauth_redirect",
)
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_LENGTH = 1000


def is_loopback(uri: str) -> bool:
    parts = urlsplit(uri)
    return parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_HOSTS and not parts.fragment


def allowed(uri: str, extra: tuple[str, ...] | list[str] = ()) -> bool:
    """Whether a client may register ``uri`` as a redirect URI."""
    if not isinstance(uri, str) or not uri or len(uri) > MAX_LENGTH or "#" in uri:
        return False
    if is_loopback(uri) or uri in BUILT_IN:
        return True
    for entry in extra or ():
        entry = str(entry).strip()
        if not entry.startswith("https://"):
            continue
        if entry.endswith("*") and uri.startswith(entry[:-1]) and urlsplit(uri).scheme == "https":
            return True
        if uri == entry:
            return True
    return False


def host_of(uri: str) -> str:
    """What the consent page shows as the verified destination: the host (with port for loopback)."""
    parts = urlsplit(uri)
    host = parts.hostname or uri
    return f"{host}:{parts.port}" if parts.port and is_loopback(uri) else host
