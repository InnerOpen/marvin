"""Clearing the workspace-scoped rows that don't cascade on their own.

Most tables keyed on ``groups.id`` declare ``ondelete="CASCADE"`` and disappear with the workspace.
A handful were created without it, so their rows keep a foreign key against the group and abort the
DELETE — which is precisely what a force delete is meant to push through. Clear those explicitly,
children before parents.

Users are deliberately not touched. They outlive the workspace, and the caller refuses the delete
while any still have it as their primary group.
"""

from pydantic import UUID4
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from marvin.db.models.groups.invite_tokens import GroupInviteToken
from marvin.db.models.groups.preferences import GroupPreferencesModel
from marvin.db.models.groups.reports import ReportEntryModel, ReportModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.platform.event_log import EventLogModel


def purge_group_dependents(session: Session, group_id: UUID4) -> None:
    """Delete the non-cascading rows belonging to ``group_id``, leaving the group itself."""
    report_ids = select(ReportModel.id).where(ReportModel.group_id == group_id)

    statements = [
        # Children first — they reference the per-group parents below, not the group itself.
        delete(ReportEntryModel).where(ReportEntryModel.report_id.in_(report_ids)),
        # Then the group-scoped parents. webhook_execution_logs cascade off webhook_urls.
        delete(ReportModel).where(ReportModel.group_id == group_id),
        delete(GroupInviteToken).where(GroupInviteToken.group_id == group_id),
        delete(GroupWebhooksModel).where(GroupWebhooksModel.group_id == group_id),
        delete(EventLogModel).where(EventLogModel.workspace_id == group_id),
        delete(GroupPreferencesModel).where(GroupPreferencesModel.group_id == group_id),
    ]
    for stmt in statements:
        session.execute(stmt)
    session.flush()
