"""Entries webhook handler — sends content entry statistics."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.platform.entries import Entries

from .base_webhook import BaseWebhook


class EntriesWebhook(BaseWebhook):
    def info(self, webhook_config: Any, context: dict) -> dict:
        last_log = self.session.execute(
            select(WebhookExecutionLogModel.executed_at)
            .where(WebhookExecutionLogModel.webhook_id == webhook_config.id)
            .order_by(WebhookExecutionLogModel.executed_at.desc())
            .limit(1)
        ).scalar()
        since = last_log if last_log else datetime.now(UTC) - timedelta(hours=24)
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since

        def _count(*where):  # entries in the Trash are not counted
            stmt = select(func.count()).select_from(Entries).where(Entries.group_id == self._group_id, Entries.status != "trashed", *where)
            return self.session.execute(stmt).scalar() or 0

        return {
            "total_entries": _count(),
            "published_entries": _count(Entries.status == "published"),
            "draft_entries": _count(Entries.status == "draft"),
            "new_entries_since_last_run": _count(Entries.created_at >= since_naive),
            "published_since_last_run": _count(
                Entries.status == "published",
                Entries.published_at >= since_naive,
            ),
        }
