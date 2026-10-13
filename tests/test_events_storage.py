"""Events hub, slice 1: "who listens to what" lives in real columns and tables.

* Outgoing webhooks keep their subscriptions in `webhook_event_subscriptions`; the API still reads
  and writes `subscribedEvents`.
* A workflow's trigger lives in `trigger_type` / `trigger_event` / `trigger_ref` / `trigger_config`;
  the API still reads and writes `definition.trigger`, in the same shape, for every trigger type.
* Everything a blueprint creates records which integration (and blueprint) installed it.
* The two migrations move existing data there and back.
"""

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient

import marvin.db.migration_types as mt
from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.automations import WorkspaceAutomationModel, assemble_trigger, split_trigger

_VERSIONS = Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions"


def _migration(revision: str):
    path = next(_VERSIONS.glob(f"*_{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


storage_mig = _migration("cba7c23b692e")
provenance_mig = _migration("1dbc9b51d024")

# Every trigger shape the API accepts → what it returns. Identical except the old `{"event": X}`
# shape, which now comes back typed (the engine and the definition schema always read it as "event").
TRIGGERS = {
    "event": ({"type": "event", "event": "entry_published"}, None),
    "legacy event": ({"event": "entry_updated"}, {"type": "event", "event": "entry_updated"}),
    "event + extra key": ({"type": "event", "event": "asset_uploaded", "note": "kept"}, None),
    "manual": ({"type": "manual"}, None),
    "schedule": ({"type": "schedule", "schedule_type": "interval", "schedule_config": {"interval_seconds": 3600}}, None),
    "chained (any)": ({"type": "chained"}, None),
    "chained (target)": ({"type": "chained", "automation": "first-workflow"}, None),
    "on_error (any)": ({"type": "on_error", "automation": "any"}, None),
    "on_error (target)": ({"type": "on_error", "automation": "first-workflow"}, None),
    "incoming_webhook (any)": ({"type": "incoming_webhook"}, None),
    "incoming_webhook (slug)": ({"type": "incoming_webhook", "webhook": "square-events"}, None),
    "mcp": ({"type": "mcp"}, None),
}

# trigger shape → (trigger_type, trigger_event, trigger_ref, trigger_config)
COLUMNS = {
    "event": ("event", "entry_published", None, None),
    "legacy event": ("event", "entry_updated", None, None),
    "event + extra key": ("event", "asset_uploaded", None, {"note": "kept"}),
    "manual": ("manual", None, None, None),
    "schedule": ("schedule", None, None, {"schedule_type": "interval", "schedule_config": {"interval_seconds": 3600}}),
    "chained (any)": ("chained", "automation_ran", None, None),
    "chained (target)": ("chained", "automation_ran", "first-workflow", None),
    "on_error (any)": ("on_error", "automation_failed", "any", None),
    "on_error (target)": ("on_error", "automation_failed", "first-workflow", None),
    "incoming_webhook (any)": ("incoming_webhook", "incoming_webhook", None, None),
    "incoming_webhook (slug)": ("incoming_webhook", "incoming_webhook", "square-events", None),
    "mcp": ("mcp", None, None, None),
}

CONDITIONS = [{"field": "entry.status", "op": "eq", "value": "published"}]
ACTIONS = [{"kind": "handler", "task": "request_site_rebuild", "config": {"reason": "test"}}]


# ── the split itself (pure) ──────────────────────────────────────────────────


@pytest.mark.parametrize("shape", list(TRIGGERS))
def test_every_trigger_shape_splits_into_columns_and_back(shape):
    sent, returned = TRIGGERS[shape]
    columns = split_trigger(sent)
    assert tuple(columns.values()) == COLUMNS[shape]
    assert assemble_trigger(*columns.values()) == (returned or sent)


@pytest.mark.parametrize("trigger", [*(t for t, _ in TRIGGERS.values()), None, {"type": "someday", "x": 1}, {"type": "on_error", "automation": None}])
def test_the_migration_splits_exactly_like_the_model(trigger):
    """The migration carries its own copy (a migration must not change meaning when the model moves
    on); this keeps the two in step while they describe the same storage."""
    assert storage_mig._split_trigger(trigger) == split_trigger(trigger)
    assert storage_mig._assemble_trigger(*split_trigger(trigger).values()) == assemble_trigger(*split_trigger(trigger).values())


def test_no_trigger_stays_no_trigger():
    assert split_trigger(None) == {"trigger_type": None, "trigger_event": None, "trigger_ref": None, "trigger_config": None}
    assert assemble_trigger(None, None, None, None) is None


# ── workspace fixtures ───────────────────────────────────────────────────────


def _drop_workspace(db_session, gid):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    db_session.rollback()
    for model in (
        WorkspaceAutomationModel,
        ScheduledTaskModel,
        WorkspaceIncomingWebhookModel,
        IntegrationEventSubscriptionModel,
        Collections,
        IntegrationModel,
    ):
        db_session.query(model).filter(model.group_id == gid).delete(synchronize_session=False)
    for hook in db_session.query(GroupWebhooksModel).filter(GroupWebhooksModel.group_id == gid).all():
        db_session.delete(hook)  # the ORM delete takes its subscriptions along
    db_session.flush()
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    purge_group_dependents(db_session, gid)  # the Event Log rows the webhook routes now write, among others
    db_session.query(Users).filter(Users.group_id == gid).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id == gid).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def workspace(db_session):
    """A workspace whose admin is signed in to the API."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    g = Groups(session=db_session, name=f"evs-{gid.hex[:8]}", slug=f"evs-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"evs-{uid.hex[:8]}",
            email=f"evs-{uid.hex[:8]}@t.test",
            full_name="Events Admin",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uid, group_id=gid, active_group_id=gid, admin=True, is_superuser=False)
    yield gid
    app.dependency_overrides.pop(get_current_user, None)
    _drop_workspace(db_session, gid)


def _api(method: str, path: str, expect: int, json=None):
    kwargs = {"json": json} if json is not None else {}
    res = getattr(TestClient(app), method)(f"/api{path}", **kwargs)
    assert res.status_code == expect, res.text
    return res.json() if res.content else None


# ── workflows: API contract ──────────────────────────────────────────────────

WORKFLOW_KEYS = {
    "id",
    "groupId",
    "name",
    "slug",
    "enabled",
    "definition",
    "createdBy",
    "sourceIntegrationId",
    "sourceBlueprint",
    "sourceRecipe",
    "sourceRecipeVersion",
}


@pytest.mark.parametrize("shape", list(TRIGGERS))
def test_workflow_api_round_trips_every_trigger_type(db_session, workspace, shape):
    sent, returned = TRIGGERS[shape]
    definition = {"trigger": sent, "conditions": CONDITIONS, "actions": ACTIONS}
    expected = {**definition, "trigger": returned or sent}

    created = _api("post", "/automations", 201, {"name": f"WF {shape}", "definition": definition})
    assert set(created) == WORKFLOW_KEYS
    assert created["definition"] == expected
    assert created["sourceIntegrationId"] is None and created["sourceBlueprint"] is None
    assert _api("get", f"/automations/{created['id']}", 200)["definition"] == expected
    assert [w["definition"] for w in _api("get", "/automations", 200) if w["id"] == created["id"]] == [expected]

    row = db_session.get(WorkspaceAutomationModel, uuid.UUID(created["id"]))
    db_session.refresh(row)
    assert (row.trigger_type, row.trigger_event, row.trigger_ref, row.trigger_config) == COLUMNS[shape]
    assert row.body == {"conditions": CONDITIONS, "actions": ACTIONS}  # the trigger is not stored twice


def test_workflow_api_update_moves_the_trigger_and_keeps_the_rest(db_session, workspace):
    created = _api("post", "/automations", 201, {"name": "Moves", "definition": {"trigger": TRIGGERS["event"][0], "actions": ACTIONS}})
    for shape in ("incoming_webhook (slug)", "schedule", "chained (target)", "manual"):
        definition = {"trigger": TRIGGERS[shape][0], "conditions": CONDITIONS, "actions": ACTIONS}
        assert _api("patch", f"/automations/{created['id']}", 200, {"definition": definition})["definition"] == definition
    # Renaming alone leaves the definition as it was.
    renamed = _api("patch", f"/automations/{created['id']}", 200, {"name": "Renamed"})
    assert renamed["definition"] == {"trigger": {"type": "manual"}, "conditions": CONDITIONS, "actions": ACTIONS}


def test_workflow_without_a_trigger_reads_back_without_one(db_session, workspace):
    created = _api("post", "/automations", 201, {"name": "Bare", "definition": {"actions": ACTIONS}})
    assert created["definition"] == {"actions": ACTIONS}
    assert _api("post", "/automations", 201, {"name": "Empty"})["definition"] == {}


def test_a_schedule_trigger_still_gets_its_backing_task(db_session, workspace):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    created = _api("post", "/automations", 201, {"name": "Hourly", "definition": {"trigger": TRIGGERS["schedule"][0], "actions": ACTIONS}})
    task = db_session.query(ScheduledTaskModel).filter_by(group_id=workspace, slug=f"wf-{created['id']}").one()
    assert task.schedule_config == {"interval_seconds": 3600}


def test_provenance_is_not_writable_through_the_api(db_session, workspace):
    from marvin.db.models.groups.integrations import IntegrationModel

    integration = IntegrationModel(session=db_session, group_id=workspace, provider="acme", name="Acme", slug="acme", enabled=True, config={})
    db_session.add(integration)
    db_session.commit()
    spoof = {"sourceIntegrationId": str(integration.id), "sourceBlueprint": "acme-wf", "source_blueprint": "acme-wf"}
    created = _api("post", "/automations", 201, {"name": "Mine", "definition": {"trigger": {"type": "manual"}}, **spoof})
    assert created["sourceIntegrationId"] is None and created["sourceBlueprint"] is None
    updated = _api("patch", f"/automations/{created['id']}", 200, {"name": "Still mine", **spoof})
    assert updated["sourceIntegrationId"] is None and updated["sourceBlueprint"] is None


# ── webhooks: API contract ───────────────────────────────────────────────────

WEBHOOK_KEYS = {
    "enabled",
    "name",
    "url",
    "method",
    "webhookType",
    "scheduledTime",
    "headers",
    "subscribedEvents",
    "customPayload",
    "groupId",
    "id",
}


def test_webhook_api_reads_and_writes_subscribed_events(db_session, workspace):
    from marvin.db.models.groups.webhook_event_subscriptions import WebhookEventSubscriptionModel

    body = {
        "name": "Deploy hook",
        "url": "https://hooks.example.test/deploy",
        "webhookType": "event_driven",
        "subscribedEvents": ["webhook_triggered"],
    }
    created = _api("post", "/groups/webhooks", 201, body)
    assert set(created) == WEBHOOK_KEYS
    assert created["subscribedEvents"] == ["webhook_triggered"]
    hook_id = created["id"]

    def stored():
        return sorted(
            e
            for (e,) in db_session.query(WebhookEventSubscriptionModel.event_type).filter(
                WebhookEventSubscriptionModel.webhook_id == uuid.UUID(hook_id)
            )
        )

    assert stored() == ["webhook_triggered"]
    # The Events page's Subscribe adds one and PUTs the whole webhook back.
    updated = _api("put", f"/groups/webhooks/{hook_id}", 200, {**created, "subscribedEvents": ["webhook_triggered", "entry_published"]})
    assert updated["subscribedEvents"] == ["entry_published", "webhook_triggered"]
    assert stored() == ["entry_published", "webhook_triggered"]
    assert _api("get", f"/groups/webhooks/{hook_id}", 200)["subscribedEvents"] == ["entry_published", "webhook_triggered"]
    listed = [w for w in _api("get", "/groups/webhooks", 200)["items"] if w["id"] == hook_id]
    assert set(listed[0]) == WEBHOOK_KEYS and listed[0]["subscribedEvents"] == ["entry_published", "webhook_triggered"]
    # …and Unsubscribe removes it.
    assert _api("put", f"/groups/webhooks/{hook_id}", 200, {**created, "subscribedEvents": ["entry_published"]})["subscribedEvents"] == [
        "entry_published"
    ]
    assert stored() == ["entry_published"]
    assert _api("put", f"/groups/webhooks/{hook_id}", 200, {**created, "subscribedEvents": []})["subscribedEvents"] == []
    assert stored() == []
    # Deleting the webhook takes its subscriptions with it.
    _api("put", f"/groups/webhooks/{hook_id}", 200, {**created, "subscribedEvents": ["entry_published"]})
    _api("delete", f"/groups/webhooks/{hook_id}", 200)
    db_session.expire_all()
    assert stored() == []


def test_webhook_subscriptions_are_a_set(db_session, workspace):
    """The list never meant an order or repeats: duplicates collapse and it reads back sorted."""
    body = {
        "name": "Dupes",
        "url": "https://hooks.example.test/x",
        "webhookType": "event_driven",
        "subscribedEvents": ["b_event", "a_event", "b_event", ""],
    }
    assert _api("post", "/groups/webhooks", 201, body)["subscribedEvents"] == ["a_event", "b_event"]
    body = {"name": "None", "url": "https://hooks.example.test/y", "webhookType": "event_driven", "subscribedEvents": None}
    assert _api("post", "/groups/webhooks", 201, body)["subscribedEvents"] == []


def test_the_webhook_listener_and_deploy_targets_read_the_table(db_session, workspace):
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.services.event_bus_service.event_bus_listener import WebhookEventListener
    from marvin.services.event_bus_service.event_types import EventTypes, WebhookMode
    from marvin.services.site_rebuild import deploy_targets

    def hook(name, events, *, mode=WebhookMode.event_driven, enabled=True):
        row = GroupWebhooksModel(
            session=db_session,
            group_id=workspace,
            name=name,
            url="https://hooks.example.test/h",
            webhook_type=mode,
            enabled=enabled,
            subscribed_events=events,
        )
        db_session.add(row)
        return row

    rebuild = hook("Rebuild", ["webhook_triggered"])
    hook("Also published", ["entry_published", "webhook_triggered"])
    hook("Scheduled", ["webhook_triggered"], mode=WebhookMode.generic)
    hook("Off", ["webhook_triggered"], enabled=False)
    hook("Elsewhere", ["entry_published"])
    db_session.commit()

    assert sorted(t.name for t in deploy_targets(db_session, workspace)) == ["Also published", "Rebuild"]
    listener = WebhookEventListener(workspace)
    event = SimpleNamespace(event_type=EventTypes.webhook_triggered, document_data=None)
    assert sorted(w.name for w in listener.get_subscribers(event)) == ["Also published", "Rebuild"]
    event = SimpleNamespace(event_type=EventTypes.entry_published, document_data=None)
    assert sorted(w.name for w in listener.get_subscribers(event)) == ["Also published", "Elsewhere"]
    assert rebuild.subscribed_events == ["webhook_triggered"]


# ── the engine selects by trigger_event ──────────────────────────────────────


def test_engine_runs_only_the_workflows_listening_to_the_event(db_session, workspace):
    from marvin.services.automation.engine import run_automations_for_event

    def workflow(slug, trigger, enabled=True):
        row = WorkspaceAutomationModel(
            session=db_session, group_id=workspace, name=slug, slug=slug, enabled=enabled, definition={"trigger": trigger, "actions": ACTIONS}
        )
        db_session.add(row)

    workflow("on-publish", {"type": "event", "event": "entry_published"})
    workflow("on-publish-legacy", {"event": "entry_published"})
    workflow("on-publish-off", {"type": "event", "event": "entry_published"}, enabled=False)
    workflow("on-update", {"type": "event", "event": "entry_updated"})
    workflow("hook-a", {"type": "incoming_webhook", "webhook": "hook-a"})
    workflow("hook-any", {"type": "incoming_webhook"})
    workflow("after-publish", {"type": "chained", "automation": "on-publish"})
    workflow("after-anything", {"type": "chained"})
    workflow("on-fail", {"type": "on_error", "automation": "any"})
    workflow("by-hand", {"type": "manual"})
    workflow("tool", {"type": "mcp"})
    db_session.commit()

    def count(event_ctx):
        return run_automations_for_event(db_session, workspace, event_ctx, run_action=lambda *a, **k: {}, dry_run=True)

    assert count({"event_type": "entry_published"}) == 2
    assert count({"event_type": "entry_updated"}) == 1
    assert count({"event_type": "incoming_webhook", "webhook_slug": "hook-a"}) == 2
    assert count({"event_type": "incoming_webhook", "webhook_slug": "hook-b"}) == 1
    assert count({"event_type": "automation_ran", "automation_slug": "on-publish"}) == 2
    assert count({"event_type": "automation_ran", "automation_slug": "on-update"}) == 1
    assert count({"event_type": "automation_failed", "automation_slug": "on-update"}) == 1
    assert count({"event_type": "asset_uploaded"}) == 0


# ── "installed by" on what a blueprint creates ───────────────────────────────


def _integration(db_session, gid, provider, slug):
    from marvin.db.models.groups.integrations import IntegrationModel

    row = IntegrationModel(session=db_session, group_id=gid, provider=provider, name=provider.title(), slug=slug, enabled=True, config={})
    db_session.add(row)
    db_session.commit()
    return row


def _blueprints():
    from marvin.schemas.platform.blueprints import Blueprint

    return [
        Blueprint(kind="collection", slug="acme-picks", name="Acme picks", source="acme", payload={"is_smart": False}),
        Blueprint(
            kind="scheduled_task",
            slug="acme-sync",
            name="Acme sync",
            source="acme",
            payload={
                "schedule_type": "interval",
                "schedule_config": {"interval_seconds": 3600},
                "task_type": "remove_orphaned_assets",
                "task_config": {},
            },
        ),
        Blueprint(kind="incoming_webhook", slug="acme-events", name="Acme events", source="acme", payload={}),
        Blueprint(
            kind="workflow",
            slug="acme-on-publish",
            name="Acme: on publish",
            source="acme",
            payload={"definition": {"trigger": {"type": "event", "event": "entry_published"}, "actions": ACTIONS}},
        ),
        Blueprint(
            kind="event_subscription",
            slug="acme-announce",
            name="Announce",
            source="acme",
            payload={"event_type": "entry_published", "action": "notify"},
        ),
    ]


def _provenance(db_session, gid):
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    db_session.expire_all()
    return {
        model.__tablename__: {(r.source_integration_id, r.source_blueprint) for r in db_session.query(model).filter(model.group_id == gid)}
        for model in (Collections, ScheduledTaskModel, WorkspaceIncomingWebhookModel, WorkspaceAutomationModel, IntegrationEventSubscriptionModel)
    }


def test_everything_a_blueprint_creates_records_its_integration(db_session, workspace):
    from marvin.services.blueprints import apply_many

    acme = _integration(db_session, workspace, "acme", "acme")
    results = apply_many(db_session, workspace, _blueprints())
    db_session.commit()
    assert all(r.created for r in results), [r.detail for r in results]

    seen = _provenance(db_session, workspace)
    assert seen["collections"] >= {(acme.id, "acme-picks")}
    assert seen["scheduled_tasks"] == {(acme.id, "acme-sync")}
    assert seen["workspace_incoming_webhooks"] == {(acme.id, "acme-events")}
    assert seen["workspace_automations"] == {(acme.id, "acme-on-publish")}
    assert seen["integration_event_subscriptions"] == {(acme.id, "acme-announce")}

    # …and the API shows it, read-only.
    workflow = next(w for w in _api("get", "/automations", 200) if w["slug"] == "acme-on-publish")
    assert (workflow["sourceIntegrationId"], workflow["sourceBlueprint"]) == (str(acme.id), "acme-on-publish")
    hook = next(h for h in _api("get", "/incoming-webhooks", 200) if h["slug"] == "acme-events")
    assert (hook["sourceIntegrationId"], hook["sourceBlueprint"]) == (str(acme.id), "acme-events")


def test_with_two_connections_the_one_the_card_passed_wins_else_none(db_session, workspace):
    from marvin.services.blueprints import apply_blueprint

    first = _integration(db_session, workspace, "acme", "acme-1")
    _integration(db_session, workspace, "acme", "acme-2")
    workflow, collection = _blueprints()[3], _blueprints()[0]
    assert apply_blueprint(db_session, workspace, workflow, integration_id=first.id).created
    assert apply_blueprint(db_session, workspace, collection).created
    db_session.commit()
    seen = _provenance(db_session, workspace)
    assert seen["workspace_automations"] == {(first.id, "acme-on-publish")}
    assert (None, "acme-picks") in seen["collections"]  # two connections and none named: not guessed


def test_a_core_blueprint_records_the_blueprint_but_no_integration(db_session, workspace):
    from marvin.services.blueprints import apply_blueprint, get_blueprint

    assert apply_blueprint(db_session, workspace, get_blueprint("new-this-week")).created
    db_session.commit()
    assert (None, "new-this-week") in _provenance(db_session, workspace)["collections"]


def test_uninstalling_the_integration_keeps_the_rows(db_session, workspace):
    from marvin.services.blueprints import apply_blueprint

    acme = _integration(db_session, workspace, "acme", "acme")
    assert apply_blueprint(db_session, workspace, _blueprints()[3]).created
    db_session.commit()
    db_session.delete(acme)
    db_session.commit()
    assert _provenance(db_session, workspace)["workspace_automations"] == {(None, "acme-on-publish")}


# ── migration 1: data moves there and back ───────────────────────────────────


@pytest.fixture
def scratch():
    """An in-memory DB with just the columns the storage migration touches."""
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    hooks = sa.Table(
        "webhook_urls",
        meta,
        sa.Column("id", mt.GUID(), primary_key=True),
        sa.Column("name", sa.String()),
        sa.Column("subscribed_events", sa.JSON(), nullable=True),
    )
    autos = sa.Table("workspace_automations", meta, sa.Column("id", mt.GUID(), primary_key=True), sa.Column("definition", sa.JSON(), nullable=True))
    meta.create_all(engine)
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        original = storage_mig.op
        storage_mig.op = ops
        try:
            yield conn, hooks, autos
        finally:
            storage_mig.op = original


def test_storage_migration_moves_the_json_out_and_back(scratch):
    conn, hooks, autos = scratch
    lists = {
        "null": None,
        "empty": [],
        "one": ["entry_published"],
        "dupes": ["webhook_triggered", "entry_published", "webhook_triggered"],
        "junk": ["entry_created", 5, ""],
    }
    hook_ids = {name: uuid.uuid4() for name in lists}
    conn.execute(hooks.insert(), [{"id": hook_ids[n], "name": n, "subscribed_events": v} for n, v in lists.items()])
    definitions = {name: {"trigger": t, "conditions": CONDITIONS, "actions": ACTIONS} for name, (t, _) in TRIGGERS.items()}
    definitions |= {"no trigger": {"actions": ACTIONS}, "empty": {}, "null": None}
    auto_ids = {name: uuid.uuid4() for name in definitions}
    conn.execute(autos.insert(), [{"id": auto_ids[n], "definition": d} for n, d in definitions.items()])

    storage_mig.upgrade()

    subs = conn.execute(sa.text("select webhook_id, event_type from webhook_event_subscriptions")).fetchall()
    by_hook: dict = {}
    for wid, ev in subs:
        by_hook.setdefault(uuid.UUID(wid), []).append(ev)
    assert {n: sorted(by_hook.get(i, [])) for n, i in hook_ids.items()} == {
        "null": [],
        "empty": [],
        "one": ["entry_published"],
        "dupes": ["entry_published", "webhook_triggered"],
        "junk": ["entry_created"],
    }
    assert "subscribed_events" not in {c["name"] for c in sa.inspect(conn).get_columns("webhook_urls")}
    rows = {
        uuid.UUID(r[0]): r[1:]
        for r in conn.execute(sa.text("select id, trigger_type, trigger_event, trigger_ref, trigger_config, definition from workspace_automations"))
    }
    import json

    for name, (shape_cols) in COLUMNS.items():
        ttype, event, ref, config, body = rows[auto_ids[name]]
        assert (ttype, event, ref, json.loads(config) if config else None) == shape_cols, name
        assert json.loads(body) == {"conditions": CONDITIONS, "actions": ACTIONS}
    assert rows[auto_ids["no trigger"]][0] is None and json.loads(rows[auto_ids["no trigger"]][4]) == {"actions": ACTIONS}

    storage_mig.downgrade()

    back_hooks = {uuid.UUID(r[0]): json.loads(r[1]) for r in conn.execute(sa.text("select id, subscribed_events from webhook_urls"))}
    assert {n: back_hooks[i] for n, i in hook_ids.items()} == {
        "null": [],
        "empty": [],
        "one": ["entry_published"],
        "dupes": ["entry_published", "webhook_triggered"],
        "junk": ["entry_created"],
    }
    back = {
        uuid.UUID(r[0]): json.loads(r[1]) if r[1] is not None else None
        for r in conn.execute(sa.text("select id, definition from workspace_automations"))
    }
    for name, (sent, returned) in TRIGGERS.items():
        assert back[auto_ids[name]] == {"trigger": returned or sent, "conditions": CONDITIONS, "actions": ACTIONS}, name
    assert back[auto_ids["no trigger"]] == {"actions": ACTIONS}
    assert back[auto_ids["empty"]] == {}
    assert back[auto_ids["null"]] is None
    assert "webhook_event_subscriptions" not in sa.inspect(conn).get_table_names()


# ── migration 2: matching existing rows to their integration ─────────────────


def _row(**kw):
    return SimpleNamespace(**{"slug": None, "name": None, **kw})


def test_provenance_backfill_matches_by_blueprint_slug_then_name_prefix():
    square, n8n, a1, a2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    integrations = {
        "square": [square],
        "n8n": [n8n],
        "buttondown": [a1, a2],
        "by_id": {square: "square", n8n: "n8n", a1: "buttondown", a2: "buttondown"},
    }
    match = provenance_mig._match

    assert match("workflow", _row(slug="square-list-for-sale", name="Square: list for sale"), integrations) == (square, "square-list-for-sale")
    assert match("incoming_webhook", _row(slug="n8n", name="n8n results"), integrations) == (n8n, "n8n")
    assert match("collection", _row(slug="n8n-failed", name="n8n: failed"), integrations) == (n8n, "n8n-failed")
    # A slug is only a blueprint's for that kind.
    assert match("collection", _row(slug="n8n", name="n8n"), integrations) == (None, None)
    # Name prefix: needs the colon, gives the integration but not the blueprint.
    assert match("workflow", _row(slug="square-custom", name="Square: my tweak"), integrations) == (square, None)
    assert match("workflow", _row(slug="n8n-ping", name="n8n ping"), integrations) == (None, None)
    # Two connections of the provider: unsure, left NULL.
    assert match("workflow", _row(slug="buttondown-issue-on-publish", name="Buttondown: email an issue"), integrations) == (None, None)
    # No connection of the provider at all.
    assert match("workflow", _row(slug="cloudflare-pages-deploy-failed", name="Cloudflare Pages: deploy failed"), integrations) == (None, None)
    assert match("collection", _row(slug="featured", name="Featured"), integrations) == (None, None)


def test_provenance_backfill_matches_subscriptions_by_their_own_integration():
    slack, apprise = uuid.uuid4(), uuid.uuid4()
    integrations = {"slack": [slack], "apprise": [apprise], "by_id": {slack: "slack", apprise: "apprise"}}
    match = provenance_mig._match
    sub = SimpleNamespace(integration_id=slack, event_type="entry_published", action="send_message")
    assert match("event_subscription", sub, integrations) == (slack, "announce-published-entries")
    sub = SimpleNamespace(integration_id=slack, event_type="entry_created", action="send_message")
    assert match("event_subscription", sub, integrations) == (None, None)
    sub = SimpleNamespace(integration_id=apprise, event_type="entry_created", action="notify")
    assert match("event_subscription", sub, integrations) == (None, None)
