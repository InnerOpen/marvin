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


# ── Slice D: hand-off children ───────────────────────────────────────────────


def test_child_thread_for_finds_the_specialists_thread_per_parent_and_user(db_session, workspace):
    parent = svc.create_thread(db_session, workspace.group_id, workspace.alice, "marvin", "route me")
    assert svc.child_thread_for(db_session, parent, "materials", workspace.alice) is None
    child = svc.create_thread(db_session, workspace.group_id, workspace.alice, "materials", "stock?", parent_thread_id=parent.id)
    assert child.parent_thread_id == parent.id
    assert svc.child_thread_for(db_session, parent, "materials", workspace.alice).id == child.id
    assert svc.child_thread_for(db_session, parent, "ask", workspace.alice) is None  # another specialist
    assert svc.child_thread_for(db_session, parent, "materials", workspace.bob) is None  # another user
    other_parent = svc.create_thread(db_session, workspace.group_id, workspace.alice, "marvin", "again")
    assert svc.child_thread_for(db_session, other_parent, "materials", workspace.alice) is None


def test_list_threads_hides_children_unless_asked(db_session, workspace):
    parent = svc.create_thread(db_session, workspace.group_id, workspace.alice, "marvin", "route me")
    child = svc.create_thread(db_session, workspace.group_id, workspace.alice, "materials", "stock?", parent_thread_id=parent.id)
    top = svc.list_threads(db_session, workspace.group_id, workspace.alice)
    assert [t.id for t in top] == [parent.id]
    assert svc.list_threads(db_session, workspace.group_id, workspace.alice, agent_slug="materials") == []
    with_children = svc.list_threads(db_session, workspace.group_id, workspace.alice, include_children=True)
    assert {t.id for t in with_children} == {parent.id, child.id}
    by_agent = svc.list_threads(db_session, workspace.group_id, workspace.alice, agent_slug="materials", include_children=True)
    assert [t.id for t in by_agent] == [child.id]


def test_deleting_the_parent_orphans_the_child(db_session, workspace):
    from marvin.db.models.groups.ai_threads import AIThreadModel

    parent = svc.create_thread(db_session, workspace.group_id, workspace.alice, "marvin", "route me")
    child = svc.create_thread(db_session, workspace.group_id, workspace.alice, "materials", "stock?", parent_thread_id=parent.id)
    db_session.commit()
    db_session.delete(parent)
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(AIThreadModel, child.id)
    assert row is not None and row.parent_thread_id is None
    # the orphan is now a top-level thread of its own
    assert child.id in {t.id for t in svc.list_threads(db_session, workspace.group_id, workspace.alice)}


def test_extract_handoffs_reads_successful_run_agent_steps_and_passes_referrals_through():
    ok = _step(
        "run_agent",
        {"agent": "materials", "threadId": "t1", "executionId": "e1", "referrals": [{"agent": "ask", "question": "q"}, "junk", {"name": "no slug"}]},
    )
    err = _step("run_agent", {"error": "unknown agent 'ghost'", "agent": "ghost"})
    other = _step("search_content", {"results": []})
    broken = _step("run_agent", "not json")
    handoffs, referrals = svc.extract_handoffs([ok, err, other, broken])
    assert handoffs == [{"agent": "materials", "threadId": "t1", "executionId": "e1"}]
    assert referrals == [{"agent": "ask", "question": "q"}]
    assert svc.extract_handoffs([]) == ([], [])
