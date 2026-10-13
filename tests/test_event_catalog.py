"""Honesty guard for the event catalog.

The Events UI advertises events users can subscribe to. Advertising an event that nothing ever
dispatches is a lie — the subscription can never deliver. These tests scan the source for real
`EventTypes.X` references and assert the *subscribable* catalog only contains events with an emitter,
so the ~40 dead events stay gated and the drift can't silently come back.
"""

import pathlib
import re

from marvin.services.events.event_catalog import _NO_EMITTER, CATALOG

# Files where an EventTypes reference is a *declaration/advertisement*, not an emission.
_EXCLUDE = {"event_types.py", "event_catalog.py", "payload_schemas.py", "event_variables.py"}
_PAT = re.compile(r"EventTypes\.(\w+)")


def _referenced_in_code() -> set[str]:
    """EventTypes members referenced anywhere in app code (a proxy for 'has an emitter')."""
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "marvin"
    seen: set[str] = set()
    for f in root.rglob("*.py"):
        if f.name in _EXCLUDE:
            continue
        for m in _PAT.finditer(f.read_text()):
            seen.add(m.group(1))
    return seen


def test_every_subscribable_catalog_entry_has_an_emitter():
    # A workflow's Emit event step sends the catalog's `emittable` events by name (no EventTypes.X reference).
    ref = _referenced_in_code() | {c.event_type for c in CATALOG if c.emittable}
    offenders = sorted(c.event_type for c in CATALOG if c.enabled and c.event_type not in ref)
    assert not offenders, (
        f"These events are advertised for subscription but nothing emits them — add a dispatch site or gate them in _NO_EMITTER: {offenders}"
    )


def test_no_emitter_set_hides_only_genuinely_dead_events():
    ref = _referenced_in_code()
    wrongly_gated = sorted(e for e in _NO_EMITTER if e in ref)
    assert not wrongly_gated, f"These events are gated as dead but ARE referenced in code — remove them from _NO_EMITTER: {wrongly_gated}"


def test_gated_events_are_not_subscribable():
    disabled = {c.event_type for c in CATALOG if not c.enabled}
    still_on = sorted(_NO_EMITTER - disabled)
    assert not still_on, f"gated events still marked subscribable: {still_on}"
