"""
Embedding service — chunk text, embed via a provider, store, and search.

Vectors are stored as JSON float arrays in ai_embeddings (cross-DB), and cosine
similarity is computed in Python (numpy). This is O(n) over a workspace's chunks —
fine at hobby scale; migrate to pgvector on Postgres if it ever needs to scale.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

# Platform settings that override a provider's default embedding model. Azure shares OpenAI's; any other
# provider (a plugin's) reads <SLUG>_EMBEDDING_MODEL.
_EMBEDDING_SETTING_KEYS: dict[str, str] = {
    "openai": "OPENAI_EMBEDDING_MODEL",
    "azure": "OPENAI_EMBEDDING_MODEL",
    "google": "GOOGLE_EMBEDDING_MODEL",
    "ollama": "OLLAMA_EMBEDDING_MODEL",
}


def default_embedding_model(provider_type: str) -> str | None:
    """Resolve the embedding model — the platform setting first, then the provider's own default."""
    from marvin.core.config import get_app_settings
    from marvin.services.ai.registry import find_class
    from marvin.services.plugin_loader import settings_source

    key = _EMBEDDING_SETTING_KEYS.get(provider_type) or f"{provider_type}_EMBEDDING_MODEL".upper().replace("-", "_")
    configured = settings_source(get_app_settings()).get(key)
    if configured:
        return configured
    cls = find_class(provider_type)
    return cls.default_embedding_model if cls else None


# Marvin's own embedding model, used by every workspace whatever its chat provider: an index can only be read by the
# model that built it, so tying search to the chat provider broke it on every switch (and Anthropic offers no
# embeddings at all). Small (384 numbers per chunk, ~65 MB), fast on CPU; the Docker image carries it
# (EMBEDDINGS_BUILTIN_CACHE), so nothing is downloaded at run time. EMBEDDINGS_BUILTIN_ENABLED=false goes back to the
# provider's own embedding model.
BUILTIN_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
BUILTIN_PROVIDER_TYPE = "builtin"
BUILTIN_BATCH = 4


class BuiltinEmbedder:
    """The embed() half of an AI provider, run in this process with fastembed (ONNX). Loaded once, on first use."""

    provider_type = BUILTIN_PROVIDER_TYPE
    supports_embeddings = True
    _model = None
    _lock = None

    @classmethod
    def _load(cls):
        import threading

        if cls._lock is None:
            cls._lock = threading.Lock()
        with cls._lock:
            if cls._model is None:
                import os

                from fastembed import TextEmbedding

                # One thread: it runs inside the API process, beside requests.
                cls._model = TextEmbedding(BUILTIN_EMBEDDING_MODEL, cache_dir=os.environ.get("EMBEDDINGS_BUILTIN_CACHE") or None, threads=1)
        return cls._model

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        # Small batches: the model takes ~250 MB loaded, and a batch of long chunks adds to that in proportion (64 at once
        # added ~770 MB in a measurement, the whole pod; 4 at a time stays near +300 MB at the same speed).
        return [vector.tolist() for vector in self._load().embed(list(texts), batch_size=BUILTIN_BATCH)]


def builtin_embeddings_available() -> bool:
    import importlib.util

    from marvin.core.config import get_app_settings

    return bool(getattr(get_app_settings(), "EMBEDDINGS_BUILTIN_ENABLED", True)) and importlib.util.find_spec("fastembed") is not None


def builtin_embedding_dimensions() -> int | None:
    """Vector size of the built-in model, from fastembed's model catalogue (a static list: no weights are loaded);
    None when fastembed isn't installed."""
    try:
        from fastembed import TextEmbedding

        return next((int(m["dim"]) for m in TextEmbedding.list_supported_models() if m["model"] == BUILTIN_EMBEDDING_MODEL), None)
    except Exception:  # noqa: BLE001 — a status readout never breaks on a library quirk
        return None


def _package_version(name: str) -> str | None:
    import importlib.metadata as md

    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


def indexed_models(session: Session) -> list[tuple[str, int]]:
    """(model id, chunk count) for every embedding model that has vectors stored, platform-wide, most chunks first.
    A model that isn't the one in use is a stale index waiting for a reindex."""
    import sqlalchemy as sa

    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    count = sa.func.count(AIEmbeddingModel.id)
    rows = session.query(AIEmbeddingModel.model_id, count).group_by(AIEmbeddingModel.model_id).order_by(count.desc(), AIEmbeddingModel.model_id).all()
    return [(model_id, int(n)) for model_id, n in rows]


def embeddings_status(session: Session) -> dict:
    """What Admin → System shows about embeddings. Reads settings, package metadata and one grouped count; never
    loads the model."""
    from marvin.core.config import get_app_settings

    available = builtin_embeddings_available()
    return {
        "builtin_enabled": bool(getattr(get_app_settings(), "EMBEDDINGS_BUILTIN_ENABLED", True)),
        "builtin_available": available,
        "model": BUILTIN_EMBEDDING_MODEL if available else None,
        "dimensions": builtin_embedding_dimensions() if available else None,
        "engine": "fastembed",
        "engine_version": _package_version("fastembed"),
        "onnxruntime_version": _package_version("onnxruntime"),
        "indexed_models": [{"model_id": m, "chunks": n} for m, n in indexed_models(session)],
    }


def embedder_for(provider) -> tuple[object, str] | tuple[None, None]:
    """(embedder, model id) a workspace embeds with: Marvin's built-in model; with it switched off, the AI provider's
    own embedding model if it has one; else (None, None). The embedder has `embed(texts, model)`; the model id is
    stored with each vector, so an index built by one model is never read with another."""
    if builtin_embeddings_available():
        return BuiltinEmbedder(), BUILTIN_EMBEDDING_MODEL
    if provider is not None and getattr(provider, "supports_embeddings", False):
        model = default_embedding_model(provider.provider_type)
        if model:
            return provider, model
    return None, None


def embedding_model_for_settings(provider_type: str | None) -> str | None:
    """The embedding model a workspace on `provider_type` ends up with (for "did it change?" and "is there search?")."""
    from marvin.services.ai.registry import find_class

    if builtin_embeddings_available():
        return BUILTIN_EMBEDDING_MODEL
    cls = find_class(provider_type) if provider_type else None
    if cls is not None and getattr(cls, "supports_embeddings", False):
        return default_embedding_model(provider_type)
    return None


def chunk_text(text: str, max_chars: int = 1500, overlap: int = 150) -> list[str]:
    """Split text into overlapping character windows. Simple and provider-agnostic."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(1, max_chars - overlap)
    while start < len(text):
        chunks.append(text[start : start + max_chars])
        start += step
    return chunks


def index_entity(
    session: Session,
    group_id: UUID4,
    entity_type: str,
    entity_id: UUID4,
    text: str,
    provider,
    model: str,
) -> int:
    """Chunk + embed `text` and (re)store the chunks for this entity+model. Returns chunk count."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    app = get_app_settings()
    chunks = chunk_text(
        text,
        max_chars=getattr(app, "AI_EMBED_CHUNK_SIZE", 1500),
        overlap=getattr(app, "AI_EMBED_CHUNK_OVERLAP", 150),
    )
    if not chunks:
        # No content — clear any stale embeddings for this entity+model.
        session.query(AIEmbeddingModel).filter_by(group_id=group_id, entity_type=entity_type, entity_id=entity_id, model_id=model).delete()
        session.commit()
        return 0

    vectors = provider.embed(chunks, model)
    _store_chunks(session, group_id, entity_type, entity_id, model, chunks, vectors)
    session.commit()
    return len(chunks)


def _tags_line(obj) -> str | None:
    """A 'Tags: …' line (display names, human words) so tag vocabulary is semantically searchable."""
    tags = getattr(obj, "tags", None)
    if not tags:
        return None
    names: list[str] = []
    for t in tags:
        name = getattr(t, "name", None) or getattr(t, "slug", "") or ""
        if name:
            names.append(str(name))
    return ("Tags: " + ", ".join(names)) if names else None


def _entry_text(e) -> str:
    return "\n".join(filter(None, [e.title, e.summary, e.description, str(e.data_json or ""), _tags_line(e)]))


def _resource_text(r) -> str:
    return "\n".join(filter(None, [r.name, r.description, r.url, _tags_line(r)]))


def _asset_text(a) -> str:
    return "\n".join(filter(None, [a.name, a.alt_text, a.description, _tags_line(a)]))


def purge_embeddings(session: Session, group_id: UUID4, entity_type: str, entity_id: UUID4, model: str | None = None) -> int:
    """Remove an entity's embedding chunks (all models, or one). Called when the entity is deleted."""
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    q = session.query(AIEmbeddingModel).filter_by(group_id=group_id, entity_type=entity_type, entity_id=entity_id)
    if model:
        q = q.filter_by(model_id=model)
    n = q.delete()
    session.commit()
    return n


EMBED_BATCH_CHUNKS = 64
"""Chunks sent per embedding call. One call per item made a workspace reindex take minutes (one round
trip each); batching makes it a handful of calls. Kept well under providers' per-request input limits."""

MAX_REPORTED_ERRORS = 3


@dataclass
class ReindexResult:
    entities: int = 0
    """Items (re)embedded this run."""
    chunks: int = 0
    """Chunks written this run."""
    skipped: int = 0
    """Items whose text hadn't changed since they were last embedded (nothing to do)."""
    purged: int = 0
    """Items too thin to index whose old chunks were dropped."""
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    """The first few distinct failure messages — so a run that embeds nothing says why."""

    @property
    def summary(self) -> str:
        text = f"Reindexed {self.entities} items ({self.chunks} chunks)"
        if self.skipped:
            text += f", {self.skipped} unchanged"
        if self.failed:
            text += f", {self.failed} failed: {self.errors[0] if self.errors else 'unknown error'}"
        return text


def entity_chunks(text: str) -> list[str]:
    """`text` split the way the index stores it (AI_EMBED_CHUNK_SIZE / _OVERLAP)."""
    from marvin.core.config import get_app_settings

    app = get_app_settings()
    return chunk_text(text, max_chars=getattr(app, "AI_EMBED_CHUNK_SIZE", 1500), overlap=getattr(app, "AI_EMBED_CHUNK_OVERLAP", 150))


def chunks_unchanged(session: Session, group_id, entity_type: str, entity_id, model: str, chunks: list[str]) -> bool:
    """True when the entity's stored chunks for this model are exactly these — nothing to re-embed."""
    return bool(chunks) and _existing_chunks(session, group_id, entity_type, entity_id, model) == chunks


def _existing_chunks(session: Session, group_id, entity_type: str, entity_id, model: str) -> list[str]:
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    rows = (
        session.query(AIEmbeddingModel.chunk_text)
        .filter_by(group_id=group_id, entity_type=entity_type, entity_id=entity_id, model_id=model)
        .order_by(AIEmbeddingModel.chunk_index)
        .all()
    )
    return [r[0] for r in rows]


def _store_chunks(session: Session, group_id, entity_type: str, entity_id, model: str, chunks: list[str], vectors) -> None:
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    dims = len(vectors[0]) if vectors else 0
    session.query(AIEmbeddingModel).filter_by(group_id=group_id, entity_type=entity_type, entity_id=entity_id, model_id=model).delete()
    for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False)):
        session.add(
            AIEmbeddingModel(
                session=session,
                group_id=group_id,
                entity_type=entity_type,
                entity_id=entity_id,
                chunk_index=i,
                chunk_text=chunk,
                embedding=list(vec),
                model_id=model,
                dimensions=dims,
            )
        )


def reindex_workspace(
    session: Session,
    group_id: UUID4,
    provider,
    model: str,
    *,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> ReindexResult:
    """(Re)index every indexable entity in a workspace — the one path the Reindex button and the
    scheduled task share.

    Items whose chunks are unchanged since their last embedding are skipped (unless `force`), the rest
    are embedded in batches of EMBED_BATCH_CHUNKS, and a failing batch is counted with its error rather
    than swallowed. `progress(done, total)` is called as items are handled.
    """
    from marvin.services.ai.embeddings_registry import REGISTRY

    result = ReindexResult()
    targets = [(desc, obj) for desc in REGISTRY.values() for obj in session.query(desc.model).filter_by(group_id=group_id).all()]
    total, done = len(targets), 0
    pending: list[tuple[str, object, list[str]]] = []

    def note_error(message: str) -> None:
        if message not in result.errors and len(result.errors) < MAX_REPORTED_ERRORS:
            result.errors.append(message)

    def flush() -> None:
        nonlocal done
        if not pending:
            return
        texts = [chunk for _, _, chunks in pending for chunk in chunks]
        try:
            vectors = provider.embed(texts, model)
            if len(vectors) != len(texts):
                raise ValueError(f"provider returned {len(vectors)} vectors for {len(texts)} chunks")
            at = 0
            for entity_type, entity_id, chunks in pending:
                _store_chunks(session, group_id, entity_type, entity_id, model, chunks, vectors[at : at + len(chunks)])
                at += len(chunks)
                result.entities += 1
                result.chunks += len(chunks)
            session.commit()
        except Exception as e:  # noqa: BLE001 — counted and reported, never silently dropped
            session.rollback()
            result.failed += len(pending)
            note_error(f"{type(e).__name__}: {str(e)[:300]}")
            logger.warning("reindex: embedding batch of %d items failed for %s: %s", len(pending), group_id, e)
        done += len(pending)
        pending.clear()
        if progress:
            progress(done, total)

    for desc, obj in targets:
        try:
            if not desc.content_ok(obj):
                if purge_embeddings(session, group_id, desc.entity_type, obj.id, model):
                    result.purged += 1
                done += 1
                continue
            chunks = entity_chunks(desc.text(obj))
            if not chunks:
                purge_embeddings(session, group_id, desc.entity_type, obj.id, model)
                done += 1
                continue
            if not force and _existing_chunks(session, group_id, desc.entity_type, obj.id, model) == chunks:
                result.skipped += 1
                done += 1
                continue
        except Exception as e:  # noqa: BLE001 — one unreadable item must not stop the run
            result.failed += 1
            note_error(f"{type(e).__name__}: {str(e)[:300]}")
            done += 1
            continue
        pending.append((desc.entity_type, obj.id, chunks))
        if sum(len(c) for _, _, c in pending) >= EMBED_BATCH_CHUNKS:
            flush()
    flush()
    if progress:
        progress(total, total)
    return result


def search_embeddings(
    session: Session,
    group_id: UUID4,
    query_vector: list[float],
    limit: int = 5,
    entity_types: list[str] | None = None,
    model: str | None = None,
) -> list[dict]:
    """Return the top-`limit` chunks by cosine similarity to `query_vector`, among those `model` embedded (a vector is
    only comparable with one from the same model; an older model's stay in the table until a re-index replaces them)."""
    import numpy as np

    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    q = session.query(AIEmbeddingModel).filter_by(group_id=group_id)
    if model:
        q = q.filter_by(model_id=model)
    if entity_types:
        q = q.filter(AIEmbeddingModel.entity_type.in_(entity_types))
    rows = q.all()
    # Entries of an internal type (services/entry_listing.py) are never retrieved, whatever an older index still holds.
    if rows and (not entity_types or "entry" in entity_types):
        from marvin.services.entry_listing import unlisted_entry_ids

        if hidden := {str(i) for i in unlisted_entry_ids(session, group_id)}:
            rows = [r for r in rows if not (r.entity_type == "entry" and str(r.entity_id) in hidden)]
    if not rows:
        return []

    qv = np.asarray(query_vector, dtype=float)
    qn = float(np.linalg.norm(qv)) or 1.0

    scored: list[tuple[float, AIEmbeddingModel]] = []
    for r in rows:
        v = np.asarray(r.embedding, dtype=float)
        if v.shape != qv.shape:
            continue  # dimension mismatch (different embedding model) — skip
        denom = (float(np.linalg.norm(v)) * qn) or 1.0
        scored.append((float(np.dot(v, qv) / denom), r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "text": r.chunk_text,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id),
            "score": round(s, 4),
        }
        for s, r in scored[:limit]
    ]
