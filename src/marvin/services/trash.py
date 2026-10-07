"""The Trash for assets and resources, and the workspace's Trash as a whole.

Entries keep theirs in services/entries/trash.py (status ``trashed``). An asset or a resource has no status:
it is in the Trash while its ``trashed_at`` is set (``trashed_by``: who put it there). While there it is out of
sight — every listing, picker, search, tag count, collection, the AI's tools, workflow targets and the
publishing API (an entry's attached assets/resources included) leave it out — but a fetch by id still shows it,
with its ``trashed_at``. Its links to entries and collections are kept, so a restore puts it back in place.
An asset's file stays in storage while it is in the Trash (sites serve files straight from the bucket); it is
removed only when the asset is deleted forever.

Deleting forever goes through ``delete_asset`` / ``delete_resource`` — the same path the REST deletes take —
so ``asset_deleted`` / ``resource_deleted`` fire and an asset's file leaves storage: "Delete forever" on one
trashed item, emptying the Trash (ADMIN/OWNER; ``empty_all`` empties entries too), and the hourly auto-empty
(``purge_expired``), which ages items by ``trashed_at`` against the same effective setting as entries.
"""

from datetime import UTC, datetime, timedelta

from marvin.core.root_logger import get_logger
from marvin.services.entries import trash as entry_trash
from marvin.services.event_bus_service.event_types import EventAssetData, EventOperation, EventResourceData, EventTypes

logger = get_logger(__name__)

ASSET, RESOURCE = "asset", "resource"
KINDS = (ASSET, RESOURCE)
_INTEGRATION = {ASSET: "asset_management", RESOURCE: "resource_management"}
_EVENTS = {
    ASSET: (EventTypes.asset_trashed, EventTypes.asset_restored),
    RESOURCE: (EventTypes.resource_trashed, EventTypes.resource_restored),
}


def model(kind: str):
    from marvin.db.models.platform import Assets, Resources

    return {ASSET: Assets, RESOURCE: Resources}[kind]


def not_trashed(model_cls):
    """SQL filter that hides trashed rows of Assets or Resources — what every listing applies."""
    return model_cls.trashed_at.is_(None)


def is_trashed(row) -> bool:
    return getattr(row, "trashed_at", None) is not None


def _get(session, group_id, kind: str, item_id):
    row = session.get(model(kind), item_id)
    return row if row is not None and row.group_id == group_id else None


# ── Events ────────────────────────────────────────────────────────────────────
def _names(session, group_id, actor_id) -> tuple[str | None, str | None]:
    """(workspace name, actor's full name) for an event payload."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    group = session.get(Groups, group_id)
    actor = session.get(Users, actor_id) if actor_id else None
    return getattr(group, "name", None), getattr(actor, "full_name", None)


def event_data(session, group_id, kind: str, row, operation: EventOperation, *, actor_id=None):
    """The payload asset_* / resource_* events carry, built the way the REST routes build it."""
    workspace_name, actor_name = _names(session, group_id, actor_id)
    if kind == ASSET:
        from marvin.schemas.platform import AssetRead

        return EventAssetData.from_schema(
            AssetRead.model_validate(row),
            workspace_id=group_id,
            workspace_name=workspace_name,
            uploader_id=actor_id,
            uploader_name=actor_name,
        )
    return EventResourceData(
        operation=operation,
        resource_id=row.id,
        resource_name=row.name,
        resource_slug=row.slug,
        resource_type=row.resource_type,
        workspace_id=group_id,
        workspace_name=workspace_name,
        url=row.url,
    )


def _bus(event_bus):
    if event_bus is not None:
        return event_bus
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    return EventBusService(bg_tasks=None)  # synchronous fan-out, like EntryService


def _emit(session, group_id, kind, row, event_type, operation, message, *, actor_id, event_bus, integration_id=None, reaction_depth=0) -> None:
    _bus(event_bus).dispatch(
        integration_id=integration_id or _INTEGRATION[kind],
        group_id=group_id,
        event_type=event_type,
        document_data=event_data(session, group_id, kind, row, operation, actor_id=actor_id),
        message=message,
        user_id=actor_id,
        entity_id=row.id,
        entity_type=kind,
        reaction_depth=reaction_depth,
    )


# ── Trash / restore ───────────────────────────────────────────────────────────
def trash(session, group_id, kind: str, item_id, *, actor_id=None, event_bus=None, reaction_depth: int = 0):
    """Move an asset or resource to the Trash and emit ``<kind>_trashed``. Already trashed → returned as is,
    nothing emitted. None if it doesn't exist in this workspace."""
    row = _get(session, group_id, kind, item_id)
    if row is None or is_trashed(row):
        return row
    row.trashed_at = datetime.now(UTC)
    row.trashed_by = actor_id
    session.commit()
    trashed, _ = _EVENTS[kind]
    label = "Asset" if kind == ASSET else "Resource"
    _emit(
        session, group_id, kind, row, trashed, EventOperation.update, f"{label} '{row.name}' moved to the Trash",
        actor_id=actor_id, event_bus=event_bus, reaction_depth=reaction_depth,
    )  # fmt: skip
    return row


def restore(session, group_id, kind: str, item_id, *, actor_id=None, event_bus=None, reaction_depth: int = 0):
    """Take an asset or resource out of the Trash and emit ``<kind>_restored``. Not trashed → returned as is.
    None if it doesn't exist in this workspace."""
    row = _get(session, group_id, kind, item_id)
    if row is None or not is_trashed(row):
        return row
    row.trashed_at = None
    row.trashed_by = None
    session.commit()
    _, restored = _EVENTS[kind]
    label = "Asset" if kind == ASSET else "Resource"
    _emit(
        session, group_id, kind, row, restored, EventOperation.update, f"{label} '{row.name}' restored from the Trash",
        actor_id=actor_id, event_bus=event_bus, reaction_depth=reaction_depth,
    )  # fmt: skip
    return row


# ── Deleting for good ─────────────────────────────────────────────────────────
def delete_asset(session, group_id, asset_id, *, actor_id=None, event_bus=None, integration_id: str | None = None) -> bool:
    """Delete an asset for good: its file from storage (and any old-key copies), its row, then ``asset_deleted``.
    The one path every asset delete takes. False if it doesn't exist in this workspace."""
    from marvin.repos import AllRepositories
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.provider_factory import get_storage_provider

    asset = _get(session, group_id, ASSET, asset_id)
    if asset is None:
        return False
    data = event_data(session, group_id, ASSET, asset, EventOperation.delete, actor_id=actor_id)
    name = asset.name
    if not AssetStorageService(AllRepositories(session, group_id=group_id), get_storage_provider()).delete_asset(asset_id):
        return False
    _bus(event_bus).dispatch(
        integration_id=integration_id or _INTEGRATION[ASSET],
        group_id=group_id,
        event_type=EventTypes.asset_deleted,
        document_data=data,
        message=f"Asset {name} deleted",
        user_id=actor_id,
        entity_id=asset_id,
        entity_type=ASSET,
    )
    return True


def delete_resource(session, group_id, resource_id, *, actor_id=None, event_bus=None, integration_id: str | None = None) -> bool:
    """Delete a resource for good: ``resource_deleted``, then the row. False if it doesn't exist here."""
    from marvin.repos import AllRepositories

    resource = _get(session, group_id, RESOURCE, resource_id)
    if resource is None:
        return False
    _emit(
        session, group_id, RESOURCE, resource, EventTypes.resource_deleted, EventOperation.delete,
        f"Resource '{resource.name}' deleted", actor_id=actor_id, event_bus=event_bus, integration_id=integration_id,
    )  # fmt: skip
    AllRepositories(session, group_id=group_id).resources.delete(resource_id)
    return True


_DELETE = {ASSET: delete_asset, RESOURCE: delete_resource}


def trashed_ids(session, group_id, kind: str) -> list:
    m = model(kind)
    return [row[0] for row in session.query(m.id).filter(m.group_id == group_id, m.trashed_at.isnot(None)).all()]


def delete_forever(session, group_id, kind: str, item_ids, *, actor_id=None, event_bus=None, integration_id: str | None = None) -> int:
    """Permanently delete these assets or resources — only those still in the Trash — one ``<kind>_deleted``
    each. One already gone or restored meanwhile is skipped, so a second run (another replica, a double
    click) deletes nothing twice. Returns how many were deleted."""
    deleted = 0
    for item_id in item_ids:
        row = _get(session, group_id, kind, item_id)
        if row is None or not is_trashed(row):
            continue
        try:
            if _DELETE[kind](session, group_id, item_id, actor_id=actor_id, event_bus=event_bus, integration_id=integration_id):
                deleted += 1
        except Exception as e:  # noqa: BLE001 — one item failing must not keep the rest in the Trash
            session.rollback()
            logger.warning(f"Trash: could not delete {kind} {item_id}: {e}")
    return deleted


# ── The whole Trash ───────────────────────────────────────────────────────────
def counts(session, group_id) -> dict:
    """``{entries, assets, resources, total}`` in the workspace's Trash."""
    n = {
        "entries": len(entry_trash.trashed_ids(session, group_id)),
        "assets": len(trashed_ids(session, group_id, ASSET)),
        "resources": len(trashed_ids(session, group_id, RESOURCE)),
    }
    return {**n, "total": sum(n.values())}


def empty_all(session, group_id, *, actor_id=None, event_bus=None) -> dict:
    """Empty the workspace's Trash: every trashed entry, asset (file included) and resource, forever.
    Returns ``{entries, assets, resources, total}`` deleted."""
    n = {
        "entries": entry_trash.empty_trash(session, group_id, actor_id=actor_id, event_bus=event_bus),
        "assets": delete_forever(session, group_id, ASSET, trashed_ids(session, group_id, ASSET), actor_id=actor_id, event_bus=event_bus),
        "resources": delete_forever(session, group_id, RESOURCE, trashed_ids(session, group_id, RESOURCE), actor_id=actor_id, event_bus=event_bus),
    }
    return {**n, "total": sum(n.values())}


def expired_ids(session, group_id, kind: str, days: int, *, now: datetime | None = None) -> list:
    """Assets or resources trashed at or before ``days`` ago. 0 days (never) → none."""
    if not days:
        return []
    m = model(kind)
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    return [row[0] for row in session.query(m.id).filter(m.group_id == group_id, m.trashed_at.isnot(None), m.trashed_at <= cutoff).all()]


def purge_expired(session, *, event_bus=None, now: datetime | None = None) -> dict:
    """The auto-empty pass for assets and resources (entries: services/entries/trash.purge_expired): delete
    those trashed longer ago than their workspace's effective setting. Returns ``{group_id: deleted}`` for
    workspaces that lost any. Safe to run twice (see delete_forever); the scheduler runs it on the leader."""
    from sqlalchemy import distinct

    group_ids: set = set()
    for kind in KINDS:
        m = model(kind)
        group_ids.update(row[0] for row in session.query(distinct(m.group_id)).filter(m.trashed_at.isnot(None)).all())
    if not group_ids:
        return {}
    platform = entry_trash.platform_auto_empty_days(session)
    purged: dict = {}
    for group_id in group_ids:
        override = entry_trash.workspace_auto_empty_override(session, group_id)
        days = platform if override is None else override
        n = 0
        for kind in KINDS:
            ids = expired_ids(session, group_id, kind, days, now=now)
            if ids:
                n += delete_forever(session, group_id, kind, ids, event_bus=event_bus, integration_id="trash_auto_empty")
        if n:
            purged[group_id] = n
            logger.info(f"Trash auto-empty: deleted {n} asset(s)/resource(s) older than {days} days in workspace {group_id}")
    return purged
