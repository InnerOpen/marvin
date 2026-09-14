"""Live run progress registry (services/ai/run_progress.py): ownership, lifecycle, pruning."""

import uuid

import pytest

from marvin.services.ai import run_progress as rp


@pytest.fixture(autouse=True)
def _clean():
    rp._reset_for_tests()
    yield
    rp._reset_for_tests()


def test_normalize_run_id_accepts_uuids_only():
    rid = str(uuid.uuid4())
    assert rp.normalize_run_id(rid) == rid
    assert rp.normalize_run_id(f"  {rid.upper()} ") == rid
    for junk in (None, "", "not-a-uuid", "../x", 42):
        assert rp.normalize_run_id(junk) is None


def test_start_push_finish_round_trip_for_the_owner():
    rid = str(uuid.uuid4())
    owner = (uuid.uuid4(), uuid.uuid4())
    rp.start(rid, owner)
    rp.push(rid, {"type": "thinking"})
    rp.push(rid, {"type": "tool_call", "tool": "search_content", "arguments": {"query": "x"}})
    live = rp.get(rid, owner)
    assert live is not None and live.status == "running"
    assert [e["type"] for e in live.events] == ["thinking", "tool_call"]
    assert all("at" in e for e in live.events)

    rp.finish(rid, "completed")
    done = rp.get(rid, (str(owner[0]), str(owner[1])))  # string ids match uuid ids
    assert done is not None and done.status == "completed" and done.done
    assert done.to_dict()["events"][1]["tool"] == "search_content"


def test_get_hides_runs_from_other_users_and_unknown_ids():
    rid = str(uuid.uuid4())
    group = uuid.uuid4()
    rp.start(rid, (group, uuid.uuid4()))
    assert rp.get(rid, (group, uuid.uuid4())) is None
    assert rp.get(str(uuid.uuid4()), (group, uuid.uuid4())) is None


def test_push_and_finish_on_an_unknown_run_are_noops():
    rp.push("nope", {"type": "thinking"})
    rp.finish("nope", "completed")
    assert rp.get("nope", ("g", "u")) is None


def test_prune_drops_expired_finished_runs_and_caps_the_registry(monkeypatch):
    owner = ("g", "u")
    old = str(uuid.uuid4())
    rp.start(old, owner)
    rp.finish(old, "completed")
    # Age it past the TTL.
    with rp._LOCK:
        rp._RUNS[old].finished_at -= rp._FINISHED_TTL_SECONDS + 1
    assert rp.get(old, owner) is None

    monkeypatch.setattr(rp, "_MAX_RUNS", 3)
    ids = [str(uuid.uuid4()) for _ in range(5)]
    for rid in ids:
        rp.start(rid, owner)
        rp.finish(rid, "completed")
    rp.start(str(uuid.uuid4()), owner)  # a running one is never pruned
    live = [rid for rid in ids if rp.get(rid, owner) is not None]
    assert len(live) <= 3
    assert ids[-1] in live  # newest finished survive, oldest go
