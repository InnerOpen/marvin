"""A citation of a recording opens it at the passage that matched (services/media_time.py).

Marvin Media writes a transcribed recording's timestamped transcript into the asset's description (``[0:01:05] words``, a line per
phrase), and the index chunks it, so a matched chunk carries the minutes it covers. An asset hit whose chunk holds markers says where
it starts (its first marker): Ask's ``retrieved_sources`` as ``start_seconds``, ``search_content`` and an agent run's ``sources`` as
``startSeconds``, and the MCP connector's ``search`` links to ``/workspace/assets/<id>/view?t=<seconds>``. Anything else is unchanged.
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from marvin.services.ai import embeddings as emb
from marvin.services.ai.entity_resolve import resolve_retrieved_sources
from marvin.services.ai.threads import extract_sources
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext
from marvin.services.media_time import asset_page_path, first_marker_seconds

# ── the marker ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("Speech in take 3, as text with where each part starts:\n[0:00:00] Hello.\n[0:01:05] More.", 0),
        ("ere each part starts:\n[0:01:05] More.\n[1:02:03] Late.", 65),
        ("half a line from the chunk before. [1:02:03] Late.", 3723),
        ("[12:00:00] long", 43200),
    ],
)
def test_the_first_marker_in_a_chunk_is_where_it_starts(text, seconds):
    assert first_marker_seconds(text) == seconds


@pytest.mark.parametrize("text", [None, "", "met at 1:05 for coffee", "[1:05] short", "[0:1:05] one digit", "[0:61:00] no such minute"])
def test_text_without_a_marker_has_no_start(text):
    assert first_marker_seconds(text) is None


def test_the_asset_page_opens_at_a_time_only_when_there_is_one():
    assert asset_page_path("a1", 65) == "/workspace/assets/a1/view?t=65"
    assert asset_page_path("a1", 0) == "/workspace/assets/a1/view?t=0"
    assert asset_page_path("a1") == "/workspace/assets/a1"


# ── Ask's retrieved_sources ──────────────────────────────────────────────────


class _NoRows:
    """A session whose title lookups find nothing (the titles fall back to the type and id)."""

    def query(self, *_a):
        return self

    def filter(self, *_a):
        return self

    def all(self):
        return []


def test_ask_sources_of_a_timestamped_asset_chunk_say_where_it_starts():
    asset, entry = str(uuid.uuid4()), str(uuid.uuid4())
    retrieved = [
        {"entity_type": "asset", "entity_id": asset, "text": "the middle of it.\n[0:10:00] Ten minutes in.\n[0:10:07] More.", "score": 0.9},
        {"entity_type": "asset", "entity_id": asset, "text": "A picture of a coat, no times here.", "score": 0.5},
        {"entity_type": "entry", "entity_id": entry, "text": "[0:00:05] an entry quoting a transcript", "score": 0.4},
    ]
    timed, plain, other = resolve_retrieved_sources(_NoRows(), retrieved)
    assert timed["start_seconds"] == 600 and timed["entity_id"] == asset and timed["index"] == 1
    assert "start_seconds" not in plain  # added, never renamed: a chunk without markers is the row it always was
    assert set(plain) == {"index", "entity_type", "entity_id", "title", "score"}
    assert "start_seconds" not in other  # only an asset has a recording to open


# ── search_content, an agent run's sources, the MCP connector ────────────────

WORDS = ("hello", "middle", "leather", "ending")


def _fake_vector(text: str) -> list[float]:
    low = text.lower()
    return [float(low.count(w)) + 0.01 for w in WORDS]


@pytest.fixture
def builtin(monkeypatch):
    monkeypatch.setattr(emb, "builtin_embeddings_available", lambda: True)
    monkeypatch.setattr(emb.BuiltinEmbedder, "embed", lambda self, texts, model=None: [_fake_vector(t) for t in texts])


def _transcript() -> str:
    """A recording's description as Marvin Media writes it: long enough to be chunked, the leather talk in the middle."""
    lines = ["Speech in Workshop talk, as text with where each part starts:"]
    for i in range(60):
        words = "we talk about leather and leather care" if 25 <= i < 32 else "hello and some other words about the day"
        lines.append(f"[0:{i // 2:02d}:{(i % 2) * 30:02d}] {words} number {i}.")
    return "\n".join(lines)


def test_search_content_and_the_agents_sources_open_a_recording_at_the_matched_passage(builtin, db_session):
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    g = Groups(session=db_session, name=f"seek-{gid.hex[:8]}", slug=f"seek-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    user = {"id": uid, "group_id": gid, "full_name": "O", "username": f"o-{gid.hex[:8]}", "email": f"o-{gid.hex[:8]}@x.test", "password": "x"}
    db_session.execute(sa.insert(Users.__table__).values(**user, auth_method="MARVIN", is_superuser=False, platform_role="NONE", admin=False))
    desc = _transcript()
    talk = Assets(session=db_session, group_id=gid, slug="talk", name="Workshop talk", original_filename="talk.m4a", filename="talk.m4a",
                  extension="m4a", file_size=1, mime_type="audio/mp4", asset_type="audio", checksum=uuid.uuid4().hex, storage_provider="local",
                  storage_key=f"lib/{gid.hex}/talk", uploaded_by=uid, description=desc)  # fmt: skip
    db_session.add(talk)
    db_session.flush()
    chunks = emb.index_entity(db_session, gid, "asset", talk.id, f"Workshop talk\n{desc}", emb.BuiltinEmbedder(), emb.BUILTIN_EMBEDDING_MODEL)
    assert chunks > 1  # the transcript really is cut, so the best chunk starts somewhere in the middle
    db_session.commit()
    try:
        out = json.loads(get_tool("search_content").handler(ToolContext(session=db_session, group_id=gid, provider=None), {"query": "leather"}))
        best = out["results"][0]
        stored = db_session.query(AIEmbeddingModel.chunk_text).filter_by(group_id=gid, entity_id=talk.id).all()
        best_chunk = max((c for (c,) in stored), key=lambda c: c.lower().count("leather"))
        assert best["entityType"] == "asset" and best["entityId"] == str(talk.id)
        assert best["startSeconds"] == first_marker_seconds(best_chunk) and best["startSeconds"] > 0
        assert all(isinstance(r.get("startSeconds"), int) for r in out["results"])  # every chunk of this one has markers

        # An agent run's citations come from its search_content results: one per entity, the best match's time.
        step = SimpleNamespace(tool="search_content", result=json.dumps(out))
        assert extract_sources([step]) == [
            {"entityType": "asset", "entityId": str(talk.id), "title": "Workshop talk", "startSeconds": best["startSeconds"]}
        ]
    finally:
        db_session.query(AIEmbeddingModel).filter_by(group_id=gid).delete()
        db_session.query(Assets).filter(Assets.group_id == gid).delete()
        db_session.query(Users).filter(Users.id == uid).delete()
        db_session.query(Groups).filter(Groups.id == gid).delete()
        db_session.commit()


def test_an_agents_sources_without_a_time_are_as_they_were():
    hits = {"results": [{"entityType": "asset", "entityId": "a1", "title": "Coat"}, {"entityType": "entry", "entityId": "e1", "title": "Note"}]}
    assert extract_sources([{"tool": "search_content", "result": hits}]) == [
        {"entityType": "asset", "entityId": "a1", "title": "Coat"},
        {"entityType": "entry", "entityId": "e1", "title": "Note"},
    ]


def test_the_mcp_connectors_search_links_a_recording_at_its_passage(monkeypatch):
    from marvin.services.mcp_remote import server

    hits = [
        {"entityType": "asset", "entityId": "a1", "title": "Workshop talk", "startSeconds": 600},
        {"entityType": "asset", "entityId": "a2", "title": "Coat photo"},
        {"entityType": "entry", "entityId": "e1", "title": "Note", "startSeconds": 5},
    ]
    monkeypatch.setattr(server, "call_tool_for", lambda _conn, name, _args: {"results": hits} if name == "search_content" else {})
    urls = [r["url"] for r in server.search_for(None, {"query": "leather"})["results"]]
    assert urls[0].endswith("/workspace/assets/a1/view?t=600")
    assert urls[1].endswith("/workspace/assets/a2")  # no time: the page it always linked to
    assert urls[2].endswith("/workspace/entries/e1")  # only an asset opens at a time
