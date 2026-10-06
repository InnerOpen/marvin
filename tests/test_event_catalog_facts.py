"""The event catalog is the one list of facts about each event type — these tests keep the code that acts on
those facts (the workflow trigger gate, the Emit event step, the built-in reactions) and the catalog in step.

Companion to tests/test_event_catalog.py (which keeps `enabled` honest against the code's dispatch sites).
"""

import pathlib
import re
import uuid
from types import SimpleNamespace

import pytest

from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.emit_event import run_emit_event
from marvin.services.automation.authz import ROLE_OWNER
from marvin.services.event_bus_service import event_bus_listener as L
from marvin.services.event_bus_service.event_types import EventTypes
from marvin.services.events.event_catalog import (
    _NO_EMITTER,
    CATALOG,
    CATALOG_BY_TYPE,
    EMITTABLE_EVENT_TYPES,
    TRIGGERABLE_EVENT_TYPES,
    offered_emittable,
    trigger_groups,
)

_DECLARATIONS = {"event_types.py", "event_catalog.py", "payload_schemas.py", "event_variables.py"}

# Dispatched, but with no catalog entry yet: always audited (audit_settings audits uncatalogued types), never
# offered for subscription, absent from the Events catalog. Giving one an entry changes what the Event Log
# settings and the Events catalog show, so it's a deliberate step — this set may only shrink.
_KNOWN_UNCATALOGUED = frozenset({"automation_ran", "automation_failed", "email_template_created", "email_template_updated", "email_template_deleted"})


def _referenced_in_code() -> set[str]:
    """EventTypes members referenced in app code outside their declarations — every dispatch site among them."""
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "marvin"
    seen: set[str] = set()
    for f in root.rglob("*.py"):
        if f.name not in _DECLARATIONS:
            seen |= set(re.findall(r"EventTypes\.(\w+)", f.read_text()))
    return seen


def _event(et: EventTypes) -> SimpleNamespace:
    return SimpleNamespace(event_type=et, reaction_depth=0, document_data=None, entity_id=None, message=None)


def _names(events) -> set[str]:
    return {e.name for e in events}


# ── Every sent event is in the catalog and says who sends it ──────────────────────────────────────────


def test_every_dispatched_event_type_has_a_catalog_entry():
    uncatalogued = _referenced_in_code() - set(CATALOG_BY_TYPE)
    assert uncatalogued == _KNOWN_UNCATALOGUED, (
        f"Give these a catalog entry (services/events/event_catalog.py): {sorted(uncatalogued - _KNOWN_UNCATALOGUED)}; "
        f"these now have one — drop them from _KNOWN_UNCATALOGUED: {sorted(_KNOWN_UNCATALOGUED - uncatalogued)}"
    )


def test_every_sent_event_says_who_sends_it():
    silent = sorted(e.event_type for e in CATALOG if e.event_type not in _NO_EMITTER and not e.sent_by)
    assert not silent, f"These events are sent but have no sent_by line: {silent}"
    claimed = sorted(e.event_type for e in CATALOG if e.event_type in _NO_EMITTER and e.sent_by)
    assert not claimed, f"Nothing sends these (_NO_EMITTER), yet they list a sender: {claimed}"
    blank = sorted(e.event_type for e in CATALOG for line in e.sent_by if not line.strip())
    assert not blank, blank


def test_every_event_with_a_sender_is_really_sent():
    # sent_by is prose; this ties it to the code: a dispatch site, or the Emit event step (emittable).
    sent = _referenced_in_code() | EMITTABLE_EVENT_TYPES
    unsent = sorted(e.event_type for e in CATALOG if e.sent_by and e.event_type not in sent)
    assert not unsent, f"These list a sender but nothing in src/marvin sends them: {unsent}"


# ── leads_to ──────────────────────────────────────────────────────────────────────────────────────────


def test_every_leads_to_target_is_a_sent_catalog_event():
    for e in CATALOG:
        for target in e.leads_to:
            assert target in CATALOG_BY_TYPE, f"{e.event_type} leads to unknown event {target!r}"
            assert target != e.event_type, e.event_type
            assert CATALOG_BY_TYPE[target].sent_by, f"{e.event_type} leads to {target}, which nothing sends"


def _leading_to(target: str) -> set[str]:
    return {e.event_type for e in CATALOG if target in e.leads_to}


def test_leads_to_site_rebuild_queued_is_what_the_site_rebuild_reaction_reacts_to():
    assert _leading_to("site_rebuild_queued") == _names(L.SiteRebuildReactionListener.reacts_to())


def test_leads_to_ai_embeddings_reindexed_is_what_ai_search_indexes_on():
    # The indexing reaction announces each item it (re)indexes; a delete purges quietly.
    from marvin.services.ai.embeddings_registry import REGISTRY

    assert _leading_to("ai_embeddings_reindexed") == {et.name for d in REGISTRY.values() for et in d.index_on}


def test_the_chains_marvin_runs_itself():
    assert CATALOG_BY_TYPE["site_rebuild_queued"].leads_to == ["webhook_triggered"]  # the scheduler sends the queued rebuild
    assert _leading_to("scheduled_task_started") == _names(L.ScheduledTaskListener.reacts_to())


# ── triggerable: the workflow trigger gate and the builder's dropdown ────────────────────────────────


def test_triggerable_is_what_the_automation_listener_reacts_to():
    listener = L.AutomationReactionListener(uuid.uuid4())
    accepted = {et.name for et in EventTypes if listener.get_subscribers(_event(et))}
    # Plus the events the incoming_webhook / chained / on_error trigger types listen to.
    assert accepted == TRIGGERABLE_EVENT_TYPES | {"incoming_webhook", "automation_ran", "automation_failed"}


def test_triggerable_events_are_sent_and_subscribable():
    assert not sorted(t for t in TRIGGERABLE_EVENT_TYPES if not CATALOG_BY_TYPE[t].enabled)


def test_trigger_group_is_only_set_where_it_matters():
    for e in CATALOG:
        if e.trigger_group is not None:
            assert e.triggerable, f"{e.event_type} has a trigger_group but isn't triggerable"
            assert e.trigger_group != e.category, f"{e.event_type}: trigger_group repeats the category"


def test_the_builder_dropdown_lists_every_triggerable_event_once():
    listed = [name for names in trigger_groups().values() for name in names]
    assert sorted(listed) == sorted(TRIGGERABLE_EVENT_TYPES)


# ── emittable: the Emit event step ───────────────────────────────────────────────────────────────────


def _emit_accepts(name: str) -> bool:
    action = {"kind": "emit_event", "event": name, "entity_id": str(uuid.uuid4())}
    try:
        run_emit_event(None, uuid.uuid4(), action, {"event": {}, "depth": 0}, authorizer_role=ROLE_OWNER, dry_run=True)
    except AutomationActionError:
        return False
    return True


def test_emittable_is_what_emit_event_accepts():
    assert {et.name for et in EventTypes if _emit_accepts(et.name)} == EMITTABLE_EVENT_TYPES


def test_the_builder_offers_emittable_events_that_are_subscribable():
    offered = offered_emittable()
    assert len(offered) == len(set(offered))
    assert set(offered) == {t for t in EMITTABLE_EVENT_TYPES if CATALOG_BY_TYPE[t].enabled}


# ── Built-in reactions declare themselves ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls", L.BUILTIN_REACTIONS, ids=lambda c: c.__name__)
def test_a_builtin_reaction_reacts_to_exactly_what_it_declares(cls):
    listener = cls(uuid.uuid4())
    acted_on = {et for et in EventTypes if listener.get_subscribers(_event(et))}
    assert acted_on == set(cls.reacts_to())
    assert cls.label and cls.label.strip()
    assert _names(cls.reacts_to()) <= set(CATALOG_BY_TYPE), f"{cls.__name__} reacts to uncatalogued events"


def test_every_builtin_reaction_is_listed_and_runs():
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    assert set(L.BuiltinReaction.__subclasses__()) == set(L.BUILTIN_REACTIONS)
    running = [type(listener) for listener in EventBusService(bg_tasks=None)._get_listeners(uuid.uuid4())]
    assert [c for c in running if c in L.BUILTIN_REACTIONS] == list(L.BUILTIN_REACTIONS)


def test_builtin_reactions_lookup():
    labels = [label for label, _ in L.builtin_reactions("entry_published")]
    assert labels == ["Refreshes AI search", "Warms the media-embed cache", "Queues a site rebuild", "Updates smart collections"]
    assert L.builtin_reactions(EventTypes.scheduled_task_triggered) == [("Runs the scheduled task", L.ScheduledTaskListener)]
    assert L.builtin_reactions("user_signup") == []
    assert L.builtin_reactions("no_such_event") == []


# ── The retired side lists, as they stood on develop: the catalog-derived sets equal them exactly ────

_OLD_TRIGGER_EVENT_GROUPS = {  # services/automation/triggers.py TRIGGER_EVENT_GROUPS
    "Entries": {
        "entry_created", "entry_updated", "entry_published", "entry_unpublished", "entry_archived", "entry_restored", "entry_deleted",
        "entry_scheduled_publish_blocked", "entry_resource_attached", "entry_resource_detached", "entry_tag_attached",
        "entry_tag_detached", "asset_attached_to_entry", "asset_detached_from_entry",
    },
    "Collections": {"entry_added_to_collection", "entry_removed_from_collection", "collection_created", "collection_updated", "collection_deleted"},
    "Assets": {"asset_uploaded", "asset_updated", "asset_deleted"},
    "Resources": {"resource_created", "resource_updated", "resource_deleted"},
    "Forms": {
        "form_submission_received", "submission_surge_detected", "form_created", "form_updated", "form_published", "form_archived", "form_deleted",
    },
    "Entry types": {"entry_type_created", "entry_type_updated", "entry_type_deleted"},
    "Site": {"site_build_started", "site_build_completed", "site_build_failed", "site_deployment_started", "site_deployment_completed",
             "site_deployment_failed"},
}  # fmt: skip
_OLD_SITE_EVENTS = _OLD_TRIGGER_EVENT_GROUPS["Site"]  # services/automation/actions/emit_event.py SITE_EVENTS
_OLD_LISTENER_SETS = {
    "ScheduledTaskListener": {"scheduled_task_triggered"},
    "IndexingReactionListener": {
        "entry_published", "entry_updated", "entry_deleted", "entry_unpublished", "entry_archived", "resource_created", "resource_updated",
        "resource_deleted", "asset_uploaded", "asset_updated", "asset_deleted",
    },
    "MediaEmbedReactionListener": {"entry_created", "entry_updated", "entry_published"},
    "SiteRebuildReactionListener": {
        "entry_published", "entry_unpublished", "entry_archived", "entry_updated", "entry_added_to_collection", "entry_removed_from_collection",
        "entry_tag_attached", "entry_tag_detached", "entry_resource_attached", "entry_resource_detached", "asset_attached_to_entry",
        "asset_detached_from_entry", "entry_deleted", "collection_updated", "collection_deleted", "asset_updated", "asset_deleted",
        "resource_updated", "resource_deleted", "workspace_settings_changed",
    },
    "SmartCollectionReactionListener": {"entry_created", "entry_updated", "entry_published", "entry_unpublished", "entry_archived", "entry_restored"},
}  # fmt: skip


def test_trigger_groups_equal_the_old_list():
    assert {label: set(names) for label, names in trigger_groups().items()} == _OLD_TRIGGER_EVENT_GROUPS


def test_emittable_equals_what_emit_event_accepted():
    # Old rule: SITE_EVENTS, or any EventTypes member named entry_*.
    assert EMITTABLE_EVENT_TYPES == _OLD_SITE_EVENTS | {et.name for et in EventTypes if et.name.startswith("entry_")}


def test_the_emit_menu_equals_the_old_one():
    # Old builder rule: triggerable entry_* events, then the six site events.
    old = {n for names in _OLD_TRIGGER_EVENT_GROUPS.values() for n in names if n.startswith("entry_")} | _OLD_SITE_EVENTS
    assert set(offered_emittable()) == old


@pytest.mark.parametrize("cls", L.BUILTIN_REACTIONS, ids=lambda c: c.__name__)
def test_builtin_reaction_sets_equal_the_old_ones(cls):
    assert _names(cls.reacts_to()) == _OLD_LISTENER_SETS[cls.__name__]
