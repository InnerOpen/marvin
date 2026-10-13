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
    ALIASES,
    CATALOG,
    CATALOG_BY_TYPE,
    CATEGORIES,
    EMITTABLE_EVENT_TYPES,
    HIDDEN_EVENT_TYPES,
    INTERNAL_EVENT_TYPES,
    TRIGGERABLE_EVENT_TYPES,
    aliases_of,
    canonical_event_type,
    offered_emittable,
    trigger_groups,
)

_DECLARATIONS = {"event_types.py", "event_catalog.py", "payload_schemas.py", "event_variables.py"}


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
    uncatalogued = sorted(_referenced_in_code() - set(CATALOG_BY_TYPE))
    assert not uncatalogued, f"Give these a catalog entry (services/events/event_catalog.py): {uncatalogued}"


def test_every_category_is_listed():
    # An entry whose category isn't in CATEGORIES vanishes from the Events catalog (/event/types).
    assert not sorted({e.category for e in CATALOG} - set(CATEGORIES))


def test_every_sent_event_says_who_sends_it():
    silent = sorted(e.event_type for e in CATALOG if not e.hidden and not e.sent_by)
    assert not silent, f"These events are shown but have no sent_by line: {silent}"
    claimed = sorted(e.event_type for e in CATALOG if e.hidden and e.sent_by)
    assert not claimed, f"These are hidden (nothing sends them, or an alias), yet they list a sender: {claimed}"
    blank = sorted(e.event_type for e in CATALOG for line in e.sent_by if not line.strip())
    assert not blank, blank


def test_every_event_with_a_sender_is_really_sent():
    # sent_by is prose; this ties it to the code: a dispatch site, or the Emit event step (emittable).
    sent = _referenced_in_code() | EMITTABLE_EVENT_TYPES
    unsent = sorted(e.event_type for e in CATALOG if e.sent_by and e.event_type not in sent)
    assert not unsent, f"These list a sender but nothing in src/marvin sends them: {unsent}"


# ── Hidden types: explicit, and offered nowhere ────────────────────────────────────────────────────


# Hiding a type is a decision, so the list is spelled out: a change here should be a change someone meant.
NEVER_SENT = {
    # security signals with no feature behind them yet (platform scope, always audited: one flag to turn on)
    "api_rate_limit_exceeded",
    "suspicious_activity_detected",
    # one event per successful delivery is noise; the webhook's activity log records each
    "webhook_delivery_succeeded",
    # nothing publishes "the site" as one act (site_rebuild_queued / webhook_triggered do)
    "site_published",
    # declared, never built
    "backup_started",
    "comment_added",
    "comment_updated",
    "comment_deleted",
    "mention_created",
    "entry_shared",
    "form_submission_processed",
    "form_submission_failed",
    "scheduled_task_cancelled",
    "storage_quota_warning",
    "storage_quota_exceeded",
    "user_updated",
    "user_deleted",
    "user_password_reset_completed",
}
OLD_NAMES = {f"site_build_{s}": f"site_deployment_{s}" for s in ("started", "completed", "failed")}


def test_hidden_types_are_exactly_the_listed_ones():
    assert _NO_EMITTER == NEVER_SENT
    assert ALIASES == OLD_NAMES
    assert HIDDEN_EVENT_TYPES == NEVER_SENT | set(OLD_NAMES)
    assert {e.event_type for e in CATALOG if e.hidden} == HIDDEN_EVENT_TYPES


def test_hidden_types_are_not_offered_for_anything():
    for name in HIDDEN_EVENT_TYPES:
        entry = CATALOG_BY_TYPE[name]
        assert not (entry.enabled or entry.triggerable or entry.sent_by or entry.leads_to), name
        assert not any(name in e.leads_to for e in CATALOG), f"{name} is hidden but something leads to it"
    assert not HIDDEN_EVENT_TYPES & {t for names in trigger_groups().values() for t in names}
    assert not HIDDEN_EVENT_TYPES & set(offered_emittable())
    # The Emit event step still accepts every entry_* type, entry_shared included, though the builder doesn't offer
    # it (open question 6 in tasks/todo.md); nothing else hidden can be emitted.
    assert {e.event_type for e in CATALOG if e.hidden and e.emittable} == {"entry_shared"}


def test_hidden_types_are_not_shown_in_audit_coverage_or_the_admin_catalog():
    from marvin.services.events.audit_settings import settings

    assert not HIDDEN_EVENT_TYPES & {s.event_type for s in settings({})}
    # (the admin catalog, /event/types and the connections summary are checked over HTTP in test_events_cleanup.py)


def test_security_types_stay_platform_and_locked():
    for name in ("api_rate_limit_exceeded", "login_failed_multiple_times", "suspicious_activity_detected"):
        entry = CATALOG_BY_TYPE[name]
        assert entry.scope == "platform" and entry.audit_locked and entry.category == "Security", name


def test_newly_sent_types_are_shown():
    sent = {"webhook_created", "webhook_updated", "webhook_deleted", "webhook_delivery_failed"}
    sent |= {"api_token_created", "api_token_rotated", "api_token_revoked", "login_failed_multiple_times"}
    assert not sent & HIDDEN_EVENT_TYPES
    assert sent <= _referenced_in_code()
    for name in ("api_token_created", "api_token_rotated", "api_token_revoked"):
        assert CATALOG_BY_TYPE[name].scope == "platform" and CATALOG_BY_TYPE[name].audit_locked, name


def test_an_alias_stands_for_a_shown_type_and_nothing_sends_it():
    referenced = _referenced_in_code()
    for alias, target in ALIASES.items():
        assert target in CATALOG_BY_TYPE and not CATALOG_BY_TYPE[target].hidden, alias
        assert CATALOG_BY_TYPE[target].triggerable and CATALOG_BY_TYPE[target].emittable, target
        assert CATALOG_BY_TYPE[alias].category == CATALOG_BY_TYPE[target].category, alias
        assert alias not in referenced, f"{alias} is an alias; send {target}"
        assert canonical_event_type(alias) == target and alias in aliases_of(target)
        assert canonical_event_type(target) == target
    assert canonical_event_type("entry_published") == "entry_published" and aliases_of("entry_published") == []


def test_site_rebuild_sent_is_the_publishing_signal():
    entry = CATALOG_BY_TYPE["webhook_triggered"]
    assert (entry.name, entry.category) == ("Site Rebuild Sent", "Publishing")
    assert "deploy hook" in entry.description


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
    # ...plus the old names of emittable types, which emit their counterpart (site_build_* → site_deployment_*).
    old_names = {alias for alias, target in ALIASES.items() if target in EMITTABLE_EVENT_TYPES}
    assert old_names == set(ALIASES)
    assert {et.name for et in EventTypes if _emit_accepts(et.name)} == EMITTABLE_EVENT_TYPES | old_names


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


def test_internal_events_stay_out_of_the_console():
    listener = L.ConsoleEventListener(uuid.uuid4())
    assert {et.name for et in EventTypes if not listener.get_subscribers(_event(et))} == INTERNAL_EVENT_TYPES
    assert INTERNAL_EVENT_TYPES == {"webhook_task"} | {f"scheduled_task_{s}" for s in ("triggered", "started", "completed", "failed")}
