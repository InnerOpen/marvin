"""Client for the external MCP servers a workspace registers for its agent.

HTTP/SSE transports only (no stdio). The MCP SDK is async; this exposes **sync** wrappers that
`asyncio.run` a short-lived connection per call — safe from the synchronous agent loop / controller
(a sync `def` runs in a threadpool with no running event loop, per the P0 spike). Errors become
:class:`McpClientError` so callers can surface them without crashing the agent.

This module only *connects and calls*. The deny-by-default allowlist, the `external_mcp_enabled`
master switch, and role gating all live in the caller (the agent wiring / the endpoints).
"""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass

DEFAULT_TIMEOUT = 20.0  # seconds, per call


@dataclass
class McpToolInfo:
    """A tool advertised by an external MCP server's tools/list.

    `read_only` / `destructive` come from the server's tool annotations (readOnlyHint,
    destructiveHint); None when the server sends no annotations — callers must treat that as
    "unknown, assume it writes".
    """

    name: str
    description: str
    input_schema: dict
    read_only: bool | None = None
    destructive: bool | None = None


def tool_info_from_listed(t) -> McpToolInfo:
    """Build a McpToolInfo from an `mcp.types.Tool`, keeping the hints the server chose to send."""
    ann = getattr(t, "annotations", None)
    return McpToolInfo(
        name=t.name,
        description=t.description or "",
        input_schema=t.inputSchema or {},
        read_only=getattr(ann, "readOnlyHint", None) if ann else None,
        destructive=getattr(ann, "destructiveHint", None) if ann else None,
    )


class McpClientError(Exception):
    """An external MCP server was unreachable, timed out, or returned a protocol error."""


def headers_for_server(server) -> dict:
    """Auth headers for a registered server — Bearer <resolved secret> when `secret_ref` is set.

    Uses the same secret resolver as the AI provider factory. `secret_ref` is a WorkspaceSecret
    *slug*; we also accept the `{{SLUG}}` template form users know from variables/prompts and
    normalize it to the bare slug. (A configurable header name can come later; Bearer is the common
    case.)
    """
    ref = (getattr(server, "secret_ref", None) or "").strip()
    if ref.startswith("{{") and ref.endswith("}}"):
        ref = ref[2:-2].strip()
    if not ref:
        return {}
    from marvin.services.secrets.resolver import resolve_secret

    token = resolve_secret(ref, server.group_id)
    return {"Authorization": f"Bearer {token}"} if token else {}


@asynccontextmanager
async def _open_session(url: str, transport: str, headers: dict | None, timeout: float):
    """Open a transport + initialized ClientSession for one short-lived connection."""
    from mcp import ClientSession

    if transport == "sse":
        from mcp.client.sse import sse_client

        client_cm = sse_client(url, headers=headers or None, timeout=timeout)
    else:  # "http" (streamable)
        from mcp.client.streamable_http import streamablehttp_client

        client_cm = streamablehttp_client(url, headers=headers or None, timeout=timeout)

    async with client_cm as streams:
        read, write = streams[0], streams[1]  # http yields a 3-tuple, sse a 2-tuple
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _alist_tools(url, transport, headers, timeout) -> list[McpToolInfo]:
    async with _open_session(url, transport, headers, timeout) as session:
        listed = await session.list_tools()
        return [tool_info_from_listed(t) for t in listed.tools]


async def _acall_tool(url, transport, headers, name, args, timeout) -> tuple[str, bool]:
    async with _open_session(url, transport, headers, timeout) as session:
        res = await session.call_tool(name, args or {})
        parts = [c.text for c in res.content if getattr(c, "type", None) == "text"]
        text = "\n".join(parts)
        if not text and getattr(res, "structuredContent", None):
            text = json.dumps(res.structuredContent)
        return text, bool(getattr(res, "isError", False))


def _describe(exc: BaseException) -> str:
    """A useful message from a failed client call.

    The async transports wrap failures in an anyio ExceptionGroup ("unhandled errors in a
    TaskGroup"), which is meaningless to a user — unwrap to the leaf and, for HTTP errors, lead
    with the status code (a 401 usually means the server wants auth / OAuth we don't do yet).
    """
    seen = 0
    while (nested := getattr(exc, "exceptions", None)) and seen < 10:  # unwrap ExceptionGroup chains
        exc = nested[0]
        seen += 1
    status = getattr(getattr(exc, "response", None), "status_code", None)
    msg = str(exc).strip() or type(exc).__name__
    if status == 401:
        return "HTTP 401 — the server requires authentication (an OAuth sign-in or a token this client can't provide)."
    if status:
        return f"HTTP {status} — {msg}"
    return msg


def _run(coro, timeout: float):
    """Run an async client coroutine from sync code with a hard timeout ceiling."""
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout + 2))
    except McpClientError:
        raise
    except TimeoutError as e:
        raise McpClientError("timed out connecting to the server") from e
    except Exception as e:  # connection refused, protocol error, auth, …
        raise McpClientError(_describe(e)) from e


def list_tools(url: str, transport: str = "http", headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> list[McpToolInfo]:
    return _run(_alist_tools(url, transport, headers, timeout), timeout)


def call_tool(
    url: str, transport: str = "http", *, name: str, args: dict | None = None, headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT
) -> tuple[str, bool]:
    """Call a tool; returns (result_text, is_error)."""
    return _run(_acall_tool(url, transport, headers, name, args, timeout), timeout)


# ── Convenience over a WorkspaceMcpServerModel row ─────────────────────────────


def list_server_tools(server, timeout: float = DEFAULT_TIMEOUT) -> list[McpToolInfo]:
    return list_tools(server.url, server.transport, headers_for_server(server), timeout)


def call_server_tool(server, name: str, args: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, bool]:
    return call_tool(
        server.url,
        server.transport,
        name=name,
        args=args,
        headers=headers_for_server(server),
        timeout=timeout,
    )
