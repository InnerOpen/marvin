"""A workspace's own events: `custom.<name>` registered with typed payload fields.

A workspace registers one (an admin, through the API: validated name, simply typed fields); a workflow's Emit
event step sends it with a templated payload held to those fields; a workflow can start on it, and webhook,
email and integration subscriptions can name it, like any other event; the editor, the Events pages, the AI's
`describe_event` and the authoring guide all list it. An emitted event carries reaction_depth + 1, so a chain of
workflows reacting to one another's custom events stops at engine.MAX_REACTION_DEPTH.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.custom_events import CustomEventDefinition
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.emit_event import run_emit_event
from marvin.services.automation.authz import ROLE_ADMIN
from marvin.services.events import custom_events

URL = "/api/groups/custom-events"
MILESTONE = {
    "title": "Milestone reached",
    "description": "A project reached a milestone.",
    "fields": [
        {"key": "milestone", "type": "string"},
        {"key": "points", "type": "number"},
        {"key": "public", "type": "boolean"},
        {"key": "reached_on", "type": "date"},
    ],
}


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    slug = f"cust-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    if db_session.query(GroupPreferencesModel).filter_by(group_id=gid).first() is None:
        db_session.add(GroupPreferencesModel(session=db_session, group_id=gid))
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=slug,
            email=f"{slug}@t.test",
            full_name="CUST",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(WorkspaceAutomationModel).filter_by(group_id=gid).delete()
    db_session.query(GroupWebhooksModel).filter_by(group_id=gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole | None) -> TestClient:
    members = [SimpleNamespace(group_id=workspace.gid, workspace_role=role)] if role else []
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="CUST",
        email=f"{workspace.slug}@t.test",
        platform_role="NONE",
        workspace_memberships=members,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _register(db_session, workspace, name="milestone", **body) -> CustomEventDefinition:
    definition = CustomEventDefinition(name=name, **{**MILESTONE, **body})
    custom_events.save(db_session, workspace.gid, definition)
    return definition


def _workflow(db_session, workspace, slug: str, trigger: str, actions: list[dict], *, enabled: bool = True):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = {"trigger": {"type": "event", "event": trigger}, "conditions": [], "actions": actions}
    row = WorkspaceAutomationModel(session=db_session, group_id=workspace.gid, name=slug, slug=slug, enabled=enabled, definition=definition)
    db_session.add(row)
    db_session.commit()
    return row


# ── names and fields ─────────────────────────────────────────────────────────


def test_a_name_is_custom_dot_and_a_slug():
    assert CustomEventDefinition(name="custom.kit_shipped").name == "kit_shipped"  # the prefix is accepted, then dropped
    assert CustomEventDefinition(name=" Kit_Shipped ").name == "kit_shipped"
    for bad in ("", "1st", "kit-shipped", "kit shipped", "kit.shipped", "custom.", "x" * 41, "é"):
        with pytest.raises(ValidationError):
            CustomEventDefinition(name=bad)


def test_fields_are_simply_typed_uniquely_keyed_and_few():
    assert [f.type for f in CustomEventDefinition(name="a", fields=[{"key": "x"}]).fields] == ["string"]  # the default
    for fields in (
        [{"key": "x", "type": "object"}],  # string, number, boolean, date only
        [{"key": "X-1"}],
        [{"key": "x"}, {"key": "x"}],
        [{"key": f"k{i}"} for i in range(13)],
    ):
        with pytest.raises(ValidationError):
            CustomEventDefinition(name="a", fields=fields)


# ── the registry ─────────────────────────────────────────────────────────────


def test_registering_replaces_by_name_and_removing_forgets(db_session, workspace):
    _register(db_session, workspace)
    _register(db_session, workspace, title="Renamed", fields=[{"key": "milestone"}])
    (only,) = custom_events.read(db_session, workspace.gid)
    assert (only.name, only.title, [f.key for f in only.fields]) == ("milestone", "Renamed", ["milestone"])
    assert custom_events.find(db_session, workspace.gid, "custom.milestone") and custom_events.find(db_session, workspace.gid, "custom.nope") is None

    custom_events.remove(db_session, workspace.gid, "milestone")
    assert custom_events.read(db_session, workspace.gid) == []
    with pytest.raises(KeyError):
        custom_events.remove(db_session, workspace.gid, "milestone")


def test_a_workspace_registers_at_most_fifty(db_session, workspace, monkeypatch):
    monkeypatch.setattr(custom_events, "MAX_EVENTS", 2)
    _register(db_session, workspace, "a")
    _register(db_session, workspace, "b")
    _register(db_session, workspace, "b", title="again")  # replacing one is not adding
    with pytest.raises(custom_events.CustomEventError, match="can register 2"):
        _register(db_session, workspace, "c")


def test_events_are_per_workspace(db_session, workspace):
    _register(db_session, workspace)
    assert custom_events.read(db_session, uuid.uuid4()) == []


def test_the_catalog_entry_makes_it_triggerable_emittable_and_visible(db_session, workspace):
    from marvin.services.events.event_catalog import CATEGORIES

    _register(db_session, workspace)
    (entry,) = custom_events.catalog_entries(db_session, workspace.gid)
    assert (entry.event_type, entry.name, entry.category) == ("custom.milestone", "Milestone reached", "Custom")
    assert entry.category in CATEGORIES and entry.triggerable and entry.emittable and entry.enabled and not entry.hidden
    assert [(v.slug, v.type) for v in entry.variables] == [
        ("milestone", "string"),
        ("points", "number"),
        ("public", "boolean"),
        ("reached_on", "date"),
    ]


# ── the payload ──────────────────────────────────────────────────────────────


def test_a_payload_is_held_to_the_fields_and_coerced(db_session, workspace):
    definition = _register(db_session, workspace)
    raw = {"milestone": "shipped", "points": "12", "public": "Yes", "reached_on": "2026-10-18T09:30:00Z"}
    assert custom_events.build_payload(definition, raw) == {"milestone": "shipped", "points": 12, "public": True, "reached_on": "2026-10-18"}
    assert custom_events.build_payload(definition, {"points": 2.5, "public": False, "milestone": 7}) == {
        "points": 2.5,
        "public": False,
        "milestone": "7",
    }
    assert custom_events.build_payload(definition, {"milestone": "", "points": None}) == {}  # empty is left out
    assert custom_events.build_payload(definition, None) == {}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"colour": "red"}, "no field colour"),
        ({"points": "many"}, "points"),
        ({"points": True}, "points"),
        ({"public": "maybe"}, "public"),
        ({"reached_on": "next week"}, "reached_on"),
        ({"milestone": {"a": 1}}, "milestone"),
        (["milestone"], "object"),
    ],
)
def test_a_payload_the_fields_cant_hold_is_refused(db_session, workspace, raw, message):
    definition = _register(db_session, workspace)
    with pytest.raises(custom_events.CustomEventError, match=message):
        custom_events.build_payload(definition, raw)


# ── the Emit event step ──────────────────────────────────────────────────────


@fixture
def dispatched(monkeypatch):
    calls = []

    class _Bus:
        def __init__(self, *a, **k):
            pass

        def dispatch(self, **kw):
            calls.append(kw)

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _Bus)
    return calls


def _emit(db_session, workspace, action, context=None, **kw):
    ctx = {"event": {"entry_id": str(uuid.uuid4())}, "entry": {"title": "Brass lantern"}, "depth": 0, **(context or {})}
    return run_emit_event(db_session, workspace.gid, {"kind": "emit_event", **action}, ctx, authorizer_role=ROLE_ADMIN, user_id=workspace.uid, **kw)


def test_emit_sends_the_event_with_a_templated_payload_one_hop_deeper(db_session, workspace, dispatched):
    _register(db_session, workspace)
    entry_id = uuid.uuid4()

    out = _emit(
        db_session,
        workspace,
        {
            "event": "custom.milestone",
            "payload": {"milestone": "shipped: ${entry.title}", "points": "${event.points}"},
            "message": "${entry.title} shipped",
        },
        {"event": {"entry_id": str(entry_id), "points": 5}, "depth": 1},
    )

    (call,) = dispatched
    assert out == {"emitted": "custom.milestone", "payload": {"milestone": "shipped: Brass lantern", "points": 5}, "reaction_depth": 2}
    assert call["event_type"].name == "custom.milestone" and call["reaction_depth"] == 2
    assert call["title"] == "Milestone reached" and call["message"] == "Brass lantern shipped"
    assert (call["entity_id"], call["entity_type"]) == (entry_id, "entry")
    doc = call["document_data"]
    assert (doc.event_name, doc.payload, doc.workspace_id) == ("milestone", out["payload"], workspace.gid)


def test_emit_needs_no_entry(db_session, workspace, dispatched):
    _register(db_session, workspace)
    _emit(db_session, workspace, {"event": "custom.milestone", "payload": {"milestone": "x"}, "entity_id": ""}, {"event": {}})
    assert dispatched[0]["entity_id"] is None and dispatched[0]["entity_type"] is None


def test_a_dry_run_shows_the_payload_and_sends_nothing(db_session, workspace, dispatched):
    _register(db_session, workspace)
    out = _emit(db_session, workspace, {"event": "custom.milestone", "payload": {"points": "3"}}, dry_run=True)
    assert out["dry_run"] and out["payload"] == {"points": 3} and out["reaction_depth"] == 1 and dispatched == []


def test_emit_refuses_what_is_not_registered_or_does_not_fit(db_session, workspace, dispatched):
    with pytest.raises(AutomationActionError, match="not a custom event of this workspace"):
        _emit(db_session, workspace, {"event": "custom.milestone"})
    _register(db_session, workspace)
    with pytest.raises(AutomationActionError, match="no field colour"):
        _emit(db_session, workspace, {"event": "custom.milestone", "payload": {"colour": "red"}})
    with pytest.raises(AutomationActionError, match="points"):
        _emit(db_session, workspace, {"event": "custom.milestone", "payload": {"points": "lots"}})
    assert dispatched == []


# ── the API ──────────────────────────────────────────────────────────────────


def test_an_admin_registers_lists_changes_and_removes(db_session, workspace):
    client = _sign_in(workspace, WorkspaceRole.ADMIN)

    created = client.put(f"{URL}/custom.milestone", json=MILESTONE)  # the prefix is accepted in the path
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "milestone" and body["eventType"] == "custom.milestone" and body["usedBy"] == []
    assert [(f["key"], f["type"]) for f in body["fields"]][:2] == [("milestone", "string"), ("points", "number")]

    changed = client.put(f"{URL}/milestone", json={"title": "Renamed", "fields": [{"key": "milestone"}]})
    assert changed.status_code == 200 and changed.json()["title"] == "Renamed"
    assert [e["eventType"] for e in client.get(URL).json()] == ["custom.milestone"]

    assert client.delete(f"{URL}/milestone").status_code == 204
    assert client.get(URL).json() == [] and client.delete(f"{URL}/milestone").status_code == 404


def test_a_change_is_recorded_as_a_workspace_settings_change(db_session, workspace, monkeypatch):
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    seen = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: seen.append(kw))
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    client.put(f"{URL}/milestone", json=MILESTONE)
    client.delete(f"{URL}/milestone")
    assert [(c["event_type"].name, c["document_data"].changed_fields, c["message"]) for c in seen] == [
        ("workspace_settings_changed", ["custom_events"], "Custom event custom.milestone registered"),
        ("workspace_settings_changed", ["custom_events"], "Custom event custom.milestone removed"),
    ]


@pytest.mark.parametrize("role", [None, WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, WorkspaceRole.EDITOR])
def test_only_an_admin_manages_them(db_session, workspace, role):
    client = _sign_in(workspace, role)
    assert client.get(URL).status_code in (401, 403)
    assert client.put(f"{URL}/milestone", json=MILESTONE).status_code in (401, 403)
    assert client.delete(f"{URL}/milestone").status_code in (401, 403)
    assert custom_events.read(db_session, workspace.gid) == []


@pytest.mark.parametrize(
    "path, body",
    [
        ("Milestone-1", {"fields": []}),
        ("milestone", {"fields": [{"key": "x", "type": "json"}]}),
        ("milestone", {"fields": [{"key": "x"}, {"key": "x"}]}),
        ("milestone", {"title": "t" * 81}),
    ],
)
def test_a_bad_name_or_field_is_a_422_and_stores_nothing(db_session, workspace, path, body):
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    assert client.put(f"{URL}/{path}", json=body).status_code == 422
    assert custom_events.read(db_session, workspace.gid) == []


def test_an_event_a_workflow_names_cant_be_removed(db_session, workspace):
    _register(db_session, workspace)
    _workflow(db_session, workspace, "award", "custom.milestone", [{"kind": "webhook", "url": "https://example.test"}])
    client = _sign_in(workspace, WorkspaceRole.ADMIN)

    assert client.get(URL).json()[0]["usedBy"] == ["award"]
    refused = client.delete(f"{URL}/milestone")
    assert refused.status_code == 409 and "award" in refused.json()["detail"]
    assert custom_events.find(db_session, workspace.gid, "custom.milestone")


# ── where the editor, the Events pages and the AI see them ───────────────────


def test_the_trigger_picker_and_emit_step_offer_registered_events(db_session, workspace):
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    before = client.get("/api/automations/options").json()
    assert "Custom" not in before["triggerGroups"] and not [e for e in before["emittable"] if e.startswith("custom.")]

    _register(db_session, workspace)
    options = client.get("/api/automations/options").json()
    assert options["triggerGroups"]["Custom"] == ["custom.milestone"] and "custom.milestone" in options["triggers"]
    assert "custom.milestone" in options["emittable"]


def test_subscription_pickers_list_them_with_their_fields_and_a_payload_example(db_session, workspace):
    _register(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    entries = {e["value"]: e for e in client.get("/api/event/types").json()}

    mine = entries["custom.milestone"]
    assert (mine["label"], mine["category"]) == ("Milestone reached", "Custom")
    assert [v["slug"] for v in mine["variables"]] == ["milestone", "points", "public", "reached_on"]
    assert mine["payloadExample"]["documentData"]["payload"] == {"milestone": "text", "points": 3, "public": True, "reached_on": "2026-10-18"}
    assert "custom.milestone" not in {e["value"] for e in _sign_in_other_workspace(db_session).get("/api/event/types").json()}


def _sign_in_other_workspace(db_session) -> TestClient:
    other = SimpleNamespace(gid=uuid.uuid4(), uid=uuid.uuid4(), slug="other")
    return _sign_in(other, WorkspaceRole.ADMIN)


def test_the_events_hub_knows_them(db_session, workspace):
    _register(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.ADMIN)

    counts = {c["eventType"]: c for c in client.get("/api/platform/event-types/connections").json()}
    assert counts["custom.milestone"]["name"] == "Milestone reached" and counts["custom.milestone"]["senders"] == 0

    _workflow(db_session, workspace, "award", "custom.milestone", [{"kind": "webhook", "url": "https://example.test"}])
    _workflow(
        db_session, workspace, "announce", "entry_published", [{"kind": "emit_event", "event": "custom.milestone", "payload": {"milestone": "x"}}]
    )
    detail = client.get("/api/platform/event-types/custom.milestone/connections").json()
    assert detail["category"] == "Custom"
    assert [r["name"] for r in detail["reactions"]] == ["award"] and detail["reactions"][0]["enabled"]
    assert [s["name"] for s in detail["senders"]] == ["announce"]

    assert client.get("/api/platform/event-types/custom.nope/connections").status_code == 404


def test_describe_event_explains_it(db_session, workspace):
    from marvin.services.ai.tools.builtins_insights import describe_event

    _register(db_session, workspace)
    _workflow(db_session, workspace, "award", "custom.milestone", [{"kind": "webhook", "url": "https://example.test"}])
    ctx = SimpleNamespace(
        session=db_session,
        group_id=workspace.gid,
        user=SimpleNamespace(platform_role="NONE", is_superuser=False, id=workspace.uid),
        repos=None,
    )
    out = json.loads(describe_event(ctx, {"event": "custom.milestone"}))
    assert out["found"] and out["eventType"] == "custom.milestone" and out["category"] == "Custom"
    assert out["payload"] == {"milestone": "string", "points": "number", "public": "boolean", "reached_on": "date"}
    assert [r["name"] for r in out["reactions"]] == ["award"]
    assert json.loads(describe_event(ctx, {"event": "milestone reached"}))["eventType"] == "custom.milestone"  # by hint, too


def test_the_authoring_guide_lists_them(db_session, workspace):
    from marvin.services.automation.authoring import authoring_guide

    assert "custom" not in authoring_guide(db_session, workspace.gid, "events")["events"]
    _register(db_session, workspace)
    events = authoring_guide(db_session, workspace.gid, "events")["events"]
    assert list(events["triggerable"]["Custom"]) == ["custom.milestone"] and "custom.milestone" in events["emittable"]
    assert events["custom"]["events"]["custom.milestone"] == {"milestone": "string", "points": "number", "public": "boolean", "reached_on": "date"}


def test_validation_knows_registered_events_and_their_fields(db_session, workspace):
    from marvin.services.automation.authoring import reference_issues

    def issues(trigger, step=None):
        definition = {"trigger": {"type": "event", "event": trigger}, "actions": [step or {"kind": "emit_event", "event": "custom.milestone"}]}
        return [(i["path"], i["message"]) for i in reference_issues(db_session, workspace.gid, definition)]

    assert [p for p, _ in issues("custom.milestone")] == ["trigger.event", "actions[0].event"]  # not registered yet
    _register(db_session, workspace)
    assert issues("custom.milestone", {"kind": "emit_event", "event": "custom.milestone", "payload": {"milestone": "${entry.title}"}}) == []
    [(path, message)] = issues("entry_published", {"kind": "emit_event", "event": "custom.milestone", "payload": {"colour": "red"}})
    assert path == "actions[0].payload" and "no field colour" in message and "milestone" in message


def test_the_rest_gate_accepts_the_step_and_its_validate_route_checks_the_names(db_session, workspace):
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    definition = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [{"kind": "emit_event", "event": "custom.milestone", "payload": {"milestone": "${entry.title}"}}],
    }
    unregistered = client.post("/api/automations/validate", json={"definition": definition}).json()["issues"]
    assert [(i["level"], i["path"]) for i in unregistered if "custom.milestone" in i["message"]] == [("warning", "actions[0].event")]
    _register(db_session, workspace)
    assert not [i for i in client.post("/api/automations/validate", json={"definition": definition}).json()["issues"] if "custom." in i["message"]]
    definition["actions"][0]["payload"] = {"colour": "red"}
    wrong = client.post("/api/automations/validate", json={"definition": definition}).json()["issues"]
    assert [(i["level"], i["path"]) for i in wrong if "no field colour" in i["message"]] == [("warning", "actions[0].payload")]


def test_a_recipe_that_starts_on_a_custom_event_is_offered_once_the_event_is_registered_with_its_fields(db_session, workspace):
    from marvin.services.automation import recipes
    from marvin.services.automation.authoring import workspace_refs

    item = recipes.entry("achievement-cabinet")
    missing = lambda: recipes.missing_prerequisites(item, workspace_refs(db_session, workspace.gid))  # noqa: E731

    assert missing() == ["needs the custom event custom.milestone (Settings → Automation → Custom events)"]
    _register(db_session, workspace, "milestone", fields=[{"key": "milestone"}])
    assert missing() == ["needs the custom event custom.milestone to carry the field(s) badge"]
    _register(db_session, workspace, "milestone", fields=[{"key": "milestone"}, {"key": "badge"}])
    assert missing() == []


# ── subscriptions: the same listeners, the same payload ──────────────────────


def _event(name: str, payload: dict, workspace, depth: int = 0):
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventCustomData, EventOperation

    return Event(
        message=EventBusMessage(title="Milestone reached", body="shipped"),
        event_type=custom_events.event_type_member(name),
        integration_id="automation",
        document_data=EventCustomData(
            operation=EventOperation.info, event_name=name.removeprefix("custom."), payload=payload, workspace_id=workspace.gid
        ),
        workspace_id=workspace.gid,
        reaction_depth=depth,
    )


def test_a_webhook_subscribed_to_it_is_sent_the_event_with_its_payload(db_session, workspace, monkeypatch):
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.services.event_bus_service.event_bus_listener import WebhookEventListener
    from marvin.services.event_bus_service.event_types import WebhookMode
    from marvin.services.event_bus_service.publisher import WebhookPublisher

    _register(db_session, workspace)
    hook = GroupWebhooksModel(
        session=db_session,
        group_id=workspace.gid,
        name="Hook",
        url="https://example.test/hook",
        enabled=True,
        webhook_type=WebhookMode.event_driven,
        subscribed_events=["custom.milestone"],
    )
    db_session.add(hook)
    db_session.commit()

    event = _event("custom.milestone", {"milestone": "shipped", "points": 5}, workspace)
    listener = WebhookEventListener(workspace.gid)
    subscribers = listener.get_subscribers(event)
    assert [s.name for s in subscribers] == ["Hook"]
    assert listener.get_subscribers(_event("custom.other", {}, workspace)) == []  # only the one it names

    sent = []
    monkeypatch.setattr(WebhookPublisher, "publish", lambda self, ev, urls, **kw: sent.append((urls, kw, jsonable_encoder(ev, exclude_none=True))))
    listener.publish_to_subscribers(event, subscribers)

    ((urls, _, body),) = sent
    assert [str(u) for u in urls] == ["https://example.test/hook"]
    assert body["eventType"] == "custom.milestone" and body["message"]["title"] == "Milestone reached"
    assert body["documentData"]["payload"] == {"milestone": "shipped", "points": 5}
    assert body["documentData"]["eventName"] == "milestone" and body["workspaceId"] == str(workspace.gid)


def test_an_email_template_reads_its_fields_like_any_event_variable():
    from marvin.services.events.event_variables import build_event_variables

    event = _event("custom.milestone", {"milestone": "shipped", "points": 5}, SimpleNamespace(gid=uuid.uuid4()))
    variables = build_event_variables(event)
    assert (variables["milestone"], variables["points"], variables["event_type"]) == ("shipped", 5, "custom.milestone")
    assert variables["payload"] == {"milestone": "shipped", "points": 5}


def test_the_event_log_and_workflows_listen_for_any_registered_name(db_session, workspace):
    from marvin.services.event_bus_service.event_bus_listener import AuditLogListener, AutomationReactionListener

    event = _event("custom.milestone", {}, workspace)
    assert AutomationReactionListener(workspace.gid).get_subscribers(event) == ["automation"]
    assert AuditLogListener(workspace.gid).get_subscribers(event) == ["database"]  # recorded: an uncatalogued type always is
    assert AutomationReactionListener(workspace.gid).get_subscribers(_event("custom.milestone", {}, workspace, depth=3)) == []


# ── the whole chain, on the real bus: emit → trigger → emit … until the depth bound ──


def test_a_chain_of_workflows_reacting_to_each_others_events_stops_at_the_depth_bound(db_session, workspace, monkeypatch):
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.services.automation.engine import MAX_REACTION_DEPTH
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    names = ["one", "two", "three", "four", "five"]
    for name in names:
        _register(db_session, workspace, name, fields=[{"key": "hop"}])
    # one → two → three → four → five: each workflow reacts to its event and sends the next (its own emit never wakes it).
    for here, nxt in zip(names, names[1:], strict=False):
        _workflow(
            db_session,
            workspace,
            f"on-{here}",
            f"custom.{here}",
            [{"kind": "emit_event", "event": f"custom.{nxt}", "payload": {"hop": "${event.payload.hop}>" + nxt}}],
        )
    _workflow(db_session, workspace, "on-five", "custom.five", [{"kind": "emit_event", "event": "custom.one", "payload": {"hop": "loop"}}])

    ran = []
    from marvin.services.automation import engine

    real = engine.run_automations_for_event

    def spy(session, group_id, event_ctx, **kw):
        n = real(session, group_id, event_ctx, **kw)
        ran.append((event_ctx["event_type"], event_ctx["reaction_depth"], n))
        return n

    monkeypatch.setattr(engine, "run_automations_for_event", spy)
    starter = _event("custom.one", {"hop": "start"}, workspace)
    EventBusService(bg_tasks=None).dispatch(
        integration_id="test",
        group_id=workspace.gid,
        event_type=starter.event_type,
        document_data=starter.document_data,
        message="start",
        user_id=workspace.uid,
        correlation_id="chain-1",
    )

    reacted = {(t, d) for t, d, n in ran if n}
    # depth 0 (sent by a person) .. 2 react; the event at depth MAX_REACTION_DEPTH (3) is recorded but nothing reacts to it
    assert reacted == {("custom.one", 0), ("custom.two", 1), ("custom.three", 2)}
    logged = {
        (row.event_type, row.event_data.get("reactionDepth"))
        for row in db_session.query(EventLogModel).filter_by(workspace_id=workspace.gid, correlation_id="chain-1")
        if row.event_type.startswith("custom.")
    }
    assert logged == {("custom.one", 0), ("custom.two", 1), ("custom.three", 2), ("custom.four", 3)}
    assert MAX_REACTION_DEPTH == 3
