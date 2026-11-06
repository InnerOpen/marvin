"""Recipes a workspace's online runners offer (services/automation/runner_recipes.py): one "run this on a worker" workflow per kind of
job a worker that has reported in recently can do, built from the contract it advertised, never from workflow text it sends."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.services.automation import recipes, runner_recipes
from marvin.services.automation.authoring import draft_issues
from tests.test_workflow_authoring import AD, gates, workspace, ws  # noqa: F401 — fixtures

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
TRANSCRIBE = {
    "kind": "transcribe",
    "description": "An audio or video asset to text.",
    "inputs": {
        "audio": {"type": "asset", "accepts": ["audio/*", "video/*"], "required": True, "description": "the recording"},
        "hotwords": {"type": "string", "required": False, "description": "names to listen for"},
        "language": {"type": "string", "required": False},
    },
    "produces": ["transcript"],
}


@pytest.fixture
def worker_type(ws):  # noqa: F811
    """A workspace set up for workers: the `worker` and `job` record types (returns the worker one)."""
    job_fields = [{"key": "kind", "label": "Kind", "type": "text"}, {"key": "args", "label": "Arguments", "type": "json"}]
    job_fields.append({"key": "status", "label": "Status", "type": "select", "options": ["queued", "claimed", "running", "done", "failed"]})
    schemas = {"worker": {}, "job": {"fields": job_fields}}
    rows = [EntryTypes(session=ws.session, group_id=ws.gid, name=n.title(), slug=n, schema_json=schemas[n]) for n in ("worker", "job")]
    ws.session.add_all(rows)
    ws.session.commit()
    yield rows[0]
    ws.session.rollback()
    for row in rows:
        ws.session.query(Entries).filter(Entries.entry_type_id == row.id).delete(synchronize_session=False)
        ws.session.query(EntryTypes).filter(EntryTypes.id == row.id).delete(synchronize_session=False)
    ws.session.commit()


def _worker(ws, worker_type, *, host="desktop-transcriber", kinds=(TRANSCRIBE,), seen=NOW, **more):  # noqa: F811
    data = {"host": host, "role": "runner", "kinds": list(kinds), **more}
    if seen is not None:
        data["last_seen"] = seen.isoformat()
    row = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=worker_type.id, title=host, slug=f"{host}-{uuid.uuid4().hex[:6]}", status="draft",
        data_json=data, metadata_json={},
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    return row


def test_a_kind_a_worker_that_is_online_can_do_becomes_a_recipe(ws, worker_type):  # noqa: F811
    _worker(ws, worker_type)
    built = runner_recipes.recipes(ws.session, ws.gid, NOW + timedelta(seconds=60))

    assert list(built) == ["runner.transcribe"]
    entry = built["runner.transcribe"]["entry"]
    assert entry["category"] == "Workers" and entry["trigger"]["type"] == "manual" and entry["setup_variables"] == []
    assert "An audio or video asset to text." in entry["outcome"] and "desktop-transcriber" in entry["outcome"] and "transcript" in entry["outcome"]
    assert entry["source"]["name"] == "desktop-transcriber"

    definition = built["runner.transcribe"]["document"]["definition"]
    inputs = {i["name"]: i for i in definition["trigger"]["inputs"]}
    assert inputs["audio"]["type"] == "asset" and inputs["audio"]["required"] is True and "audio/*" in inputs["audio"]["description"]
    assert inputs["hotwords"]["type"] == "text" and inputs["hotwords"]["required"] is False
    [step] = definition["actions"]
    assert (step["op"], step["entry_type"], step["status"]) == ("create", "job", "draft")
    assert step["data"] == {
        "kind": "transcribe",
        "args": {"audio": "${input.audio}", "hotwords": "${input.hotwords}", "language": "${input.language}"},
        "status": "queued",
    }


def test_the_recipe_is_a_valid_workflow_in_this_workspace(ws, worker_type):  # noqa: F811
    _worker(ws, worker_type)
    definition = runner_recipes.recipes(ws.session, ws.gid, NOW)["runner.transcribe"]["document"]["definition"]
    assert draft_issues(ws.session, ws.gid, definition) == []


def test_a_worker_gone_quiet_offers_nothing(ws, worker_type):  # noqa: F811
    _worker(ws, worker_type, seen=NOW - timedelta(minutes=10))
    _worker(ws, worker_type, host="never-reported", seen=None)
    assert runner_recipes.recipes(ws.session, ws.gid, NOW) == {}


def test_two_workers_offering_a_kind_share_one_recipe(ws, worker_type):  # noqa: F811
    _worker(ws, worker_type, host="desk")
    _worker(ws, worker_type, host="laptop")
    built = runner_recipes.recipes(ws.session, ws.gid, NOW)
    assert list(built) == ["runner.transcribe"] and built["runner.transcribe"]["entry"]["source"]["name"] in ("desk, laptop", "laptop, desk")


def test_what_a_worker_sends_is_only_ever_read_as_labels(ws, worker_type):  # noqa: F811
    nasty = {
        "kind": "transcribe",
        "description": "ok\n" + "x" * 500,
        "workflow": {"actions": [{"kind": "webhook"}]},  # a definition a worker slipped in: never read
        "inputs": {"audio": {"type": "asset", "required": True}, "Bad Name!": {"type": "string"}, "3rd": {"type": "string"}},
    }
    _worker(ws, worker_type, kinds=(nasty, {"kind": "Not A Slug"}, {"kind": "../etc"}, "junk"))
    built = runner_recipes.recipes(ws.session, ws.gid, NOW)

    assert list(built) == ["runner.transcribe"]  # a kind that is not a plain slug is ignored
    assert len(built["runner.transcribe"]["entry"]["outcome"]) < 400 and "\n" not in built["runner.transcribe"]["entry"]["outcome"]
    definition = built["runner.transcribe"]["document"]["definition"]
    assert [a["kind"] for a in definition["actions"]] == ["entry"]  # never the worker's
    names = [i["name"] for i in definition["trigger"]["inputs"]]
    assert names == ["audio", "bad_name"]  # "3rd" can't be a run input name
    assert definition["actions"][0]["data"]["args"] == {
        "audio": "${input.audio}",
        "Bad Name!": "${input.bad_name}",
    }  # the job still gets its own name


def test_a_contract_with_two_entry_inputs_is_not_offered(ws, worker_type):  # noqa: F811
    both = {"kind": "pair", "inputs": {"a": {"type": "entry"}, "b": {"type": "entry"}}}
    _worker(ws, worker_type, kinds=(both,))
    assert runner_recipes.recipes(ws.session, ws.gid, NOW) == {}


def test_configure_builds_it_for_this_workspace_and_refuses_when_nobody_is_online(ws, worker_type):  # noqa: F811
    worker = _worker(ws, worker_type, seen=datetime.now(UTC))
    document = recipes.configure_for(ws.session, ws.gid, "runner.transcribe", {})
    assert document["definition"]["actions"][0]["data"]["kind"] == "transcribe"

    worker.data_json = {**worker.data_json, "last_seen": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    ws.session.commit()
    with pytest.raises(recipes.RecipeUnavailable, match="online"):
        recipes.configure_for(ws.session, ws.gid, "runner.transcribe", {})
