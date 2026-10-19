"""Deleting a workspace safely: what is at stake (the preview), the backup rule, and the `workspace_deleted` event.

Decisions 2026-10-18 (tasks/retire-platform-workspace-plan.md): an admin deletes a workspace by typing its name,
and only with a backup bundle of it from the last 24 hours — or with an explicit "delete without a backup".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

BACKUP_MAX_AGE = timedelta(hours=24)
"""The newest bundle must be at most this old for a delete without an explicit skip."""


def latest_bundle_at(session: Session, group: Any, backup_dir: Path) -> datetime | None:
    """When the newest backup bundle of ``group`` in ``backup_dir`` was written (UTC), or None. Bundles are
    ``<slug>-backup-<date>-<token>.zip``; a renamed workspace's earlier bundles carry its former slugs."""
    from marvin.services.group.workspace_rename import former_slugs

    if not backup_dir.exists():
        return None
    slugs = list(dict.fromkeys([s for s in (group.slug, *former_slugs(session, group.id)) if s]))
    newest: float | None = None
    for slug in slugs:
        for path in backup_dir.glob(f"{slug}-backup-*.zip"):
            if path.name.split("-backup-", 1)[0] != slug:  # `a-backup-` must not match `a-backup-x-backup-...`'s owner
                continue
            mtime = path.stat().st_mtime
            newest = mtime if newest is None or mtime > newest else newest
    return datetime.fromtimestamp(newest, UTC) if newest is not None else None


def has_recent_bundle(last: datetime | None, now: datetime | None = None) -> bool:
    return last is not None and (now or datetime.now(UTC)) - last <= BACKUP_MAX_AGE


def preview(session: Session, group: Any, backup_dir: Path) -> dict:
    """The counts an admin should see before deleting ``group``."""
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel
    from marvin.db.models.platform import Assets, Entries
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    def count(model: Any, column: Any) -> int:
        return int(session.scalar(select(func.count()).select_from(model).where(column == group.id)) or 0)

    assets, asset_bytes = session.execute(
        select(func.count(Assets.id), func.coalesce(func.sum(Assets.file_size), 0)).where(Assets.group_id == group.id)
    ).one()
    last = latest_bundle_at(session, group, backup_dir)
    return {
        "workspace_id": group.id,
        "workspace_name": group.name,
        "members": count(WorkspaceMembers, WorkspaceMembers.group_id),
        "entries": count(Entries, Entries.group_id),
        "assets": int(assets or 0),
        "asset_bytes": int(asset_bytes or 0),
        "integrations": count(IntegrationModel, IntegrationModel.group_id),
        "scheduled_tasks": count(ScheduledTaskModel, ScheduledTaskModel.group_id),
        "smtp_profiles": count(WorkspaceSMTPProfileModel, WorkspaceSMTPProfileModel.group_id),
        "home_users": count(Users, Users.group_id),
        "last_backup_at": last,
        "backup_is_recent": has_recent_bundle(last),
        "backup_max_age_hours": int(BACKUP_MAX_AGE.total_seconds() // 3600),
    }
