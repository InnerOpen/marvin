"""Operational events as workflow triggers: a failed webhook delivery, a budget crossing, a connection that needs
attention, a failed scheduled task.

A workflow can start on any of them (the builder's "Operations" heading, `${event.<field>}`), but never on a failure
its own run caused — its webhook step, its AI call, its integration step, the delivery of an event it sent — so
answering a failure can't start a loop. The failure of such a workflow still reaches people through Settings →
Automation → Notifications, which needs no workflow.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
import requests

from marvin.services.automation.context import event_context
from marvin.services.automation.engine import run_automations_for_event
from marvin.services.automation.recorder import ExecutionRecorder
from marvin.services.event_bus_service import event_types as et
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import EventTypes
from marvin.services.events.event_catalog import (
    CATALOG_BY_TYPE,
    COMMON_VARS,
    OPERATIONAL_EVENT_TYPES,
    OPERATIONS,
    TRIGGERABLE_EVENT_TYPES,
    operational_fields,
    trigger_groups,
)
from tests import test_workspace_notifications as wn

world = wn.world  # a workspace with one member per role; email captured

OPS = {
    "ai_budget_threshold_reached": et.EventAIBudgetData,
    "ai_budget_exceeded": et.EventAIBudgetData,
    "integration_attention_needed": et.EventIntegrationAttentionData,
    "integration_attention_resolved": et.EventIntegrationAttentionData,
    "webhook_delivery_failed": et.EventWebhookDeliveryData,
    "scheduled_task_failed": et.EventScheduledTaskData,
}


# ── the catalogue ────────────────────────────────────────────────────────────


def test_the_operational_events_are_triggerable_under_one_heading():
    assert set(OPS) == OPERATIONAL_EVENT_TYPES <= TRIGGERABLE_EVENT_TYPES
    assert trigger_groups()[OPERATIONS] == [e for e in CATALOG_BY_TYPE if e in OPS]
    for name in OPS:
        entry = CATALOG_BY_TYPE[name]
        assert entry.enabled and not entry.hidden and entry.scope == "workspace", name  # a workflow is a workspace's own
    # what stays out: the events that report nothing a person must act on
    for name in ("scheduled_task_completed", "scheduled_task_started", "ai_model_unpriced", "integration_action_enabled"):
        assert name not in OPERATIONAL_EVENT_TYPES


@pytest.mark.parametrize("name", sorted(OPS))
def test_every_field_offered_is_a_field_of_the_payload_that_sends_it(name):
    """`${event.<field>}` reads the payload's own keys: a field the catalogue offers that the payload lacks would
    resolve to nothing, quietly."""
    offered = operational_fields(name)
    assert offered, name
    assert not set(offered) & {v.slug for v in COMMON_VARS}, "an email's extras aren't on $event"
    model_fields = set(OPS[name].model_fields)
    assert set(offered) <= model_fields, f"{name}: {sorted(set(offered) - model_fields)} aren't on {OPS[name].__name__}"
    assert all(f["type"] and f["description"] for f in offered.values())


def test_another_event_has_no_operational_fields():
    assert operational_fields("entry_published") == {} and operational_fields("custom.anything") == {}


def test_describe_event_and_the_guide_name_the_fields(db_session, world):
    from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.base import ToolContext
    from marvin.services.automation.authoring import authoring_guide, workspace_refs

    user = SimpleNamespace(
        id=world.users["admin"], group_id=world.gid, active_group_id=world.gid, admin=False, is_superuser=False,
        platform_role=PlatformRole.NONE, get_workspace_role=lambda g: WorkspaceRole.ADMIN,
    )  # fmt: skip
    ctx = ToolContext(session=db_session, group_id=world.gid, user=user)
    out = json.loads(get_tool("describe_event").handler(ctx, {"event": "webhook_delivery_failed"}))
    assert out["found"] and out["workflowTrigger"]["triggerable"] is True
    assert {"webhook_name", "delivered_event_type", "status_code", "error_message", "attempts"} <= set(out["workflowTrigger"]["fields"])
    assert "never runs for a failure its own run caused" in out["workflowTrigger"]["note"]
    assert "workflowTrigger" not in json.loads(get_tool("describe_event").handler(ctx, {"event": "entry_published"}))

    guide = authoring_guide(db_session, world.gid, "events")
    events = json.loads(guide) if isinstance(guide, str) else guide
    events = events.get("events", events)
    assert set(events["triggerable"][OPERATIONS]) == set(OPS)
    assert events["operations"]["fields"]["scheduled_task_failed"]["consecutive_failures"] == "count"
    assert "never woken by a failure its own run caused" in events["operations"]["note"]
    assert workspace_refs  # the guide builds from the same refs the editor does


# ── what the senders put in the payload ──────────────────────────────────────


def test_a_failed_scheduled_task_says_what_went_wrong(db_session, world, monkeypatch):
    """The workflow reads `${event.error_message}`: the scheduler puts the (shortened) error in the payload."""
    from datetime import UTC, datetime

    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.services.event_bus_service.event_bus_listener import ScheduledTaskListener
    from marvin.services.event_bus_service.event_types import EventScheduledTaskData

    task = ScheduledTaskModel(
        session=db_session, group_id=world.gid, name="Poll the shop", slug="poll-the-shop", task_type="ops_boom", enabled=True,
        schedule_type="interval", schedule_config={"interval_seconds": 3600},
    )  # fmt: skip
    db_session.add(task)
    db_session.commit()
    sent: list[dict] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
    repos = SimpleNamespace(
        session=db_session,
        scheduled_task_executions=SimpleNamespace(log_execution=lambda **k: None),
        scheduled_tasks=SimpleNamespace(update_execution_state=lambda **k: None, update_next_run=lambda *a: None, _compute_next_run=lambda *a: None),
    )
    triggering = SimpleNamespace(document_data=EventScheduledTaskData.from_model(task))
    message = "the shop said no " + "x" * 600

    ScheduledTaskListener(world.gid)._handle_task_failure(
        repos, task, datetime.now(UTC), message, None, EventBusService(bg_tasks=None), triggering, RuntimeError(message)
    )

    (failed,) = sent
    assert failed["event_type"] == EventTypes.scheduled_task_failed and failed["group_id"] == world.gid
    payload = failed["document_data"]
    assert payload.error_message == message[:500] and payload.consecutive_failures == 1 and payload.task_slug == "poll-the-shop"


# ── origin: never answer a failure the workflow itself caused ─────────────────


@pytest.fixture
def desk(db_session, world, monkeypatch):
    """A workspace whose only outgoing webhook is down (it listens to entry_updated), an anchor entry, and a
    bystander workflow that only reads — it shows which failures a workflow answered."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.services.event_bus_service import publisher
    from marvin.services.event_bus_service.event_types import WebhookMode
    from marvin.services.group.group_purge import purge_group_dependents

    posts: list[str] = []

    def down(url, **kw):
        posts.append(str(url))
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(publisher.requests, "post", down)
    monkeypatch.setattr(publisher.time, "sleep", lambda *_: None)
    kind = EntryTypes(session=db_session, group_id=world.gid, name="Task", slug="task", schema_json={})
    db_session.add(kind)
    db_session.flush()
    anchor = Entries(session=db_session, group_id=world.gid, entry_type_id=kind.id, title="Anchor", slug=f"anchor-{world.marker}", status="draft")
    db_session.add(anchor)
    db_session.add(
        GroupWebhooksModel(
            session=db_session, group_id=world.gid, name="Search index", url="https://hooks.example.test/index",
            webhook_type=WebhookMode.event_driven, enabled=True, subscribed_events=["entry_updated"],
        )
    )  # fmt: skip
    db_session.commit()

    def workflow(slug: str, actions: list[dict], trigger: str = "webhook_delivery_failed", target: dict | None = None):
        definition = {"trigger": {"type": "event", "event": trigger}, "conditions": [], "actions": actions}
        row = WorkspaceAutomationModel(
            session=db_session, group_id=world.gid, name=slug.title(), slug=slug, enabled=True,
            definition={**definition, **({"target": target} if target else {})},
        )  # fmt: skip
        db_session.add(row)
        db_session.commit()
        return row

    rows: dict[str, WorkspaceAutomationModel] = {}

    def remembered(slug: str, *a, **kw):
        rows[slug] = workflow(slug, *a, **kw)
        return rows[slug]

    yield SimpleNamespace(workflow=remembered, anchor=anchor, posts=posts, rows=rows)
    db_session.rollback()
    db_session.query(WorkspaceAutomationModel).filter_by(group_id=world.gid).delete()
    db_session.query(GroupWebhooksModel).filter_by(group_id=world.gid).delete()
    purge_group_dependents(db_session, world.gid)
    db_session.commit()


def _runs(db_session, world, slug: str) -> int:
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    db_session.expire_all()
    return db_session.query(AutomationExecutionModel).filter_by(group_id=world.gid, automation_slug=slug).count()


def _answer(db_session, world, event_type: str, document: dict, **kw) -> int:
    ctx = event_context(event_type, document, correlation_id=kw.pop("correlation_id", "failure-1"), **kw)
    return run_automations_for_event(db_session, world.gid, ctx, recorder=ExecutionRecorder(db_session, world.gid))


FAILED = {
    "webhook_id": str(uuid.uuid4()),
    "webhook_name": "Search index",
    "delivered_event_type": "entry_updated",
    "error_message": "HTTP 503",
    "attempts": 3,
}


@pytest.mark.parametrize("bystander_first", [False, True], ids=["repair-runs-first", "bystander-runs-first"])
def test_a_workflow_does_not_answer_the_failure_its_own_work_caused(db_session, world, desk, bystander_first):
    """`repair` answers a failed delivery by sending entry_updated — which the down webhook then fails to deliver:
    a second failure, caused by `repair`. Only the bystander answers that one, whichever of the two runs first (the
    bystander that ran first has a run in the same chain, but it did not cause the failure)."""

    def repair():
        # (an entry event is built from the run's entry: an ops event has none, so the workflow targets the anchor)
        desk.workflow(
            "repair",
            [{"kind": "emit_event", "event": "entry_updated", "entity_id": "${entry.id}"}],
            target={"entity": "entry", "query": {"entry_type": "task"}},
        )

    def bystander():
        desk.workflow("bystander", [{"kind": "collect", "id": "all", "entity": "entry", "query": {}, "limit": 1}])

    for make in (bystander, repair) if bystander_first else (repair, bystander):
        make()

    assert _answer(db_session, world, "webhook_delivery_failed", FAILED) == 2

    assert desk.posts == ["https://hooks.example.test/index"] * 3  # the delivery really failed (three attempts), once
    assert _runs(db_session, world, "repair") == 1  # not woken by the failure it caused
    assert _runs(db_session, world, "bystander") == 2  # the failure nobody caused, and the one `repair` did


def test_the_failure_of_an_ops_workflow_still_reaches_the_admins(db_session, world, desk):
    desk.workflow("repair", [{"kind": "emit_event", "event": "entry_updated", "entity_id": "not-an-entry"}])

    EventBusService(bg_tasks=None).dispatch(
        integration_id="webhook_delivery",
        group_id=world.gid,
        event_type=EventTypes.webhook_delivery_failed,
        document_data=et.EventWebhookDeliveryData(
            webhook_id=uuid.uuid4(), webhook_name="Search index", delivered_event_type="entry_updated", error_message="HTTP 503", attempts=3
        ),
        message="Outgoing webhook 'Search index' couldn't deliver entry_updated: HTTP 503",
    )

    assert _runs(db_session, world, "repair") == 1
    assert set(wn._subjects(world)) == {"Workflow failed: Repair"}  # the existing channel, with no workflow in it
    assert {to for to, *_ in world.sent} == {world.emails["owner"], world.emails["admin"]}


def test_a_delivery_that_fails_after_the_run_ended_is_still_the_runs_failure(db_session, world, desk):
    """The delivery of an event a workflow sent can run later than the run (a background task): the failure names the
    workflows that sent the event, and those sit it out. It needs no run recorded — nothing is looked up."""
    desk.workflow("repair", [{"kind": "collect", "id": "all", "entity": "entry", "query": {}, "limit": 1}])
    bystander = desk.workflow("bystander", [{"kind": "collect", "id": "all", "entity": "entry", "query": {}, "limit": 1}])

    caused = [str(desk.rows["repair"].id)]
    assert _answer(db_session, world, "webhook_delivery_failed", FAILED, caused_by_workflows=caused) == 1  # only the bystander
    assert _runs(db_session, world, "repair") == 0 and _runs(db_session, world, "bystander") == 1
    # nobody's workflow caused this one: both answer it
    assert _answer(db_session, world, "webhook_delivery_failed", FAILED) == 2
    # a run the failure doesn't name (another chain, say) is not held back by having run
    both = [str(desk.rows["repair"].id), str(bystander.id)]
    assert _answer(db_session, world, "webhook_delivery_failed", FAILED, caused_by_workflows=both) == 0


def test_the_origin_rule_is_for_operational_events_only(db_session, world, desk):
    """Another event in a chain a workflow already ran in still reaches the workflows listening to it."""
    desk.workflow("on-update", [{"kind": "collect", "id": "all", "entity": "entry", "query": {}, "limit": 1}], trigger="entry_updated")
    doc = {"entry_id": str(desk.anchor.id), "entry_title": "Anchor"}
    for _ in range(2):
        assert (
            _answer(
                db_session, world, "entry_updated", doc, correlation_id="chain-a", reaction_depth=1, entity_id=desk.anchor.id, entity_type="entry"
            )
            == 1
        )


def test_a_failure_dispatched_through_the_bus_carries_the_delivered_events_chain(db_session, world, desk):
    """The publisher announces a failed delivery inside the chain of the event it carried."""
    from marvin.db.models.platform.event_log import EventLogModel

    desk.workflow("bystander", [{"kind": "collect", "id": "all", "entity": "entry", "query": {}, "limit": 1}])
    EventBusService(bg_tasks=None).dispatch(
        integration_id="automation",
        group_id=world.gid,
        event_type=EventTypes.entry_updated,
        document_data=et.EventEntryData(
            operation=et.EventOperation.update, entry_id=desk.anchor.id, entry_title="Anchor", workspace_id=world.gid, workspace_name=None
        ),
        entity_id=desk.anchor.id,
        entity_type="entry",
        reaction_depth=2,
        correlation_id="chain-z",
    )
    db_session.expire_all()
    (failure,) = db_session.query(EventLogModel).filter_by(workspace_id=world.gid, event_type="webhook_delivery_failed").all()
    assert failure.correlation_id == "chain-z"
    assert (failure.event_data.get("reactionDepth") or failure.event_data.get("reaction_depth")) == 2


def test_an_event_a_run_sends_names_the_workflows_that_sent_it_for_a_late_failure(db_session, world, desk):
    """The workflows running when an event is dispatched are read then and carried by the event; the failed delivery
    of it — announced by the publisher, possibly after the run ended — carries them on."""
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.services.event_bus_service.correlation import workflows_running

    bus = EventBusService(bg_tasks=None)
    entry = {
        "integration_id": "automation",
        "group_id": world.gid,
        "event_type": EventTypes.entry_updated,
        "document_data": et.EventEntryData(
            operation=et.EventOperation.update, entry_id=desk.anchor.id, entry_title="Anchor", workspace_id=world.gid, workspace_name=None
        ),
        "entity_id": desk.anchor.id,
        "entity_type": "entry",
    }
    token = workflows_running.set(frozenset({"wf-a", "wf-b"}))
    try:
        bus.dispatch(**entry)  # sent by a run
    finally:
        workflows_running.reset(token)
    bus.dispatch(**entry)  # sent by no one: its failure names no workflow

    db_session.expire_all()
    failures = (
        db_session.query(EventLogModel)
        .filter_by(workspace_id=world.gid, event_type="webhook_delivery_failed")
        .order_by(EventLogModel.occurred_at)
        .all()
    )
    named = [row.event_data.get("causedByWorkflows", row.event_data.get("caused_by_workflows")) for row in failures]
    assert named == [["wf-a", "wf-b"], []]
