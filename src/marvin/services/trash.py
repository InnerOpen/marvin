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
(``purge_expired``), which ages items by ``trashed_at`` against the same effective setting as entries. The day
before, ``remind_auto_empty`` says what is about to go (``trash_auto_empty_soon``, once a day per workspace).
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
    """Empty the workspace's Trash: every trashed entry, asset (file included) and resource, forever, then one
    ``trash_emptied`` saying how much went. Returns ``{entries, assets, resources, total}`` deleted."""
    n = {
        "entries": entry_trash.empty_trash(session, group_id, actor_id=actor_id, event_bus=event_bus),
        "assets": delete_forever(session, group_id, ASSET, trashed_ids(session, group_id, ASSET), actor_id=actor_id, event_bus=event_bus),
        "resources": delete_forever(session, group_id, RESOURCE, trashed_ids(session, group_id, RESOURCE), actor_id=actor_id, event_bus=event_bus),
    }
    counts = {**n, "total": sum(n.values())}
    emit_emptied(session, group_id, counts, how="emptied", actor_id=actor_id, event_bus=event_bus)
    return counts


def emit_emptied(session, group_id, counts: dict, *, how: str, actor_id=None, event_bus=None) -> None:
    """One ``trash_emptied`` for items deleted forever in one go (``how``: emptied | auto_empty), on top of each
    item's own ``*_deleted``. Nothing deleted, nothing sent."""
    if not counts.get("total"):
        return
    from marvin.db.models.platform.collections import Collections
    from marvin.services.collections.system_collections import TRASH_COLLECTION_SLUG
    from marvin.services.event_bus_service.event_types import EventTrashEmptiedData

    workspace_name, _ = _names(session, group_id, None)
    trash = session.query(Collections.id).filter(Collections.group_id == group_id, Collections.slug == TRASH_COLLECTION_SLUG).first()
    total = counts["total"]
    who = "Emptied the Trash" if how == "emptied" else "Trash auto-empty"
    _bus(event_bus).dispatch(
        integration_id="trash_auto_empty" if how == "auto_empty" else "trash_management",
        group_id=group_id,
        event_type=EventTypes.trash_emptied,
        document_data=EventTrashEmptiedData(
            operation=EventOperation.delete,
            workspace_id=group_id,
            workspace_name=workspace_name,
            how=how,
            total=total,
            entries=counts.get("entries", 0),
            assets=counts.get("assets", 0),
            resources=counts.get("resources", 0),
            trash_collection_id=trash[0] if trash else None,
        ),
        message=f"{who}: {total} item{'' if total == 1 else 's'} deleted forever",
        user_id=actor_id,
        entity_id=trash[0] if trash else None,
        entity_type="collection" if trash else None,
    )


def expired_ids(session, group_id, kind: str, days: int, *, now: datetime | None = None) -> list:
    """Assets or resources trashed at or before ``days`` ago. 0 days (never) → none."""
    if not days:
        return []
    m = model(kind)
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    return [row[0] for row in session.query(m.id).filter(m.group_id == group_id, m.trashed_at.isnot(None), m.trashed_at <= cutoff).all()]


def purge_expired(session, *, event_bus=None, now: datetime | None = None) -> dict:
    """The auto-empty pass for assets and resources (entries: services/entries/trash.purge_expired): delete
    those trashed longer ago than their workspace's effective setting. Returns ``{group_id: {assets, resources}}``
    for workspaces that lost any. Safe to run twice (see delete_forever); the scheduler runs it (``auto_empty``)."""
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
        n = {"assets": 0, "resources": 0}
        for kind in KINDS:
            ids = expired_ids(session, group_id, kind, days, now=now)
            if ids:
                n[f"{kind}s"] = delete_forever(session, group_id, kind, ids, event_bus=event_bus, integration_id="trash_auto_empty")
        if any(n.values()):
            purged[group_id] = n
            logger.info(
                f"Trash auto-empty: deleted {n['assets']} asset(s), {n['resources']} resource(s) older than {days} days in workspace {group_id}"
            )
    return purged


def auto_empty(session, *, event_bus=None, now: datetime | None = None) -> dict:
    """The hourly auto-empty, every workspace: entries, assets and resources trashed longer ago than its setting,
    then one ``trash_emptied`` (how: auto_empty) per workspace that lost anything. Returns ``{group_id: counts}``."""
    entries = entry_trash.purge_expired(session, event_bus=event_bus, now=now)
    items = purge_expired(session, event_bus=event_bus, now=now)
    emptied: dict = {}
    for group_id in set(entries) | set(items):
        counts = {"entries": entries.get(group_id, 0), "assets": 0, "resources": 0, **items.get(group_id, {})}
        counts["total"] = counts["entries"] + counts["assets"] + counts["resources"]
        emit_emptied(session, group_id, counts, how="auto_empty", event_bus=event_bus)
        emptied[group_id] = counts
    return emptied


# ── The day before ────────────────────────────────────────────────────────────
REMINDER_WINDOW = timedelta(hours=24)


def expiring_soon(session, group_id, days: int, *, now: datetime | None = None) -> dict:
    """``{entries, assets, resources, total}`` the auto-empty will delete forever within REMINDER_WINDOW (those
    already due included). 0 days (never) → none."""
    later = (now or datetime.now(UTC)) + REMINDER_WINDOW
    n = {
        "entries": len(entry_trash.expired_ids(session, group_id, days, now=later)),
        "assets": len(expired_ids(session, group_id, ASSET, days, now=later)),
        "resources": len(expired_ids(session, group_id, RESOURCE, days, now=later)),
    }
    return {**n, "total": sum(n.values())}


def _claim_reminder(session, group_id, today) -> bool:
    """Mark today's reminder as sent for the workspace — True only for the first to do so (another replica, a
    second tick the same day, a restart: False)."""
    from sqlalchemy import or_, update

    from marvin.db.models.groups.preferences import GroupPreferencesModel

    if session.query(GroupPreferencesModel.id).filter_by(group_id=group_id).first() is None:
        session.add(GroupPreferencesModel(session=session, group_id=group_id))
        session.commit()
    claimed = session.execute(
        update(GroupPreferencesModel)
        .where(
            GroupPreferencesModel.group_id == group_id,
            or_(GroupPreferencesModel.trash_reminded_on.is_(None), GroupPreferencesModel.trash_reminded_on < today),
        )
        .values(trash_reminded_on=today)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return claimed.rowcount == 1


def remind_auto_empty(session, *, event_bus=None, now: datetime | None = None) -> dict:
    """Once a day per workspace, ``trash_auto_empty_soon`` for each workspace whose auto-empty isn't "never" and
    will delete something forever within a day — push (services/push_notifications.py) and the workspace's
    notifications (services/workspace_alerts.py) hang off it. Returns ``{group_id: total}`` reminded. Safe to run
    every hour and on several replicas: a workspace already reminded today is skipped."""
    from sqlalchemy import distinct

    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entries import Entries
    from marvin.services.collections.system_collections import TRASH_COLLECTION_SLUG
    from marvin.services.event_bus_service.event_types import EventTrashAutoEmptyData

    now = now or datetime.now(UTC)
    group_ids: set = {row[0] for row in session.query(distinct(Entries.group_id)).filter(Entries.status == entry_trash.TRASHED).all()}
    for kind in KINDS:
        m = model(kind)
        group_ids.update(row[0] for row in session.query(distinct(m.group_id)).filter(m.trashed_at.isnot(None)).all())
    if not group_ids:
        return {}
    platform = entry_trash.platform_auto_empty_days(session)
    reminded: dict = {}
    for group_id in group_ids:
        override = entry_trash.workspace_auto_empty_override(session, group_id)
        days = platform if override is None else override
        if not days:
            continue
        n = expiring_soon(session, group_id, days, now=now)
        if not n["total"] or not _claim_reminder(session, group_id, now.date()):
            continue
        workspace_name, _ = _names(session, group_id, None)
        trash = session.query(Collections.id).filter(Collections.group_id == group_id, Collections.slug == TRASH_COLLECTION_SLUG).first()
        noun = "item" if n["total"] == 1 else "items"
        _bus(event_bus).dispatch(
            integration_id="trash_auto_empty",
            group_id=group_id,
            event_type=EventTypes.trash_auto_empty_soon,
            document_data=EventTrashAutoEmptyData(
                operation=EventOperation.info,
                workspace_id=group_id,
                workspace_name=workspace_name,
                days=days,
                trash_collection_id=trash[0] if trash else None,
                **n,
            ),
            message=f"{n['total']} {noun} in the Trash will be deleted forever within a day",
            entity_id=trash[0] if trash else None,
            entity_type="collection" if trash else None,
        )
        reminded[group_id] = n["total"]
        logger.info(f"Trash reminder: {n['total']} item(s) will be deleted forever within a day in workspace {group_id}")
    return reminded
