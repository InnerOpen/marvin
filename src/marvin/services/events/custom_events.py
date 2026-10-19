"""A workspace's own events: `custom.<name>`, registered with the fields their payload carries.

The catalog (`event_catalog.py`) lists what Marvin itself sends. A workspace can add events of its own — a
"milestone reached", a "kit shipped" — that nothing in Marvin sends but its workflows' Emit event steps, and that
everything else treats like any other event: a workflow can start on one, a webhook, email or integration
subscription can name one, the Event Log records it and `describe_event` explains it.

Registered events live in `group_preferences.custom_events_json` (a list, like the audit overrides next to it):

    [{"name": "milestone", "title": "Milestone reached", "description": "…",
      "fields": [{"key": "project", "type": "string", "description": "…"}, …]}]

A field is `string`, `number`, `boolean` or `date`. `build_payload` holds an Emit event step's payload to them: a
key the event doesn't declare is refused, a value is coerced to its field's type (or refused), an empty one is left
out. The event carries `reaction_depth + 1` like every emitted event, so a chain of workflows sending and reacting
to custom events is bounded the same way (engine.MAX_REACTION_DEPTH).

An unregistered `custom.*` name is never sent (the Emit event step looks it up) and never offered, though a stored
subscription or an old Event Log row may still name one. The catalog's static sets (`TRIGGERABLE_EVENT_TYPES`,
`EMITTABLE_EVENT_TYPES`) don't hold them: the workspace's own entries come from `catalog_entries`.
"""

import json
import math
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from marvin.schemas.group.custom_events import FIELD_TYPES, MAX_EVENTS, PREFIX, CustomEventDefinition
from marvin.services.events.event_catalog import CatalogEntry, EventVariable

CATEGORY = "Custom"
TRIGGER_GROUP = "Custom"
_VARIABLE_TYPES = {"string": "string", "number": "number", "boolean": "boolean", "date": "date"}
TEXT_LIMIT = 2000
"""A string field's longest value; longer text is cut."""


class CustomEventError(ValueError):
    """A change to the registry the workspace can't make; the message says why."""


class CustomEventInUse(CustomEventError):
    """The event is still named by workflows."""

    def __init__(self, event_type: str, workflows: list[str]) -> None:
        self.workflows = workflows
        super().__init__(f"{event_type} is still used by: {', '.join(workflows)}. Change those workflows first.")


def is_custom(event_type: str | None) -> bool:
    return isinstance(event_type, str) and event_type.startswith(PREFIX)


def event_type_of(name: str) -> str:
    return f"{PREFIX}{name}"


# ── the registry ────────────────────────────────────────────────────────────


def _prefs(session: Session, group_id):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    return session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()


def read(session: Session, group_id) -> list[CustomEventDefinition]:
    """The workspace's registered events, by name. A stored row that no longer validates is skipped."""
    prefs = _prefs(session, group_id)
    out: dict[str, CustomEventDefinition] = {}
    for raw in (prefs.custom_events_json if prefs is not None else None) or []:
        try:
            parsed = CustomEventDefinition.model_validate(raw)
        except ValueError:
            continue
        out.setdefault(parsed.name, parsed)
    return sorted(out.values(), key=lambda e: e.name)


def find(session: Session, group_id, event_type: str) -> CustomEventDefinition | None:
    """The registered event named `custom.<name>` (or None)."""
    return next((e for e in read(session, group_id) if event_type_of(e.name) == event_type), None)


def registered_types(session: Session, group_id) -> list[str]:
    return [event_type_of(e.name) for e in read(session, group_id)]


def _write(session: Session, group_id, events: list[CustomEventDefinition]) -> None:
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = _prefs(session, group_id)
    if prefs is None:
        prefs = GroupPreferencesModel(session=session, group_id=group_id)
        session.add(prefs)
    prefs.custom_events_json = [e.model_dump() for e in sorted(events, key=lambda e: e.name)] or None
    session.commit()


def save(session: Session, group_id, definition: CustomEventDefinition) -> tuple[CustomEventDefinition, bool]:
    """Register the event, or replace the registered one of the same name. Returns it and whether it is new."""
    events = read(session, group_id)
    created = all(e.name != definition.name for e in events)
    if created and len(events) >= MAX_EVENTS:
        raise CustomEventError(f"A workspace can register {MAX_EVENTS} custom events; remove one first.")
    _write(session, group_id, [*(e for e in events if e.name != definition.name), definition])
    return definition, created


def usage(session: Session, group_id, event_types: list[str]) -> dict[str, list[str]]:
    """For each event type, the names of the workflows (switched off ones too) whose trigger or steps name it."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    quoted = {t: json.dumps(t) for t in event_types}
    used: dict[str, list[str]] = {t: [] for t in event_types}
    for row in session.query(WorkspaceAutomationModel).filter_by(group_id=group_id).order_by(WorkspaceAutomationModel.name):
        body = json.dumps(row.definition or {})
        for event_type, needle in quoted.items():
            if needle in body:
                used[event_type].append(row.name or row.slug)
    return used


def remove(session: Session, group_id, name: str) -> CustomEventDefinition:
    """Unregister the event. Refused while a workflow names it (it would stop validating and stop sending); the
    Event Log keeps what it recorded, and a subscription that names it just never fires again."""
    events = read(session, group_id)
    gone = next((e for e in events if e.name == name), None)
    if gone is None:
        raise KeyError(name)
    event_type = event_type_of(name)
    if used := usage(session, group_id, [event_type])[event_type]:
        raise CustomEventInUse(event_type, used)
    _write(session, group_id, [e for e in events if e.name != name])
    return gone


# ── the catalog's view ──────────────────────────────────────────────────────


def entry_title(definition: CustomEventDefinition) -> str:
    """The event's display name: its title, else its name in words ("kit_shipped" → "Kit shipped")."""
    return definition.title or definition.name.replace("_", " ").capitalize()


def catalog_entry(definition: CustomEventDefinition) -> CatalogEntry:
    """What the catalog would say about it: a workspace event any workflow can start on and send, any subscription
    can name, and nothing in Marvin sends."""
    fields = ", ".join(f"{f.key} ({f.type})" for f in definition.fields)
    return CatalogEntry(
        event_type=event_type_of(definition.name),
        name=entry_title(definition),
        description=definition.description or ("Sent by a workflow's Emit event step" + (f", carrying {fields}." if fields else ".")),
        category=CATEGORY,
        variables=[
            EventVariable(f.key, f.description or f"The {f.key} the sender gave ({f.type})", _example(f.type), type=_VARIABLE_TYPES[f.type])
            for f in definition.fields
        ],
        triggerable=True,
        trigger_group=TRIGGER_GROUP,
        emittable=True,
    )


def catalog_entries(session: Session, group_id) -> list[CatalogEntry]:
    """The workspace's registered events as catalog entries, by name."""
    return [catalog_entry(e) for e in read(session, group_id)]


def entry_for(session: Session, group_id, event_type: str) -> CatalogEntry | None:
    """A catalog entry by type for this workspace: the static catalog's, or a registered custom event's."""
    from marvin.services.events.event_catalog import get_catalog_entry

    if is_custom(event_type):
        found = find(session, group_id, event_type)
        return catalog_entry(found) if found else None
    return get_catalog_entry(event_type)


def payload_example(definition: CustomEventDefinition) -> dict:
    """What a subscription receives for the event, in the shape of `payload_schemas.get_payload_example`."""
    return {
        "eventType": event_type_of(definition.name),
        "eventId": "851a54f3-bc85-4123-aa35-7c139db2cb59",
        "timestamp": "2026-07-16T00:34:37Z",
        "workspaceId": "<workspace-uuid>",
        "integrationId": "automation",
        "message": {"title": entry_title(definition), "body": ""},
        "documentData": {
            "documentType": "generic",
            "operation": "info",
            "eventName": definition.name,
            "payload": {f.key: _EXAMPLE_VALUES[f.type] for f in definition.fields},
            "workspaceId": "<workspace-uuid>",
        },
    }


_EXAMPLE_VALUES: dict[str, Any] = {"string": "text", "number": 3, "boolean": True, "date": "2026-10-18"}


def _example(kind: str) -> str:
    return str(_EXAMPLE_VALUES[kind]).lower()


# ── the event bus's view ────────────────────────────────────────────────────


@lru_cache(maxsize=256)
def event_type_member(event_type: str):
    """An event type object for `custom.<name>`, as `EventBusService.dispatch` takes: an enum member whose `name` is the
    event's name, built once per name. (The bus and its listeners read `event.event_type.name`, nothing else.)"""
    from marvin.services.event_bus_service.event_types import EventTypeBase

    return next(iter(EventTypeBase("CustomEvent", {event_type: event_type})))


# ── the payload ─────────────────────────────────────────────────────────────

_TRUE = {"true", "yes", "y", "1", "on"}
_FALSE = {"false", "no", "n", "0", "off"}


def _coerce(kind: str, value: Any) -> Any:
    """`value` as a field of `kind`; ValueError says what was wrong. None / "" is not coerced (the caller leaves it out)."""
    if kind == "string":
        if isinstance(value, bool | int | float | str):
            return str(value)[:TEXT_LIMIT]
        raise ValueError("expected text")
    if kind == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        if isinstance(value, str):
            text = value.strip()
            try:
                value = int(text)
            except ValueError:
                try:
                    value = float(text)
                except ValueError:
                    raise ValueError(f"expected a number, got {value!r}") from None
        if isinstance(value, int | float) and math.isfinite(value):
            return value
        raise ValueError("expected a number")
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        word = str(value).strip().lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
        raise ValueError(f"expected true or false, got {value!r}")
    if kind == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            raise ValueError(f"expected a date (2026-10-18), got {value!r}") from None
    raise ValueError(f"unknown field type {kind}")  # pragma: no cover — the registry only stores FIELD_TYPES


def build_payload(definition: CustomEventDefinition, raw: Any) -> dict:
    """An Emit event step's (already templated) payload, held to the event's fields. Raises CustomEventError for a
    key the event doesn't declare or a value of the wrong type; a missing or empty value is left out."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CustomEventError("payload must be an object of the event's fields")
    kinds = {f.key: f.type for f in definition.fields}
    unknown = sorted(str(k) for k in raw if k not in kinds)
    if unknown:
        declared = ", ".join(kinds) or "none"
        raise CustomEventError(f"{event_type_of(definition.name)} has no field {', '.join(unknown)} (fields: {declared})")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            out[key] = _coerce(kinds[key], value)
        except ValueError as e:
            raise CustomEventError(f"{event_type_of(definition.name)} field {key} ({kinds[key]}): {e}") from None
    return out


__all__ = [
    "CATEGORY",
    "FIELD_TYPES",
    "PREFIX",
    "CustomEventError",
    "CustomEventInUse",
    "build_payload",
    "catalog_entries",
    "catalog_entry",
    "entry_for",
    "event_type_member",
    "find",
    "is_custom",
    "read",
    "registered_types",
    "remove",
    "save",
    "usage",
]
