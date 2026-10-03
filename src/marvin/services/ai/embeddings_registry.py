"""Registry of RAG-indexable entity types.

The single place that says "this entity type participates in the RAG index, on these events, with
this text". A generic reaction listener (IndexingReactionListener) and the bulk reindex / semantic
search paths all iterate this registry, so **adding a new indexable type is one registration** —
no new listener, no editing the reindex or search code.

Each type declares:
  - which lifecycle events (re)index it and which purge it (delete),
  - how to build its embed text (include tags so the vocabulary is searchable),
  - the document_data field carrying its id, and
  - an optional per-type gate (e.g. entries: only re-embed a live, already-indexed entry on update).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from marvin.db.models.platform import Assets, Entries, Resources
from marvin.services.ai.embeddings import _asset_text, _entry_text, _resource_text
from marvin.services.event_bus_service.event_types import EventTypes


@dataclass(frozen=True)
class Indexable:
    """A description of one RAG-indexable entity type."""

    entity_type: str  # "entry" | "resource" | "asset" — the embedding's entity_type key
    model: type  # SQLAlchemy model (queried in bulk reindex, loaded on reactive index)
    text: Callable[[object], str]  # build the text to embed (should include tags)
    id_field: str  # document_data attribute carrying the entity id, e.g. "entry_id"
    index_on: tuple  # EventTypes that (re)index this entity
    delete_on: tuple = field(default_factory=tuple)  # EventTypes that purge it from the index
    # Per-type gate, given (obj, event_type, has_existing_index) → whether to index this occurrence.
    should_index: Callable[..., bool] = lambda obj, event_type, has_index: True
    # Content gate, given (obj) → whether this object has enough substance to be worth embedding.
    # Honored by BOTH the reactive listener and the full reindex, so a content-thin object never
    # enters the index (or is purged if it becomes thin). Default: everything is worth indexing.
    content_ok: Callable[[object], bool] = lambda obj: True


REGISTRY: dict[str, Indexable] = {}


def register_indexable(desc: Indexable) -> None:
    """Register (or replace) an indexable type. Call once per type at import time."""
    REGISTRY[desc.entity_type] = desc


def indexable_types() -> list[str]:
    """Entity-type keys currently indexed — the set semantic search should retrieve over."""
    return list(REGISTRY)


def trigger_events() -> set:
    """Every event that the indexing listener must react to (index + delete, across all types)."""
    events: set = set()
    for desc in REGISTRY.values():
        events |= set(desc.index_on) | set(desc.delete_on)
    return events


def index_descriptor_for(event_type) -> Indexable | None:
    """The descriptor whose index_on contains this event (or None)."""
    return next((d for d in REGISTRY.values() if event_type in d.index_on), None)


def delete_descriptor_for(event_type) -> Indexable | None:
    """The descriptor whose delete_on contains this event (or None)."""
    return next((d for d in REGISTRY.values() if event_type in d.delete_on), None)


# ── Per-type gates ────────────────────────────────────────────────────────────


def _asset_content_ok(asset) -> bool:
    """An asset earns a place in the semantic index only if it carries descriptive text — a
    description or alt text. A bare icon/logo (name + tags only, e.g. an SVG "Envelope\\nTags:
    site asset") embeds to near-nothing but its tag, hijacking tag-adjacent searches; skip it.
    Its tags remain discoverable via list_tags and structured tag filters, not RAG."""
    return bool((getattr(asset, "description", None) or "").strip() or (getattr(asset, "alt_text", None) or "").strip())


def _entry_should_index(entry, event_type, has_index: bool) -> bool:
    """Entries: always index on publish; on a bare update only re-embed a live, already-indexed
    entry. Skips draft/inbox/archived saves and avoids double-embedding the publish transition
    (which emits entry_updated *then* entry_published — the update no-ops before the first index)."""
    if event_type == EventTypes.entry_published:
        return True
    return getattr(entry, "status", None) == "published" and has_index


# ── Default registrations ─────────────────────────────────────────────────────


def _register_defaults() -> None:
    register_indexable(
        Indexable(
            entity_type="entry",
            model=Entries,
            text=_entry_text,
            id_field="entry_id",
            index_on=(EventTypes.entry_published, EventTypes.entry_updated),
            # Only published entries are searchable, so leaving 'published' takes an entry out of the
            # index — not only deleting it (an archived duplicate must not keep answering questions).
            delete_on=(EventTypes.entry_deleted, EventTypes.entry_unpublished, EventTypes.entry_archived),
            should_index=_entry_should_index,
            # The same rule for the full reindex: drafts, inbox and archived entries are left out (and purged).
            content_ok=lambda entry: getattr(entry, "status", None) == "published",
        )
    )
    register_indexable(
        Indexable(
            entity_type="resource",
            model=Resources,
            text=_resource_text,
            id_field="resource_id",
            index_on=(EventTypes.resource_created, EventTypes.resource_updated),
            delete_on=(EventTypes.resource_deleted,),
        )
    )
    register_indexable(
        Indexable(
            entity_type="asset",
            model=Assets,
            text=_asset_text,
            id_field="asset_id",
            index_on=(EventTypes.asset_uploaded, EventTypes.asset_updated),
            delete_on=(EventTypes.asset_deleted,),
            content_ok=_asset_content_ok,  # skip content-thin icons/logos (name+tags only)
        )
    )


_register_defaults()
