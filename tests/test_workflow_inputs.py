"""Run inputs: a manual workflow asks for what it needs when someone runs it — the Run button's form, the API's body,
the agent's run_workflow `inputs` — read as ${input.<name>}. An entry input is the entry the run acts on. What doesn't
fit the declarations is refused with a message saying which; a dry run fills what's missing with a stand-in."""

# ruff: noqa: F811 — `ws` / `workspace` are fixtures, not redefinitions
import uuid

import pytest

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.services.automation.engine import run_automation_now
from marvin.services.automation.inputs import RunInputError, resolve
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_workflow_authoring import AD, _tool, gates, workspace, ws  # noqa: F401 — fixtures

INPUTS = [
    {"name": "piece", "label": "Which piece", "type": "entry"},
    {"name": "style", "type": "choice", "options": ["haiku", "limerick"], "default": "haiku"},
    {"name": "lines", "type": "number", "required": False},
    {"name": "note", "type": "text", "required": False},
]
REMIX = {
    "trigger": {"type": "manual", "inputs": INPUTS},
    "actions": [{"kind": "entry", "op": "set_metadata", "metadata": {"remix": "${input.style}", "lines": "${input.lines}", "of": "${entry.title}"}}],
}


def _entry(ws, title="Brass lantern"):
    from marvin.db.models.platform.entries import Entries

    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}", status="draft", data_json={}, metadata_json={},
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _workflow(ws, definition=REMIX, enabled=True):
    row = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Remix", slug="remix", enabled=enabled, definition=definition)
    ws.session.add(row)
    ws.session.commit()
    return row


def _metadata(ws, entry) -> dict:
    ws.session.expire_all()
    return ws.session.get(type(entry), entry.id).metadata_json or {}


def test_a_run_reads_its_inputs_and_acts_on_the_entry_it_was_given(ws):
    lantern = _entry(ws)
    row = _workflow(ws)

    result = run_automation_now(
        ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), inputs={"piece": lantern.slug, "lines": "3"}
    )

    assert result["ok"]
    assert _metadata(ws, lantern) == {"remix": "haiku", "lines": 3, "of": "Brass lantern"}  # the default; a number; the entry


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({}, "“Which piece” is needed"),
        ({"piece": "no-such-entry"}, "no entry 'no-such-entry'"),
        ({"piece": "x", "colour": "red"}, "has no input colour"),
        ({"piece": "x", "style": "sonnet"}, "one of haiku, limerick"),
        ({"piece": "x", "lines": "many"}, "is a number"),
    ],
)
def test_what_doesnt_fit_is_refused_with_why(ws, given, message):
    lantern = _entry(ws)
    given = {k: (lantern.slug if v == "x" else v) for k, v in given.items()}
    with pytest.raises(RunInputError, match=message):
        resolve(ws.session, ws.gid, _workflow(ws), given)


def test_a_dry_run_fills_a_missing_input_with_a_stand_in(ws):
    row = _workflow(
        ws, {"trigger": {"type": "manual", "inputs": [{"name": "topic"}]}, "actions": [{"kind": "collect", "query": {"text": "${input.topic}"}}]}
    )
    result = run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, dry_run=True)
    assert result["ok"] and resolve(ws.session, ws.gid, row, {}, dry_run=True)[0] == {"topic": "‹topic›"}


def test_the_run_route_takes_inputs_in_its_body(ws):
    lantern = _entry(ws)
    row = _workflow(ws)
    client = gates._sign_in(ws.workspace, AD)

    missing = client.post(f"/api/automations/{row.id}/run", json={})
    assert missing.status_code == 400 and "Which piece" in missing.json()["detail"]
    ran = client.post(f"/api/automations/{row.id}/run", json={"inputs": {"piece": str(lantern.id), "style": "limerick"}})
    assert ran.status_code == 200 and ran.json()["ok"]
    assert _metadata(ws, lantern)["remix"] == "limerick"


def test_the_agent_sees_a_workflows_inputs_and_passes_them(ws):
    lantern = _entry(ws)
    _workflow(ws)

    listed = _tool(ws, "list_workflows", {})["workflows"]
    assert [i["name"] for i in listed[0]["inputs"]] == ["piece", "style", "lines", "note"]
    refused = _tool(ws, "run_workflow", {"workflow": "remix"})
    assert "is needed" in refused["error"] and refused["inputs"][0]["type"] == "entry"
    ran = _tool(ws, "run_workflow", {"workflow": "remix", "inputs": {"piece": lantern.slug}})
    assert ran["ok"] and _metadata(ws, lantern)["remix"] == "haiku"


def test_the_validator_reads_inputs(ws):
    from marvin.services.automation.authoring import draft_issues

    assert draft_issues(ws.session, ws.gid, REMIX) == []  # ${input.*}, ${entry.*} and an entry step are fine here
    no_options = {"trigger": {"type": "manual", "inputs": [{"name": "style", "type": "choice"}]}, "actions": REMIX["actions"]}
    assert any(i.get("path") == "trigger.inputs[0]" for i in draft_issues(ws.session, ws.gid, no_options))
    two_entries = {
        "trigger": {"type": "manual", "inputs": [{"name": "a", "type": "entry"}, {"name": "b", "type": "entry"}]},
        "actions": REMIX["actions"],
    }
    assert draft_issues(ws.session, ws.gid, two_entries)
