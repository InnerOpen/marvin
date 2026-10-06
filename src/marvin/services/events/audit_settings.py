"""Per-workspace audit settings: which event types land in the Event Log.

Each catalog entry declares a default (`CatalogEntry.audited`). A workspace admin can override it per event
type; the overrides live in `group_preferences.audit_overrides_json` as `{event_type: bool}`, holding only the
types that differ from the default. Locked entries (`CatalogEntry.audit_locked`: members, auth, workspace
settings, security, secrets, API clients) are always audited, whatever the map says, and so is any event
type the catalog doesn't know.

`is_audited` runs for every event the bus dispatches, so the map is cached per workspace: dropped on every
write in this process, and re-read after `CACHE_TTL_SECONDS` so another process's write (a second worker, the
scheduler) is picked up too. If the read fails the event is audited — losing an audit record is worse than
keeping one an admin didn't want.
"""

import threading
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.services.events.event_catalog import CATALOG, CATEGORIES, CatalogEntry, get_catalog_entry

logger = get_logger()

CACHE_TTL_SECONDS = 30.0

_cache: dict[str, tuple[float, dict[str, bool]]] = {}
_cache_lock = threading.Lock()


class UnknownEventTypes(ValueError):
    """The change names event types the catalog doesn't have."""

    def __init__(self, event_types: list[str]) -> None:
        self.event_types = event_types
        super().__init__(f"Unknown event type: {', '.join(event_types)}.")


class LockedEventTypes(ValueError):
    """The change names event types that are always audited."""

    def __init__(self, event_types: list[str]) -> None:
        self.event_types = event_types
        super().__init__(f"Always audited, can't be changed (security event): {', '.join(event_types)}.")


@dataclass(frozen=True)
class AuditSetting:
    event_type: str
    name: str
    category: str
    default_audited: bool
    audited: bool
    locked: bool


def _effective(entry: CatalogEntry, overrides: dict[str, bool]) -> bool:
    if entry.audit_locked:
        return True
    value = overrides.get(entry.event_type)
    return value if isinstance(value, bool) else entry.audited


def _prefs(session: Session, group_id):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    return session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()


def _clean(raw) -> dict[str, bool]:
    """The stored map, keeping only boolean values for types that are still in the catalog and unlocked
    and that still differ from their default (a default can change after an override was saved)."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, bool] = {}
    for event_type, value in raw.items():
        entry = get_catalog_entry(event_type)
        if entry is None or entry.audit_locked or not isinstance(value, bool) or value == entry.audited:
            continue
        out[event_type] = value
    return out


def read_overrides(session: Session, group_id) -> dict[str, bool]:
    """The workspace's effective overrides, straight from the database."""
    prefs = _prefs(session, group_id)
    return _clean(prefs.audit_overrides_json if prefs is not None else None)


def _sort_key(entry: CatalogEntry) -> tuple[int, str]:
    rank = CATEGORIES.index(entry.category) if entry.category in CATEGORIES else len(CATEGORIES)
    return rank, entry.category


def settings(overrides: dict[str, bool]) -> list[AuditSetting]:
    """Every catalog event type with its default and effective coverage, grouped by category (display order,
    then the catalog's own order within a category)."""
    return [
        AuditSetting(
            event_type=entry.event_type,
            name=entry.name,
            category=entry.category,
            default_audited=entry.audited or entry.audit_locked,
            audited=_effective(entry, overrides),
            locked=entry.audit_locked,
        )
        for entry in sorted(CATALOG, key=_sort_key)
    ]


def excluded(overrides: dict[str, bool]) -> list[AuditSetting]:
    """The event types the workspace's Event Log does not record."""
    return [s for s in settings(overrides) if not s.audited]


def apply_changes(session: Session, group_id, changes: dict[str, bool | None]) -> tuple[dict[str, bool], dict[str, bool | None]]:
    """Merge `changes` (`{event_type: bool | None}`, None = back to the default) into the workspace's overrides
    and commit. Validates everything before writing anything.

    Returns the new overrides and what actually changed (`{event_type: new value}`, None where an override
    was removed); the latter is empty when the request changed nothing.

    Raises UnknownEventTypes or LockedEventTypes.
    """
    unknown = sorted(t for t in changes if get_catalog_entry(t) is None)
    if unknown:
        raise UnknownEventTypes(unknown)
    locked = sorted(t for t in changes if get_catalog_entry(t).audit_locked)  # type: ignore[union-attr]
    if locked:
        raise LockedEventTypes(locked)

    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = _prefs(session, group_id)
    before = _clean(prefs.audit_overrides_json if prefs is not None else None)
    after = dict(before)
    for event_type, value in changes.items():
        entry = get_catalog_entry(event_type)
        if value is None or value == entry.audited:  # type: ignore[union-attr]
            after.pop(event_type, None)
        else:
            after[event_type] = value

    changed: dict[str, bool | None] = {}
    for event_type in sorted(set(before) | set(after)):
        if before.get(event_type) != after.get(event_type):
            changed[event_type] = after.get(event_type)

    if changed:
        if prefs is None:
            prefs = GroupPreferencesModel(session=session, group_id=group_id)
            session.add(prefs)
        prefs.audit_overrides_json = after or None
        session.commit()
    invalidate(group_id)
    return after, changed


def describe(changed: dict[str, bool | None]) -> str:
    """One line for the Event Log: "entry_updated off, asset_uploaded default"."""
    words = {True: "on", False: "off", None: "default"}
    return ", ".join(f"{event_type} {words[value]}" for event_type, value in changed.items())


# ---- the listener's read ---------------------------------------------------------------------------


def invalidate(group_id=None) -> None:
    """Drop the cached overrides for one workspace (or all of them)."""
    with _cache_lock:
        if group_id is None:
            _cache.clear()
        else:
            _cache.pop(str(group_id), None)


def cached_overrides(group_id) -> dict[str, bool]:
    """The workspace's overrides, from the cache when fresh. Raises if the database read fails (nothing is
    cached then, so the next event tries again)."""
    key = str(group_id)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

    from marvin.db.db_setup import session_context

    with session_context() as session:
        overrides = read_overrides(session, group_id)
    with _cache_lock:
        _cache[key] = (now, overrides)
    return overrides


def is_audited(group_id, event_type: str) -> bool:
    """Whether an event of this type is written to this workspace's Event Log."""
    entry = get_catalog_entry(event_type)
    if entry is None or entry.audit_locked:
        return True
    if group_id is None:  # a platform/system event: no workspace to override it
        return entry.audited
    try:
        overrides = cached_overrides(group_id)
    except Exception:  # noqa: BLE001 — fail safe: an unreadable setting must not drop audit records
        logger.warning(f"audit settings: could not read overrides for workspace {group_id}; auditing {event_type}", exc_info=True)
        return True
    return _effective(entry, overrides)
