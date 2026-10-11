"""Conditional steps (`when`): a step runs only if its conditions hold at that point of the run — reading earlier steps'
output — and is recorded as skipped (not failed) otherwise, so two steps with opposite `when`s are an if/else.

The case: a classification step says whether a form submission is spam; one branch files it, the other answers it."""

from types import SimpleNamespace

from marvin.schemas.group.automation_definition import AutomationDefinition
from marvin.services.automation.engine import _run_pipeline
from marvin.services.automation.recorder import CollectingRecorder
from marvin.services.automation.validation import validate_definition, when_issues

IS_SPAM = {"field": "steps.classify.output.is_spam", "op": "eq", "value": True}
STEPS = [
    {"kind": "emit_event", "id": "classify", "event": "classify"},
    {"kind": "emit_event", "id": "file", "event": "file_as_spam", "when": IS_SPAM},
    {"kind": "emit_event", "id": "answer", "event": "send_answer", "when": {"not": IS_SPAM}},
    {"kind": "emit_event", "event": "log", "data": {"filed": "${steps.file.output.ok}", "answered": "${steps.answer.output.ok}"}},
]


def _run(is_spam: bool, steps=STEPS, *, fail: str | None = None):
    ran: list[tuple[str, dict]] = []

    def run_action(session, group_id, action, context, **_):
        from marvin.services.automation.actions import AutomationActionError
        from marvin.services.automation.matcher import interpolate

        if action["event"] == fail:
            raise AutomationActionError(f"{fail} broke")
        ran.append((action["event"], interpolate(action.get("data") or {}, context)))
        return {"is_spam": is_spam} if action["event"] == "classify" else {"ok": True}

    recorder = CollectingRecorder()
    automation = SimpleNamespace(slug="triage", definition={"actions": steps})
    result = _run_pipeline(
        None, None, automation, {"event": {}}, user_id=None, authorizer_role=None, logger=None, run_action=run_action, recorder=recorder, exec_id="x"
    )
    return result, ran, recorder.plan


def test_only_the_branch_whose_when_holds_runs_and_the_other_is_skipped_not_failed():
    (ok, steps_ok, failed), ran, plan = _run(is_spam=True)

    assert [event for event, _ in ran] == ["classify", "file_as_spam", "log"]
    assert (ok, failed) == (True, 0)
    assert [p["status"] for p in plan] == ["success", "success", "skipped", "success"]
    skipped = plan[2]["resolved"]
    assert skipped["skipped"] is True and skipped["when"][0]["pass"] is False  # the verdict says why


def test_the_other_input_takes_the_else_branch_and_a_skipped_steps_output_reads_as_nothing():
    _, ran, plan = _run(is_spam=False)

    assert [event for event, _ in ran] == ["classify", "send_answer", "log"]
    assert ran[-1][1] == {"filed": None, "answered": True}  # the skipped step left no output: None
    assert [p["status"] for p in plan] == ["success", "skipped", "success", "success"]


def test_a_failing_step_on_the_taken_branch_still_fails_the_run():
    (ok, _, failed), ran, plan = _run(is_spam=True, fail="file_as_spam")

    assert (ok, failed) == (False, 1) and [p["status"] for p in plan] == ["success", "failed"]


def test_when_takes_a_list_or_a_group_and_the_definition_model_keeps_it():
    definition = AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": STEPS})
    assert definition.actions[1].when.field == IS_SPAM["field"]
    assert definition.actions[2].when.not_.field == IS_SPAM["field"]


def test_a_when_that_reads_a_step_not_yet_run_is_flagged():
    steps = [
        {"kind": "emit_event", "event": "a", "when": {"field": "previous.ok", "op": "exists"}},
        {"kind": "emit_event", "event": "b", "when": {"field": "steps.later.output.ok", "op": "exists"}},
        {"kind": "emit_event", "id": "later", "event": "c", "when": {"field": "steps.0.output.ok", "op": "exists"}},
    ]
    on_failure = [{"kind": "emit_event", "event": "d", "when": {"field": "steps.later.output.ok", "op": "exists"}}]
    issues = when_issues({"actions": steps, "on_failure": on_failure})

    assert [(i["where"], i["index"]) for i in issues] == [("actions", 0), ("actions", 1)]  # on_failure may read any main step
    assert "steps.later" in issues[1]["message"]
    assert any("steps.later" in i["message"] for i in validate_definition({"trigger": {"type": "manual"}, "actions": steps}))
