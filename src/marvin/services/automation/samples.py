"""Samples a workflow dry run tests against — the events that would have triggered it.

A real run of an event-triggered workflow is driven by an event; without one, `${entry.title}` and
`$event.*` resolve to nothing and the trigger + conditions are never checked. A sample supplies it:

* ``event`` — an event_log row replayed through the same context builder the listener uses;
* ``entry`` — for an entry lifecycle trigger with nothing logged, the event the entry service would
  emit for that entry (built, never dispatched).

The context's `entry` is loaded as it is now, not as it was when the event was logged — which is
what a run fired now would see.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from .context import event_context_from_event, event_context_from_log
from .engine import _trigger_matches, match_context
from .matcher import matches

SCAN_LIMIT = 25
"""How many recent events (then entries) the default pick looks through for one whose conditions pass."""

MAX_SAMPLES = 25

# The entry lifecycle events EntryService emits — the triggers a sample can be built for from an
# entry. Each maps to the status an entry has right after that event (None = any status).
ENTRY_SAMPLE_EVENTS: dict[str, str | None] = {
    "entry_created": None,
    "entry_updated": None,
    "entry_published": "published",
    "entry_unpublished": None,
    "entry_archived": "archived",
    "entry_restored": None,
}

# The event each event-driven trigger type fires on (manual / schedule / mcp have none).
_TRIGGER_EVENTS = {"incoming_webhook": "incoming_webhook", "chained": "automation_ran", "on_error": "automation_failed"}


class SampleNotFound(LookupError):
    """The requested entry or event isn't in this workspace."""


class SampleNotApplicable(ValueError):
    """The requested sample can't drive this workflow (e.g. an entry for a webhook trigger)."""


@dataclass
class Sample:
    kind: str  # "event" (a logged event replayed) | "entry" (an event built for an entry)
    id: str
    label: str
    event_type: str
    occurred_at: datetime | None
    event_ctx: dict
    conditions_pass: bool | None = None

    def describe(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "event_type": self.event_type,
            # Entry timestamps are stored naive (UTC); say so, so a browser doesn't read them as local.
            "occurred_at": self.occurred_at.replace(tzinfo=UTC) if self.occurred_at and self.occurred_at.tzinfo is None else self.occurred_at,
            "synthesized": self.kind == "entry",
            "conditions_pass": self.conditions_pass,
        }


def trigger_event(automation) -> str | None:
    """The event type that fires this automation's trigger, or None when nothing event-driven does."""
    trig = (automation.definition or {}).get("trigger") or {}
    ttype = trig.get("type", "event")
    if ttype == "event":
        return trig.get("event") or None
    return _TRIGGER_EVENTS.get(ttype)


def list_samples(session, group_id, automation, *, user_id=None, limit: int = 10) -> list[Sample]:
    """Recent events this automation's trigger would have fired on, newest first, each marked with
    whether its conditions pass — then, for an entry trigger, recent entries no logged event covers."""
    event_type = trigger_event(automation)
    if not event_type:
        return []
    limit = max(1, min(limit, MAX_SAMPLES))
    logged = _logged_samples(session, group_id, automation, event_type, limit)
    covered = {str(s.event_ctx.get("entry_id")) for s in logged}
    entries = [s for s in _entry_samples(session, group_id, automation, event_type, limit + len(covered), user_id) if s.id not in covered]
    return logged + entries[:limit]


def default_sample(session, group_id, automation, *, user_id=None) -> Sample | None:
    """The sample a dry run uses when none is picked: the most recent logged event of the trigger's
    type whose conditions pass, else the most recent one (its `conditions_pass` says they fail). With
    nothing logged, an entry trigger falls back to the most recent entry, picked the same way."""
    event_type = trigger_event(automation)
    if not event_type:
        return None
    found = _logged_samples(session, group_id, automation, event_type, SCAN_LIMIT) or _entry_samples(
        session, group_id, automation, event_type, SCAN_LIMIT, user_id
    )
    return next((s for s in found if s.conditions_pass), found[0]) if found else None


def resolve_sample(session, group_id, automation, *, entry_id=None, event_id=None, user_id=None) -> Sample | None:
    """The sample a dry run tests against: the logged event `event_id`, the entry `entry_id` (its
    latest logged event of the trigger's type, else one built for it), or the default pick."""
    if (entry_id or event_id) and not trigger_event(automation):
        raise SampleNotApplicable("Only an event-triggered workflow can be tested against a sample.")
    if event_id:
        return _evaluated(session, group_id, automation, _from_log(_log_row(session, group_id, event_id)))
    if entry_id:
        return _entry_sample(session, group_id, automation, entry_id, user_id)
    return default_sample(session, group_id, automation, user_id=user_id)


# ── Internals ────────────────────────────────────────────────────────────────


def _evaluated(session, group_id, automation, sample: Sample) -> Sample:
    """Mark whether the sample passes the conditions — left None for a `target` workflow, whose
    conditions filter the target rows rather than gate the event."""
    defn = automation.definition or {}
    if not defn.get("target"):
        sample.conditions_pass = matches(defn.get("conditions"), match_context(session, group_id, sample.event_ctx))
    return sample


def _fires(automation, sample: Sample) -> bool:
    return _trigger_matches((automation.definition or {}).get("trigger") or {}, sample.event_ctx)


def _log_query(session, group_id, event_type):
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.repos.platform.event_log import workspace_events_clause

    return (
        session.query(EventLogModel)
        .filter(EventLogModel.workspace_id == group_id, EventLogModel.event_type == event_type, workspace_events_clause())
        .order_by(EventLogModel.occurred_at.desc())
    )


def _log_row(session, group_id, event_id):
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.services.events.event_catalog import is_platform_event

    row = session.get(EventLogModel, event_id)
    # A platform event isn't in the workspace's log, so it isn't a sample either.
    if row is None or row.workspace_id != group_id or is_platform_event(row.event_type):
        raise SampleNotFound("Event not found in this workspace.")
    return row


def _from_log(row) -> Sample:
    return Sample(
        kind="event",
        id=str(row.id),
        label=row.message_body or row.message_title,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        event_ctx=event_context_from_log(row),
    )


def _logged_samples(session, group_id, automation, event_type: str, limit: int) -> list[Sample]:
    """Recent logged events the trigger fires on (a webhook trigger may name one webhook, a chained
    trigger one source workflow — so the type alone isn't enough)."""
    found: list[Sample] = []
    for row in _log_query(session, group_id, event_type).limit(SCAN_LIMIT):
        sample = _from_log(row)
        if _fires(automation, sample):
            found.append(_evaluated(session, group_id, automation, sample))
            if len(found) >= limit:
                break
    return found


def _from_entry(session, group_id, entry, event_type: str, user_id) -> Sample:
    from marvin.services.entries.entry_service import EntryService
    from marvin.services.event_bus_service.event_types import EventTypes

    event = EntryService(session, group_id, actor_id=user_id).sample_event(entry, EventTypes[event_type])
    etype = entry.entry_type.slug if entry.entry_type else None
    return Sample(
        kind="entry",
        id=str(entry.id),
        label=f"{entry.title} ({etype})" if etype else entry.title,
        event_type=event_type,
        occurred_at=entry.update_at,
        event_ctx=event_context_from_event(event),
    )


def _entry_samples(session, group_id, automation, event_type: str, limit: int, user_id) -> list[Sample]:
    """Recent entries an entry lifecycle trigger could have fired on (in the status that event
    leaves an entry in), as built events. Empty for any other trigger."""
    if event_type not in ENTRY_SAMPLE_EVENTS:
        return []
    from marvin.db.models.platform.entries import Entries

    query = session.query(Entries).filter(Entries.group_id == group_id)
    status = ENTRY_SAMPLE_EVENTS[event_type]
    if status:
        query = query.filter(Entries.status == status)
    newest = Entries.created_at if event_type == "entry_created" else Entries.update_at
    rows = query.order_by(newest.desc()).limit(min(limit, SCAN_LIMIT)).all()
    return [_evaluated(session, group_id, automation, _from_entry(session, group_id, e, event_type, user_id)) for e in rows]


def _entry_sample(session, group_id, automation, entry_id, user_id) -> Sample:
    from marvin.db.models.platform.entries import Entries

    entry = session.get(Entries, entry_id)
    if entry is None or entry.group_id != group_id:
        raise SampleNotFound("Entry not found in this workspace.")
    event_type = trigger_event(automation)
    # The entry's own logged event carries what really happened (its change diff); prefer it.
    from marvin.db.models.platform.event_log import EventLogModel

    row = _log_query(session, group_id, event_type).filter(EventLogModel.entity_id == entry.id).first()
    if row is not None:
        return _evaluated(session, group_id, automation, _from_log(row))
    if event_type not in ENTRY_SAMPLE_EVENTS:
        raise SampleNotApplicable(f"No logged {event_type} event for this entry, and one can't be built from an entry.")
    return _evaluated(session, group_id, automation, _from_entry(session, group_id, entry, event_type, user_id))
