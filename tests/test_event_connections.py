"""Events hub, slice 3: one lookup for what sends an event type and what reacts to it.

* Each reaction kind (workflow, integration action, email, outgoing webhook) appears and disappears with its row,
  switched-off ones are listed as disabled, and what's listed as enabled is exactly what the event bus runs —
  checked against each listener, not against a copy of its rules.
* Senders: Marvin's own (catalog), workflows whose steps send it (Emit event, a task step, an entry step), the
  incoming webhooks that start such a workflow, scheduled tasks whose type sends it. The step and task tables
  (`OP_SENDS`, `ScheduledTaskHandler.sends`) are checked by running them.
* Recent events and whether the workspace records the type; the chain both ways.
* The summary equals the detail for every catalog type, in a fixed number of queries.
* The API: workspace OWNER/ADMIN only, one workspace's rows never in another's, platform types only on the admin one
  (and never offered by the workspace pickers); Marvin's system emails send with no subscription.
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.event_bus_service.event_types import EventTypes, WebhookMode
from marvin.services.events import connections
from marvin.services.events.event_catalog import CATALOG, CATALOG_BY_TYPE, get_catalog_entry

WS = "/api/platform/event-types"
ADMIN = "/api/admin/event-types"


# ── fixtures ─────────────────────────────────────────────────────────────────


def _add(db, model, **kw):
    try:
        row = model(session=db, **kw)  # auto_init models
    except TypeError:  # plain declarative ones take no session
        row = model(**kw)
    db.add(row)
    db.commit()
    return row


def _purge(db, gid):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.email_templates import EmailTemplateModel
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.webhook_event_subscriptions import WebhookEventSubscriptionModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    db.rollback()
    hooks = sa.select(GroupWebhooksModel.id).where(GroupWebhooksModel.group_id == gid)
    db.execute(sa.delete(WebhookEventSubscriptionModel).where(WebhookEventSubscriptionModel.webhook_id.in_(hooks)))
    collections = sa.select(Collections.id).where(Collections.group_id == gid)
    db.execute(sa.delete(EntryCollections).where(EntryCollections.collection_id.in_(collections)))
    for model in (
        EmailEventSubscriptionModel,
        IntegrationEventSubscriptionModel,
        WorkspaceAutomationModel,
        ScheduledTaskModel,
        WorkspaceIncomingWebhookModel,
        EmailTemplateModel,
        Collections,
        Entries,
        EntryTypes,
        IntegrationModel,
    ):
        db.execute(sa.delete(model).where(model.group_id == gid))
    purge_group_dependents(db, gid)
    db.execute(sa.delete(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == gid))
    db.execute(sa.delete(Users).where(Users.group_id == gid))
    db.execute(sa.delete(Groups).where(Groups.id == gid))
    db.commit()


@pytest.fixture
def world(db_session):
    """Two workspaces, A and B, each with one user."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    tag = uuid.uuid4().hex[:8]
    ga, gb, ua, ub = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for gid, uid, key in ((ga, ua, "a"), (gb, ub, "b")):
        group = Groups(session=db_session, name=f"evc-{tag}-{key}", slug=f"evc-{tag}-{key}")
        group.id = gid
        db_session.add(group)
        db_session.flush()
        db_session.execute(
            Users.__table__.insert().values(
                id=uid,
                group_id=gid,
                username=f"evc-{tag}-{key}",
                email=f"evc-{tag}-{key}@t.test",
                full_name="Events Person",
                password="x",
                is_superuser=False,
                platform_role="NONE",
                auth_method="MARVIN",
            )
        )
    db_session.commit()
    yield SimpleNamespace(a=ga, b=gb, ua=ua, ub=ub, tag=tag)
    app.dependency_overrides.pop(get_current_user, None)
    for gid in (ga, gb):
        _purge(db_session, gid)


def _caller(world, role, platform_role=PlatformRole.NONE):
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(world.a) else None

    return SimpleNamespace(
        id=world.ua,
        group_id=world.a,
        active_group_id=world.a,
        admin=False,
        is_superuser=False,
        username=f"evc-{world.tag}-a",
        full_name="Events Person",
        email=f"evc-{world.tag}-a@t.test",
        platform_role=platform_role,
        workspace_memberships=[SimpleNamespace(group_id=world.a, workspace_role=role)] if role else [],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )


def _client(world, role=WorkspaceRole.OWNER, platform_role=PlatformRole.NONE) -> TestClient:
    user = _caller(world, role, platform_role)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ── row makers ───────────────────────────────────────────────────────────────


def integration(db, gid, name="Acme", provider="acme", enabled=True):
    from marvin.db.models.groups.integrations import IntegrationModel

    return _add(
        db, IntegrationModel, group_id=gid, provider=provider, name=name, slug=f"{provider}-{uuid.uuid4().hex[:6]}", enabled=enabled, config={}
    )


def isub(db, gid, integ, event, action="notify", enabled=True, source=None):
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel

    return _add(
        db,
        IntegrationEventSubscriptionModel,
        group_id=gid,
        integration_id=integ.id,
        event_type=event,
        action=action,
        enabled=enabled,
        source_integration_id=source.id if source else None,
        source_blueprint="acme-announce" if source else None,
    )


def template(db, gid, name="Note", template_type="custom", enabled=True):
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    return _add(db, EmailTemplateModel, group_id=gid, name=name, template_type=template_type, subject="Hi", body_markdown="Hi", enabled=enabled)


def esub(db, gid, tmpl, event, enabled=True, recipient_type="admins"):
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel

    return _add(
        db,
        EmailEventSubscriptionModel,
        group_id=gid,
        template_id=tmpl.id,
        event_type=event,
        recipient_type=recipient_type,
        recipient_email="secret-person@t.test" if recipient_type == "specific" else None,
        enabled=enabled,
    )


def webhook(db, gid, name, events, mode=WebhookMode.event_driven, enabled=True):
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    return _add(
        db,
        GroupWebhooksModel,
        group_id=gid,
        name=name,
        url="https://hooks.example.test/very-secret-token",
        webhook_type=mode,
        enabled=enabled,
        subscribed_events=events,
    )


def workflow(db, gid, name, trigger=None, actions=(), enabled=True, source=None, on_failure=None):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = {"actions": list(actions)}
    if trigger is not None:
        definition["trigger"] = trigger
    if on_failure is not None:
        definition["on_failure"] = on_failure
    return _add(
        db,
        WorkspaceAutomationModel,
        group_id=gid,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}",
        enabled=enabled,
        definition=definition,
        source_integration_id=source.id if source else None,
        source_blueprint="acme-flow" if source else None,
    )


def incoming(db, gid, name, slug, enabled=True):
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel

    return _add(db, WorkspaceIncomingWebhookModel, group_id=gid, name=name, slug=slug, enabled=enabled, token=uuid.uuid4().hex)


def task(db, gid, name, task_type, enabled=True):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return _add(
        db,
        ScheduledTaskModel,
        group_id=gid,
        name=name,
        slug=f"t-{uuid.uuid4().hex[:8]}",
        enabled=enabled,
        schedule_type="interval",
        schedule_config={"interval_seconds": 3600},
        task_type=task_type,
        task_config={},
    )


def _event(event_type: str):
    return SimpleNamespace(event_type=EventTypes[event_type], document_data=None, reaction_depth=0)


def _data(reactions, kind=None):
    return [r for r in reactions if r.kind != "builtin" and (kind is None or r.kind == kind)]


def _names(rows, **match):
    return sorted(r.name for r in rows if all(getattr(r, k) == v for k, v in match.items()))


EMIT = {"kind": "emit_event", "event": "site_deployment_completed"}
REBUILD = {"kind": "handler", "task": "request_site_rebuild"}
PUBLISH = {"kind": "entry", "op": "publish"}


# ── reactions: each kind comes and goes with its row ────────────────────────


def test_integration_actions_appear_disabled_and_disappear(db_session, world):
    acme = integration(db_session, world.a)
    off = integration(db_session, world.a, name="Off Co", provider="offco", enabled=False)
    on = isub(db_session, world.a, acme, "entry_published")
    isub(db_session, world.a, acme, "entry_published", action="archive", enabled=False)
    isub(db_session, world.a, off, "entry_published")
    isub(db_session, world.b, integration(db_session, world.b), "entry_published")

    rows = _data(connections.reactions(db_session, world.a, "entry_published"), "integration_action")
    assert sorted((r.name, r.detail, r.enabled) for r in rows) == [("Acme", "archive", False), ("Acme", "notify", True), ("Off Co", "notify", False)]
    assert {r.managed_at for r in rows} == {"/workspace/settings/integrations"}

    db_session.delete(on)
    db_session.commit()
    rows = _data(connections.reactions(db_session, world.a, "entry_published"), "integration_action")
    assert sorted((r.detail, r.enabled) for r in rows if r.name == "Acme") == [("archive", False)]


def test_emails_appear_disabled_without_addresses(db_session, world):
    note = template(db_session, world.a, "Note")
    off_template = template(db_session, world.a, "Paused", enabled=False)
    to_admins = esub(db_session, world.a, note, "entry_published")
    esub(db_session, world.a, note, "entry_published", recipient_type="specific", enabled=False)
    esub(db_session, world.a, off_template, "entry_published")
    esub(db_session, world.b, template(db_session, world.b, "B note"), "entry_published")

    rows = _data(connections.reactions(db_session, world.a, "entry_published"), "email")
    assert sorted((r.name, r.detail, r.enabled) for r in rows) == [
        ("Note", "To specific addresses", False),
        ("Note", "To the workspace admins", True),
        ("Paused", "To the workspace admins", False),
    ]
    assert {r.managed_at for r in rows if r.name == "Note"} == {f"/workspace/settings/email/{note.id}"}
    assert "secret-person" not in str([r.model_dump() for r in rows])

    db_session.delete(to_admins)
    db_session.commit()
    assert [r.enabled for r in _data(connections.reactions(db_session, world.a, "entry_published"), "email") if r.name == "Note"] == [False]


def test_webhooks_appear_disabled_and_only_event_driven_ones(db_session, world):
    hook = webhook(db_session, world.a, "Deploy hook", ["entry_published", "webhook_triggered"])
    webhook(db_session, world.a, "Off hook", ["entry_published"], enabled=False)
    webhook(db_session, world.a, "Scheduled", ["entry_published"], mode=WebhookMode.generic)
    webhook(db_session, world.b, "B hook", ["entry_published"])

    rows = _data(connections.reactions(db_session, world.a, "entry_published"), "webhook")
    assert sorted((r.name, r.enabled) for r in rows) == [("Deploy hook", True), ("Off hook", False)]
    assert next(r for r in rows if r.name == "Deploy hook").managed_at == f"/automation/webhooks/{hook.id}"
    assert "very-secret-token" not in str([r.model_dump() for r in rows])

    hook.subscribed_events = ["webhook_triggered"]
    db_session.commit()
    assert _names(_data(connections.reactions(db_session, world.a, "entry_published"), "webhook")) == ["Off hook"]


def test_workflows_appear_disabled_with_their_trigger(db_session, world):
    flow = workflow(db_session, world.a, "On publish", {"type": "event", "event": "entry_published"})
    workflow(db_session, world.a, "Paused", {"type": "event", "event": "entry_published"}, enabled=False)
    workflow(db_session, world.a, "From Acme hook", {"type": "incoming_webhook", "webhook": "acme"})
    workflow(db_session, world.a, "After on publish", {"type": "chained", "automation": "on-publish"})
    workflow(db_session, world.a, "By hand", {"type": "manual"})
    workflow(db_session, world.b, "B flow", {"type": "event", "event": "entry_published"})

    rows = _data(connections.reactions(db_session, world.a, "entry_published"), "workflow")
    assert sorted((r.name, r.enabled, r.trigger_type) for r in rows) == [("On publish", True, "event"), ("Paused", False, "event")]
    assert next(r for r in rows if r.name == "On publish").managed_at == f"/automation/workflows?workflow={flow.id}"

    hooked = _data(connections.reactions(db_session, world.a, "incoming_webhook"), "workflow")
    assert [(r.name, r.detail, r.trigger_type) for r in hooked] == [("From Acme hook", "acme", "incoming_webhook")]
    chained = _data(connections.reactions(db_session, world.a, "automation_ran"), "workflow")
    assert [(r.name, r.detail, r.enabled) for r in chained] == [("After on publish", "on-publish", True)]

    db_session.delete(flow)
    db_session.commit()
    assert _names(_data(connections.reactions(db_session, world.a, "entry_published"), "workflow")) == ["Paused"]


def test_a_workflow_on_an_event_the_listener_ignores_is_listed_as_not_running(db_session, world):
    workflow(db_session, world.a, "On queue", {"type": "event", "event": "site_rebuild_queued"})  # not triggerable
    rows = _data(connections.reactions(db_session, world.a, "site_rebuild_queued"), "workflow")
    assert [(r.name, r.enabled) for r in rows] == [("On queue", False)]


def test_installed_by_names_the_integration(db_session, world):
    square = integration(db_session, world.a, name="Square", provider="square")
    workflow(db_session, world.a, "Square: sync", {"type": "event", "event": "entry_updated"}, actions=[PUBLISH], source=square)
    workflow(db_session, world.a, "Mine", {"type": "event", "event": "entry_updated"})
    isub(db_session, world.a, square, "entry_updated", source=square)

    rows = {(r.kind, r.name): r for r in _data(connections.reactions(db_session, world.a, "entry_updated"))}
    for key in (("workflow", "Square: sync"), ("integration_action", "Square")):
        by = rows[key].installed_by
        assert (by.integration_id, by.name, by.provider) == (square.id, "Square", "square")
    assert rows[("workflow", "Mine")].installed_by is None
    sender = next(s for s in connections.senders(db_session, world.a, "entry_published") if s.kind == "workflow")
    assert (sender.name, sender.installed_by.name, sender.installed_by.blueprint) == ("Square: sync", "Square", "acme-flow")


def test_builtin_reactions_come_last_from_code(db_session, world):
    from marvin.services.event_bus_service.event_bus_listener import builtin_reactions

    workflow(db_session, world.a, "On publish", {"type": "event", "event": "entry_published"})
    rows = connections.reactions(db_session, world.a, "entry_published")
    builtins = [r for r in rows if r.kind == "builtin"]
    assert [r.name for r in builtins] == [label for label, _ in builtin_reactions("entry_published")]
    assert "Queues a site rebuild" in [r.name for r in builtins]
    assert all(r.enabled and r.id is None for r in builtins)
    assert rows[-len(builtins) :] == builtins
    assert [r.kind for r in connections.reactions(db_session, world.a, "member_added")] == []


# ── listed as running == what the listener runs ─────────────────────────────


def _listed_running(db, gid, event_type, kind):
    return {r.id for r in _data(connections.reactions(db, gid, event_type), kind) if r.enabled}


def _listed_stopped(db, gid, event_type, kind):
    return {r.id for r in _data(connections.reactions(db, gid, event_type), kind) if not r.enabled}


def test_integration_reactions_match_the_listener(db_session, world):
    from marvin.services.event_bus_service.event_bus_listener import IntegrationEventListener

    acme, off = integration(db_session, world.a), integration(db_session, world.a, name="Off", provider="off", enabled=False)
    subs = [
        isub(db_session, world.a, acme, "entry_published"),
        isub(db_session, world.a, acme, "entry_published", action="b", enabled=False),
        isub(db_session, world.a, off, "entry_published", action="c"),
        isub(db_session, world.a, acme, "entry_updated", action="d"),
    ]
    isub(db_session, world.b, integration(db_session, world.b), "entry_published", action="e")
    ran = {(s["integration_id"], s["action"]) for s in IntegrationEventListener(world.a).get_subscribers(_event("entry_published"))}
    by_id = {s.id: (s.integration_id, s.action) for s in subs}
    assert {by_id[i] for i in _listed_running(db_session, world.a, "entry_published", "integration_action")} == ran
    assert not {by_id[i] for i in _listed_stopped(db_session, world.a, "entry_published", "integration_action")} & ran


def _emails_sent(gid, event_type):
    """What EmailEventListener would send: its subscribers, minus what publish_to_subscribers skips."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.groups.email_templates import EmailTemplateModel
    from marvin.services.event_bus_service.event_bus_listener import EmailEventListener

    out = set()
    with session_context() as session:
        for sub in EmailEventListener(gid).get_subscribers(_event(event_type)):
            tmpl = session.get(EmailTemplateModel, sub.template_id)
            if tmpl is None or not tmpl.enabled or (tmpl.group_id is not None and str(tmpl.group_id) != str(sub.group_id or gid)):
                continue
            out.add(sub.id if sub.id is not None else tmpl.id)  # a system template's virtual subscription: the template
    return out


def test_email_reactions_match_the_listener(db_session, world):
    note, paused = template(db_session, world.a, "Note"), template(db_session, world.a, "Paused", enabled=False)
    esub(db_session, world.a, note, "entry_published")
    esub(db_session, world.a, note, "entry_published", enabled=False)
    esub(db_session, world.a, paused, "entry_published")
    esub(db_session, world.b, template(db_session, world.b), "entry_published")
    sent = _emails_sent(world.a, "entry_published")
    assert sent and _listed_running(db_session, world.a, "entry_published", "email") == sent
    assert not _listed_stopped(db_session, world.a, "entry_published", "email") & sent


@contextmanager
def _system_template(db, template_type="invitation"):
    """The one system template of a type (made here when the database has none)."""
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    existing = db.query(EmailTemplateModel).filter(EmailTemplateModel.group_id.is_(None), EmailTemplateModel.template_type == template_type).all()
    if len(existing) > 1:
        pytest.skip(f"more than one system {template_type} template")
    made = not existing
    tmpl = existing[0] if existing else template(db, None, f"{template_type} (system)", template_type=template_type)
    was = tmpl.enabled
    try:
        yield tmpl
    finally:
        db.rollback()
        if made:
            db.delete(db.get(EmailTemplateModel, tmpl.id))
        else:
            db.get(EmailTemplateModel, tmpl.id).enabled = was
        db.commit()


def test_system_email_is_listed_and_replaced_like_the_listener_does(db_session, world):
    with _system_template(db_session) as system:
        system.enabled = True
        db_session.commit()
        other = template(db_session, world.a, "Welcome aboard")
        esub(db_session, world.a, other, "invitation_sent")

        # No workspace invitation template connected: the system one sends, and only it.
        rows = _data(connections.reactions(db_session, world.a, "invitation_sent"), "email")
        assert {(r.id, r.detail, r.enabled) for r in rows if r.id == system.id} == {(system.id, "System template", True)}
        assert next(r for r in rows if r.id == system.id).managed_at == f"/workspace/settings/email?customize={system.id}"
        assert _listed_running(db_session, world.a, "invitation_sent", "email") == _emails_sent(world.a, "invitation_sent") == {system.id}

        # The workspace connects its own invitation template: that replaces the system one.
        own = template(db_session, world.a, "Our invitation", template_type="invitation")
        mine = esub(db_session, world.a, own, "invitation_sent")
        assert _listed_running(db_session, world.a, "invitation_sent", "email") == _emails_sent(world.a, "invitation_sent") == {mine.id}

        # System template switched off and nothing connected: every enabled subscription sends.
        db_session.delete(mine)
        system.enabled = False
        db_session.commit()
        sent = _emails_sent(world.a, "invitation_sent")
        assert _listed_running(db_session, world.a, "invitation_sent", "email") == sent and len(sent) == 1
        assert system.id in _listed_stopped(db_session, world.a, "invitation_sent", "email")


@pytest.mark.parametrize(
    ("template_type", "event_type"),
    [("welcome", "user_signup"), ("password_reset", "user_password_reset_requested"), ("invitation", "invitation_sent")],
)
def test_system_emails_send_with_no_subscription(db_session, world, template_type, event_type):
    """Marvin's own welcome, password-reset and invitation emails aren't subscriptions: they send with nothing
    connected, platform event or not, although the workspace side no longer offers platform types."""
    with _system_template(db_session, template_type) as system:
        system.enabled = True
        db_session.commit()
        assert _emails_sent(world.a, event_type) == {system.id}


def test_webhook_reactions_match_the_listener(db_session, world):
    from marvin.services.event_bus_service.event_bus_listener import WebhookEventListener

    webhook(db_session, world.a, "On", ["entry_published"])
    webhook(db_session, world.a, "Off", ["entry_published"], enabled=False)
    webhook(db_session, world.a, "Generic", ["entry_published"], mode=WebhookMode.generic)
    webhook(db_session, world.b, "B", ["entry_published"])
    sent = {w.id for w in WebhookEventListener(world.a).get_subscribers(_event("entry_published"))}
    assert sent and _listed_running(db_session, world.a, "entry_published", "webhook") == sent
    assert not _listed_stopped(db_session, world.a, "entry_published", "webhook") & sent


def _workflows_run(monkeypatch, db, gid, event_ctx):
    """The workflows the automation listener + engine would run for this event."""
    import marvin.services.automation.engine as engine
    from marvin.services.event_bus_service.event_bus_listener import AutomationReactionListener

    if not AutomationReactionListener(gid).get_subscribers(_event(event_ctx["event_type"])):
        return set()
    ran = set()

    def record(session, group_id, automation, *a, **k):
        ran.add(automation.id)
        return False, True, None

    monkeypatch.setattr(engine, "_run_targets", record)
    engine.run_automations_for_event(db, gid, event_ctx, run_action=lambda *a, **k: {}, dry_run=True)
    return ran


@pytest.mark.parametrize(
    ("event_ctx", "rows"),
    [
        ({"event_type": "entry_published"}, ["event:entry_published", "off:event:entry_published", "event:entry_updated"]),
        ({"event_type": "site_rebuild_queued"}, ["event:site_rebuild_queued"]),
        ({"event_type": "incoming_webhook", "webhook_slug": "acme"}, ["incoming_webhook:acme", "incoming_webhook:", "off:incoming_webhook:"]),
        ({"event_type": "automation_ran", "automation_slug": "x"}, ["chained:", "chained:x", "on_error:"]),
        ({"event_type": "automation_failed", "automation_slug": "x"}, ["on_error:any", "chained:"]),
    ],
)
def test_workflow_reactions_match_the_engine(monkeypatch, db_session, world, event_ctx, rows):
    for spec in rows:
        enabled = not spec.startswith("off:")
        kind, _, ref = spec.removeprefix("off:").partition(":")
        trigger = {"type": kind, "event": ref} if kind == "event" else {"type": kind}
        if kind == "incoming_webhook" and ref:
            trigger["webhook"] = ref
        if kind in ("chained", "on_error") and ref:
            trigger["automation"] = ref
        workflow(db_session, world.a, f"wf {spec}", trigger, enabled=enabled)
        workflow(db_session, world.b, f"b {spec}", trigger)
    ran = _workflows_run(monkeypatch, db_session, world.a, event_ctx)
    assert _listed_running(db_session, world.a, event_ctx["event_type"], "workflow") == ran
    assert not _listed_stopped(db_session, world.a, event_ctx["event_type"], "workflow") & ran


# ── senders ──────────────────────────────────────────────────────────────────


def test_marvin_senders_are_the_catalog_lines(db_session, world):
    rows = connections.senders(db_session, world.a, "entry_published")
    assert [s.name for s in rows if s.kind == "marvin"] == CATALOG_BY_TYPE["entry_published"].sent_by
    assert all(s.enabled and s.id is None for s in rows if s.kind == "marvin")


def test_a_workflow_with_an_emit_event_step_sends_it(db_session, world):
    flow = workflow(db_session, world.a, "Deploy notice", {"type": "manual"}, actions=[EMIT])
    workflow(db_session, world.a, "Not emittable", {"type": "manual"}, actions=[{"kind": "emit_event", "event": "user_signup"}])
    workflow(db_session, world.b, "B notice", {"type": "manual"}, actions=[EMIT])
    rows = [s for s in connections.senders(db_session, world.a, "site_deployment_completed") if s.kind == "workflow"]
    assert [(s.id, s.detail, s.enabled, s.managed_at) for s in rows] == [
        (flow.id, "Emit event step", True, f"/automation/workflows?workflow={flow.id}")
    ]
    assert [s for s in connections.senders(db_session, world.a, "user_signup") if s.kind != "marvin"] == []


def test_a_workflow_that_requests_a_rebuild_sends_the_rebuild_events(db_session, world):
    workflow(db_session, world.a, "Rebuild on sale", {"type": "event", "event": "entry_updated"}, actions=[REBUILD], enabled=False)
    for event_type in ("site_rebuild_queued", "webhook_triggered"):
        rows = [s for s in connections.senders(db_session, world.a, event_type) if s.kind == "workflow"]
        assert [(s.name, s.detail, s.enabled) for s in rows] == [("Rebuild on sale", "Request Site Rebuild step", False)]


def test_entry_and_on_failure_steps_send_their_events(db_session, world):
    workflow(
        db_session,
        world.a,
        "Publish it",
        {"type": "manual"},
        actions=[PUBLISH, {"kind": "entry", "op": "add_to_collection", "collection_slug": "x"}],
        on_failure=[{"kind": "entry", "op": "request_review"}],
    )
    assert _names([s for s in connections.senders(db_session, world.a, "entry_published") if s.kind == "workflow"]) == ["Publish it"]
    row = next(s for s in connections.senders(db_session, world.a, "entry_updated") if s.kind == "workflow")
    assert row.detail == "Entry step: publish; Entry step: request review"
    assert _names([s for s in connections.senders(db_session, world.a, "entry_added_to_collection") if s.kind == "workflow"]) == ["Publish it"]


def test_incoming_webhooks_that_start_a_sending_workflow_send_it(db_session, world):
    deploys, other = incoming(db_session, world.a, "Host deploys", "deploys"), incoming(db_session, world.a, "Other", "other", enabled=False)
    flow = workflow(db_session, world.a, "Deploy notice", {"type": "incoming_webhook", "webhook": "deploys"}, actions=[EMIT])
    any_flow = workflow(db_session, world.a, "Any hook", {"type": "incoming_webhook"}, actions=[EMIT])
    incoming(db_session, world.b, "B deploys", "deploys")

    hooks = [s for s in connections.senders(db_session, world.a, "site_deployment_completed") if s.kind == "incoming_webhook"]
    assert sorted((s.name, s.via_workflow_name, s.enabled) for s in hooks) == [
        ("Host deploys", "Any hook", True),
        ("Host deploys", "Deploy notice", True),
        ("Other", "Any hook", False),
    ]
    assert {s.via_workflow_id for s in hooks} == {flow.id, any_flow.id}
    assert {s.id for s in hooks} == {deploys.id, other.id}
    # Every incoming webhook sends incoming_webhook itself.
    direct = [s for s in connections.senders(db_session, world.a, "incoming_webhook") if s.kind == "incoming_webhook"]
    assert sorted(s.name for s in direct) == ["Host deploys", "Other"]


def test_scheduled_tasks_whose_type_sends_it(db_session, world):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    rebuild = task(db_session, world.a, "Nightly rebuild", "request_site_rebuild")
    task(db_session, world.a, "Tidy", "remove_orphaned_assets")
    task(db_session, world.b, "B rebuild", "request_site_rebuild")
    system = task(db_session, None, f"System rebuild {world.tag}", "request_site_rebuild", enabled=False)
    try:
        for event_type in ("site_rebuild_queued", "webhook_triggered"):
            rows = [s for s in connections.senders(db_session, world.a, event_type) if s.kind == "scheduled_task"]
            mine = [s for s in rows if s.name in ("Nightly rebuild", f"System rebuild {world.tag}", "B rebuild")]
            assert sorted((s.name, s.enabled, s.managed_at) for s in mine) == [
                ("Nightly rebuild", True, f"/workspace/scheduled-tasks/{rebuild.id}"),
                (f"System rebuild {world.tag}", False, None),
            ]
        publishing = [s.name for s in connections.senders(db_session, world.a, "entry_published") if s.kind == "scheduled_task"]
        assert "Nightly rebuild" not in publishing
    finally:
        db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.id == system.id).delete()
        db_session.commit()


# ── the tables of what steps and tasks send, checked by running them ────────


@pytest.fixture
def dispatched(monkeypatch):
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    seen: list[str] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: seen.append(kw["event_type"].name))
    return seen


@pytest.fixture
def entries(db_session, world):
    from marvin.db.models.platform import Collections, Entries, EntryTypes

    et = _add(
        db_session,
        EntryTypes,
        group_id=world.a,
        name="Note",
        slug="note",
        schema_json={"fields": [{"key": "colour", "label": "Colour", "type": "text"}]},
    )
    coll = _add(db_session, Collections, group_id=world.a, name="Picks", slug="picks")

    def make(status="draft", **fields):
        entry = Entries(
            session=db_session,
            group_id=world.a,
            entry_type_id=et.id,
            title=f"E-{uuid.uuid4().hex[:6]}",
            slug=f"e-{uuid.uuid4().hex[:8]}",
            status=status,
            **fields,
        )
        db_session.add(entry)
        db_session.commit()
        return entry.id

    return SimpleNamespace(make=make, collection=coll)


@pytest.mark.parametrize(
    ("op", "status", "extra"),
    [
        ("publish", "draft", {}),
        ("unpublish", "published", {}),
        ("archive", "draft", {}),
        ("restore", "archived", {}),
        ("add_to_collection", "draft", {"collection_slug": "picks"}),
        ("remove_from_collection", "draft", {"collection_slug": "picks"}),
        ("set_metadata", "draft", {"metadata": {"k": "v"}}),
        ("set_data", "draft", {"data": {"colour": "red"}}),
        ("request_review", "draft", {"reason": "check"}),
    ],
)
def test_each_entry_step_sends_what_op_sends_says(db_session, world, entries, dispatched, op, status, extra):
    from marvin.services.automation.actions.entry import OP_SENDS, run_entry_action
    from marvin.services.automation.authz import ROLE_ADMIN
    from marvin.services.entries import EntryService

    entry_id = entries.make(status)
    if op == "remove_from_collection":
        EntryService(db_session, world.a).add_to_collection(entry_id, "picks")
    dispatched.clear()
    action = {"kind": "entry", "op": op, **extra}
    run_entry_action(db_session, world.a, action, {"event": {"entry_id": str(entry_id)}, "steps": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)
    assert sorted(dispatched) == sorted(OP_SENDS[op])


def test_every_op_has_its_sends(db_session):
    from marvin.services.automation.actions.entry import ALL_OPS, OP_SENDS

    assert set(OP_SENDS) == set(ALL_OPS)
    assert {e for sends in OP_SENDS.values() for e in sends} <= set(CATALOG_BY_TYPE)


def test_task_types_send_what_they_declare(db_session, world, entries, dispatched):
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

    for task_type in TaskHandlerRegistry.list_registered_types():
        assert set(TaskHandlerRegistry.get_handler(task_type).sends) <= set(CATALOG_BY_TYPE), task_type

    def run(task_type):
        dispatched.clear()
        handler = TaskHandlerRegistry.get_handler(task_type)
        handler.execute(SimpleNamespace(group_id=world.a, task_config={}), EventBusService(bg_tasks=None))
        return set(dispatched)

    past = datetime.now(UTC) - timedelta(hours=1)
    entries.make(publish_at=past)
    entries.make(publish_at=past, expire_at=past)  # refused: already expired
    assert run("publish_scheduled_entries") == {"entry_updated", "entry_published", "entry_scheduled_publish_blocked"}
    entries.make("published", expire_at=past)
    assert run("unpublish_expired_entries") == {"entry_updated", "entry_unpublished", "entry_archived"}
    # The request opens a batch; the scheduler sends it later (site_rebuild_queued leads to webhook_triggered).
    assert run("request_site_rebuild") == {"site_rebuild_queued"}
    assert "webhook_triggered" in CATALOG_BY_TYPE["site_rebuild_queued"].leads_to
    assert TaskHandlerRegistry.get_handler("request_site_rebuild").sends == ("site_rebuild_queued", "webhook_triggered")


# ── recent, audited, chain ──────────────────────────────────────────────────


def _log(db, gid, event_type, minutes_ago, title):
    from marvin.db.models.platform.event_log import EventLogModel

    db.add(
        EventLogModel(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            event_type=event_type,
            occurred_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            workspace_id=gid,
            integration_id="test",
            event_data={},
            message_title=title,
        )
    )
    db.commit()


def test_recent_is_the_workspace_newest_first_and_says_if_recorded(db_session, world):
    from marvin.services.events.audit_settings import apply_changes, invalidate

    for minutes, title in ((5, "older"), (1, "newest"), (3, "middle")):
        _log(db_session, world.a, "entry_published", minutes, title)
    _log(db_session, world.a, "entry_updated", 0, "other type")
    _log(db_session, world.b, "entry_published", 0, "other workspace")

    latest = connections.recent(db_session, world.a, "entry_published", limit=2)
    assert [e.message_title for e in latest.events] == ["newest", "middle"] and latest.audited is True

    apply_changes(db_session, world.a, {"entry_published": False})
    db_session.commit()
    invalidate(world.a)
    try:
        assert connections.recent(db_session, world.a, "entry_published").audited is False
        assert connections.recent(db_session, world.b, "entry_published").audited is True
    finally:
        apply_changes(db_session, world.a, {"entry_published": None})
        db_session.commit()
        invalidate(world.a)


def test_chain_both_ways():
    assert [r.event_type for r in connections.leads_to("site_rebuild_queued")] == ["webhook_triggered"]
    assert [r.event_type for r in connections.caused_by("webhook_triggered")] == ["site_rebuild_queued"]
    causes = {r.event_type for r in connections.caused_by("site_rebuild_queued")}
    assert {"entry_published", "entry_updated"} <= causes
    assert all(r.name == CATALOG_BY_TYPE[r.event_type].name for r in connections.caused_by("site_rebuild_queued"))


# ── summary == detail, in a fixed number of queries ─────────────────────────


def _seed(db, world):
    acme, square = integration(db, world.a), integration(db, world.a, name="Square", provider="square", enabled=False)
    isub(db, world.a, acme, "entry_published")
    isub(db, world.a, square, "entry_updated", source=square)
    isub(db, world.a, acme, "form_submission_received", enabled=False)
    note, paused = template(db, world.a, "Note"), template(db, world.a, "Paused", enabled=False)
    esub(db, world.a, note, "form_submission_received")
    esub(db, world.a, paused, "entry_published")
    esub(db, world.a, note, "invitation_sent")
    webhook(db, world.a, "Deploy", ["webhook_triggered", "entry_published"])
    webhook(db, world.a, "Off", ["site_deployment_completed"], enabled=False)
    workflow(db, world.a, "On publish", {"type": "event", "event": "entry_published"}, actions=[REBUILD, EMIT])
    workflow(db, world.a, "Paused", {"type": "event", "event": "entry_updated"}, actions=[PUBLISH], enabled=False)
    workflow(db, world.a, "Hooked", {"type": "incoming_webhook", "webhook": "deploys"}, actions=[EMIT])
    workflow(db, world.a, "After", {"type": "chained"})
    workflow(db, world.a, "Queue", {"type": "event", "event": "site_rebuild_queued"})
    incoming(db, world.a, "Deploys", "deploys")
    task(db, world.a, "Nightly", "request_site_rebuild")
    task(db, world.a, "Publisher", "publish_scheduled_entries")
    _log(db, world.a, "entry_published", 2, "published")
    _log(db, world.a, "member_added", 1, "member")
    # B's rows must not count for A.
    isub(db, world.b, integration(db, world.b), "entry_published")
    workflow(db, world.b, "B", {"type": "event", "event": "entry_published"}, actions=[EMIT])
    _log(db, world.b, "entry_updated", 0, "b")


def test_summary_equals_detail_for_every_catalog_type(db_session, world):
    _seed(db_session, world)
    rows = {r.event_type: r for r in connections.summary(db_session, world.a)}
    assert set(rows) == {e.event_type for e in CATALOG if e.scope == "workspace"}
    for event_type, row in rows.items():
        reactions = connections.reactions(db_session, world.a, event_type)
        data = _data(reactions)
        assert (row.senders, row.reactions, row.active_reactions, row.builtin_reactions) == (
            len(connections.senders(db_session, world.a, event_type)),
            len(data),
            sum(r.enabled for r in data),
            len(reactions) - len(data),
        ), event_type
    assert rows["entry_published"].reactions >= 4 and rows["entry_published"].last_occurred_at is not None
    assert rows["entry_updated"].last_occurred_at is None  # B's event


@contextmanager
def _count_queries():
    from marvin.db.db_setup import engine

    seen: list[str] = []

    def count(conn, cursor, statement, *args):
        seen.append(statement)

    sa.event.listen(engine, "before_cursor_execute", count)
    try:
        yield seen
    finally:
        sa.event.remove(engine, "before_cursor_execute", count)


def test_summary_takes_a_fixed_number_of_queries(db_session, world):
    db_session.expire_all()
    with _count_queries() as empty:
        connections.summary(db_session, world.a)
    _seed(db_session, world)
    db_session.expire_all()
    with _count_queries() as seeded:
        connections.summary(db_session, world.a)
    assert len(empty) == len(seeded) <= 6, (len(empty), len(seeded))


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_workspace_admins_read_both(db_session, world, role):
    _seed(db_session, world)
    client = _client(world, role)
    res = client.get(f"{WS}/connections")
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["eventType"] == "entry_published")
    assert set(row) == {"eventType", "senders", "reactions", "activeReactions", "builtinReactions", "lastOccurredAt"}

    res = client.get(f"{WS}/entry_published/connections", params={"limit": 1})
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"eventType", "name", "description", "category", "senders", "reactions", "audited", "recent", "leadsTo", "causedBy"}
    assert [e["messageTitle"] for e in body["recent"]] == ["published"]
    flow = next(r for r in body["reactions"] if r["kind"] == "workflow")
    assert set(flow) == {"kind", "id", "name", "enabled", "detail", "triggerType", "managedAt", "installedBy"}
    assert "site_rebuild_queued" in [r["eventType"] for r in body["leadsTo"]]
    assert "very-secret-token" not in res.text


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER, None])
def test_members_below_admin_are_refused(world, role):
    client = _client(world, role)
    assert client.get(f"{WS}/connections").status_code == 403
    assert client.get(f"{WS}/entry_published/connections").status_code == 403


def test_another_workspace_never_shows(db_session, world):
    _seed(db_session, world)
    body = _client(world).get(f"{WS}/entry_published/connections").json()
    names = {r["name"] for r in body["reactions"]} | {s["name"] for s in body["senders"]}
    assert "B" not in names
    ws_ids = {r["id"] for r in body["reactions"] if r["id"]}
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel

    b_subs = {str(s.id) for s in db_session.query(IntegrationEventSubscriptionModel).filter_by(group_id=world.b)}
    assert b_subs and not ws_ids & b_subs
    assert next(r for r in _client(world).get(f"{WS}/connections").json() if r["eventType"] == "entry_updated")["lastOccurredAt"] is None


def test_unknown_and_platform_types_are_not_found_on_the_workspace_api(world):
    client = _client(world)
    assert client.get(f"{WS}/no_such_event/connections").status_code == 404
    assert client.get(f"{WS}/user_signup/connections").status_code == 404
    listed = {r["eventType"] for r in client.get(f"{WS}/connections").json()}
    assert "user_signup" not in listed and "backup_completed" not in listed and "entry_published" in listed


def test_workspace_pickers_offer_no_platform_types(world):
    """The workspace event catalog (/event/types: the Events list, the webhook, email and integration pickers) and
    the workflow trigger options leave the platform's events out; every enabled workspace type is offered."""
    client = _client(world)
    res = client.get("/api/event/types")
    assert res.status_code == 200, res.text
    offered = [e["value"] for e in res.json()]
    platform = {e.event_type for e in CATALOG if e.scope == "platform"}
    assert platform and not platform & set(offered)
    assert set(offered) == {e.event_type for e in CATALOG if e.enabled and e.scope == "workspace"}

    options = client.get("/api/automations/options").json()
    triggers = {t for group in options["triggerGroups"].values() for t in group} | set(options["triggers"])
    assert triggers and not platform & triggers
    assert not platform & set(options["emittable"])


def test_platform_types_are_on_the_admin_api(db_session, world):
    note = template(db_session, world.a, "Signup note")
    esub(db_session, world.a, note, "user_signup")
    _log(db_session, world.a, "user_signup", 1, "signed up")
    _log(db_session, world.b, "user_signup", 2, "b signed up")
    client = _client(world, None, PlatformRole.SUPER_ADMIN)

    res = client.get(f"{ADMIN}/user_signup/connections")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["name"] for s in body["senders"]] == get_catalog_entry("user_signup").sent_by
    mine = next(w for w in body["workspaces"] if w["workspaceId"] == str(world.a))
    assert [(r["kind"], r["name"]) for r in mine["reactions"]] == [("email", "Signup note")]
    titles = [e["messageTitle"] for e in body["recent"]]
    assert titles.index("signed up") < titles.index("b signed up")

    assert client.get(f"{ADMIN}/entry_published/connections").status_code == 404
    assert client.get(f"{ADMIN}/no_such_event/connections").status_code == 404
    assert _client(world, WorkspaceRole.OWNER).get(f"{ADMIN}/user_signup/connections").status_code == 403
