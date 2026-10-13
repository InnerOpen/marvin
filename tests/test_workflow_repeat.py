"""Repeat steps: a few inner steps once for each item of a list — each item as ${<as>.*}, its place as ${each.*}, the
inner steps reading each other's output for that item only. A create inside makes one entry per item, and the same
event handled twice makes none again. A failing item stops the repeat, or is noted and skipped (on_item_error:
continue); a run can't park mid-loop, so no wait, approval or repeat inside."""

# ruff: noqa: F811 — `ws` / `workspace` are fixtures, not redefinitions
import uuid

import pytest
from pydantic import ValidationError

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.schemas.group.automation_definition import AutomationDefinition
from marvin.services.automation.context import event_context
from marvin.services.automation.engine import run_automation_now, run_automations_for_event
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures


def _entry(ws, title, data=None, status="published"):
    from marvin.db.models.platform.entries import Entries

    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}", status=status, data_json=data or {}, metadata_json={},
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _workflow(ws, actions, trigger=None):
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Each", slug=f"each-{uuid.uuid4().hex[:6]}", enabled=True,
        definition={"trigger": trigger or {"type": "manual"}, "actions": actions},
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    return row


def _run(ws, row, **kwargs):
    return run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), **kwargs)


def _output(ws, row, index):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    ws.session.expire_all()
    run = ws.session.query(AutomationExecutionModel).filter_by(automation_id=row.id).order_by(AutomationExecutionModel.started_at.desc()).first()
    step = next(a for a in run.actions if a.action_index == index)
    return step.output_snapshot, step.error


def _meta(ws, entry) -> dict:
    ws.session.expire_all()
    return ws.session.get(type(entry), entry.id).metadata_json or {}


GATHER = {"kind": "collect", "id": "people", "entity": "entry", "query": {"text": "Maker", "status": "published"}}


def test_each_item_runs_the_inner_steps_with_its_own_values(ws):
    ada, grace = _entry(ws, "Maker Ada"), _entry(ws, "Maker Grace")
    row = _workflow(
        ws,
        [
            GATHER,
            {
                "kind": "repeat",
                "id": "credit",
                "for_each": "${steps.people.output.rows}",
                "as": "person",
                "steps": [
                    {
                        "kind": "entry",
                        "id": "mark",
                        "op": "set_metadata",
                        "entity_id": "${person.id}",
                        "metadata": {"place": "${each.number} of ${each.count}", "name": "${person.title}"},
                    },
                    {"kind": "entry", "op": "set_metadata", "entity_id": "${person.id}", "metadata": {"saw": "${steps.mark.output.op}"}},
                ],
            },  # fmt: skip
            {"kind": "entry", "op": "set_metadata", "entity_id": str(ada.id), "metadata": {"after": "${person.title}|${steps.mark.output.op}"}},
        ],
    )

    assert _run(ws, row)["ok"]

    places = {_meta(ws, e)["name"]: _meta(ws, e)["place"] for e in (ada, grace)}
    assert sorted(places.values()) == ["1 of 2", "2 of 2"] and set(places) == {"Maker Ada", "Maker Grace"}
    assert _meta(ws, grace)["saw"] == "set_metadata"  # an inner step reads the one before it, for the same item
    assert _meta(ws, ada)["after"] == "|"  # after the repeat: no item, no inner step outputs
    out, _ = _output(ws, row, 1)
    assert (out["count"], out["done"], out["failed"]) == (2, 2, 0) and set(out["results"][0]) == {"mark", "1"}


def test_a_create_inside_makes_one_entry_per_item_once(ws):
    from marvin.db.models.platform.entries import Entries

    for name in ("Maker Ada", "Maker Grace"):
        _entry(ws, name)
    repeat = {
        "kind": "repeat", "for_each": "${steps.people.output.rows}", "as": "person",
        "steps": [{"kind": "entry", "op": "create", "entry_type": ws.et["slug"], "title": "Thanks, ${person.title}", "status": "draft"}],
    }  # fmt: skip
    _workflow(ws, [GATHER, repeat], trigger={"type": "event", "event": "entry_published"})
    news = _entry(ws, "News")

    for _ in range(2):  # the same event (correlation) handled twice
        ctx = event_context("entry_published", {"entry_id": str(news.id)}, entity_id=news.id, entity_type="entry", correlation_id="corr-thanks")
        run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))

    ws.session.expire_all()
    titles = sorted(e.title for e in ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.title.like("Thanks,%")))
    assert titles == ["Thanks, Maker Ada", "Thanks, Maker Grace"]


@pytest.mark.parametrize(("mode", "ok", "done"), [("stop", False, 0), ("continue", True, 1)])
def test_a_failing_item_stops_the_repeat_or_is_skipped(ws, mode, ok, done):
    real = _entry(ws, "Real one")
    missing = str(uuid.uuid4())
    row = _workflow(
        ws,
        [
            {
                "kind": "repeat",
                "for_each": [missing, str(real.id)],
                "on_item_error": mode,
                "steps": [{"kind": "entry", "op": "set_metadata", "entity_id": "${item}", "metadata": {"touched": True}}],
            }  # fmt: skip
        ],
    )

    assert _run(ws, row)["ok"] is ok
    assert bool(_meta(ws, real).get("touched")) is (mode == "continue")
    out, error = _output(ws, row, 0)
    if ok:
        assert (out["done"], out["failed"], out["errors"][0]["index"]) == (done, 1, 0)
    else:
        assert error.startswith("item 1 of 2, step 0:")


def test_comma_text_nothing_and_the_limit(ws):
    row = _workflow(ws, [{"kind": "repeat", "for_each": "a, b ,c", "limit": 2, "steps": [{"kind": "fetch", "url": "https://example.com/${item}"}]}])
    assert _run(ws, row, dry_run=True)["ok"]
    empty = _workflow(ws, [{"kind": "repeat", "for_each": "${steps.none.output.rows}", "steps": [{"kind": "entry", "op": "publish"}]}])
    assert _run(ws, empty)["ok"]
    out, _ = _output(ws, empty, 0)
    assert out["count"] == 0


def test_a_dry_run_writes_nothing(ws):
    from marvin.db.models.platform.entries import Entries

    _entry(ws, "Maker Ada")
    repeat = {
        "kind": "repeat", "for_each": "${steps.people.output.rows}", "as": "person",
        "steps": [{"kind": "entry", "op": "create", "entry_type": ws.et["slug"], "title": "Dry ${person.title}", "status": "draft"}],
    }  # fmt: skip
    result = run_automation_now(ws.session, ws.gid, _workflow(ws, [GATHER, repeat]), user_id=ws.uid, dry_run=True)
    assert result["ok"]
    assert ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.title.like("Dry %")).count() == 0


@pytest.mark.parametrize(
    "repeat",
    [
        {"kind": "repeat", "for_each": "x", "steps": [{"kind": "wait", "for": "1d"}]},
        {"kind": "repeat", "for_each": "x", "steps": [{"kind": "approval", "message": "ok?"}]},
        {"kind": "repeat", "for_each": "x", "steps": [{"kind": "repeat", "for_each": "y", "steps": [{"kind": "entry", "op": "publish"}]}]},
        {"kind": "repeat", "for_each": "x", "as": "entry", "steps": [{"kind": "entry", "op": "publish"}]},
        {"kind": "repeat", "for_each": "x", "limit": 26, "steps": [{"kind": "entry", "op": "publish"}]},
        {"kind": "repeat", "for_each": "x", "steps": []},
    ],
    ids=["wait", "approval", "nested", "reserved-name", "over-limit", "no-steps"],
)
def test_what_a_repeat_cant_hold(repeat):
    with pytest.raises(ValidationError):
        AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": [repeat]})


def test_the_validator_checks_inner_steps(ws):
    from marvin.services.automation.authoring import draft_issues

    inner = {"kind": "integration", "integration": "no-such-integration", "action": "send"}
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [{"kind": "repeat", "for_each": "a,b", "steps": [inner]}]})
    assert any("no-such-integration" in i["message"] and ".steps[0]." in i.get("path", "") for i in issues), issues
