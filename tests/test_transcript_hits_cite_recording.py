"""Ask cites the RECORDING, not the transcript files made from it (search_content, get_asset, an agent run's sources).

Transcription workers keep what they heard as files of their own (``metadata_json.kind == "transcript"``) that name the recording in
``source`` (its id, or its slug in older files) or ``derived_from``. Two runs made several such files of one recording, named alike;
they filled every search slot while the recording never made the cut, and Ask pasted a file's storage URL. Now search_content asks
the index for more than it shows and folds near-duplicates away (same title, same snippet, or the same recording cited), and a
transcript file's hit and record name the recording (``recordingAssetId``, ``recordingAssetUrl``, ``recordingTitle``, ``note``),
opened at the passage when the matched text is timestamped. With nothing to fold, the results are what they always were.
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from marvin.services.ai import embeddings as emb
from marvin.services.ai.threads import extract_sources
from marvin.services.ai.tools import builtins, get_tool
from marvin.services.ai.tools.base import ToolContext

WORDS = ("hello", "middle", "leather", "ending")
TODAYS_HIT_KEYS = {"title", "entityType", "entityId", "snippet", "score", "assets"}
RECORDING_KEYS = {"recordingAssetId", "recordingAssetUrl", "recordingTitle", "note"}


def _fake_vector(text: str) -> list[float]:
    low = text.lower()
    return [float(low.count(w)) + 0.01 for w in WORDS]


@pytest.fixture
def builtin(monkeypatch):
    monkeypatch.setattr(emb, "builtin_embeddings_available", lambda: True)
    monkeypatch.setattr(emb.BuiltinEmbedder, "embed", lambda self, texts, model=None: [_fake_vector(t) for t in texts])


@pytest.fixture
def top_k(monkeypatch):
    from marvin.core.config import get_app_settings

    def set_to(n: int):
        monkeypatch.setattr(get_app_settings(), "AI_RAG_TOP_K", n)

    return set_to


@pytest.fixture
def workspace(db_session):
    """A group and its owner; ``add(slug, name, description, meta=None, index=True)`` adds an asset (indexed as asset_updated does)."""
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.users import Users
    from marvin.services.ai.embeddings_registry import index_descriptor_for
    from marvin.services.event_bus_service.event_types import EventTypes

    gid, uid = uuid.uuid4(), uuid.uuid4()
    g = Groups(session=db_session, name=f"hits-{gid.hex[:8]}", slug=f"hits-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    user = {"id": uid, "group_id": gid, "full_name": "O", "username": f"o-{gid.hex[:8]}", "email": f"o-{gid.hex[:8]}@x.test", "password": "x"}
    db_session.execute(sa.insert(Users.__table__).values(**user, auth_method="MARVIN", is_superuser=False, platform_role="NONE", admin=False))
    describe = index_descriptor_for(EventTypes.asset_updated)

    def add(slug, name, description, meta=None, index=True, asset_type="document"):
        a = Assets(session=db_session, group_id=gid, slug=slug, name=name, original_filename=f"{slug}.txt", filename=f"{slug}.txt",
                   extension="txt", file_size=1, mime_type="text/plain", asset_type=asset_type, checksum=uuid.uuid4().hex,
                   storage_provider="local", storage_key=f"lib/{gid.hex}/{slug}", uploaded_by=uid, description=description,
                   metadata_json=meta)  # fmt: skip
        db_session.add(a)
        db_session.flush()
        if index:
            emb.index_entity(db_session, gid, "asset", a.id, describe.text(a), emb.BuiltinEmbedder(), emb.BUILTIN_EMBEDDING_MODEL)
        return a

    ws = SimpleNamespace(gid=gid, add=add, ctx=ToolContext(session=db_session, group_id=gid, provider=None))
    yield ws
    db_session.rollback()
    db_session.query(AIEmbeddingModel).filter_by(group_id=gid).delete()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _transcript() -> str:
    """A recording's description as Marvin Media writes it: long enough to be chunked, the leather talk in the middle."""
    lines = ["Speech in Workshop talk, as text with where each part starts:"]
    for i in range(60):
        words = "we talk about leather and leather care" if 25 <= i < 32 else "hello and some other words about the day"
        lines.append(f"[0:{i // 2:02d}:{(i % 2) * 30:02d}] {words} number {i}.")
    return "\n".join(lines)


def _search(ws, query="leather") -> dict:
    return json.loads(get_tool("search_content").handler(ws.ctx, {"query": query}))


def _get_asset(ws, ident) -> dict:
    return json.loads(get_tool("get_asset").handler(ws.ctx, {"id_or_slug": ident}))


def test_transcript_files_fold_into_one_hit_that_cites_the_recording_at_its_passage(builtin, top_k, workspace, db_session):
    ws = workspace
    top_k(4)
    talk = ws.add("workshop-talk", "Workshop talk", _transcript(), meta={"recording": {"source": "browser"}}, asset_type="audio")
    by_id = ws.add("talk-times", "Transcript with times: Workshop talk", "[0:12:30] we talk about leather and leather care.",
                   meta={"kind": "transcript", "source": str(talk.id), "language": "en"})  # fmt: skip
    by_slug = ws.add("talk-text", "Transcript: Workshop talk", "Speech in Workshop talk, as text (faster-whisper). hello leather",
                     meta={"kind": "transcript", "source": "workshop-talk", "language": "en", "seconds": 9.5})  # fmt: skip
    lost = ws.add("talk-json", "Transcript (json)", "leather leather hello as json", meta={"kind": "transcript", "source": "no-such-recording"})
    price_a = ws.add("price-a", "Price list", "leather prices for the middle of the year")
    price_b = ws.add("price-b", "price LIST", "leather costs in the middle, hello")
    db_session.commit()

    out = _search(ws)
    hits = out["results"]
    assert out["count"] == len(hits) <= 4
    # The best hit is the timestamped transcript file: it stays, and names the recording, opened at its passage.
    best = hits[0]
    assert best["entityId"] == str(by_id.id) and best["startSeconds"] == 750
    assert best["recordingAssetId"] == str(talk.id)
    assert best["recordingAssetUrl"] == f"/workspace/assets/{talk.id}/view?t=750"
    assert best["recordingTitle"] == "Workshop talk" and "Workshop talk" in best["note"] and "cite the recording" in best["note"]
    # Everything else citing that recording (its own chunks, the slug-named file) was folded into it.
    citing = [h for h in hits if h["entityId"] == str(talk.id) or h.get("recordingAssetId") == str(talk.id)]
    assert citing == [best]
    assert str(by_slug.id) not in {h["entityId"] for h in hits}
    # Two different assets with one title (ignoring case): only the better one.
    assert len([h for h in hits if h["entityId"] in (str(price_a.id), str(price_b.id))]) == 1
    # A transcript file whose source names nothing here is the hit it always was.
    (orphan,) = [h for h in hits if h["entityId"] == str(lost.id)]
    assert set(orphan) == TODAYS_HIT_KEYS

    # The agent's citations: the recording (its name, the passage's time), once.
    step = SimpleNamespace(tool="search_content", result=json.dumps(out))
    sources = extract_sources([step])
    assert sources[0] == {"entityType": "asset", "entityId": str(talk.id), "title": "Workshop talk", "startSeconds": 750}
    assert [s["entityId"] for s in sources].count(str(talk.id)) == 1


def test_get_asset_of_a_transcript_file_names_its_recording(workspace, db_session):
    ws = workspace
    talk = ws.add("workshop-talk", "Workshop talk", "[0:00:00] hello", asset_type="audio", index=False)
    by_id = ws.add("t-id", "Transcript", "x", meta={"kind": "transcript", "source": str(talk.id)}, index=False)
    by_slug = ws.add("t-slug", "Transcript", "x", meta={"kind": "transcript", "source": "workshop-talk"}, index=False)
    by_derived = ws.add("t-media", "Transcript", "x", meta={"kind": "transcript", "source": "rec-slug-of-a-recording", "derived_from": str(talk.id)},
                        index=False)  # fmt: skip
    lost = ws.add("t-lost", "Transcript", "x", meta={"kind": "transcript", "source": "gone"}, index=False)
    itself = ws.add("t-self", "Transcript", "x", meta={"kind": "transcript", "source": "t-self"}, index=False)
    db_session.commit()

    for f in (by_id, by_slug, by_derived):
        rec = _get_asset(ws, f.slug)
        assert rec["id"] == str(f.id) and rec["metadataJson"]["kind"] == "transcript"  # the record it always was, plus:
        assert {k: rec[k] for k in ("recordingAssetId", "recordingAssetUrl", "recordingTitle")} == {
            "recordingAssetId": str(talk.id),
            "recordingAssetUrl": f"/workspace/assets/{talk.id}",
            "recordingTitle": "Workshop talk",
        }
        assert "cite the recording" in rec["note"]
    for f in (lost, itself, talk):  # nothing to name: today's record, no error
        rec = _get_asset(ws, str(f.id))
        assert rec["id"] == str(f.id) and not RECORDING_KEYS & set(rec)


def test_with_nothing_to_fold_the_results_are_byte_identical(builtin, top_k, workspace, db_session, monkeypatch):
    ws = workspace
    top_k(3)
    for i, words in enumerate(["leather", "leather hello", "leather middle", "leather ending", "hello middle", "middle ending", "ending"]):
        ws.add(f"note-{i}", f"Note {i}", f"{words} number {i}")
    db_session.commit()

    now = get_tool("search_content").handler(ws.ctx, {"query": "leather"})
    monkeypatch.setattr(builtins, "SEARCH_OVERFETCH", 1)  # what search_content asked the index for before: exactly top_k
    before = get_tool("search_content").handler(ws.ctx, {"query": "leather"})
    assert now == before
    assert json.loads(now)["count"] == 3


def test_near_duplicate_snippets_of_different_entities_fold_and_passages_of_one_stay():
    hits = [
        {"title": "A", "entityType": "asset", "entityId": "a", "snippet": "We talk about leather!"},
        {"title": "A", "entityType": "asset", "entityId": "a", "snippet": "a second passage of A"},
        {"title": "B", "entityType": "asset", "entityId": "b", "snippet": "we talk  about LEATHER"},
        {"title": "C", "entityType": "entry", "entityId": "c", "snippet": "something else"},
        {"title": "D", "entityType": "entry", "entityId": "d", "snippet": "and more"},
    ]
    assert [h["entityId"] for h in builtins._collapse_near_duplicates(hits, 3)] == ["a", "a", "c"]
    assert builtins._collapse_near_duplicates(hits[3:], 5) == hits[3:]


def test_the_mcp_connectors_search_links_the_recording_of_a_transcript_file(monkeypatch):
    from marvin.services.mcp_remote import server

    hits = [
        {
            "entityType": "asset",
            "entityId": "f1",
            "title": "Transcript: talk",
            "startSeconds": 750,
            "recordingAssetId": "r1",
            "recordingTitle": "Talk",
        },
        {"entityType": "asset", "entityId": "r1", "title": "Talk", "startSeconds": 5},
        {"entityType": "asset", "entityId": "f2", "title": "Transcript (json)"},
    ]
    monkeypatch.setattr(server, "call_tool_for", lambda _conn, name, _args: {"results": hits} if name == "search_content" else {})
    results = server.search_for(None, {"query": "leather"})["results"]
    assert [(r["id"], r["title"]) for r in results] == [("asset:r1", "Talk"), ("asset:f2", "Transcript (json)")]
    assert results[0]["url"].endswith("/workspace/assets/r1/view?t=750")
