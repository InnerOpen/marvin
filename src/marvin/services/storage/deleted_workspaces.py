"""Files a deleted workspace left in storage: recorded at the delete, purged after a grace period.

Deleting a workspace removes its asset rows (they cascade), so the files they named — on the platform's storage or
in the workspace's own bucket — would be orphaned for good. ``record`` runs in the delete's transaction and writes
one ``deleted_workspace_storage`` row per storage location the workspace used. After ``GRACE`` (30 days, decision
2026-10-18) the daily ``purge_deleted_workspace_storage`` task calls ``purge_due``; an admin can ``purge`` one now or
``keep`` it (never purged). Nothing here touches a bucket until a purge.

A workspace's own bucket is reachable only through its connection and keys, and both go with the workspace. So
``record`` snapshots the connection's plain settings and copies its key values into **platform secrets** named
``DELETED_WS_<record>_<SETTING>``; ``purge`` and ``keep`` remove the copies. With a secret backend that can't store
platform secrets (the env backend) the copy fails: the location is still listed, but a purge says it can't reach
the bucket and leaves the files where they are.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marvin.db.models.platform.deleted_workspace_storage import (
    STATE_KEPT,
    STATE_PENDING,
    STATE_PURGED,
    DeletedWorkspaceStorageModel,
)

logger = logging.getLogger(__name__)

GRACE = timedelta(days=30)
"""How long a deleted workspace's files are kept before the daily task purges them."""


_SAFE_PREFIX = re.compile(r"^[a-z2-7]{12}/$")
"""A workspace storage code and a slash: the only prefix a purge will list and delete under."""


class PurgeError(RuntimeError):
    """A purge that can't reach (or finish clearing) a location. The message is safe to show and never names a key value."""


def _now() -> datetime:
    return datetime.now(UTC)


def due_at(row: DeletedWorkspaceStorageModel) -> datetime:
    return row.deleted_at + GRACE


# ── recording (inside the workspace delete) ──────────────────────────────────


def _location_label(session: Session, location: str) -> str:
    from marvin.services.storage import registry
    from marvin.services.storage import workspace as ws

    if ws.is_workspace_location(location):
        from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel

        conn = session.get(WorkspaceStorageConnectionModel, ws.connection_id_of(location))
        return (conn.label if conn is not None and conn.label else None) or "The workspace's own bucket"
    try:
        return registry.get_plugin(location).name
    except Exception:
        return location


def _snapshot_connection(session: Session, group_id: Any, location: str, row_id: Any) -> dict | None:
    """The workspace's bucket as ``{plugin_slug, settings, secrets}``, its key values copied to platform secrets.
    None when the connection row is already gone."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel
    from marvin.services.secrets.factory import get_secret_backend
    from marvin.services.secrets.platform import PlatformSecretReadOnly, set_platform_secret
    from marvin.services.storage import workspace as ws

    conn = session.get(WorkspaceStorageConnectionModel, ws.connection_id_of(location))
    if conn is None or conn.group_id != group_id:
        return None
    copies: dict[str, str] = {}
    for env, slug in (conn.secret_refs or {}).items():
        value = get_secret_backend().get(str(slug), group_id) if slug else None
        if value is None:
            continue
        copy_slug = f"DELETED_WS_{str(row_id).replace('-', '')[:12].upper()}_{env}"
        try:
            set_platform_secret(copy_slug, value, session)
        except PlatformSecretReadOnly:
            logger.warning("deleted workspace storage: the secret backend can't keep the bucket's keys; its files can't be purged later")
            return {"plugin_slug": conn.plugin_slug, "settings": dict(conn.settings or {}), "secrets": {}, "keys_missing": True}
        copies[env] = copy_slug
    return {"plugin_slug": conn.plugin_slug, "settings": dict(conn.settings or {}), "secrets": copies}


def record(session: Session, group: Any, now: datetime | None = None) -> list[DeletedWorkspaceStorageModel]:
    """Record the stored files of ``group`` (a ``Groups`` row) before it is deleted; flushes, doesn't commit.

    One row per location its asset rows (and the old keys they left, ``storage_key_aliases``) are stored at. A
    workspace with no stored files records nothing."""
    from marvin.db.models.platform import Assets, StorageKeyAliasModel

    now = now or _now()
    prefix = f"{group.storage_code}/" if group.storage_code else None
    by_location: dict[str, dict[str, Any]] = {}

    def bucket(location: str) -> dict[str, Any]:
        return by_location.setdefault(location, {"count": 0, "bytes": 0, "extra": set()})

    for location, key, size in session.execute(
        select(Assets.storage_provider, Assets.storage_key, Assets.file_size).where(Assets.group_id == group.id)
    ):
        entry = bucket(location)
        entry["count"] += 1
        entry["bytes"] += int(size or 0)
        if not (prefix and key.startswith(prefix)):
            entry["extra"].add(key)
    alias_rows = session.execute(
        select(StorageKeyAliasModel.provider, StorageKeyAliasModel.storage_key)
        .where(StorageKeyAliasModel.pruned_at.is_(None))
        .where(StorageKeyAliasModel.asset_id.in_(select(Assets.id).where(Assets.group_id == group.id)))
    )
    for location, key in alias_rows:
        bucket(location)["extra"].add(key)  # an unpruned old copy: it is the workspace's file, at a key outside the prefix

    rows = []
    for location, entry in sorted(by_location.items()):
        row = DeletedWorkspaceStorageModel(
            session=session,
            workspace_id=group.id,
            workspace_name=group.name,
            workspace_slug=group.slug,
            location=location,
            label=_location_label(session, location),
            prefix=prefix,
            extra_keys=sorted(entry["extra"]),
            object_count=entry["count"],
            total_bytes=entry["bytes"],
            deleted_at=now,
            state=STATE_PENDING,
        )
        session.add(row)
        session.flush()
        from marvin.services.storage import workspace as ws

        if ws.is_workspace_location(location):
            row.connection = _snapshot_connection(session, group.id, location, row.id)
        rows.append(row)
    return rows


# ── purging ──────────────────────────────────────────────────────────────────


def _provider(row: DeletedWorkspaceStorageModel):
    """The provider the files are read through: the platform's for a platform location, the snapshot of the workspace's
    own bucket (keys from the platform-secret copies) for ``ws:<id>``."""
    from marvin_integration_sdk.storage import StorageConfigError, read_config

    from marvin.services.secrets.platform import get_platform_secret
    from marvin.services.storage import provider_factory
    from marvin.services.storage import workspace as ws

    if not ws.is_workspace_location(row.location):
        try:
            return provider_factory.provider_for(row.location)
        except Exception as e:
            raise PurgeError(f"storage {row.location!r} can't be reached: {e}") from e
    snap = row.connection or {}
    if not snap or snap.get("keys_missing"):
        raise PurgeError("the workspace's own bucket can't be reached: its connection or keys were not kept; its files stay where they are")
    try:
        cls = ws.plugin_class(snap["plugin_slug"])
        declared = {s.env: s for s in cls.workspace_settings}
        values = {env: v for env, v in (snap.get("settings") or {}).items() if env in declared and not declared[env].secret}
        for env, slug in (snap.get("secrets") or {}).items():
            values[env] = get_platform_secret(slug) or ""
        endpoint = getattr(cls, "endpoint_setting", None)
        from marvin.db.db_setup import session_context

        with session_context() as session:
            endpoint_policy = ws.policy(session).endpoint_policy
        ws.check_endpoint(values.get(endpoint) if endpoint else None, endpoint_policy, production=ws._production())
        return cls.from_config(read_config(cls.workspace_settings, values))
    except (StorageConfigError, KeyError) as e:
        raise PurgeError(f"the workspace's own bucket can't be reached: {e}") from e


def _drop_secret_copies(row: DeletedWorkspaceStorageModel, session: Session) -> None:
    from marvin.services.secrets.platform import delete_platform_secret

    for slug in ((row.connection or {}).get("secrets") or {}).values():
        delete_platform_secret(slug, session)


def purge(session: Session, row: DeletedWorkspaceStorageModel, now: datetime | None = None) -> int:
    """Delete the recorded files from storage and mark the row ``purged``; returns how many were deleted. Raises
    ``PurgeError`` (the row stays pending, with ``last_error``) when the location can't be reached or a delete fails."""
    if row.state == STATE_PURGED:
        return row.purged_objects or 0
    now = now or _now()
    try:
        if row.prefix and not _SAFE_PREFIX.match(row.prefix):
            raise PurgeError("the recorded key prefix isn't a workspace storage code; refusing to delete by it")
        provider = _provider(row)
        deleted = 0
        keys: list[str] = []
        if row.prefix:
            keys.extend(provider.iter_keys(row.prefix))
        keys.extend(k for k in (row.extra_keys or []) if k not in set(keys))
        for key in keys:
            if provider.delete(key) is not False:
                deleted += 1
    except PurgeError as e:
        row.last_error = str(e)[:500]
        session.commit()
        raise
    except Exception as e:
        row.last_error = f"{type(e).__name__}: {e}"[:500]
        session.commit()
        raise PurgeError(row.last_error) from e
    _drop_secret_copies(row, session)
    row.state, row.state_at, row.purged_objects, row.last_error = STATE_PURGED, now, deleted, None
    session.commit()
    return deleted


def keep(session: Session, row: DeletedWorkspaceStorageModel, now: datetime | None = None) -> None:
    """Never purge this location's files; the platform-secret copies of its bucket keys are removed."""
    if row.state == STATE_PURGED:
        return
    _drop_secret_copies(row, session)
    row.state, row.state_at, row.last_error = STATE_KEPT, now or _now(), None
    session.commit()


def pending(session: Session) -> list[DeletedWorkspaceStorageModel]:
    """Locations still waiting (not purged, not kept), oldest delete first."""
    return list(
        session.execute(
            select(DeletedWorkspaceStorageModel)
            .where(DeletedWorkspaceStorageModel.state == STATE_PENDING)
            .order_by(DeletedWorkspaceStorageModel.deleted_at, DeletedWorkspaceStorageModel.workspace_name)
        ).scalars()
    )


@dataclass
class PurgeRun:
    purged: int = 0
    objects: int = 0
    failed: int = 0
    pending: int = 0


def purge_due(session: Session, now: datetime | None = None) -> PurgeRun:
    """Purge every pending location whose grace period has passed (the daily task). A failure is recorded on its row
    and retried the next day; it doesn't stop the others."""
    now = now or _now()
    run = PurgeRun()
    for row in pending(session):
        if due_at(row) > now:
            run.pending += 1
            continue
        try:
            run.objects += purge(session, row, now)
            run.purged += 1
        except PurgeError:
            run.failed += 1
            run.pending += 1
    return run


def count_pending(session: Session) -> int:
    return int(
        session.scalar(select(func.count()).select_from(DeletedWorkspaceStorageModel).where(DeletedWorkspaceStorageModel.state == STATE_PENDING)) or 0
    )
