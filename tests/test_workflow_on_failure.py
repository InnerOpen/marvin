"""A workflow's `on_failure` steps: run in the same run when a step fails, with the failure as `${error.*}`.

Built for a signup an integration refuses (Buttondown's firewall): the run still fails, but the entry
is sent to review with the reason instead of sitting silently in the inbox. Also the `request_review`
entry op those steps use.
"""

import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.services.automation import engine
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.entry import run_entry_action
from marvin.services.automation.authz import ROLE_ADMIN
from marvin.services.automation.matcher import interpolate
from marvin.services.automation.recorder import CollectingRecorder
from marvin.services.automation.validation import structural_issues, validate_definition
from tests.workflow_fakes import fake_workflow

SUBSCRIBE = {"kind": "integration", "id": "subscribe", "integration": "buttondown", "action": "subscribe"}
REMEMBER = {"kind": "entry", "op": "set_metadata", "metadata": {"subscriber": "${steps.subscribe.output.id}"}}
FLAG = {"kind": "entry", "op": "request_review", "reason": "Refused: ${error.message}"}
NOTE = {"kind": "entry", "op": "set_metadata", "metadata": {"error": {"code": "${error.code}", "step": "${error.step}"}}}


class _Query:
    def filter_by(self, **kw):
        return self

    def filter(self, *criteria):
        return self

    def all(self):
        return []

    def scalar(self):
        return None  # no Canonical URL


class _Session:
    def query(self, _model):
        return _Query()

    def get(self, _model, _id):
        return None

    def commit(self):
        pass

    def rollback(self):
        pass


class _Recorder:
    def __init__(self):
        self.actions, self.finished = [], []

    def start(self, *a, **k):
        return "EXEC"

    def action(self, exec_id, **kw):
        self.actions.append(kw)

    def finish(self, exec_id, **kw):
        self.finished.append(kw)


def _workflow(actions, on_failure=None):
    definition = {"trigger": {"type": "manual"}, "conditions": [], "actions": actions}
    if on_failure is not None:
        definition["on_failure"] = on_failure
    return fake_workflow(id=uuid.uuid4(), slug="subscribe-on-signup", name="Subscribe", enabled=True, group_id="G", definition=definition)


def _runner(*, fail: dict[str, AutomationActionError]):
    """Runs steps by recording them (resolved against the context); a step whose op/action is in
    `fail` raises that error."""
    calls: list[dict] = []

    def run(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False):
        calls.append({"action": action, "resolved": interpolate(action, context), "error": dict(context.get("error") or {})})
        key = action.get("action") or action.get("op")
        if key in fail:
            raise fail[key]
        return {"id": "sub_1"}

    run.calls = calls
    return run


def _run(workflow, runner, recorder=None):
    return engine.run_automation_now(_Session(), uuid.uuid4(), workflow, run_action=runner, recorder=recorder)


@fixture
def announced(monkeypatch):
    from marvin.services.event_bus_service import event_bus_service

    dispatched: list[dict] = []

    class _Bus:
        def __init__(self, *a, **kw):
            pass

        def dispatch(self, **kw):
            dispatched.append(kw)

    monkeypatch.setattr(event_bus_service, "EventBusService", _Bus)
    return dispatched


class TestOnFailureSteps:
    def test_failed_step_runs_on_failure_steps_with_the_error_in_context(self, announced):
        runner = _runner(fail={"subscribe": AutomationActionError("buttondown.subscribe failed: firewall", code="blocked")})

        _run(_workflow([SUBSCRIBE, REMEMBER], on_failure=[FLAG, NOTE]), runner)

        assert [c["action"] for c in runner.calls] == [SUBSCRIBE, FLAG, NOTE]  # REMEMBER never runs
        error = runner.calls[1]["error"]
        assert (error["message"], error["code"], error["step"], error["kind"]) == (
            "buttondown.subscribe failed: firewall",
            "blocked",
            "subscribe",
            "integration",
        )
        assert error["at"]

    def test_on_failure_step_templates_resolve_against_the_error(self, announced):
        runner = _runner(fail={"subscribe": AutomationActionError("firewall", code="blocked")})

        _run(_workflow([SUBSCRIBE], on_failure=[FLAG, NOTE]), runner)

        assert runner.calls[1]["resolved"]["reason"] == "Refused: firewall"
        assert runner.calls[2]["resolved"]["metadata"] == {"error": {"code": "blocked", "step": "subscribe"}}

    def test_error_step_is_the_position_when_the_step_has_no_id(self, announced):
        runner = _runner(fail={"set_metadata": AutomationActionError("nothing to set")})

        _run(_workflow([{"kind": "emit_event", "event": "x"}, REMEMBER], on_failure=[FLAG]), runner)

        assert runner.calls[-1]["error"]["step"] == "1" and runner.calls[-1]["error"]["code"] is None

    def test_successful_run_skips_on_failure_steps(self, announced):
        runner = _runner(fail={})

        result = _run(_workflow([SUBSCRIBE, REMEMBER], on_failure=[FLAG]), runner)

        assert result["ok"] is True
        assert [c["action"] for c in runner.calls] == [SUBSCRIBE, REMEMBER]

    def test_handled_run_is_still_recorded_failed_with_its_on_failure_steps(self, announced):
        recorder = _Recorder()
        runner = _runner(fail={"subscribe": AutomationActionError("firewall", code="blocked")})

        result = _run(_workflow([SUBSCRIBE, REMEMBER], on_failure=[FLAG, NOTE]), runner, recorder)

        assert result["ok"] is False
        assert [(a["action_index"], a["status"], a.get("on_failure", False)) for a in recorder.actions] == [
            (0, "failed", False),
            (2, "success", True),  # after the workflow's own two steps
            (3, "success", True),
        ]
        finished = recorder.finished[0]
        assert (finished["status"], finished["steps_ok"], finished["steps_failed"], finished["error"]) == ("failed", 0, 1, "firewall")

    def test_failing_on_failure_step_stops_the_rest_and_runs_nothing_again(self, announced):
        recorder = _Recorder()
        runner = _runner(
            fail={"subscribe": AutomationActionError("firewall"), "request_review": AutomationActionError("entry not found")},
        )

        result = _run(_workflow([SUBSCRIBE], on_failure=[FLAG, NOTE]), runner, recorder)

        assert result["ok"] is False
        assert [c["action"] for c in runner.calls] == [SUBSCRIBE, FLAG]  # once each; NOTE never runs
        assert [a["status"] for a in recorder.actions] == ["failed", "failed"]

    def test_failed_event_names_the_workflows_step_and_says_it_was_handled(self, announced):
        runner = _runner(fail={"subscribe": AutomationActionError("firewall", code="blocked")})

        _run(_workflow([SUBSCRIBE], on_failure=[FLAG]), runner)

        failed = announced[-1]
        assert failed["event_type"].name == "automation_failed"
        assert failed["document_data"].error == "firewall"
        assert failed["message"] == "Automation 'subscribe-on-signup' failed — integration 'buttondown.subscribe': firewall (on-failure steps ran)"
        assert [s.get("on_failure", False) for s in failed["document_data"].steps] == [False, True]

    def test_failed_event_says_when_an_on_failure_step_failed_too(self, announced):
        runner = _runner(fail={"subscribe": AutomationActionError("firewall"), "request_review": AutomationActionError("gone")})

        _run(_workflow([SUBSCRIBE], on_failure=[FLAG]), runner)

        assert announced[-1]["message"].endswith("integration 'buttondown.subscribe': firewall (an on-failure step failed too)")

    def test_dry_run_plan_labels_on_failure_steps(self, announced):
        recorder = CollectingRecorder()
        runner = _runner(fail={"subscribe": AutomationActionError("gate")})

        engine._run_targets(
            _Session(),
            "G",
            _workflow([SUBSCRIBE], on_failure=[FLAG]),
            {"event": {}, "previous": {}, "depth": 0},
            user_id=None,
            authorizer_role=ROLE_ADMIN,
            logger=None,
            run_action=runner,
            gate_conditions=False,
            recorder=recorder,
            dry_run=True,
        )

        assert [(p["label"], p["on_failure"]) for p in recorder.plan] == [("buttondown.subscribe", False), ("on failure: request_review", True)]


class TestOnFailureDefinition:
    def test_on_failure_steps_are_structurally_validated(self):
        definition = _workflow([SUBSCRIBE], on_failure=[FLAG, {"kind": "nope"}]).definition

        issues = structural_issues(definition)

        assert issues and all(i["where"] == "on_failure" for i in issues)

    def test_well_formed_on_failure_passes(self):
        assert structural_issues(_workflow([SUBSCRIBE], on_failure=[FLAG, NOTE]).definition) == []

    def test_on_failure_entry_step_without_an_entry_is_warned_about(self):
        issues = validate_definition(_workflow([SUBSCRIBE], on_failure=[FLAG]).definition)  # manual trigger: no entry

        assert any(i["where"] == "on_failure" and "request_review" in i["message"] for i in issues)


class TestRequestReviewOp:
    def _service(self, monkeypatch, saved: dict):
        import marvin.services.entries as entries_mod

        class _Svc:
            def __init__(self, *a, **k): ...

            def set_status(self, entry_id, status, *, reaction_depth=0):
                saved.update(set_status=(str(entry_id), status, reaction_depth))
                return object()

            def update(self, entry_id, data, *, reaction_depth=0):
                saved.update(update=data)
                return object()

        monkeypatch.setattr(entries_mod, "EntryService", _Svc)

    def test_without_a_reason_only_the_status_changes(self, monkeypatch):
        saved: dict = {}
        self._service(monkeypatch, saved)
        eid = uuid.uuid4()

        out = run_entry_action(None, "G", {"kind": "entry", "op": "request_review"}, {"event": {"entry_id": str(eid)}, "depth": 0})

        assert saved == {"set_status": (str(eid), "needs_review", 1)}
        assert out == {"entry_id": str(eid), "op": "request_review", "status": "needs_review", "reason": None}

    def test_dry_run_previews_the_resolved_reason(self, monkeypatch):
        out = run_entry_action(
            None,
            "G",
            FLAG,
            {"event": {"entry_id": str(uuid.uuid4())}, "error": {"message": "firewall"}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
            dry_run=True,
        )

        assert (out["would_set_status"], out["reason"]) == ("needs_review", "Refused: firewall")


@fixture
def signup(db_session):
    """A workspace with one signup entry waiting in the inbox, as a newsletter form leaves it."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"news-{marker}", slug=f"news-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Newsletter", slug="newsletter", schema_json={"fields": []})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(
        session=db_session,
        group_id=gid,
        entry_type_id=et.id,
        title="reader@example.com",
        slug=f"signup-{marker}",
        data_json={"email": "reader@example.com"},
        metadata_json={"submission": {"received_at": "2026-10-04T10:00:00+00:00"}},
        status="inbox",
    )
    db_session.add(entry)
    db_session.commit()
    yield SimpleNamespace(group_id=gid, entry_id=entry.id)

    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _request_review(db_session, signup, reason):
    return run_entry_action(
        db_session,
        signup.group_id,
        {"kind": "entry", "op": "request_review", "reason": reason},
        {"event": {"entry_id": str(signup.entry_id)}, "steps": {}, "depth": 0},
        authorizer_role=ROLE_ADMIN,
    )


def test_request_review_moves_the_entry_to_needs_review_with_its_reason(db_session, signup):
    from marvin.db.models.platform import Entries

    _request_review(db_session, signup, "Buttondown refused the signup")

    db_session.expire_all()
    entry = db_session.get(Entries, signup.entry_id)
    assert entry.status == "needs_review"
    assert entry.metadata_json["review_reasons"] == ["Buttondown refused the signup"]
    assert entry.metadata_json["submission"] == {"received_at": "2026-10-04T10:00:00+00:00"}  # the rest is kept


def test_request_review_lists_a_repeated_reason_once(db_session, signup):
    from marvin.db.models.platform import Entries

    _request_review(db_session, signup, "Buttondown refused the signup")
    _request_review(db_session, signup, "Buttondown refused the signup")
    _request_review(db_session, signup, "Another reason")

    db_session.expire_all()
    assert db_session.get(Entries, signup.entry_id).metadata_json["review_reasons"] == ["Buttondown refused the signup", "Another reason"]


def test_request_review_of_a_missing_entry_fails_the_step(db_session, signup):
    with pytest.raises(AutomationActionError, match="not found"):
        run_entry_action(
            db_session,
            signup.group_id,
            {"kind": "entry", "op": "request_review", "reason": "x"},
            {"event": {"entry_id": str(uuid.uuid4())}, "steps": {}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
        )
