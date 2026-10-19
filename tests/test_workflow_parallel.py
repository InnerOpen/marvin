"""Parallel steps: named branches of steps that run independently — one after another, in the order written, inside the
run — and join. A branch reads what ran before the step but not its siblings; the merge is by name in written order;
join all needs every branch, join any is satisfied by the first that succeeds (the rest are skipped); on_branch_failure
fail stops the step (and, under all, the branches after the failing one), continue reports and goes on. A run can't park
mid-branch, so no wait, approval, repeat or parallel inside; the branches' steps count against the workflow step limit."""

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


def _entry(ws, title, status="published"):
    from marvin.db.models.platform.entries import Entries

    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}", status=status, data_json={}, metadata_json={},
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _workflow(ws, actions, trigger=None):
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Side", slug=f"side-{uuid.uuid4().hex[:6]}", enabled=True,
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


def _mark(entity, **metadata):
    return {"kind": "entry", "op": "set_metadata", "entity_id": str(entity), "metadata": metadata}


def _fails():
    return {"kind": "entry", "op": "set_metadata", "entity_id": str(uuid.uuid4()), "metadata": {"x": 1}}  # no such entry


def _branch(name, *steps):
    return {"name": name, "steps": list(steps)}


def test_branches_merge_by_name_in_written_order_and_dont_see_each_other(ws):
    a, b, c = _entry(ws, "Branch a"), _entry(ws, "Branch b"), _entry(ws, "Branch c")
    row = _workflow(
        ws,
        [
            {"kind": "entry", "id": "before", "op": "set_metadata", "entity_id": str(a.id), "metadata": {"seeded": "yes"}},
            {
                "kind": "parallel",
                "id": "p",
                "branches": [
                    _branch(
                        "zeta",
                        {**_mark(a.id, saw_before="${steps.before.output.op}"), "id": "one"},
                        _mark(a.id, saw_own="${steps.one.output.op}"),
                    ),
                    _branch("alpha", _mark(b.id, saw_sibling="[${steps.one.output.op}]")),  # a sibling's step: not readable
                    _branch("mid", _mark(c.id, done=True)),
                ],
            },
            _mark(c.id, merged="${steps.p.output.branches.zeta.steps.one.op}|${steps.p.output.branches.alpha.output.op}|${steps.p.output.satisfied}"),
        ],
    )  # fmt: skip

    assert _run(ws, row)["ok"]

    assert _meta(ws, a)["saw_before"] == "set_metadata" and _meta(ws, a)["saw_own"] == "set_metadata"
    assert _meta(ws, b)["saw_sibling"] == "[]"
    out, _ = _output(ws, row, 1)
    assert out["order"] == ["zeta", "alpha", "mid"]  # written order, not alphabetical and not by finish
    assert (out["join"], out["count"], out["ok"], out["failed"], out["skipped"], out["satisfied"]) == ("all", 3, 3, 0, 0, True)
    assert {name: branch["status"] for name, branch in out["branches"].items()} == {"zeta": "ok", "alpha": "ok", "mid": "ok"}
    assert set(out["branches"]["zeta"]["steps"]) == {"one", "1"}
    assert _meta(ws, c)["merged"] == "set_metadata|set_metadata|True"


def test_a_failing_branch_stops_the_step_and_the_branches_after_it(ws):
    a, c = _entry(ws, "Branch a"), _entry(ws, "Branch c")
    row = _workflow(
        ws,
        [
            {
                "kind": "parallel",
                "branches": [_branch("first", _mark(a.id, ran=True)), _branch("broken", _fails()), _branch("last", _mark(c.id, ran=True))],
            }
        ],
    )

    assert _run(ws, row)["ok"] is False

    assert _meta(ws, a).get("ran") is True  # a branch that ran keeps what it did
    assert not _meta(ws, c).get("ran")  # the one after the failure never ran
    _, error = _output(ws, row, 0)
    assert error.startswith("branch “broken” failed, step 0:") and error.endswith("1 branch not run")


def test_continue_runs_every_branch_and_reports(ws):
    a, c = _entry(ws, "Branch a"), _entry(ws, "Branch c")
    row = _workflow(
        ws,
        [
            {
                "kind": "parallel",
                "id": "checks",
                "on_branch_failure": "continue",
                "branches": [_branch("first", _mark(a.id, ran=True)), _branch("broken", _fails()), _branch("last", _mark(c.id, ran=True))],
            },
            _mark(a.id, verdict="held back: ${steps.checks.output.text}", failed="${steps.checks.output.failed}"),
        ],
    )  # fmt: skip

    assert _run(ws, row)["ok"]  # the step reports instead of failing

    assert _meta(ws, a)["ran"] is True and _meta(ws, c)["ran"] is True  # the sibling after the failure still ran
    out, error = _output(ws, row, 0)
    assert error is None and (out["ok"], out["failed"], out["satisfied"]) == (2, 1, False)
    assert [(e["branch"], e["step"]) for e in out["errors"]] == [("broken", "0")]
    assert out["branches"]["broken"]["status"] == "failed" and out["branches"]["broken"]["error"]
    assert _meta(ws, a)["verdict"].startswith("held back: - broken: ") and _meta(ws, a)["failed"] == 1


def test_every_branch_failing_still_fails_under_fail_but_only_reports_under_continue(ws):
    for mode in ("fail", "continue"):
        row = _workflow(
            ws, [{"kind": "parallel", "join": "any", "on_branch_failure": mode, "branches": [_branch("x", _fails()), _branch("y", _fails())]}]
        )
        assert _run(ws, row)["ok"] is (mode == "continue")
        out, error = _output(ws, row, 0)
        if mode == "fail":
            assert error.startswith("every branch failed — the first, “x”, step 0:")
        else:
            assert (out["ok"], out["failed"], out["satisfied"], out["winner"]) == (0, 2, False, None)


def test_join_any_is_satisfied_by_the_first_branch_that_works(ws):
    a, b, c = _entry(ws, "Branch a"), _entry(ws, "Branch b"), _entry(ws, "Branch c")
    row = _workflow(
        ws,
        [
            {
                "kind": "parallel",
                "id": "p",
                "join": "any",
                "branches": [_branch("broken", _fails()), _branch("works", _mark(b.id, ran=True)), _branch("spare", _mark(c.id, ran=True))],
            }
        ],
    )  # fmt: skip

    assert _run(ws, row)["ok"]  # an earlier branch's failure doesn't matter once one succeeds

    assert _meta(ws, b).get("ran") is True and not _meta(ws, c).get("ran")  # the spare never ran
    out, _ = _output(ws, row, 0)
    assert (out["winner"], out["ok"], out["failed"], out["skipped"], out["satisfied"]) == ("works", 1, 1, 1, True)
    assert out["branches"]["spare"] == {"status": "skipped", "reason": "“works” already satisfied the join"}
    assert not _meta(ws, a).get("ran")


def test_a_dry_run_previews_every_branch_and_writes_nothing(ws):
    from marvin.db.models.platform.entries import Entries

    create = {"kind": "entry", "op": "create", "entry_type": ws.et["slug"], "status": "draft"}
    for join in ("all", "any"):
        row = _workflow(
            ws,
            [
                {
                    "kind": "parallel",
                    "id": "p",
                    "join": join,
                    "branches": [_branch("one", {**create, "title": "Dry one"}), _branch("two", {**create, "title": "Dry two"})],
                }
            ],
        )  # fmt: skip
        result = _run(ws, row, dry_run=True)
        assert result["ok"], result
        out = result["plan"][0]["resolved"]
        assert out["order"] == ["one", "two"]
        assert out["branches"]["one"]["steps"]["0"]["title"] == "Dry one"  # what it would make, shown
        if join == "all":
            assert out["branches"]["two"]["status"] == "ok"
        else:  # a real run would skip the second; the preview says so and still shows what it would do
            assert out["branches"]["two"]["status"] == "skipped" and out["branches"]["two"]["would_run"]["steps"]["0"]["title"] == "Dry two"
    assert ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.title.like("Dry %")).count() == 0


def test_a_create_inside_a_branch_makes_its_entry_once_per_event(ws):
    from marvin.db.models.platform.entries import Entries

    create = {"kind": "entry", "op": "create", "entry_type": ws.et["slug"], "status": "draft"}
    branches = [_branch("a", {**create, "title": "Made by a"}), _branch("b", {**create, "title": "Made by b"})]
    _workflow(ws, [{"kind": "parallel", "branches": branches}], trigger={"type": "event", "event": "entry_published"})
    news = _entry(ws, "News")
    for _ in range(2):  # the same event (correlation) handled twice
        ctx = event_context("entry_published", {"entry_id": str(news.id)}, entity_id=news.id, entity_type="entry", correlation_id="corr-branches")
        run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))

    ws.session.expire_all()
    titles = sorted(e.title for e in ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.title.like("Made by %")))
    assert titles == ["Made by a", "Made by b"]


def test_the_branches_steps_count_against_the_workflow_step_limit(ws, monkeypatch):
    from marvin.services.automation import engine

    monkeypatch.setattr(engine, "workflow_max_steps", lambda session, gid: 3)
    row = _workflow(ws, [{"kind": "parallel", "branches": [_branch("a", _fails(), _fails()), _branch("b", _fails(), _fails())]}])
    assert _run(ws, row)["ok"] is False
    _, error = _output(ws, row, 0)
    assert "hold 4 steps, over this workspace's limit of 3" in error

    from marvin.services.automation.validation import validate_definition

    warnings = validate_definition(row.definition, max_steps=3)
    assert any("branches hold 4 steps" in w["message"] for w in warnings)


def _definition(step):
    return {"trigger": {"type": "manual"}, "actions": [step]}


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"kind": "parallel", "branches": [_branch("a", {"kind": "wait", "for": "1d"}), _branch("b", _fails())]}, "can't hold a wait step"),
        (
            {"kind": "parallel", "branches": [_branch("a", {"kind": "approval", "message": "ok?"}), _branch("b", _fails())]},
            "can't hold a approval step",
        ),
        (
            {"kind": "parallel", "branches": [_branch("a", {"kind": "repeat", "for_each": "x", "steps": [_fails()]}), _branch("b", _fails())]},
            "can't hold a repeat step",
        ),
        (
            {
                "kind": "parallel",
                "branches": [
                    _branch("a", {"kind": "parallel", "branches": [_branch("x", _fails()), _branch("y", _fails())]}),
                    _branch("b", _fails()),
                ],
            },
            "can't hold a parallel step",
        ),
        ({"kind": "parallel", "branches": [_branch("a", _fails())]}, "at least 2 items"),
        ({"kind": "parallel", "branches": [_branch(n, _fails()) for n in "abcdef"]}, "at most 5 items"),
        ({"kind": "parallel", "branches": [_branch("a", _fails()), _branch("a", _fails())]}, "each branch needs its own name"),
        ({"kind": "parallel", "branches": [_branch("a", _fails()), _branch("Not Ok", _fails())]}, "String should match pattern"),
        ({"kind": "parallel", "branches": [_branch("a", _fails()), _branch("b")]}, "at least 1 item"),
        ({"kind": "parallel", "branches": [_branch("a", *[_fails()] * 6), _branch("b", _fails())]}, "at most 5 items"),
        ({"kind": "parallel", "join": "most", "branches": [_branch("a", _fails()), _branch("b", _fails())]}, "'all' or 'any'"),
    ],
    ids=["wait", "approval", "repeat", "nested", "one-branch", "six-branches", "same-name", "bad-name", "empty-branch", "six-steps", "bad-join"],
)
def test_what_a_parallel_step_refuses(step, message):
    from marvin.services.automation.validation import structural_issues

    with pytest.raises(ValidationError):
        AutomationDefinition.model_validate(_definition(step))
    assert any(message in issue["message"] for issue in structural_issues(_definition(step))), structural_issues(_definition(step))


def test_the_executor_refuses_what_the_model_would_when_a_definition_skipped_it(ws):
    row = _workflow(ws, [{"kind": "parallel", "branches": [_branch("a", {"kind": "wait", "for": "1d"}), _branch("b", _fails())]}])
    assert _run(ws, row)["ok"] is False
    _, error = _output(ws, row, 0)
    assert "branch “a” can't hold a wait step" in error


def test_the_validator_checks_inner_steps(ws):
    from marvin.services.automation.authoring import draft_issues

    inner = {"kind": "integration", "integration": "no-such-integration", "action": "send"}
    step = {"kind": "parallel", "branches": [_branch("a", _fails()), _branch("b", inner)]}
    issues = draft_issues(ws.session, ws.gid, _definition(step))
    assert any("no-such-integration" in i["message"] and ".branches[1].steps[0]." in i.get("path", "") for i in issues), issues
