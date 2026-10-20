# ruff: noqa: F811  (the `workspace` fixture is imported and extended)
"""Automation results: the record Marvin keeps of work it handed to another system (services/automation_results.py).

An integration action that declares ``hands_off`` is recorded by the engine (in flight when the call succeeded, failed when it
didn't), the ``automation_result`` step settles it when the other side reports back, a record in flight for more than a day shows
as No reply, a person retries or dismisses a failure through the API (ADMIN), and a daily task prunes old ones.

The hand-off is made the way a workflow makes it: the real engine runs a workflow with an integration step on a real entry, through
a fake provider whose ``start`` action declares ``hands_off`` with a service's own words for the status.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, HandsOff, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.automation_results import AutomationResultModel as Result  # noqa: E402
from marvin.db.models.groups.automations import WorkspaceAutomationModel  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.db.models.platform import Entries, EntryTypes  # noqa: E402
from marvin.db.models.users.roles import WorkspaceRole  # noqa: E402
from marvin.services import automation_results as results  # noqa: E402
from marvin.services.automation.actions.automation_result import run_automation_result_action  # noqa: E402
from marvin.services.automation.actions.base import AutomationActionError  # noqa: E402
from marvin.services.automation.actions.integration import run_integration_action  # noqa: E402
from marvin.services.automation.authz import ROLE_ADMIN, ROLE_VIEWER  # noqa: E402
from marvin.services.automation.engine import run_automations_for_event  # noqa: E402
from marvin.services.automation.recorder import ExecutionRecorder  # noqa: E402
from tests.test_content_role_gates import _sign_in, workspace  # noqa: E402, F401  (the `workspace` fixture)

API = "/api/groups/automation-results"
WORDS = {"success": "succeeded", "error": "failed", "waiting": "in_flight"}
LOGIN = "swordfish"  # a made-up credential the fake flow echoes in its error, to prove it is never kept


class _Flow(IntegrationProvider):
    """A service that starts a run and reports back later, in its own words (success | error | waiting)."""

    slug = "fake_flow"
    name = "Fake flow"
    actions = (
        ProviderAction(
            key="start",
            label="Start a run",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}, "entry_id": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"run_id": {"type": "string"}, "run_url": {"type": "string"}}},
            hands_off=HandsOff(remote_id="run_id", remote_url="run_url", target="path", statuses=WORDS),
        ),
        ProviderAction(key="ping", label="Ping"),
    )
    calls: list = []

    def run_action(self, key, args, ctx):
        _Flow.calls.append((key, args))
        if args.get("refuse"):
            raise ValueError(f"the flow refused it (credential {ctx.secret})")
        return {"run_id": f"run-{len(_Flow.calls)}", "run_url": f"https://flow.example/runs/{len(_Flow.calls)}", "ok": True}


def _definition(**over):
    step = {
        "kind": "integration",
        "id": "handoff",
        "integration": "hooks",
        "action": "start",
        "args": {"path": "marvin/new", "entry_id": "${entry.id}"},
    }
    return {
        "trigger": {"type": "event", "event": "entry_published"},
        "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "post"}],
        "actions": [step],
        **over,
    }


@pytest.fixture
def flow(db_session, workspace, monkeypatch):
    """The workspace of `workspace` with a `hooks` connection to the fake flow, a `post` type with three entries and a hand-off workflow (on)."""
    _Flow.calls = []
    monkeypatch.setitem(INTEGRATION_REGISTRY, _Flow.slug, _Flow())
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: LOGIN)
    gid = workspace.gid
    connection = IntegrationModel(
        session=db_session, group_id=gid, provider=_Flow.slug, name="Hooks", slug="hooks", enabled=True, config={}, secret_ref="X"
    )
    workflow = WorkspaceAutomationModel(session=db_session, group_id=gid, name="Hand off", slug="hand-off", enabled=True, definition=_definition())
    kind = EntryTypes(session=db_session, group_id=gid, name="Post", slug="post", schema_json={"fields": []})
    kind.id = uuid.uuid4()
    db_session.add_all([connection, workflow, kind])
    db_session.flush()
    entries = []
    for n in range(3):
        entry = Entries(
            session=db_session,
            group_id=gid,
            entry_type_id=kind.id,
            title=f"Post {n}",
            slug=f"post-{n}-{gid.hex[:6]}",
            data_json={},
            status="published",
        )
        db_session.add(entry)
        db_session.flush()
        entries.append(entry)
    db_session.commit()
    return SimpleNamespace(
        ws=workspace, session=db_session, gid=gid, connection=connection, workflow=workflow, entries=entries, a=entries[0], b=entries[1], c=entries[2]
    )


def _publish(flow, entry=None):
    """The event a published entry sends, run through the real engine."""
    event = {"event_type": "entry_published", "entry_id": str((entry or flow.a).id), "user_id": None}
    run_automations_for_event(flow.session, flow.gid, event, recorder=ExecutionRecorder(flow.session, flow.gid))
    flow.session.expire_all()


def _rows(flow, **where):
    flow.session.expire_all()
    return flow.session.query(Result).filter_by(group_id=flow.gid, **where).order_by(Result.sent_at, Result.created_at).all()


def _report(flow, status, *, role=ROLE_ADMIN, dry_run=False, **step):
    """The ``automation_result`` step, as a workflow runs it."""
    action = {"kind": "automation_result", "status": status, **step}
    out = run_automation_result_action(flow.session, flow.gid, action, {"event": {}, "steps": {}}, authorizer_role=role, dry_run=dry_run)
    flow.session.commit()  # the engine's recorder commits after a step
    flow.session.expire_all()
    return out


def _sent(flow, row, **ago):
    """Make a result look as if it was sent ``ago`` ago (hours=…, days=…)."""
    row.sent_at = datetime.now(UTC) - timedelta(**ago)
    if row.finished_at is not None:
        row.finished_at = row.sent_at
    flow.session.commit()
    return row


def _client(flow, role=WorkspaceRole.ADMIN):
    return _sign_in(flow.ws, role)


# ── the engine records a hand-off ───────────────────────────────────────────────────────────────────────────────


def test_a_hands_off_step_that_succeeds_records_an_in_flight_result_with_its_run_target_entry_and_workflow(flow):
    _publish(flow)

    (row,) = _rows(flow)
    assert (row.status, row.attempt, row.message, row.finished_at) == ("in_flight", 1, None, None)
    assert (row.remote_id, row.remote_url) == ("run-1", "https://flow.example/runs/1")
    assert (row.target, row.action) == ("marvin/new", "start")
    assert (row.entry_id, row.integration_id, row.workflow_id) == (flow.a.id, flow.connection.id, flow.workflow.id)
    assert row.sent_at is not None and row.dismissed_at is None


def test_a_call_that_fails_records_a_failed_result_with_the_providers_message_and_no_credential_in_it(flow):
    flow.workflow.definition = _definition(actions=[{**_definition()["actions"][0], "args": {"path": "marvin/new", "refuse": True}}])
    flow.session.commit()

    _publish(flow)

    (row,) = _rows(flow)
    assert (row.status, row.attempt, row.remote_id, row.remote_url) == ("failed", 1, None, None)
    assert row.finished_at is not None
    assert "the flow refused it" in row.message and LOGIN not in row.message


def test_an_action_that_does_not_declare_hands_off_leaves_no_result(flow):
    flow.workflow.definition = _definition(actions=[{"kind": "integration", "integration": "hooks", "action": "ping", "args": {}}])
    flow.session.commit()

    _publish(flow)

    assert _rows(flow) == []


def test_a_dry_run_of_a_hands_off_step_records_nothing_and_calls_nothing(flow):
    action = {"kind": "integration", "integration": "hooks", "action": "start", "args": {"path": "marvin/new"}}

    run_integration_action(flow.session, flow.gid, action, {"event": {}, "steps": {}, "depth": 0}, authorizer_role=ROLE_ADMIN, dry_run=True)

    assert _rows(flow) == [] and _Flow.calls == []


def test_two_hand_offs_of_the_same_entry_are_two_results(flow):
    _publish(flow)
    _publish(flow)

    assert [r.remote_id for r in _rows(flow)] == ["run-1", "run-2"]


def test_a_retry_run_of_a_failed_hand_off_reuses_its_result_and_counts_the_attempt(flow):
    flow.workflow.definition = _definition(actions=[{**_definition()["actions"][0], "args": {"path": "marvin/new", "refuse": True}}])
    flow.session.commit()
    _publish(flow)
    (failed,) = _rows(flow)
    step = dict(flow.workflow.definition["actions"][0], args={"path": "marvin/new"})
    context = {
        "event": {"entry_id": str(flow.a.id)},
        "entry": {"id": str(flow.a.id)},
        "steps": {},
        "depth": 0,
        "_retry": {"id": "r1"},
        "_step": {"automation_id": flow.workflow.id},
    }

    run_integration_action(flow.session, flow.gid, step, context, authorizer_role=ROLE_ADMIN)

    (row,) = _rows(flow)
    assert row.id == failed.id and (row.status, row.attempt, row.message) == ("in_flight", 2, None)
    assert row.remote_id and row.dismissed_at is None


def test_a_hand_off_with_no_entry_is_recorded_with_none(flow):
    step = {"kind": "integration", "integration": "hooks", "action": "start", "args": {"path": "marvin/nightly"}}

    run_integration_action(flow.session, flow.gid, step, {"event": {}, "steps": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)

    (row,) = _rows(flow)
    assert (row.entry_id, row.workflow_id, row.target) == (None, None, "marvin/nightly")


def test_a_run_url_that_is_not_a_web_address_is_not_kept(flow, monkeypatch):
    monkeypatch.setattr(_Flow, "run_action", lambda self, key, args, ctx: {"run_id": "r9", "run_url": "javascript:alert(1)"})

    _publish(flow)

    (row,) = _rows(flow)
    assert (row.remote_id, row.remote_url) == ("r9", None)


# ── the automation_result step settles it ───────────────────────────────────────────────────────────────────────


def test_a_report_settles_the_result_with_that_remote_id_and_the_providers_words_become_marvins(flow):
    _publish(flow)
    _publish(flow, flow.b)

    out = _report(flow, "success", integration="hooks", remote_id="run-1", message="3 items sent", finished_at="2026-10-20T12:00:00Z")

    first, second = _rows(flow)
    assert out == {"result_id": str(first.id), "status": "succeeded", "matched": "remote_id", "created": False}
    assert (first.status, first.message, first.finished_at) == ("succeeded", "3 items sent", datetime(2026, 10, 20, 12, tzinfo=UTC))
    assert second.status == "in_flight"


@pytest.mark.parametrize(
    ("word", "expected"), [("success", "succeeded"), ("error", "failed"), ("waiting", "in_flight"), ("ERROR", "failed"), ("failed", "failed")]
)
def test_each_word_the_service_uses_becomes_one_of_marvins_three(flow, word, expected):
    _publish(flow)

    _report(flow, word, integration="hooks", remote_id="run-1")

    assert _rows(flow)[0].status == expected


def test_a_report_without_a_remote_id_settles_the_newest_one_still_in_flight_for_the_entry_and_connection(flow):
    _publish(flow)
    _publish(flow)
    _publish(flow, flow.b)
    older, newer, other_entry = _rows(flow)
    _sent(flow, older, hours=3)

    out = _report(flow, "error", integration="hooks", entry_id=str(flow.a.id), message="the flow broke")

    assert out["matched"] == "entry" and out["result_id"] == str(newer.id)
    assert [r.status for r in _rows(flow)] == ["in_flight", "failed", "in_flight"]
    assert (_rows(flow)[1].message, other_entry.status) == ("the flow broke", "in_flight")


def test_the_entry_defaults_to_the_one_the_run_is_about(flow):
    _publish(flow, flow.b)
    action = {"kind": "automation_result", "status": "success", "integration": "hooks"}

    out = run_automation_result_action(flow.session, flow.gid, action, {"entry": {"id": str(flow.b.id)}, "steps": {}}, authorizer_role=ROLE_ADMIN)

    assert out["matched"] == "entry" and _rows(flow)[0].status == "succeeded"


def test_a_report_for_a_result_already_settled_is_not_matched_by_entry_but_is_by_remote_id(flow):
    _publish(flow)
    _report(flow, "success", integration="hooks", remote_id="run-1")

    by_entry = _report(flow, "error", integration="hooks", entry_id=str(flow.a.id))
    again = _report(flow, "error", integration="hooks", remote_id="run-1")

    assert by_entry["matched"] == "none" and again["matched"] == "remote_id"
    assert sorted(r.status for r in _rows(flow)) == ["failed", "failed"]


def test_a_report_that_matches_nothing_is_kept_as_a_new_result_rather_than_dropped(flow):
    out = _report(
        flow, "error", integration="hooks", remote_id="never-seen", entry_id=str(flow.c.id), target="marvin/unknown", message="nobody asked"
    )

    (row,) = _rows(flow)
    assert out["matched"] == "none" and out["created"] is True
    assert (row.status, row.remote_id, row.target, row.message) == ("failed", "never-seen", "marvin/unknown", "nobody asked")
    assert (row.entry_id, row.integration_id, row.workflow_id, row.finished_at is not None) == (flow.c.id, flow.connection.id, None, True)


def test_a_report_naming_an_entry_that_is_not_in_the_workspace_is_kept_without_an_entry(flow):
    _report(flow, "success", integration="hooks", remote_id="r-x", entry_id=str(uuid.uuid4()))

    (row,) = _rows(flow)
    assert (row.entry_id, row.status) == (None, "succeeded")


def test_a_word_the_provider_does_not_know_leaves_the_result_in_flight_with_the_word_in_its_message(flow):
    _publish(flow)

    out = _report(flow, "exploded", integration="hooks", remote_id="run-1", message="see the log")

    row = _rows(flow)[0]
    assert out["status"] == "in_flight" and row.status == "in_flight" and row.finished_at is None
    assert "unrecognised status: 'exploded'" in row.message and "see the log" in row.message


def test_without_a_connection_only_marvins_own_words_are_understood_and_the_hand_offs_own_connection_is_used_when_found(flow):
    _publish(flow)

    kept = _report(flow, "success", remote_id="run-1")  # found by its remote id: the connection it went through reads the word
    own = _report(flow, "failed", remote_id="fresh-1")  # nothing matched, no connection: only Marvin's own words are known
    unknown = _report(flow, "success", remote_id="fresh-2")

    assert (kept["status"], kept["matched"]) == ("succeeded", "remote_id")
    assert (own["status"], unknown["status"]) == ("failed", "in_flight")


def test_a_failure_reported_again_asks_for_attention_again(flow):
    _publish(flow)
    _report(flow, "error", integration="hooks", remote_id="run-1")
    (row,) = _rows(flow)
    results.dismiss(flow.session, row, flow.ws.uid)
    flow.session.commit()

    _report(flow, "error", integration="hooks", remote_id="run-1", message="still broken")

    assert _rows(flow)[0].dismissed_at is None


def test_the_step_dry_run_says_what_it_would_do_and_writes_nothing(flow):
    _publish(flow)

    settle = _report(flow, "success", integration="hooks", remote_id="run-1", dry_run=True)
    record = _report(flow, "success", integration="hooks", remote_id="nope", dry_run=True)

    assert (settle["would"], settle["status"]) == ("settle", "succeeded") and record["would"] == "record"
    assert [r.status for r in _rows(flow)] == ["in_flight"]


def test_the_step_refuses_an_unknown_connection_an_empty_status_and_an_author_below_the_role(flow):
    with pytest.raises(AutomationActionError, match="not found in this workspace"):
        _report(flow, "success", integration="nope")
    with pytest.raises(AutomationActionError, match="`status` came out empty"):
        _report(flow, "${event.missing}")
    with pytest.raises(AutomationActionError):
        _report(flow, "success", role=ROLE_VIEWER)


def test_the_step_is_a_registered_kind_the_definition_and_the_authoring_guide_know():
    from marvin.schemas.group.automation_definition import ACTION_MODELS, AutomationResultAction
    from marvin.services.automation.actions import available_kinds
    from marvin.services.automation.authoring import OWN_SECTION_KINDS, _actions

    assert ACTION_MODELS["automation_result"] is AutomationResultAction and "automation_result" in available_kinds()
    assert OWN_SECTION_KINDS["automation_result"] == "records" and "section=records" in _actions()["kinds"]["automation_result"]["description"]


def test_the_authoring_guides_records_section_documents_the_step_with_its_fields_and_a_note(flow):
    from marvin.services.automation.authoring import authoring_guide

    doc = authoring_guide(flow.session, flow.gid, "records")["records"]["automation_result"]
    assert "status" in doc["required"] and {"integration", "remote_id", "entry_id", "target", "message", "finished_at"} <= set(doc["optional"])
    assert "never dropped" in doc["note"]


def test_a_definition_with_the_step_validates_and_one_without_a_status_does_not():
    from pydantic import ValidationError

    from marvin.schemas.group.automation_definition import AutomationDefinition

    trigger = {"type": "incoming_webhook", "webhook": "n8n"}
    ok = AutomationDefinition.model_validate({"trigger": trigger, "actions": [{"kind": "automation_result", "status": "${event.payload.status}"}]})
    assert ok.actions[0].kind == "automation_result"
    for bad in (
        {"kind": "automation_result"},
        {"kind": "automation_result", "status": "  "},
    ):
        with pytest.raises(ValidationError):
            AutomationDefinition.model_validate({"trigger": trigger, "actions": [bad]})


# ── No reply ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_result_still_in_flight_after_a_day_is_no_reply_without_its_status_changing(flow):
    _publish(flow)
    _publish(flow, flow.b)
    old, fresh = _rows(flow)
    _sent(flow, old, hours=25)
    now = datetime.now(UTC)

    assert results.is_no_reply(old, now) and not results.is_no_reply(fresh, now)
    assert old.status == "in_flight"
    assert results.summary(flow.session, flow.gid) | {"can": None} == {
        "show": True, "in_flight": 1, "no_reply": 1, "failed": 0, "succeeded": 0, "attention": 1, "can": None,
    }  # fmt: skip


def test_a_failed_or_succeeded_result_is_never_no_reply_however_old(flow):
    _publish(flow)
    _report(flow, "success", integration="hooks", remote_id="run-1")
    (row,) = _rows(flow)

    assert not results.is_no_reply(_sent(flow, row, days=40), datetime.now(UTC))


def test_a_late_reply_settles_a_no_reply_result_as_usual(flow):
    _publish(flow)
    _sent(flow, _rows(flow)[0], hours=30)

    _report(flow, "success", integration="hooks", remote_id="run-1")

    (row,) = _rows(flow)
    assert row.status == "succeeded" and not results.is_no_reply(row)


# ── the API ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_nothing_is_shown_until_a_result_exists_and_the_summary_then_counts_them(flow):
    client = _client(flow, WorkspaceRole.EDITOR)
    assert client.get(f"{API}/summary").json()["show"] is False

    _publish(flow)
    _publish(flow, flow.b)
    _report(flow, "error", integration="hooks", remote_id="run-2")
    _sent(flow, _rows(flow)[0], hours=48)
    body = client.get(f"{API}/summary").json()

    assert body["show"] is True
    assert (body["inFlight"], body["noReply"], body["failed"], body["succeeded"], body["attention"]) == (0, 1, 1, 0, 2)
    assert body["can"] == {"act": False}


def test_an_editor_reads_and_an_admin_can_also_act_but_a_lower_role_is_refused_before_anything_is_looked_up(flow):
    _publish(flow)
    (row,) = _rows(flow)
    for role in (WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR):
        client = _client(flow, role)
        assert [client.get(path).status_code for path in (f"{API}/summary", API, f"{API}/{row.id}")] == [403, 403, 403]
    assert _client(flow, WorkspaceRole.EDITOR).get(f"{API}/summary").json()["can"] == {"act": False}
    assert _client(flow, WorkspaceRole.ADMIN).get(f"{API}/summary").json()["can"] == {"act": True}


def test_an_editor_cannot_retry_or_dismiss_and_a_non_member_cannot_either(flow):
    _publish(flow)
    _report(flow, "error", integration="hooks", remote_id="run-1")
    (row,) = _rows(flow)
    for role in (WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER):
        client = _client(flow, role)
        assert [client.post(f"{API}/{row.id}/{verb}").status_code for verb in ("retry", "dismiss")] == [403, 403]
    stranger = _client(flow, None)  # not in the workspace: the platform answers 409 "no workspace" before the route's own check
    assert {stranger.post(f"{API}/{row.id}/{verb}").status_code for verb in ("retry", "dismiss")} <= {403, 409}
    assert _rows(flow)[0].dismissed_at is None and len(_Flow.calls) == 1


def test_the_list_gives_each_result_with_its_entry_connection_workflow_and_times_newest_first(flow):
    _publish(flow)
    _publish(flow, flow.b)
    _sent(flow, _rows(flow)[0], hours=2)

    body = _client(flow).get(API).json()

    assert body["total"] == 2 and (body["limit"], body["offset"]) == (50, 0)
    newest, oldest = body["items"]
    assert (newest["entry"]["title"], oldest["entry"]["title"]) == ("Post 1", "Post 0")
    assert newest["connection"] == {"slug": "hooks", "name": "Hooks", "provider": "fake_flow"}
    assert newest["workflow"]["name"] == "Hand off"
    assert (newest["status"], newest["noReply"], newest["target"], newest["remoteId"], newest["attempt"]) == (
        "in_flight",
        False,
        "marvin/new",
        "run-2",
        1,
    )
    assert newest["remoteUrl"] == "https://flow.example/runs/2" and newest["finishedAt"] is None and newest["dismissed"] is False
    assert body["connections"] == [{"slug": "hooks", "name": "Hooks", "provider": "fake_flow"}]
    assert body["counts"]["inFlight"] == 2


def test_the_list_filters_by_state_connection_entry_and_text_and_pages(flow):
    other = IntegrationModel(session=flow.session, group_id=flow.gid, provider="fake_flow", name="Second", slug="second", enabled=True, config={})
    flow.session.add(other)
    flow.session.commit()
    for entry in (flow.a, flow.b, flow.c):
        _publish(flow, entry)
    _report(flow, "error", integration="hooks", remote_id="run-1", message="quota exceeded")
    _report(flow, "success", integration="hooks", remote_id="run-2")
    _sent(flow, _rows(flow)[2], hours=26)
    _report(flow, "waiting", integration="second", remote_id="elsewhere", target="marvin/other", entry_id=str(flow.a.id))
    client = _client(flow)

    def ids(**params):
        return [i["remoteId"] for i in client.get(API, params=params).json()["items"]]

    assert sorted(ids(status="failed")) == ["run-1"] and ids(status="succeeded") == ["run-2"]
    assert ids(status="no_reply") == ["run-3"]  # in flight for over a day
    assert sorted(ids(status=["in_flight", "no_reply"])) == ["elsewhere", "run-3"]
    assert ids(status="in_flight") == ["elsewhere"]  # no reply is its own tab
    assert ids(connection="second") == ["elsewhere"]
    assert sorted(ids(entry_id=str(flow.a.id))) == ["elsewhere", "run-1"]
    assert (
        ids(q="quota") == ["run-1"] and ids(q="Post 1") == ["run-2"] and ids(q="second") == ["elsewhere"] and ids(q="marvin/other") == ["elsewhere"]
    )
    assert ids(q="no such thing") == []
    page = client.get(API, params={"limit": 2, "offset": 2}).json()
    assert (page["total"], len(page["items"])) == (4, 2)


def test_a_result_of_another_workspace_is_not_found_and_not_listed(flow, db_session):
    _publish(flow)
    (row,) = _rows(flow)
    from marvin.db.models.groups.groups import Groups

    other = Groups(session=db_session, name=f"other-{uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:6]}")
    other.id = uuid.uuid4()
    db_session.add(other)
    db_session.commit()
    try:
        foreign = Result(session=db_session, group_id=other.id, status="failed", sent_at=datetime.now(UTC))
        db_session.add(foreign)
        db_session.commit()
        client = _client(flow)
        assert [i["id"] for i in client.get(API).json()["items"]] == [str(row.id)]
        assert [client.get(f"{API}/{foreign.id}").status_code, client.post(f"{API}/{foreign.id}/dismiss").status_code] == [404, 404]
    finally:
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()


# ── dismiss ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_dismissing_a_failure_stops_it_counting_as_needing_attention_and_is_kept_in_the_list(flow):
    _publish(flow)
    _report(flow, "error", integration="hooks", remote_id="run-1")
    (row,) = _rows(flow)
    client = _client(flow)

    res = client.post(f"{API}/{row.id}/dismiss")

    assert res.status_code == 200 and res.json()["result"]["dismissed"] is True
    assert results.attention(flow.session, flow.gid) == (0, 0)
    assert client.get(API).json()["total"] == 1
    assert client.get(API, params={"include_dismissed": "false"}).json()["total"] == 0
    assert client.post(f"{API}/{row.id}/dismiss").status_code == 200  # again: nothing more to do


@pytest.mark.parametrize("word", ["success", "waiting"])
def test_only_a_failed_result_can_be_dismissed(flow, word):
    _publish(flow)
    _report(flow, word, integration="hooks", remote_id="run-1")
    (row,) = _rows(flow)

    res = _client(flow).post(f"{API}/{row.id}/dismiss")

    assert res.status_code == 409 and "failed" in res.json()["detail"]


# ── retry ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _fail_the_hand_off(flow, entry=None, **definition):
    """Publish the entry with a workflow whose call is refused, then fix the call: what is left is a failure to retry."""
    refused = {**_definition()["actions"][0], "args": {"path": "marvin/new", "entry_id": "${entry.id}", "refuse": True}}
    flow.workflow.definition = _definition(actions=[refused], **definition)
    flow.session.commit()
    _publish(flow, entry)
    flow.workflow.definition = _definition(**definition)
    flow.session.commit()
    (row,) = _rows(flow)
    return row


def test_a_person_retries_a_failed_hand_off_and_it_is_in_flight_again_as_the_same_result_with_the_attempt_counted(flow):
    row = _fail_the_hand_off(flow)

    res = _client(flow).post(f"{API}/{row.id}/retry")

    assert res.status_code == 200, res.text
    body = res.json()["result"]
    assert (body["id"], body["status"], body["attempt"], body["message"], body["finishedAt"]) == (str(row.id), "in_flight", 2, None, None)
    assert body["remoteId"] and body["remoteUrl"]
    assert len(_rows(flow)) == 1 and len(_Flow.calls) == 2


def test_a_retry_that_fails_again_is_the_same_failed_result_with_its_attempt_counted_and_schedules_nothing_more(flow):
    from marvin.db.models.groups.integration_errors import IntegrationRetryModel

    row = _fail_the_hand_off(flow)
    flow.workflow.definition = _definition(
        actions=[{**flow.workflow.definition["actions"][0], "args": {"path": "marvin/new", "entry_id": "${entry.id}", "refuse": True}}]
    )
    flow.session.commit()

    res = _client(flow).post(f"{API}/{row.id}/retry")

    assert res.status_code == 200, res.text
    assert (res.json()["result"]["status"], res.json()["result"]["attempt"]) == ("failed", 2)
    assert len(_rows(flow)) == 1
    assert flow.session.query(IntegrationRetryModel).filter_by(group_id=flow.gid, attempt=2).count() == 0


def test_a_retry_runs_only_the_hand_off_step_not_the_rest_of_the_workflow(flow):
    marker = {"kind": "entry", "op": "set_metadata", "metadata": {"seen": "yes"}}
    row = _fail_the_hand_off(flow)
    flow.workflow.definition = _definition(actions=[marker, _definition()["actions"][0], marker])
    flow.session.commit()

    assert _client(flow).post(f"{API}/{row.id}/retry").status_code == 200

    flow.session.expire_all()
    assert "seen" not in (flow.session.get(Entries, flow.a.id).metadata_json or {})


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("switched_off", "switched off"),
        ("step_removed", "no longer has the step"),
        ("entry_changed", "no longer matches"),
        ("reads_the_event", "reads from the run that first started it"),
        ("two_steps", "more than one step"),
    ],
)
def test_a_retry_that_cannot_be_done_honestly_is_refused_with_the_reason_and_sends_nothing(flow, change, reason):
    row = _fail_the_hand_off(flow)
    step = _definition()["actions"][0]
    if change == "switched_off":
        flow.workflow.enabled = False
    elif change == "step_removed":
        flow.workflow.definition = _definition(actions=[{"kind": "entry", "op": "set_metadata", "metadata": {"x": "y"}}])
    elif change == "entry_changed":
        flow.a.entry_type_id = flow.session.query(EntryTypes).filter_by(group_id=flow.gid).one().id
        other = EntryTypes(session=flow.session, group_id=flow.gid, name="Page", slug="page", schema_json={"fields": []})
        other.id = uuid.uuid4()
        flow.session.add(other)
        flow.session.flush()
        flow.a.entry_type_id = other.id
    elif change == "reads_the_event":
        flow.workflow.definition = _definition(actions=[{**step, "args": {"path": "${event.payload.path}", "entry_id": "${entry.id}"}}])
    elif change == "two_steps":
        flow.workflow.definition = _definition(actions=[step, {**step, "id": "again"}])
    flow.session.commit()
    calls = len(_Flow.calls)

    res = _client(flow).post(f"{API}/{row.id}/retry")

    assert res.status_code == 409 and reason in res.json()["detail"]
    assert len(_Flow.calls) == calls and _rows(flow)[0].attempt == 1


def test_a_retry_picks_among_several_steps_on_the_connection_by_the_target_it_asked_for(flow):
    step = _definition()["actions"][0]
    two = [
        {**step, "id": "one", "args": {"path": "marvin/one", "entry_id": "${entry.id}", "refuse": True}},
        {**step, "id": "two", "args": {"path": "marvin/two", "entry_id": "${entry.id}", "refuse": True}},
    ]
    flow.workflow.definition = _definition(actions=two)
    flow.session.commit()
    _publish(flow)
    rows = _rows(flow)
    assert [r.target for r in rows] == ["marvin/one"]  # the first refusal stops the run
    flow.workflow.definition = _definition(
        actions=[
            {**two[0], "args": {"path": "marvin/one", "entry_id": "${entry.id}"}},
            {**two[1], "args": {"path": "marvin/two", "entry_id": "${entry.id}"}},
        ]
    )
    flow.session.commit()

    res = _client(flow).post(f"{API}/{rows[0].id}/retry")

    assert res.status_code == 200 and _Flow.calls[-1][1]["path"] == "marvin/one"


def test_the_workflow_being_deleted_and_a_result_that_did_not_fail_both_refuse_a_retry(flow):
    row = _fail_the_hand_off(flow)
    client = _client(flow)
    flow.session.delete(flow.workflow)
    flow.session.commit()

    gone = client.post(f"{API}/{row.id}/retry")

    assert gone.status_code == 409 and "Only a failed hand-off from a workflow" in gone.json()["detail"]
    assert [i["canRetry"] for i in client.get(API).json()["items"]] == [False]


def test_a_failure_reported_by_a_reply_with_no_workflow_cannot_be_retried(flow):
    _report(flow, "error", integration="hooks", remote_id="unannounced", entry_id=str(flow.a.id))
    (row,) = _rows(flow)

    res = _client(flow).post(f"{API}/{row.id}/retry")

    assert res.status_code == 409 and not _client(flow).get(f"{API}/{row.id}").json()["result"]["canRetry"]


# ── retention ───────────────────────────────────────────────────────────────────────────────────────────────────


def _kinds_of_age(flow):
    """One result of each kind, each sent 40 days ago: succeeded, failed (dismissed), failed (not), in flight."""
    for entry in (flow.a, flow.b, flow.c):
        _publish(flow, entry)
    _publish(flow)
    done, dismissed, failed, flying = _rows(flow)
    _report(flow, "success", integration="hooks", remote_id=done.remote_id)
    _report(flow, "error", integration="hooks", remote_id=dismissed.remote_id)
    _report(flow, "error", integration="hooks", remote_id=failed.remote_id)
    results.dismiss(flow.session, _rows(flow, remote_id=dismissed.remote_id)[0], flow.ws.uid)
    flow.session.commit()
    for row in _rows(flow):
        _sent(flow, row, days=40)
    return {r.remote_id: r for r in _rows(flow)}


def test_pruning_drops_settled_and_dismissed_results_after_30_days_and_keeps_what_still_asks_for_a_look(flow):
    _kinds_of_age(flow)
    now = datetime.now(UTC)

    deleted = results.prune(flow.session, now - timedelta(days=30), now - timedelta(days=180))

    assert deleted == 2
    assert sorted(r.status for r in _rows(flow)) == ["failed", "in_flight"]
    assert all(r.dismissed_at is None for r in _rows(flow))


def test_pruning_drops_the_unhandled_ones_after_180_days(flow):
    for row in _kinds_of_age(flow).values():
        _sent(flow, row, days=200)
    now = datetime.now(UTC)

    assert results.prune(flow.session, now - timedelta(days=30), now - timedelta(days=180)) == 4
    assert _rows(flow) == []


def test_the_prune_task_is_a_daily_system_task_with_a_handler_and_a_retention_config():
    from marvin.services.database_report import TABLES
    from marvin.services.scheduled_tasks import TaskHandlerRegistry
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    (task,) = [d for d in SYSTEM_SCHEDULED_TASKS if d.slug == "prune_automation_results"]
    assert task.schedule_config == {"interval_seconds": 86400} and task.task_config == {"retention_days": 30} and task.enabled
    assert TaskHandlerRegistry.get_handler(task.task_type).admin_only
    assert TABLES["automation_results"][1].task == "prune_automation_results"


def test_the_prune_handler_deletes_by_the_tasks_retention_and_refuses_a_workspace(flow):
    from marvin.services.scheduled_tasks.handlers.maintenance import PruneAutomationResultsHandler

    _kinds_of_age(flow)
    handler = PruneAutomationResultsHandler()
    task = SimpleNamespace(group_id=None, task_config={"retention_days": 30})

    assert "Pruned 2 automation results" in handler.execute(task, None)
    assert handler.execute(task, None) is None  # nothing left to say
    assert "disabled" in handler.execute(SimpleNamespace(group_id=None, task_config={"retention_days": 0}), None)
    assert "admin-only" in handler.execute(SimpleNamespace(group_id=flow.gid, task_config={}), None)
    assert len(_rows(flow)) == 2


# ── the dashboard ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_dashboard_counts_failed_and_no_reply_hand_offs_but_not_ones_in_flight_or_dismissed(flow):
    for entry in (flow.a, flow.b, flow.c):
        _publish(flow, entry)
    _publish(flow)
    failed, dismissed, late, flying = _rows(flow)
    _report(flow, "error", integration="hooks", remote_id=failed.remote_id)
    _report(flow, "error", integration="hooks", remote_id=dismissed.remote_id)
    results.dismiss(flow.session, _rows(flow, remote_id=dismissed.remote_id)[0], flow.ws.uid)
    _sent(flow, _rows(flow, remote_id=late.remote_id)[0], hours=30)
    flow.session.commit()

    editor = _client(flow, WorkspaceRole.EDITOR).get("/api/platform/stats/dashboard").json()["attention"]
    author = _client(flow, WorkspaceRole.AUTHOR).get("/api/platform/stats/dashboard").json()["attention"]

    assert (editor["resultsFailed"], editor["resultsNoReply"]) == (1, 1)
    assert (author["resultsFailed"], author["resultsNoReply"]) == (0, 0)


# ── the SDK's mapping, as core uses it ──────────────────────────────────────────────────────────────────────────


def test_the_provider_answers_for_its_own_words_and_marvins(flow):
    provider = INTEGRATION_REGISTRY["fake_flow"]

    assert [provider.result_status(w) for w in ("success", "error", "waiting", "in_flight", "huh")] == [
        "succeeded",
        "failed",
        "in_flight",
        "in_flight",
        None,
    ]
