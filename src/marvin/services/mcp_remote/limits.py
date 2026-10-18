"""Rate limits and audit events for the remote MCP OAuth endpoints (plan §6.1 items 10 and 12).

The limits are in memory, per process: the backend runs one process (a sliding window per key is enough, and a restart
forgetting it is harmless). Registration 10/h per IP, authorize 30/h per IP, token failures 20 per 10 minutes per IP,
120 MCP requests a minute per connection (a runaway client can't hammer Marvin; an assistant at work makes a few),
20 upload links an hour per connection and 30 upload-page attempts per 10 minutes per IP.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

LIMITS = {
    "register": (10, 3600),
    "authorize": (30, 3600),
    "token_failure": (20, 600),
    "mcp_request": (120, 60),
    "upload_link": (20, 3600),  # per connection: links asked for
    "upload_try": (30, 600),  # per IP: attempts at the upload page
}
_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


def _window(kind: str, key: str) -> tuple[deque, int, int]:
    limit, seconds = LIMITS[kind]
    hits = _hits.setdefault((kind, key), deque())
    now = time.monotonic()
    while hits and now - hits[0] > seconds:
        hits.popleft()
    return hits, limit, seconds


def check(kind: str, key: str) -> None:
    """Raise RateLimited when ``key`` already used up ``kind``'s window (without counting this attempt)."""
    with _lock:
        hits, limit, seconds = _window(kind, key)
        if len(hits) >= limit:
            retry = int(seconds - (time.monotonic() - hits[0])) + 1
            logger.warning("remote MCP: %s rate limit hit for %s", kind, key)
            raise RateLimited(max(retry, 1))


def hit(kind: str, key: str) -> None:
    with _lock:
        hits, _limit, _seconds = _window(kind, key)
        hits.append(time.monotonic())


def reset() -> None:
    with _lock:
        _hits.clear()


def announce(event_type: str, session, grant, *, reason: str | None = None) -> None:
    """mcp_connection_authorized / _revoked / mcp_token_reuse_detected: names and hosts only, never a token."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventMcpConnectionData, EventOperation, EventTypes

    from .policy import SCOPE_WRITE

    group = session.get(Groups, grant.group_id)
    user = session.get(Users, grant.user_id)
    who = (user.full_name or user.username) if user else None
    access = "write" if SCOPE_WRITE in grant.scope.split() else "read"
    kind = {  # named in full: the catalog tests find senders by `EventTypes.<name>`
        "mcp_connection_authorized": EventTypes.mcp_connection_authorized,
        "mcp_connection_revoked": EventTypes.mcp_connection_revoked,
        "mcp_token_reuse_detected": EventTypes.mcp_token_reuse_detected,
    }[event_type]
    verb = {
        "mcp_connection_authorized": "connected",
        "mcp_connection_revoked": "disconnected",
        "mcp_token_reuse_detected": "reused a token and was cut off",
    }[event_type]
    EventBusService(bg_tasks=None).dispatch(
        integration_id="remote_mcp",
        group_id=grant.group_id,
        event_type=kind,
        document_data=EventMcpConnectionData(
            operation=EventOperation.create if event_type == "mcp_connection_authorized" else EventOperation.update,
            grant_id=str(grant.id),
            client_name=grant.client_name_snapshot,
            redirect_host=grant.redirect_host,
            access=access,
            workspace_id=str(grant.group_id),
            workspace_name=group.name if group else None,
            user_name=who,
            reason=reason,
        ),
        message=f"MCP app '{grant.client_name_snapshot}' ({grant.redirect_host}) {verb} for {who or 'a user'} in "
        + (group.name if group else "a workspace")
        + (f" ({reason})" if reason else ""),
        user_id=grant.user_id,
        entity_id=grant.id,
        entity_type="mcp_connection",
    )
