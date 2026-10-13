"""User webhook handler — sends workspace member statistics."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.users.workspace_members import WorkspaceMembers

from .base_webhook import BaseWebhook


class UserWebhook(BaseWebhook):
    def info(self, webhook_config: Any, context: dict) -> dict:
        last_log = self.session.execute(
            select(WebhookExecutionLogModel.executed_at)
            .where(WebhookExecutionLogModel.webhook_id == webhook_config.id)
            .order_by(WebhookExecutionLogModel.executed_at.desc())
            .limit(1)
        ).scalar()
        since = last_log if last_log else datetime.now(UTC) - timedelta(hours=24)
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since

        total = (
            self.session.execute(select(func.count()).select_from(WorkspaceMembers).where(WorkspaceMembers.group_id == self._group_id)).scalar() or 0
        )

        new_count = (
            self.session.execute(
                select(func.count())
                .select_from(WorkspaceMembers)
                .where(
                    WorkspaceMembers.group_id == self._group_id,
                    WorkspaceMembers.created_at >= since_naive,
                )
            ).scalar()
            or 0
        )

        return {
            "total_members": total,
            "new_members_since_last_run": new_count,
        }
