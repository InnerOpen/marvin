"""Worker liveness: a `worker` entry is a dispatcher's or runner's heartbeat (it rewrites `data.last_seen` about once a minute), so one whose
heartbeat is older than ``QUIET_AFTER`` has stopped or lost its connection.

``check`` (a scheduler task, every minute) marks it: ``data.offline_since`` is set once per outage and cleared when the heartbeat is fresh
again. Each of those changes is the ``worker_offline`` / ``worker_online`` event (``EntryService._emit_worker_event``), so the check itself
dispatches nothing and cannot repeat itself: a worker already marked is left alone until it returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

QUIET_AFTER = timedelta(minutes=3)
"""A dispatcher beats about every minute (marvin-worker), so three minutes of quiet is trouble. The Workers page uses the same figure."""


@dataclass
class CheckOutcome:
    offline: list[str] = field(default_factory=list)
    online: list[str] = field(default_factory=list)


def _seen(value) -> datetime | None:
    try:
        seen = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return seen.replace(tzinfo=UTC) if seen.tzinfo is None else seen.astimezone(UTC)


def check(session, now: datetime | None = None, *, event_bus=None) -> CheckOutcome:
    """Mark every worker whose heartbeat went quiet, and clear the mark on one that is back. A worker that never wrote a readable
    `last_seen` is left alone (nothing to compare with)."""
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.services.entries import EntryService

    now = now or datetime.now(UTC)
    outcome = CheckOutcome()
    rows = (
        session.query(Entries)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(EntryTypes.slug == "worker", Entries.status != "trashed")
        .all()
    )
    for row in rows:
        data = row.data_json or {}
        seen = _seen(data.get("last_seen"))
        if seen is None:
            continue
        quiet = now - seen > QUIET_AFTER
        marked = bool(data.get("offline_since"))
        if quiet == marked:
            continue
        service = EntryService(session, row.group_id, event_bus=event_bus, integration_id="worker_health")
        service.apply_fields(row.id, {"data_json.offline_since": now.isoformat() if quiet else ""})
        (outcome.offline if quiet else outcome.online).append(row.title)
    return outcome
