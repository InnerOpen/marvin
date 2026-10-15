"""Marvin's built-in embedding model (services/ai/embeddings.py): every workspace indexes and searches with it whatever
its chat provider, and with none at all, so changing provider never breaks search (an index can only be read by the
model that built it, and Anthropic has no embedding model). The real model is a 65 MB download, so a fake stands in."""

import json
import uuid
from types import SimpleNamespace

import pytest

from marvin.services.ai import embeddings as emb
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext

WORDS = ("wax", "canvas", "coat", "denim", "seam", "leather")


def _fake_vector(text: str) -> list[float]:
    """A tiny bag of words, so 'wax canvas' is nearest to the entry about waxing canvas."""
    low = text.lower()
    return [float(low.count(w)) + 0.01 for w in WORDS]


@pytest.fixture
def builtin(monkeypatch):
    monkeypatch.setattr(emb, "builtin_embeddings_available", lambda: True)
    monkeypatch.setattr(emb.BuiltinEmbedder, "embed", lambda self, texts, model=None: [_fake_vector(t) for t in texts])


def test_every_provider_gets_the_built_in_model(builtin):
    openai_like = SimpleNamespace(provider_type="openai", supports_embeddings=True)
    for provider in (None, SimpleNamespace(provider_type="anthropic", supports_embeddings=False), openai_like):
        embedder, model = emb.embedder_for(provider)
        assert isinstance(embedder, emb.BuiltinEmbedder) and model == emb.BUILTIN_EMBEDDING_MODEL
    assert {emb.embedding_model_for_settings(p) for p in (None, "anthropic", "openai", "google")} == {emb.BUILTIN_EMBEDDING_MODEL}


def test_switched_off_it_falls_back_to_the_providers_own_model(monkeypatch):
    monkeypatch.setattr(emb, "builtin_embeddings_available", lambda: False)
    assert emb.embedder_for(SimpleNamespace(provider_type="anthropic", supports_embeddings=False)) == (None, None)
    provider = SimpleNamespace(provider_type="openai", supports_embeddings=True)
    assert emb.embedder_for(provider) == (provider, "text-embedding-3-small")


def test_search_content_finds_by_meaning_with_no_ai_provider(builtin, db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"emb-{gid.hex[:8]}", slug=f"emb-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    db_session.add(et)
    db_session.flush()
    rows = {}
    for title, body in (("Rewaxing", "wax the canvas coat twice a year, wax wax"), ("Seams", "denim seam work")):
        e = Entries(
            session=db_session,
            group_id=gid,
            entry_type_id=et.id,
            title=title,
            slug=f"{title.lower()}-{gid.hex[:6]}",
            status="published",
            data_json={"body": body},
        )
        db_session.add(e)
        db_session.flush()
        rows[title] = e
        emb.index_entity(db_session, gid, "entry", e.id, f"{title}\n{body}", emb.BuiltinEmbedder(), emb.BUILTIN_EMBEDDING_MODEL)
    # The old OpenAI index stays in the table until a re-index replaces it: same size here, so only the model name
    # keeps it out of a built-in search (it matches "wax canvas" better than anything, if it were let in).
    stale = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="Old", slug=f"old-{gid.hex[:6]}", status="published", data_json={})
    db_session.add(stale)
    db_session.flush()
    openai_like = SimpleNamespace(embed=lambda texts, model=None: [[50.0, 50.0, 1, 1, 1, 1] for _ in texts])
    emb.index_entity(db_session, gid, "entry", stale.id, "wax canvas", openai_like, "text-embedding-3-small")
    db_session.commit()
    try:
        out = json.loads(get_tool("search_content").handler(ToolContext(session=db_session, group_id=gid, provider=None), {"query": "wax canvas"}))
        assert "error" not in out, out
        assert out["results"][0]["entityId"] == str(rows["Rewaxing"].id)
        assert str(stale.id) not in {r["entityId"] for r in out["results"]}
        assert "get_entry" in out["note"]  # snippets only: the result says where the full text is
    finally:
        from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

        db_session.query(AIEmbeddingModel).filter_by(group_id=gid).delete()
        db_session.query(Entries).filter(Entries.group_id == gid).delete()
        db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
        db_session.query(Groups).filter(Groups.id == gid).delete()
        db_session.commit()
