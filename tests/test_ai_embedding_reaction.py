"""
Unit tests for the RAG IndexingReactionListener + the indexable-type registry.

The listener is registry-driven: it reacts to each registered type's index/delete events,
(re)embeds on index events (gated per-type), and purges on delete. These verify:
 - which events it subscribes to (derived from the registry across all types),
 - the entry re-embed gate (`_entry_should_index`), unchanged in behavior, and
 - that assets/resources are registered so they participate in the index.
"""

from types import SimpleNamespace
from uuid import uuid4

from marvin.services.ai.embeddings_registry import (
    REGISTRY,
    _entry_should_index,
    indexable_types,
    trigger_events,
)
from marvin.services.event_bus_service.event_bus_listener import IndexingReactionListener
from marvin.services.event_bus_service.event_types import EventTypes


def _listener() -> IndexingReactionListener:
    return IndexingReactionListener(group_id=uuid4())


class TestRegistry:
    def test_entry_resource_asset_are_registered(self):
        assert set(indexable_types()) == {"entry", "resource", "asset"}

    def test_trigger_events_cover_index_and_delete_for_all_types(self):
        evs = trigger_events()
        # index events
        assert EventTypes.entry_published in evs and EventTypes.entry_updated in evs
        assert EventTypes.resource_created in evs and EventTypes.resource_updated in evs
        assert EventTypes.asset_uploaded in evs and EventTypes.asset_updated in evs
        # delete events (purge)
        assert EventTypes.entry_deleted in evs
        assert EventTypes.resource_deleted in evs
        assert EventTypes.asset_deleted in evs

    def test_each_type_declares_a_text_builder(self):
        for desc in REGISTRY.values():
            assert callable(desc.text)


class TestTriggerEvents:
    """get_subscribers reacts to any registered index/delete event; ignores the rest."""

    def test_entry_publish_and_update_trigger(self):
        for ev in (EventTypes.entry_published, EventTypes.entry_updated):
            assert _listener().get_subscribers(SimpleNamespace(event_type=ev)) == ["ai_index"]

    def test_resource_and_asset_events_trigger(self):
        for ev in (EventTypes.resource_created, EventTypes.resource_updated, EventTypes.asset_uploaded, EventTypes.asset_updated):
            assert _listener().get_subscribers(SimpleNamespace(event_type=ev)) == ["ai_index"]

    def test_delete_events_trigger_a_purge(self):
        # Delete now DOES subscribe (to purge stale embeddings) — a behavior change from the
        # entry-only listener, which ignored deletes.
        for ev in (EventTypes.entry_deleted, EventTypes.resource_deleted, EventTypes.asset_deleted):
            assert _listener().get_subscribers(SimpleNamespace(event_type=ev)) == ["ai_index"]

    def test_entry_created_does_not_trigger(self):
        # entries index on publish/update, not on bare create.
        assert _listener().get_subscribers(SimpleNamespace(event_type=EventTypes.entry_created)) == []


class TestEntryUpdateGate:
    """_entry_should_index encodes the entry-specific judgment call (moved to the registry)."""

    def test_publish_always_indexes(self):
        entry = SimpleNamespace(status="published")
        assert _entry_should_index(entry, EventTypes.entry_published, has_index=False) is True

    def test_update_reembeds_only_when_published_and_already_indexed(self):
        assert _entry_should_index(SimpleNamespace(status="published"), EventTypes.entry_updated, True) is True

    def test_update_skips_first_publish_double_embed(self):
        # entry_published emits entry_updated too; with no prior index the update no-ops.
        assert _entry_should_index(SimpleNamespace(status="published"), EventTypes.entry_updated, False) is False

    def test_update_never_embeds_draft_inbox_archived(self):
        for status in ("draft", "inbox", "archived"):
            assert _entry_should_index(SimpleNamespace(status=status), EventTypes.entry_updated, True) is False
