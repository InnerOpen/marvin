"""The Trash: deleted entries, waiting to be restored or emptied.

Deleting an entry moves it to the Trash (status ``trashed``, EntryService.trash): it leaves the site,
every listing, search, count and collection but the Trash system collection, and keeps where it came
from in ``metadata_json.trash`` so a restore can put it back (a published entry comes back as a draft).
Nothing is lost until the Trash is emptied — by a workspace ADMIN/OWNER (``empty_trash``), by "Delete
forever" on one trashed entry, or by the auto-empty purge (``purge_expired``) once an entry has been in
the Trash longer than the workspace allows. All three delete through EntryService.delete, so
``entry_deleted`` fires and the junction rows go with the entry, as for any delete.

How long the Trash keeps entries is a platform default (platform_settings key ``trash``, a super admin
sets it; 30 days out of the box) that a workspace may override (group_preferences.trash_auto_empty_days;
null inherits). 0 means never: entries stay until someone empties the Trash.
"""

from datetime import UTC, datetime, timedelta

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

TRASHED = "trashed"
PLATFORM_KEY = "trash"
AUTO_EMPTY_CHOICES = (0, 7, 30, 90)
"""Days an entry may stay in the Trash; 0 = never emptied automatically."""
DEFAULT_AUTO_EMPTY_DAYS = 30


def not_trashed():
    """SQL filter that hides trashed entries — what every entry listing applies unless it is the Trash."""
    from marvin.db.models.platform.entries import Entries

    return Entries.status != TRASHED


def is_trash_collection(collection) -> bool:
    """Whether a collection shows trashed entries: one whose smart rules ask for them (the Trash)."""
    rules = getattr(collection, "smart_rules", None) or {}
    return bool(getattr(collection, "is_smart", False)) and TRASHED in (rules.get("statuses") or [])


def collection_entries_filter(collection):
    """SQL filter for the entries a collection lists: only trashed ones for the Trash, none for the rest
    (a manual collection keeps a trashed entry's membership, so a restore puts it back in place)."""
    from marvin.db.models.platform.entries import Entries

    return Entries.status == TRASHED if is_trash_collection(collection) else not_trashed()


def _valid_days(value) -> int | None:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days in AUTO_EMPTY_CHOICES else None


def platform_auto_empty_days(session) -> int:
    """The platform default (super admin, Admin → Settings); 30 when never set."""
    from marvin.services.platform_settings import PlatformSettingsService

    stored = PlatformSettingsService(session).get(PLATFORM_KEY) or {}
    days = _valid_days(stored.get("auto_empty_days"))
    return DEFAULT_AUTO_EMPTY_DAYS if days is None else days


def set_platform_auto_empty_days(session, days: int) -> int:
    from marvin.services.platform_settings import PlatformSettingsService

    stored = PlatformSettingsService(session).get(PLATFORM_KEY) or {}
    PlatformSettingsService(session).set(PLATFORM_KEY, {**stored, "auto_empty_days": int(days)})
    return int(days)


def workspace_auto_empty_override(session, group_id) -> int | None:
    """The workspace's own choice, or None to inherit the platform default."""
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()
    return _valid_days(getattr(prefs, "trash_auto_empty_days", None))


def auto_empty_status(session, group_id) -> dict:
    """``{platform_default_days, workspace_override_days, effective_days}`` — what the settings page and
    the Trash view show. 0 = never."""
    platform = platform_auto_empty_days(session)
    override = workspace_auto_empty_override(session, group_id)
    return {
        "platform_default_days": platform,
        "workspace_override_days": override,
        "effective_days": platform if override is None else override,
    }


def trashed_at(entry) -> datetime | None:
    """When the entry went into the Trash (metadata_json.trash.trashed_at), or None if not recorded."""
    record = (getattr(entry, "metadata_json", None) or {}).get("trash")
    raw = record.get("trashed_at") if isinstance(record, dict) else None
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def trashed_ids(session, group_id) -> list:
    from marvin.db.models.platform.entries import Entries

    return [row[0] for row in session.query(Entries.id).filter(Entries.group_id == group_id, Entries.status == TRASHED).all()]


def delete_forever(session, group_id, entry_ids, *, actor_id=None, event_bus=None, integration_id: str = "entry_management") -> int:
    """Permanently delete these entries — only those still in the Trash — through EntryService.delete
    (one `entry_deleted` each). An id already gone or restored meanwhile is skipped, so a second run
    (another replica, a double click) deletes nothing twice. Returns how many were deleted."""
    from marvin.db.models.platform.entries import Entries
    from marvin.services.entries import EntryService

    svc = EntryService(session, group_id, event_bus=event_bus, actor_id=actor_id, integration_id=integration_id)
    deleted = 0
    for entry_id in entry_ids:
        row = session.get(Entries, entry_id)
        if row is None or row.group_id != group_id or row.status != TRASHED:
            continue
        try:
            if svc.delete(entry_id):
                deleted += 1
        except Exception as e:  # noqa: BLE001 — one entry failing must not keep the rest in the Trash
            session.rollback()
            logger.warning(f"Trash: could not delete entry {entry_id}: {e}")
    return deleted


def empty_trash(session, group_id, *, actor_id=None, event_bus=None) -> int:
    """Delete every entry in the workspace's Trash forever. Returns the count."""
    return delete_forever(session, group_id, trashed_ids(session, group_id), actor_id=actor_id, event_bus=event_bus)


def expired_ids(session, group_id, days: int, *, now: datetime | None = None) -> list:
    """Trashed entries older than ``days`` by their recorded trashed_at. 0 days (never) → none. An entry
    with no trashed_at (trashed by a path that predates the record, e.g. a restored backup) is never
    purged automatically: without a date it can't be aged, and emptying the Trash still removes it."""
    from marvin.db.models.platform.entries import Entries

    if not days:
        return []
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = session.query(Entries).filter(Entries.group_id == group_id, Entries.status == TRASHED).all()
    return [e.id for e in rows if (when := trashed_at(e)) is not None and when <= cutoff]


def purge_expired(session, *, event_bus=None, now: datetime | None = None) -> dict:
    """The auto-empty pass over every workspace with something in the Trash: delete entries trashed longer
    ago than the workspace's effective setting. Returns ``{group_id: deleted}`` for workspaces that lost
    any. Safe to run twice (see delete_forever); the scheduler runs it on the leader only."""
    from sqlalchemy import distinct

    from marvin.db.models.platform.entries import Entries

    group_ids = [row[0] for row in session.query(distinct(Entries.group_id)).filter(Entries.status == TRASHED).all()]
    if not group_ids:
        return {}
    platform = platform_auto_empty_days(session)
    purged: dict = {}
    for group_id in group_ids:
        override = workspace_auto_empty_override(session, group_id)
        days = platform if override is None else override
        ids = expired_ids(session, group_id, days, now=now)
        if not ids:
            continue
        n = delete_forever(session, group_id, ids, event_bus=event_bus, integration_id="trash_auto_empty")
        if n:
            purged[group_id] = n
            logger.info(f"Trash auto-empty: deleted {n} entr{'y' if n == 1 else 'ies'} older than {days} days in workspace {group_id}")
    return purged
