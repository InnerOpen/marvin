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


# ── A real upload, indexed in the listener's own session ─────────────────────────────────────────
class _FakeEmbedder:
    def embed(self, texts, model):
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_an_uploaded_asset_is_indexed_and_announced_after_the_listeners_session_closes(db_session, monkeypatch):
    """Regression (Promote of #305 rolled back): indexing commits, which expires the Assets row, then the session
    closes; the reindexed event read `obj.id` off that detached row → "Instance <Assets> is not bound to a Session"."""
    import uuid

    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
    from marvin.db.models.platform import Assets
    from marvin.db.models.users import Users
    from marvin.services.ai import embeddings

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"Idx {marker}", slug=f"idx-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid, group_id=gid, full_name="Ada", username=f"idx-{marker}", email=f"idx-{marker}@x.test", auth_method="MARVIN"
        )
    )
    asset = Assets(
        session=db_session, group_id=gid, slug=f"poster-{marker}", name="poster.png", original_filename="poster.png",
        filename="poster.png", extension="png", file_size=3, mime_type="image/png", asset_type="image",
        checksum=marker, storage_provider="local", storage_key=f"idx/{marker}", uploaded_by=uid,
        description="A film poster: a lighthouse at dusk.",
    )  # fmt: skip
    db_session.add(asset)
    db_session.commit()
    asset_id = asset.id

    monkeypatch.setattr(embeddings, "embedder_for", lambda provider: (_FakeEmbedder(), "fake-embed"))
    listener = IndexingReactionListener(group_id=gid)
    announced = []
    monkeypatch.setattr(listener, "_emit_reindexed", lambda model, chunks, entity_type, verb, entity_id=None: announced.append(entity_id))
    event = SimpleNamespace(event_type=EventTypes.asset_uploaded, document_data=SimpleNamespace(asset_id=asset_id), entity_id=asset_id)
    try:
        listener.publish_to_subscribers(event, [])

        assert announced == [asset_id]
        assert db_session.query(AIEmbeddingModel).filter_by(group_id=gid, entity_type="asset", entity_id=asset_id).count() == 1
    finally:
        db_session.rollback()
        db_session.query(AIEmbeddingModel).filter_by(group_id=gid).delete()
        db_session.query(Assets).filter_by(group_id=gid).delete()
        db_session.query(Users).filter_by(group_id=gid).delete()
        db_session.query(Groups).filter_by(id=gid).delete()
        db_session.commit()
