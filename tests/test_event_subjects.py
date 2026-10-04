"""Every event names its subject where one exists.

The event log's entity_type / entity_id are set where the event is dispatched (or read off the
payload's own id field), so the admin can link a row to what it is about. A workflow run also names
what triggered it and what each step did, and a routine scheduled run with nothing to report logs
nothing.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from marvin.services.automation import engine
from marvin.services.automation.context import event_context, event_context_from_event
from marvin.services.automation.runner import AutomationActionError
from marvin.services.automation.summary import collapse, run_message, step_summary
from marvin.services.event_bus_service.event_types import (
    Event,
    EventAPIClientData,
    EventBusMessage,
    EventIncomingWebhookData,
    EventMemberData,
    EventOperation,
    EventTypes,
    EventWorkspaceData,
    event_entity,
)


@pytest.fixture
def dispatched(monkeypatch):
    """Every dispatch, as its keyword arguments, instead of publishing it."""
    calls = []

    class _Bus:
        def __init__(self, *a, **k):
            pass

        def dispatch(self, **kw):
            calls.append(kw)

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _Bus)
    return calls


def _of(calls, event_type):
    return [c for c in calls if c["event_type"] == event_type]


# ── Workflow runs ──────────────────────────────────────────────────────────────────────────────────
WEBHOOK_ID = uuid.uuid4()
GID = uuid.uuid4()


class _Session:
    """query() → the workflows; get() → the entry, or the named outgoing webhook."""

    def __init__(self, automations, entry=None):
        self._automations, self._entry = automations, entry

    def query(self, _model):
        rows = self._automations
        return SimpleNamespace(filter_by=lambda **kw: SimpleNamespace(all=lambda: rows))

    def get(self, model, _id):
        return SimpleNamespace(name="Buttondown: send issue") if model.__name__ == "GroupWebhooksModel" else self._entry


def _workflow(actions, trigger=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug="send-issue-to-buttondown",
        name="Send issue to Buttondown",
        enabled=True,
        created_by=None,
        definition={"trigger": trigger or {"event": "entry_published"}, "conditions": [], "actions": actions},
    )


def _entry():
    return SimpleNamespace(
        id=uuid.uuid4(), group_id=GID, status="published", title="Issue 12", slug="issue-12", entry_type=SimpleNamespace(slug="newsletter-issue")
    )


def _webhook_runner(session, group_id, action, context, **_):
    return {"status_code": 201, "ok": True, "webhook_id": action.get("webhook_id")}


def _run_for_entry(workflow, entry, run_action=_webhook_runner):
    ctx = event_context("entry_published", {"entry_id": str(entry.id)}, entity_id=entry.id, entity_type="entry")
    engine.run_automations_for_event(_Session([workflow], entry), GID, ctx, run_action=run_action)


def test_workflow_run_events_are_about_the_workflow(dispatched):
    workflow = _workflow([{"kind": "webhook", "webhook_id": str(WEBHOOK_ID)}])

    _run_for_entry(workflow, _entry())

    subjects = {(c["event_type"].name, c["entity_type"], c["entity_id"]) for c in dispatched}
    assert subjects == {("automation_started", "automation", workflow.id), ("automation_ran", "automation", workflow.id)}


def test_workflow_run_names_the_entry_that_triggered_it(dispatched):
    entry = _entry()

    _run_for_entry(_workflow([{"kind": "webhook", "webhook_id": str(WEBHOOK_ID)}]), entry)

    for call in dispatched:
        doc = call["document_data"]
        assert (doc.trigger_entity_type, doc.trigger_entity_id, doc.trigger_entity_label) == ("entry", entry.id, "Issue 12")


def test_automation_ran_summarises_its_steps(dispatched):
    _run_for_entry(_workflow([{"kind": "webhook", "webhook_id": str(WEBHOOK_ID)}]), _entry())

    (ran,) = _of(dispatched, EventTypes.automation_ran)
    assert ran["message"] == "Automation 'send-issue-to-buttondown' ran — webhook 'Buttondown: send issue' → 201"
    assert ran["document_data"].steps[0] == {
        "kind": "webhook",
        "target": "Buttondown: send issue",
        "outcome": "201",
        "ok": True,
        "error": None,
        "count": 1,
    }


def test_automation_failed_names_the_failing_step_and_error(dispatched):
    def failing(session, group_id, action, context, **_):
        if action["kind"] == "webhook":
            raise AutomationActionError("webhook POST https://api.buttondown.test -> 422: bad email")
        return {}

    workflow = _workflow([{"kind": "operation", "op": "generate-summary"}, {"kind": "webhook", "webhook_id": str(WEBHOOK_ID)}])

    _run_for_entry(workflow, _entry(), run_action=failing)

    (failed,) = _of(dispatched, EventTypes.automation_failed)
    assert failed["message"] == (
        "Automation 'send-issue-to-buttondown' failed — webhook 'Buttondown: send issue': webhook POST https://api.buttondown.test -> 422: bad email"
    )
    assert (failed["entity_type"], failed["document_data"].error) == ("automation", "webhook POST https://api.buttondown.test -> 422: bad email")


def test_webhook_triggered_run_names_the_incoming_webhook(dispatched):
    hook_id = uuid.uuid4()
    event = Event(
        message=EventBusMessage.from_type(EventTypes.incoming_webhook, body="received"),
        event_type=EventTypes.incoming_webhook,
        integration_id="incoming_webhook",
        document_data=EventIncomingWebhookData(
            webhook_id=hook_id, webhook_slug="buttondown", webhook_name="Buttondown events", workspace_id=uuid.uuid4()
        ),
        entity_id=hook_id,
        entity_type="incoming_webhook",
    )
    workflow = _workflow([{"kind": "operation", "op": "noop"}], trigger={"type": "incoming_webhook", "webhook": "buttondown"})

    engine.run_automations_for_event(_Session([workflow]), GID, event_context_from_event(event), run_action=lambda *a, **k: {})

    (ran,) = _of(dispatched, EventTypes.automation_ran)
    doc = ran["document_data"]
    assert (doc.trigger_entity_type, doc.trigger_entity_id, doc.trigger_entity_label) == ("incoming_webhook", hook_id, "Buttondown events")


def test_a_workflow_lifecycle_event_is_not_taken_for_an_entry():
    # automation_ran is about the workflow; a chained run's entry steps must not act on that id.
    workflow_id = uuid.uuid4()

    ctx = event_context("automation_ran", {"automation_id": str(workflow_id)}, entity_id=workflow_id, entity_type="automation")

    assert (ctx["entry_id"], ctx["entity_type"], ctx["entity_id"]) == (None, "automation", str(workflow_id))


def test_an_entry_event_still_supplies_its_entry_id():
    entry_id = uuid.uuid4()

    assert event_context("entry_published", {}, entity_id=entry_id, entity_type="entry")["entry_id"] == entry_id


def test_manual_run_has_no_trigger_reference(dispatched):
    workflow = _workflow([{"kind": "operation", "op": "noop"}], trigger={"type": "manual"})

    engine.run_automation_now(_Session([workflow]), GID, workflow, run_action=lambda *a, **k: {})

    (ran,) = _of(dispatched, EventTypes.automation_ran)
    assert (ran["entity_id"], ran["document_data"].trigger_entity_type) == (workflow.id, None)


def test_step_summary_collapses_a_target_querys_repeats_with_a_count():
    step = step_summary(None, {"kind": "entry", "op": "publish"}, output={"status": "published"})

    assert run_message("bulk", True, collapse([step, dict(step), dict(step)])) == "Automation 'bulk' ran — entry 'publish' → ok ×3"


def test_step_summary_counts_steps_past_the_listed_few():
    steps = [step_summary(None, {"kind": "handler", "task": f"t{i}"}, output={}) for i in range(5)]

    assert run_message("many", True, steps).endswith("handler 't2' → ok; +2 more steps")


def test_a_raw_url_webhook_step_is_named_by_its_host():
    assert (
        step_summary(None, {"kind": "webhook", "url": "https://hooks.example.test/x/y"}, output={"status_code": 204})["target"]
        == "hooks.example.test"
    )


# ── Scheduled tasks ───────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"subj-{gid.hex[:8]}", slug=f"subj-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield gid
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel, ScheduledTaskModel

    db_session.rollback()
    db_session.query(ScheduledTaskExecutionLogModel).filter(ScheduledTaskExecutionLogModel.group_id == gid).delete()
    db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _handler(result):
    from marvin.services.scheduled_tasks.handlers import ScheduledTaskHandler

    class _Handler(ScheduledTaskHandler):
        name = "test"

        def execute(self, task, event_bus):
            if isinstance(result, Exception):
                raise result
            return result

    return _Handler


def _run_task(db_session, workspace, monkeypatch, result, integration_id="scheduled_tasks"):
    """Run one scheduled task through the listener, its handler returning (or raising) `result`."""
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.services.event_bus_service.event_bus_listener import ScheduledTaskListener
    from marvin.services.event_bus_service.event_types import EventScheduledTaskData
    from marvin.services.scheduled_tasks import TaskHandlerRegistry

    monkeypatch.setitem(TaskHandlerRegistry._handlers, "test_subject_task", _handler(result))
    task = ScheduledTaskModel(
        session=db_session,
        group_id=workspace,
        name="Poll the inbox",
        slug=f"poll-{uuid.uuid4().hex[:6]}",
        schedule_type="interval",
        schedule_config={"minutes": 2},
        task_type="test_subject_task",
        task_config={},
    )
    db_session.add(task)
    db_session.commit()
    event = Event(
        message=EventBusMessage.from_type(EventTypes.scheduled_task_triggered, body="triggered"),
        event_type=EventTypes.scheduled_task_triggered,
        integration_id=integration_id,
        document_data=EventScheduledTaskData.from_model(task),
        workspace_id=workspace,
    )
    ScheduledTaskListener(workspace).publish_to_subscribers(event, ["scheduled_task_handler"])
    return task.id


def test_an_idle_routine_run_emits_no_completed_event(db_session, workspace, monkeypatch, dispatched):
    _run_task(db_session, workspace, monkeypatch, None)

    assert _of(dispatched, EventTypes.scheduled_task_completed) == []


def test_a_routine_run_with_output_completes_about_its_task(db_session, workspace, monkeypatch, dispatched):
    task_id = _run_task(db_session, workspace, monkeypatch, "Published 2 entries")

    (done,) = _of(dispatched, EventTypes.scheduled_task_completed)
    assert (done["entity_type"], done["entity_id"]) == ("scheduled_task", task_id)


def test_a_run_now_with_nothing_to_do_still_completes(db_session, workspace, monkeypatch, dispatched):
    _run_task(db_session, workspace, monkeypatch, None, integration_id="platform_api")

    assert len(_of(dispatched, EventTypes.scheduled_task_completed)) == 1


def test_a_failed_run_is_logged_about_its_task(db_session, workspace, monkeypatch, dispatched):
    task_id = _run_task(db_session, workspace, monkeypatch, RuntimeError("inbox unreachable"))

    (failed,) = _of(dispatched, EventTypes.scheduled_task_failed)
    assert (failed["entity_type"], failed["entity_id"]) == ("scheduled_task", task_id)


# ── AI ────────────────────────────────────────────────────────────────────────────────────────────
def test_an_auto_index_is_about_the_one_item_it_indexed(monkeypatch, dispatched):
    from marvin.services.event_bus_service.event_bus_listener import IndexingReactionListener

    entry_id = uuid.uuid4()
    listener = IndexingReactionListener(uuid.uuid4())
    monkeypatch.setattr(listener, "ensure_repos", lambda gid: _NullRepos())

    listener._emit_reindexed("text-embedding-3-small", 3, "entry", "on published", entity_id=entry_id)

    (call,) = dispatched
    assert (call["entity_type"], call["entity_id"]) == ("entry", entry_id)


class _NullRepos:
    def __enter__(self):
        return SimpleNamespace(groups=SimpleNamespace(get_one=lambda _id: None))

    def __exit__(self, *exc):
        return False


def _ai_execution(entity_type=None, entity_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        operation_slug="answer-workspace-question",
        provider_type="anthropic",
        model_id="claude",
        entity_type=entity_type,
        entity_id=entity_id,
        total_tokens=10,
        estimated_cost_usd=0.001,
    )


def _emit_ai_event(execution):
    from marvin.routes.ai.operations_controller import AIOperationsController

    calls = []
    host = SimpleNamespace(
        event_bus=SimpleNamespace(dispatch=lambda **kw: calls.append(kw)), group_id=uuid.uuid4(), group=None, user=None, logger=None
    )
    AIOperationsController._emit_ai_event(host, execution, "completed", None)
    return calls[0]


def test_an_ai_operation_on_an_entry_is_about_the_entry():
    entry_id = uuid.uuid4()

    call = _emit_ai_event(_ai_execution("entry", entry_id))

    assert (call["entity_type"], call["entity_id"]) == ("entry", entry_id)


def test_an_ai_operation_with_no_target_is_about_its_run():
    execution = _ai_execution()

    call = _emit_ai_event(execution)

    assert (call["entity_type"], call["entity_id"]) == ("ai_execution", execution.id)


# ── Site rebuilds and deploys: about the workspace's deploy target ────────────────────────────────
def _deploy_hook(db_session, workspace, events=("webhook_triggered",)):
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.services.event_bus_service.event_types import WebhookMode

    hook = GroupWebhooksModel(
        session=db_session,
        group_id=workspace,
        name="Pages deploy hook",
        enabled=True,
        url="https://deploy.example.test/hook",
        webhook_type=WebhookMode.event_driven,
        subscribed_events=list(events),
    )
    db_session.add(hook)
    db_session.commit()
    return hook.id


@pytest.fixture
def site_workspace(db_session, workspace):
    yield workspace
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    db_session.rollback()
    db_session.query(GroupWebhooksModel).filter(GroupWebhooksModel.group_id == workspace).delete()
    db_session.commit()


def test_a_sent_site_rebuild_is_about_the_deploy_hook(db_session, site_workspace, dispatched):
    from marvin.services.scheduled_tasks.handlers.publishing import dispatch_site_rebuild

    hook_id = _deploy_hook(db_session, site_workspace)

    dispatch_site_rebuild(site_workspace, "content change", SimpleNamespace(dispatch=lambda **kw: dispatched.append(kw)))

    (sent,) = _of(dispatched, EventTypes.webhook_triggered)
    assert (sent["entity_type"], sent["entity_id"]) == ("webhook", hook_id)


def test_a_reported_deploy_is_about_the_deploy_hook(db_session, site_workspace, dispatched):
    from marvin.services.automation.actions.emit_event import run_emit_event
    from marvin.services.automation.authz import ROLE_ADMIN

    hook_id = _deploy_hook(db_session, site_workspace)

    run_emit_event(
        db_session,
        site_workspace,
        {"kind": "emit_event", "event": "site_deployment_completed", "deployment_id": "dep-1"},
        {"event": {}, "depth": 0},
        authorizer_role=ROLE_ADMIN,
    )

    (call,) = dispatched
    assert (call["entity_type"], call["entity_id"], call["document_data"].deployment_id) == ("webhook", hook_id, "dep-1")


def test_with_two_deploy_targets_a_rebuild_names_neither(db_session, site_workspace):
    from marvin.services.site_rebuild import deploy_target

    _deploy_hook(db_session, site_workspace)
    _deploy_hook(db_session, site_workspace)

    assert deploy_target(db_session, site_workspace) is None


def test_a_hook_on_other_events_is_not_a_deploy_target(db_session, site_workspace):
    from marvin.services.site_rebuild import deploy_target

    _deploy_hook(db_session, site_workspace, events=("entry_published",))

    assert deploy_target(db_session, site_workspace) is None


# ── Families named by their payload's own id ──────────────────────────────────────────────────────
def _entity_of(document_data):
    return event_entity(SimpleNamespace(document_data=document_data, entity_id=None, entity_type=None))


def test_api_client_events_are_about_the_api_client():
    client_id = uuid.uuid4()
    data = EventAPIClientData(
        operation=EventOperation.create,
        api_client_id=client_id,
        api_client_name="Site",
        api_client_slug="site",
        workspace_id=uuid.uuid4(),
        permissions={},
        enabled=True,
    )

    assert _entity_of(data) == ("api_client", client_id)


def test_member_events_are_about_the_member():
    user_id = uuid.uuid4()
    data = EventMemberData(operation=EventOperation.update, workspace_id=uuid.uuid4(), user_id=user_id, username="grace", role="ADMIN")

    assert _entity_of(data) == ("member", user_id)


def test_workspace_events_are_about_the_workspace():
    workspace_id = uuid.uuid4()
    data = EventWorkspaceData(operation=EventOperation.update, workspace_id=workspace_id, workspace_name="W", workspace_slug="w")

    assert _entity_of(data) == ("workspace", workspace_id)


# ── Sign-up and invitations, through the API ──────────────────────────────────────────────────────
@pytest.fixture
def invite(db_session, workspace):
    from marvin.db.models.groups.invite_tokens import GroupInviteToken
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users.roles import WorkspaceRole
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers
    from marvin.repos.all_repositories import get_repositories
    from marvin.schemas.group.invite_token import InviteTokenSave

    token = f"tok-{uuid.uuid4().hex[:10]}"
    row = get_repositories(db_session, group_id=None).group_invite_tokens.create(
        InviteTokenSave(uses_left=1, workspace_role=WorkspaceRole.EDITOR, group_id=workspace, token=token)
    )
    yield SimpleNamespace(token=token, id=row.id, workspace=workspace)
    db_session.rollback()
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id == workspace).delete()
    db_session.query(WorkspaceMembers).filter(WorkspaceMembers.group_id == workspace).delete()
    db_session.query(GroupInviteToken).filter(GroupInviteToken.group_id == workspace).delete()
    db_session.query(Users).filter(Users.group_id == workspace).delete()
    db_session.commit()


def test_signup_by_invitation_logs_the_user_and_the_invitation(client, db_session, invite):
    from marvin.db.models.platform.event_log import EventLogModel

    marker = invite.token[-6:]
    response = client.post(
        "/api/users/register",
        json={
            "groupToken": invite.token,
            "email": f"grace-{marker}@t.test",
            "username": f"grace-{marker}",
            "fullName": "Grace",
            "password": "long-enough-pw",
            "passwordConfirm": "long-enough-pw",
        },
    )
    assert response.status_code == 201, response.text
    user_id = uuid.UUID(response.json()["id"])

    db_session.expire_all()
    rows = {
        r.event_type: (r.entity_type, r.entity_id) for r in db_session.query(EventLogModel).filter(EventLogModel.workspace_id == invite.workspace)
    }
    assert (rows.get("user_signup"), rows.get("invitation_accepted")) == (("user", user_id), ("invitation", invite.id))


def test_event_log_summary_exposes_the_runs_trigger():
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.schemas.platform.event_log import EventLogSummary

    entry_id = str(uuid.uuid4())
    row = EventLogModel(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        event_type="automation_ran",
        occurred_at=datetime.now(UTC),
        workspace_id=uuid.uuid4(),
        entity_type="automation",
        entity_id=uuid.uuid4(),
        integration_id="automation",
        event_data={"documentData": {"triggerEntityType": "entry", "triggerEntityId": entry_id, "triggerEntityLabel": "Issue 12"}},
        message_title="Automation Ran",
    )

    summary = EventLogSummary.model_validate(row)

    assert (summary.related_entity_type, summary.related_entity_id, summary.related_entity_label) == ("entry", entry_id, "Issue 12")
