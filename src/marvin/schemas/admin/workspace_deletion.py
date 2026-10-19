"""Schemas for deleting a workspace safely and for the stored files a deleted workspace leaves behind."""

from datetime import datetime

from pydantic import UUID4

from marvin.schemas._marvin import _MarvinModel


class WorkspaceDeletePreview(_MarvinModel):
    """What deleting a workspace removes, and whether the backup rule is met (``GET /admin/groups/{id}/delete-preview``)."""

    workspace_id: UUID4
    workspace_name: str
    members: int
    entries: int
    assets: int
    asset_bytes: int
    """Total size of the workspace's stored files."""
    integrations: int
    scheduled_tasks: int
    smtp_profiles: int
    home_users: int
    """Users whose home workspace this is; they lose the home (they stay, in no workspace)."""
    last_backup_at: datetime | None = None
    """When the newest backup bundle of this workspace was written (UTC), None when there is none."""
    backup_is_recent: bool
    """True when that bundle is no older than ``backup_max_age_hours``: a delete needs one, or ``skip_backup=true``."""
    backup_max_age_hours: int
    storage_grace_days: int
    """Its stored files are kept this long after the delete, then purged (Admin → Storage lists them)."""


class WorkspaceDeleteResult(_MarvinModel):
    status: str
    message: str
    storage_locations: int = 0
    """How many storage locations were recorded for a purge after the grace period."""
    storage_purge_after: datetime | None = None


class DeletedWorkspaceStorageRead(_MarvinModel):
    """One storage location of a deleted workspace, waiting for its purge."""

    id: UUID4
    workspace_id: UUID4
    workspace_name: str
    workspace_slug: str | None = None
    location: str
    label: str | None = None
    object_count: int
    total_bytes: int
    deleted_at: datetime
    purge_after: datetime
    """When the daily task purges it (deleted_at + the grace period); passed means the next run."""
    state: str
    """``pending``, ``kept`` or ``purged``."""
    purged_objects: int | None = None
    can_purge: bool = True
    """False when its own bucket can't be reached any more (the keys weren't kept): nothing to purge from here."""
    last_error: str | None = None


class DeletedWorkspaceStorageList(_MarvinModel):
    items: list[DeletedWorkspaceStorageRead]
    grace_days: int
