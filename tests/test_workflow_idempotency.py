"""Per-step idempotency keys: a webhook or integration step that already made this call is not made again.

Checked: the second event with the same key calls nothing and reuses the first call's output, a different key (another
entry, another destination, another workflow) is a different call, the window (default 24 hours, configurable) and what
happens when it ends, a failed call that doesn't count (so a retry still makes it), two duplicates racing that deliver
once, a dry run that says what it would do and claims nothing, an empty key that fails the step, and the purge. The
integration retry that resumes at the failed step is in test_integration_error_policy_sdk.py."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
from datetime import timedelta

import pytest
from marvin_integration_sdk import INTEGRATION_REGISTRY

from marvin.db.models.groups.workflow_step_idempotency import WorkflowStepIdempotencyModel as Key
from marvin.schemas.group.automation_definition import IntegrationAction, WebhookAction
from marvin.services.automation import idempotency
from marvin.services.automation.engine import dry_run_for_event
from marvin.services.automation.idempotency import _now
from tests.test_workflow_library import _entry, _entry_doc, _fire, _http, _install_workflow, _runs, ws  # noqa: F401 — fixtures and helpers

HANDOFF = "https://client.example/intake"


def _hook(ws, **kw) -> dict:
    return {"kind": "webhook", "id": "hand", "webhook_id": ws.values["handoff_webhook_id"], "body": {"title": "${entry.title}"}, **kw}


def _publish(ws, entry, correlation="c-1"):
    return _fire(ws, "entry_published", _entry_doc(entry), entity=entry.id, entity_type="entry", correlation_id=correlation)


def _keys(ws) -> list[Key]:
    ws.session.expire_all()
    return ws.session.query(Key).filter_by(group_id=ws.gid).all()


def _outputs(ws, slug):
    """Each run's first step output, oldest first."""
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel

    out = []
    for run in _runs(ws, slug):
        steps = (
            ws.session.query(AutomationActionExecutionModel)
            .filter_by(execution_id=run.id)
            .order_by(AutomationActionExecutionModel.action_index)
            .all()
        )
        out.append([s.output_snapshot for s in steps])
    return out


def _expire(ws):
    """Move every recorded call out of its window (as if the window had ended)."""
    for row in _keys(ws):
        row.expires_at = _now() - timedelta(minutes=1)
    ws.session.commit()


# ── A duplicate calls nothing and reuses the first call's output ──────────────────────────────────────────────────────
def test_the_same_key_twice_calls_once_and_reuses_the_first_answer(ws, monkeypatch):
    calls = _http(monkeypatch, body={"id": "rcpt_1"})
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}")])
    entry = _entry(ws, "article", "Deliverable", status="published")

    _publish(ws, entry, "c-1")
    _publish(ws, entry, "c-2")  # the same event handled again, a re-press, a re-delivery

    assert len(calls) == 1 and calls[0][1] == HANDOFF
    first, second = _outputs(ws, "handoff")
    assert first[0]["body"] == {"id": "rcpt_1"} and "idempotency" not in first[0]
    assert second[0]["body"] == {"id": "rcpt_1"}  # the earlier answer, for the steps that read it
    assert second[0]["idempotency"]["duplicate"] is True and second[0]["idempotency"]["key"] == f"handoff-{entry.id}"
    assert [r.status for r in _runs(ws, "handoff")] == ["success", "success"]  # a skipped call is not a failed step


def test_a_later_step_reads_the_reused_output_as_it_read_the_first(ws, monkeypatch):
    _http(monkeypatch, body={"id": "rcpt_1"})
    note = {"kind": "entry", "op": "set_metadata", "metadata": {"receipt": "${steps.hand.output.body.id}"}}
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}"), note])
    entry = _entry(ws, "article", "Deliverable", status="published", metadata={"receipt": "stale"})

    _publish(ws, entry, "c-1")
    entry.metadata_json = {"receipt": "cleared"}
    ws.session.commit()
    _publish(ws, entry, "c-2")

    ws.session.expire_all()
    assert entry.metadata_json["receipt"] == "rcpt_1"  # written again from the reused output


def test_a_different_entry_is_a_different_call(ws, monkeypatch):
    calls = _http(monkeypatch)
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}")])
    one, two = _entry(ws, "article", "One", status="published"), _entry(ws, "article", "Two", status="published")

    _publish(ws, one)
    _publish(ws, two)
    _publish(ws, one)

    assert len(calls) == 2


def test_the_same_key_at_another_destination_or_in_another_workflow_is_another_call(ws, monkeypatch):
    calls = _http(monkeypatch)
    other = {"kind": "webhook", "id": "fwd", "webhook_id": ws.values["forum_webhook_id"], "idempotency_key": "k-${entry.id}"}
    _install_workflow(ws, "a", "entry_published", [_hook(ws, idempotency_key="k-${entry.id}"), other])
    _install_workflow(ws, "b", "entry_published", [_hook(ws, idempotency_key="k-${entry.id}")])
    entry = _entry(ws, "article", "One", status="published")

    _publish(ws, entry)

    assert sorted(c[1] for c in calls) == sorted([HANDOFF, HANDOFF, "https://forum.example/posts.json"])
    assert len(_keys(ws)) == 3


def test_a_step_without_a_key_calls_every_time(ws, monkeypatch):
    calls = _http(monkeypatch)
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws)])
    entry = _entry(ws, "article", "One", status="published")

    _publish(ws, entry)
    _publish(ws, entry)

    assert len(calls) == 2 and _keys(ws) == []


def test_an_integration_step_is_skipped_the_same_way(ws):
    provider = INTEGRATION_REGISTRY["buttondown"]
    step = {
        "kind": "integration",
        "id": "sub",
        "integration": "newsletter",
        "action": "subscribe",
        "args": {"email": "${entry.data.email}"},
        "idempotency_key": "sub-${entry.data.email}",
    }
    _install_workflow(ws, "subscribe", "entry_published", [step])
    ada = _entry(ws, "rsvp", "Ada", status="published", data={"email": "ada@x.test"})
    bob = _entry(ws, "rsvp", "Bob", status="published", data={"email": "bob@x.test"})

    _publish(ws, ada, "c-1")
    _publish(ws, ada, "c-2")
    _publish(ws, bob, "c-3")

    assert [c[1]["email"] for c in provider.calls] == ["ada@x.test", "bob@x.test"]
    first, second, third = _outputs(ws, "subscribe")
    assert second[0]["idempotency"]["duplicate"] is True and first[0].items() <= second[0].items()
    assert "idempotency" not in third[0]
    assert {k.destination for k in _keys(ws)} == {"integration:newsletter.subscribe"}


# ── The window ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_window_defaults_to_a_day_and_is_configurable(ws, monkeypatch):
    _http(monkeypatch)
    _install_workflow(
        ws,
        "handoff",
        "entry_published",
        [_hook(ws, idempotency_key="day-${entry.id}"), {**_hook(ws, idempotency_key="week-${entry.id}", idempotency_window_hours=168), "id": "fwd"}],
    )
    _publish(ws, _entry(ws, "article", "One", status="published"))

    day, week = sorted(_keys(ws), key=lambda k: k.expires_at)
    now = _now()
    assert timedelta(hours=23, minutes=59) < day.expires_at - now <= timedelta(hours=24)
    assert timedelta(hours=167, minutes=59) < week.expires_at - now <= timedelta(hours=168)
    assert all(k.status == "done" for k in _keys(ws))


def test_a_window_is_clamped_and_a_junk_value_means_the_default():
    assert [idempotency.window_hours({"idempotency_window_hours": v}) for v in (None, "soon", True, 0, 6, 100000)] == [24, 24, 24, 24, 6, 720]


def test_after_the_window_the_call_is_made_again_and_the_window_starts_over(ws, monkeypatch):
    calls = _http(monkeypatch, body={"id": "rcpt_1"})
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}")])
    entry = _entry(ws, "article", "One", status="published")

    _publish(ws, entry, "c-1")
    _publish(ws, entry, "c-2")
    assert len(calls) == 1

    _expire(ws)
    _publish(ws, entry, "c-3")

    assert len(calls) == 2
    (row,) = _keys(ws)  # the same row, taken over
    assert row.status == "done" and row.expires_at > _now() + timedelta(hours=23)
    _publish(ws, entry, "c-4")
    assert len(calls) == 2  # and the new window holds


# ── A failed call doesn't count ───────────────────────────────────────────────────────────────────────────────────────
def test_a_failed_webhook_call_is_made_again_not_skipped(ws, monkeypatch):
    _http(monkeypatch, status=500)
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}")])
    entry = _entry(ws, "article", "One", status="published")

    _publish(ws, entry, "c-1")
    assert [r.status for r in _runs(ws, "handoff")] == ["failed"] and _keys(ws) == []  # the claim was given back

    calls = _http(monkeypatch)  # the endpoint recovers
    _publish(ws, entry, "c-2")
    _publish(ws, entry, "c-3")

    assert len(calls) == 1 and [r.status for r in _runs(ws, "handoff")] == ["failed", "success", "success"]


def test_a_failed_integration_call_is_made_again_not_skipped(ws):
    provider = INTEGRATION_REGISTRY["buttondown"]
    step = {
        "kind": "integration",
        "id": "issue",
        "integration": "newsletter",
        "action": "create_issue_email",
        "args": {"subject": "${entry.title}"},
        "idempotency_key": "issue-${entry.id}",
    }
    _install_workflow(ws, "issue", "entry_published", [step])
    entry = _entry(ws, "article", "Boom", status="published")

    _publish(ws, entry, "c-1")
    assert _keys(ws) == []

    entry.title = "Fine"
    ws.session.commit()
    _publish(ws, entry, "c-2")
    _publish(ws, entry, "c-3")

    assert [c[1]["subject"] for c in provider.calls] == ["Boom", "Fine"]  # the failure, then one delivery


# ── Two duplicates racing deliver once ────────────────────────────────────────────────────────────────────────────────
def _gate(ws, key="k-1", *, dry_run=False, step=None):
    step = step or {"kind": "webhook", "idempotency_key": key}
    ctx = {"_step": {"workflow": "wf-1", "workflow_slug": "wf"}}
    return idempotency.open_gate(ws.session, ws.gid, step, ctx, destination="webhook:w", dry_run=dry_run)


def test_a_duplicate_that_meets_a_call_in_flight_does_not_make_it(ws):
    first = _gate(ws)  # takes the claim, hasn't finished
    second = _gate(ws)

    assert first.duplicate is False and second.duplicate is True and second.in_progress is True
    out = second.skipped()
    assert out["idempotency"]["in_progress"] is True and out["idempotency"]["duplicate"] is True
    first.complete({"ok": True})
    third = _gate(ws)
    assert third.duplicate and not third.in_progress and third.skipped()["ok"] is True


def test_exactly_one_of_several_racing_claims_wins(ws):
    gates = [_gate(ws) for _ in range(5)]

    assert [g.duplicate for g in gates] == [False, True, True, True, True] and len(_keys(ws)) == 1


def test_a_claim_nobody_finished_runs_out_and_is_taken_over(ws):
    crashed = _gate(ws)
    assert crashed.row_id is not None
    _expire(ws)  # the lease ended: the worker that held it is gone

    taker, late = _gate(ws), _gate(ws)

    assert taker.duplicate is False and late.duplicate is True


def test_a_released_claim_can_be_taken_at_once(ws):
    first = _gate(ws)
    first.release()

    assert _gate(ws).duplicate is False and len(_keys(ws)) == 1


def test_an_output_too_large_to_keep_still_marks_the_call_made(ws):
    first = _gate(ws)
    first.complete({"blob": "x" * (idempotency.MAX_OUTPUT_CHARS + 1)})

    again = _gate(ws)

    assert again.duplicate and "blob" not in again.skipped() and again.skipped()["idempotency"]["duplicate"] is True


def test_the_ledger_holds_a_hash_never_the_key_text(ws):
    _gate(ws, key="ada@example.com")

    (row,) = _keys(ws)
    assert len(row.key_hash) == 64 and "ada" not in f"{row.key_hash} {row.workflow_slug} {row.destination}"


# ── An empty key ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_key_that_reads_nothing_fails_the_step_rather_than_treat_every_call_as_one(ws, monkeypatch):
    calls = _http(monkeypatch)
    _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="${entry.data.nothing_here}")])
    entry = _entry(ws, "article", "One", status="published")

    _publish(ws, entry)

    assert calls == [] and [r.status for r in _runs(ws, "handoff")] == ["failed"] and _keys(ws) == []


# ── Dry run ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _dry(ws, workflow, entry):
    event = {"event_type": "entry_published", "entry_id": str(entry.id), "user_id": None, "changed_fields": [], "before": {}, "after": {}}
    return dry_run_for_event(ws.session, ws.gid, workflow, event)


def test_a_dry_run_says_call_then_skip_and_neither_calls_nor_claims(ws, monkeypatch):
    calls = _http(monkeypatch, body={"id": "rcpt_1"})
    workflow = _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}")])
    entry = _entry(ws, "article", "One", status="published")

    before = _dry(ws, workflow, entry)["plan"][0]["resolved"]
    assert before["would"] == "call" and before["idempotency_key"] == f"handoff-{entry.id}" and before["url"] == HANDOFF
    assert calls == [] and _keys(ws) == []  # looked, didn't claim

    _publish(ws, entry)
    after = _dry(ws, workflow, entry)["plan"][0]["resolved"]

    assert after["would"] == "skip (duplicate)" and after["dry_run"] is True
    assert after["body"] == {"id": "rcpt_1"}  # what a real run would hand the next step
    assert len(calls) == 1  # the dry runs added none


def test_a_dry_run_for_an_integration_step_says_the_same(ws):
    provider = INTEGRATION_REGISTRY["buttondown"]
    step = {
        "kind": "integration",
        "id": "sub",
        "integration": "newsletter",
        "action": "subscribe",
        "args": {"email": "a@x.test"},
        "idempotency_key": "sub-${entry.id}",
    }
    workflow = _install_workflow(ws, "subscribe", "entry_published", [step])
    entry = _entry(ws, "rsvp", "Ada", status="published")

    assert _dry(ws, workflow, entry)["plan"][0]["resolved"]["would"] == "call"
    _publish(ws, entry)
    assert _dry(ws, workflow, entry)["plan"][0]["resolved"]["would"] == "skip (duplicate)"
    assert len(provider.calls) == 1


def test_a_dry_run_after_the_window_says_call_again(ws, monkeypatch):
    _http(monkeypatch)
    workflow = _install_workflow(ws, "handoff", "entry_published", [_hook(ws, idempotency_key="handoff-${entry.id}")])
    entry = _entry(ws, "article", "One", status="published")
    _publish(ws, entry)
    _expire(ws)

    assert _dry(ws, workflow, entry)["plan"][0]["resolved"]["would"] == "call"


# ── The definition ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_definition_knows_the_two_fields_on_both_steps_and_bounds_the_window():
    for model, base in (
        (WebhookAction, {"kind": "webhook", "webhook_id": "w"}),
        (IntegrationAction, {"kind": "integration", "integration": "s", "action": "a"}),
    ):
        step = model.model_validate({**base, "idempotency_key": "k-${entry.id}", "idempotency_window_hours": 6})
        assert (step.idempotency_key, step.idempotency_window_hours) == ("k-${entry.id}", 6)
        for bad in (0, 721):
            with pytest.raises(ValueError):
                model.model_validate({**base, "idempotency_window_hours": bad})


# ── The purge ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_purge_drops_ended_windows_and_keeps_live_ones(ws):
    live, dead = _gate(ws, "live"), _gate(ws, "dead")
    live.complete({"a": 1})
    dead.complete({"a": 2})
    ws.session.query(Key).filter(Key.id == dead.row_id).update({"expires_at": _now() - timedelta(hours=1)})
    ws.session.commit()

    assert idempotency.purge_expired(ws.session) == 1
    ws.session.commit()

    assert [k.id for k in _keys(ws)] == [live.row_id]


def test_the_scheduled_run_prune_also_drops_ended_windows(ws, monkeypatch):
    from types import SimpleNamespace

    from marvin.services.scheduled_tasks.handlers import maintenance

    gate = _gate(ws)
    gate.complete({"a": 1})
    ws.session.query(Key).update({"expires_at": _now() - timedelta(hours=1)})
    ws.session.commit()

    out = maintenance.PruneWorkflowRunsHandler().execute(SimpleNamespace(group_id=None, task_config={"retention_days": 90}), None)

    assert "1 expired idempotency key" in out and _keys(ws) == []
