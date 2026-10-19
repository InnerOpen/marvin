"""A workspace's own backups, in its own private bucket (BYO storage, slice 5).

A workspace that picked a verified backup bucket (Workspace settings → Storage → Backups to your own bucket) gets
its backup bundle — the same zip as Admin → Backups makes: content, settings and files, secrets encrypted under the
workspace's backup key — written there by the daily Workspace Backup Bundles task and by "Back up now". Keys are
``marvin-backups/<workspace slug>/<UTC stamp>-<bundle name>``, so they sort by time; after each new backup only the
newest ``backup_keep`` stay. The bucket is the workspace's; Marvin never reads or writes anything else in it.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import workspace as ws

PREFIX = "marvin-backups"
CHUNK = 1024 * 1024


class WorkspaceBackupError(RuntimeError):
    """A backup that can't be saved or read (the message is safe to show)."""


@dataclass
class SavedBackup:
    key: str
    size: int
    pruned: int
    bucket_label: str | None


def _settings_row(session, group_id):
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    return session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()


def has_own_backups(session, group_id) -> bool:
    row = _settings_row(session, group_id)
    return bool(row and row.backup_connection_id)


def _slug(session, group_id) -> str:
    from marvin.db.models.groups import Groups

    group = session.get(Groups, group_id)
    if group is None:
        raise WorkspaceBackupError("the workspace no longer exists")
    return group.slug


def _target(session, group_id):
    """(target, connection row) of the workspace's backup bucket. Raises when there is none or it isn't verified."""
    from marvin.services.storage.workspace_admin import _asset_buckets, get_connection

    row = _settings_row(session, group_id)
    if not row or not row.backup_connection_id:
        raise WorkspaceBackupError("this workspace has no backup bucket of its own")
    conn = get_connection(session, group_id, row.backup_connection_id)
    if conn.status != ws.STATUS_OK:
        raise WorkspaceBackupError("the workspace's backup bucket isn't verified: check it in Workspace settings → Storage")
    pol = ws.policy(session)
    if not pol.allowed:
        raise WorkspaceBackupError("the platform doesn't allow workspace storage")
    try:
        target = ws.build_connection_target(
            ws._snapshot(conn), pol.endpoint_policy, production=ws._production(), asset_buckets=_asset_buckets(session, group_id)
        )
    except Exception as e:  # noqa: BLE001 — StorageConfigError, or the plugin failing to build its client
        raise WorkspaceBackupError(f"the workspace's backup bucket can't be reached ({e})") from e
    return target, conn


def _prefix(slug: str) -> str:
    return f"{PREFIX}/{slug}/"


def save_backup(session, group_id, zip_path: Path) -> SavedBackup:
    """Upload one bundle to the workspace's backup bucket, then keep only its newest ``backup_keep`` backups there."""
    target, conn = _target(session, group_id)
    slug = _slug(session, group_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    key = f"{_prefix(slug)}{stamp}-{zip_path.name}"
    digest = hashlib.sha256()
    with zip_path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    target.put_file(key, zip_path, {"sha256": digest.hexdigest()}, "application/zip")
    keep = max(int(_settings_row(session, group_id).backup_keep or 7), 1)
    mine = sorted(target.list(_prefix(slug)))
    stale = mine[:-keep] if len(mine) > keep else []
    if stale:
        target.delete(stale)
    return SavedBackup(key=key, size=zip_path.stat().st_size, pruned=len(stale), bucket_label=conn.label)


def list_backups(session, group_id) -> list[dict[str, Any]]:
    """The workspace's backups in its bucket, newest first: {key, name, size}."""
    target, _conn = _target(session, group_id)
    prefix = _prefix(_slug(session, group_id))
    objects = target.list(prefix)
    return [{"key": k, "name": k[len(prefix) :], "size": int(objects[k].size)} for k in sorted(objects, reverse=True)]


def fetch_backup(session, group_id, key: str, dest_dir: Path) -> Path:
    """Download one of the workspace's backups into ``dest_dir`` (checked against the sha256 it was saved with)."""
    target, _conn = _target(session, group_id)
    prefix = _prefix(_slug(session, group_id))
    name = key[len(prefix) :] if key.startswith(prefix) else ""
    if not name or "/" in name or ".." in name:
        raise WorkspaceBackupError("not one of this workspace's backups")
    dest = dest_dir / f"{uuid.uuid4().hex[:8]}-{name}"
    metadata = target.get(key, dest)
    expected = (metadata or {}).get("sha256")
    if expected:
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest != expected:
            dest.unlink(missing_ok=True)
            raise WorkspaceBackupError("the backup's checksum doesn't match what was saved")
    return dest


def backup_now(session, group_id, work_dir: Path) -> SavedBackup:
    """Make the workspace's bundle and save it to its bucket now (the bundle file isn't kept locally)."""
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter

    _target(session, group_id)  # fail before building a bundle that can't be saved
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = WorkspaceExporter(get_repositories(session, group_id=group_id)).export_workspace_bundle(temp_dir=work_dir, label="own")
    try:
        return save_backup(session, group_id, zip_path)
    finally:
        zip_path.unlink(missing_ok=True)


def announce(event_bus, group_id, *, saved: SavedBackup | None = None, error: str | None = None, trigger: str = "scheduled", label=None) -> None:
    """workspace_backup_saved / workspace_backup_failed for the workspace."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceBackupData

    ok = saved is not None
    data = EventWorkspaceBackupData(
        operation=EventOperation.create if ok else EventOperation.update,
        bucket_label=saved.bucket_label if ok else label,
        key=saved.key if ok else None,
        size=saved.size if ok else 0,
        pruned=saved.pruned if ok else 0,
        trigger=trigger,
        error=None if ok else error,
    )
    message = (
        f"Backup saved to the workspace's own bucket ({saved.size / 1024**2:.1f} MB)"
        if ok
        else f"Backup to the workspace's own bucket failed: {error}"
    )
    (event_bus or EventBusService(bg_tasks=None)).dispatch(
        integration_id="workspace_storage",
        group_id=group_id,
        event_type=EventTypes.workspace_backup_saved if ok else EventTypes.workspace_backup_failed,
        document_data=data,
        message=message[:1000],
        entity_id=group_id,
        entity_type="workspace",
    )
