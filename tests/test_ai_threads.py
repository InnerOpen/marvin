"""Ask threads (services/ai/threads.py): create/append/history bounding/own-only visibility/sources.

DB-backed through `db_session` with a hand-inserted workspace row, like test_asset_resource_tags.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.services.ai import threads as svc


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"thr-{marker}", slug=f"thr-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    yield SimpleNamespace(group_id=gid, alice=uuid.uuid4(), bob=uuid.uuid4())
    db_session.rollback()


def _step(tool: str, result, arguments=None):
    return SimpleNamespace(tool=tool, arguments=arguments or {}, result=result if isinstance(result, str) else json.dumps(result))


# ── Create + append ──────────────────────────────────────────────────────────


def test_create_thread_titles_it_from_the_first_message(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "  What is   in the workshop?  ")
    assert t.title == "What is in the workshop?"
    assert t.status == "open"
    assert t.created_by == workspace.alice
    assert t.pending_json is None

    long = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "x" * 500)
    assert len(long.title) == svc.TITLE_MAX_CHARS
    assert long.title.endswith("…")


def test_append_turn_numbers_turns_and_truncates_tool_results(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "hi")
    svc.append_turn(db_session, t, "user", "hi")
    big = "r" * (svc.STEP_RESULT_MAX_CHARS + 500)
    a = svc.append_turn(db_session, t, "assistant", "hello", steps=[_step("search_content", big, {"query": "hi"})], meta={"totalTokens": 12})
    assert [m.seq for m in t.messages] == [1, 2]
    assert a.steps_json[0]["tool"] == "search_content"
    assert a.steps_json[0]["arguments"] == {"query": "hi"}
    assert len(a.steps_json[0]["result"]) == svc.STEP_RESULT_MAX_CHARS
    assert a.meta_json == {"totalTokens": 12}


def test_append_turn_keeps_only_tool_names_when_outputs_are_not_logged(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "hi")
    a = svc.append_turn(db_session, t, "assistant", "hello", steps=[_step("get_entry", {"secret": 1}, {"id": "x"})], log_outputs=False)
    assert a.steps_json == [{"tool": "get_entry"}]


def test_touch_bumps_last_message_and_accumulates_tokens(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "hi")
    assert t.last_message_at is None
    svc.touch(t, 40)
    svc.touch(t, 2)
    assert t.total_tokens == 42
    assert t.last_message_at is not None


# ── History ──────────────────────────────────────────────────────────────────


def test_history_rows_returns_the_last_n_turns_oldest_first(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "q")
    for i in range(7):
        svc.append_turn(db_session, t, "user" if i % 2 == 0 else "assistant", f"turn {i}")
    rows = svc.history_rows(t, limit=4)
    assert [r.content for r in rows] == ["turn 3", "turn 4", "turn 5", "turn 6"]
    # Rows expose role/content — the shape the controller's _bounded_history reads via getattr.
    assert rows[0].role == "assistant"


# ── Visibility ───────────────────────────────────────────────────────────────


def test_resolve_thread_is_own_only_unless_see_all(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "mine")
    assert svc.resolve_thread(db_session, workspace.group_id, t.id, workspace.alice).id == t.id
    with pytest.raises(svc.ThreadNotFound):
        svc.resolve_thread(db_session, workspace.group_id, t.id, workspace.bob)
    assert svc.resolve_thread(db_session, workspace.group_id, str(t.id), workspace.bob, see_all=True).id == t.id


def test_resolve_thread_rejects_other_workspaces_bad_ids_and_agent_mismatch(db_session, workspace):
    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "mine")
    with pytest.raises(svc.ThreadNotFound):
        svc.resolve_thread(db_session, uuid.uuid4(), t.id, workspace.alice, see_all=True)
    with pytest.raises(svc.ThreadNotFound):
        svc.resolve_thread(db_session, workspace.group_id, "not-a-uuid", workspace.alice)
    with pytest.raises(svc.ThreadAgentMismatch):
        svc.resolve_thread(db_session, workspace.group_id, t.id, workspace.alice, agent_slug="marvin")
    assert svc.resolve_thread(db_session, workspace.group_id, t.id, workspace.alice, agent_slug="ask").id == t.id


def test_list_threads_filters_by_owner_and_agent_newest_first(db_session, workspace):
    a1 = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "a1")
    a2 = svc.create_thread(db_session, workspace.group_id, workspace.alice, "workshop", "a2")
    b1 = svc.create_thread(db_session, workspace.group_id, workspace.bob, "ask", "b1")
    svc.touch(a1, 0)
    svc.touch(b1, 0)
    svc.touch(a2, 0)
    db_session.flush()

    mine = svc.list_threads(db_session, workspace.group_id, workspace.alice)
    assert [t.id for t in mine] == [a2.id, a1.id]
    assert [t.id for t in svc.list_threads(db_session, workspace.group_id, workspace.alice, agent_slug="ask")] == [a1.id]
    everyone = svc.list_threads(db_session, workspace.group_id, workspace.bob, see_all=True)
    assert {t.id for t in everyone} >= {a1.id, a2.id, b1.id}


def test_deleting_a_thread_removes_its_messages(db_session, workspace):
    from marvin.db.models.groups.ai_threads import AIThreadMessageModel

    t = svc.create_thread(db_session, workspace.group_id, workspace.alice, "ask", "bye")
    svc.append_turn(db_session, t, "user", "bye")
    tid = t.id
    db_session.delete(t)
    db_session.flush()
    assert db_session.query(AIThreadMessageModel).filter_by(thread_id=tid).count() == 0


# ── Sources ──────────────────────────────────────────────────────────────────


def test_extract_sources_dedupes_search_hits_and_ignores_other_tools():
    hits = {
        "results": [
            {"title": "Bench", "entityType": "entry", "entityId": "e1"},
            {"title": "Bench again", "entityType": "entry", "entityId": "e1"},
            {"title": None, "entityType": "resource", "entityId": "r1"},
            {"title": "no id", "entityType": "entry"},
        ]
    }
    steps = [
        _step("get_entry", {"id": "zzz"}),
        _step("search_content", hits),
        _step("search_content", "not json"),
        _step("search_content", {"results": [{"title": "T", "entityType": "asset", "entityId": "a1"}]}),
    ]
    assert svc.extract_sources(steps) == [
        {"entityType": "entry", "entityId": "e1", "title": "Bench"},
        {"entityType": "resource", "entityId": "r1", "title": None},
        {"entityType": "asset", "entityId": "a1", "title": "T"},
    ]
    assert svc.extract_sources([]) == []
    assert svc.extract_sources(None) == []
