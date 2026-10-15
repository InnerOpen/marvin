"""Purge the remote MCP server's spent OAuth records (db/models/platform/oauth.py)."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


class PurgeOAuthRecordsHandler(ScheduledTaskHandler):
    """
    Delete what can never be used again: expired sign-in requests (and their codes), expired access and refresh
    tokens, connections revoked or dead (no token left) for `grant_days`, and registered clients with no connection
    that nobody has used for `client_days`.

    Admin-only. A connection that still has a live refresh token is never touched, however old.
    """

    name = "Purge OAuth Records"
    description = "Delete expired remote MCP sign-ins and tokens, long-dead connections and unused clients (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "properties": {
            "grant_days": {"type": "integer", "default": 90, "description": "Keep a revoked or dead connection this many days"},
            "client_days": {"type": "integer", "default": 7, "description": "Keep a client with no connection this many days after it was last used"},
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: purge_oauth_records is admin-only and cannot run in a workspace context"
        config = task.task_config or {}
        counts = purge_oauth_records(
            datetime.now(UTC),
            grant_days=max(int(config.get("grant_days", 90)), 0),
            client_days=max(int(config.get("client_days", 7)), 0),
        )
        if not any(counts.values()):
            return None  # the usual daily answer; not worth a row
        summary = ", ".join(f"{n} {what}" for what, n in counts.items() if n)
        logger.info("OAuth purge: %s", summary)
        return f"Deleted {summary}"


def purge_oauth_records(now: datetime, *, grant_days: int = 90, client_days: int = 7) -> dict[str, int]:
    from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel, OAuthClientModel, OAuthGrantModel, OAuthTokenModel

    grant_cutoff = now - timedelta(days=grant_days)
    client_cutoff = now - timedelta(days=client_days)
    with session_context() as session:
        tokens = session.query(OAuthTokenModel).filter(OAuthTokenModel.expires_at < now).delete(synchronize_session=False)
        requests = (
            session.query(OAuthAuthorizationRequestModel)
            .filter(
                OAuthAuthorizationRequestModel.expires_at < now,
                sa.or_(OAuthAuthorizationRequestModel.code_expires_at.is_(None), OAuthAuthorizationRequestModel.code_expires_at < now),
            )
            .delete(synchronize_session=False)
        )
        has_token = sa.exists().where(OAuthTokenModel.grant_id == OAuthGrantModel.id)
        last_seen = sa.func.coalesce(OAuthGrantModel.last_used_at, OAuthGrantModel.created_at)
        grants = (
            session.query(OAuthGrantModel)
            .filter(sa.or_(OAuthGrantModel.revoked_at < grant_cutoff, sa.and_(~has_token, last_seen < grant_cutoff)))
            .delete(synchronize_session=False)
        )
        has_grant = sa.exists().where(OAuthGrantModel.client_fk == OAuthClientModel.id)
        client_seen = sa.func.coalesce(OAuthClientModel.last_used_at, OAuthClientModel.created_at)
        clients = session.query(OAuthClientModel).filter(~has_grant, client_seen < client_cutoff).delete(synchronize_session=False)
        session.commit()
    return {"expired token(s)": tokens, "expired sign-in request(s)": requests, "connection(s)": grants, "unused client(s)": clients}


TaskHandlerRegistry.register("purge_oauth_records", PurgeOAuthRecordsHandler)
