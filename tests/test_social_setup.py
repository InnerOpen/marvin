"""Social as its own space: the plumbing Marvin makes itself (the rule type, the engine's task, the sidebar summary), the per-network
auto-reply switch, a network's rules and its replies — and who may do each.
"""

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.app import app  # noqa: E402
from marvin.core.dependencies import get_current_user  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.db.models.platform.entries import Entries  # noqa: E402
from marvin.db.models.platform.entry_types import EntryTypes  # noqa: E402
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel  # noqa: E402
from marvin.db.models.users.roles import WorkspaceRole  # noqa: E402
from marvin.services.integrations import social_setup  # noqa: E402
from marvin.services.integrations.social_engagement import Settings, load_rules, run_engagement  # noqa: E402
from tests import test_content_role_gates as gates  # noqa: E402
from tests import test_social_engagement as se  # noqa: E402

ws, nets = se.ws, se.nets
API = "/api/groups/social-inbox"
ADMIN, EDITOR, VIEWER, AUTHOR = WorkspaceRole.ADMIN, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR


@pytest.fixture(autouse=True)
def _types(ws):
    """The workspace has the rule type (`clean` removes it for the tests of the plumbing that makes it)."""
    social_setup.ensure_rule_type(ws.session, ws.gid)


@pytest.fixture
def clean(ws):
    """The workspace as a fresh install has it: the networks connected, no rule type, no task."""
    ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").delete()
    ws.session.query(ScheduledTaskModel).filter_by(group_id=ws.gid).delete()
    ws.session.commit()
    return ws


@pytest.fixture
def api(ws):
    me = SimpleNamespace(gid=ws.gid, uid=ws.uid, slug="setup")
    yield lambda role=ADMIN: gates._sign_in(me, role)
    app.dependency_overrides.pop(get_current_user, None)


def tasks(ws):
    ws.session.expire_all()
    return ws.session.query(ScheduledTaskModel).filter_by(group_id=ws.gid, task_type="social_engagement").all()


def set_enabled(ws, enabled, *slugs):
    q = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid)
    for row in q.filter(IntegrationModel.slug.in_(slugs)) if slugs else q:
        row.enabled = enabled
    ws.session.commit()


def type_count(ws):
    return ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").count()


# ── the plumbing makes itself ────────────────────────────────────────────────────────────────────────────────────


def test_the_task_and_the_rule_type_are_made_once_a_network_reads_comments(clean):
    assert tasks(clean) == [] and type_count(clean) == 0
    assert social_setup.reconcile(clean.session, clean.gid) == {"networks": 3, "reading": 3, "task": "created"}
    [task] = tasks(clean)
    assert (task.enabled, task.slug, task.schedule_config, task.next_run_at is not None) == (
        True,
        "social-engagement",
        {"interval_seconds": 300},
        True,
    )
    assert "rehearsal" not in task.task_config and task.task_config["max_replies"] == 20
    assert type_count(clean) == 1
    assert social_setup.reconcile(clean.session, clean.gid)["task"] == "unchanged"  # idempotent
    assert len(tasks(clean)) == 1 and type_count(clean) == 1


def test_the_task_stops_when_no_network_reads_comments_and_starts_again_with_the_same_row(clean):
    social_setup.reconcile(clean.session, clean.gid)
    [task] = tasks(clean)
    set_enabled(clean, False)
    assert social_setup.reconcile(clean.session, clean.gid) == {"networks": 0, "reading": 0, "task": "disabled"}
    assert tasks(clean)[0].enabled is False and tasks(clean)[0].id == task.id
    set_enabled(clean, True, "b-main")
    assert social_setup.reconcile(clean.session, clean.gid)["task"] == "enabled"
    assert [t.id for t in tasks(clean) if t.enabled] == [task.id] and len(tasks(clean)) == 1


def test_a_network_that_can_only_post_gets_the_rule_type_but_no_task(clean, monkeypatch):
    class PostOnly(IntegrationProvider):
        name = "Post only"
        slug = "poster"
        actions = (ProviderAction(key="post", label="Post", capability="social.post", requires_approval=True),)

    monkeypatch.setitem(INTEGRATION_REGISTRY, "poster", PostOnly())
    set_enabled(clean, False)
    clean.session.add(
        IntegrationModel(session=clean.session, group_id=clean.gid, provider="poster", name="Poster", slug="poster", enabled=True, config={})
    )
    clean.session.commit()
    assert social_setup.reconcile(clean.session, clean.gid) == {"networks": 1, "reading": 0, "task": "none"}
    assert tasks(clean) == [] and type_count(clean) == 1


def test_a_workspace_with_no_social_network_gets_nothing(clean):
    clean.session.query(IntegrationModel).filter_by(group_id=clean.gid).delete()
    clean.session.commit()
    assert social_setup.reconcile(clean.session, clean.gid) == {"networks": 0, "reading": 0, "task": "none"}
    assert tasks(clean) == [] and type_count(clean) == 0


def test_the_hourly_system_task_reconciles_every_workspace(clean):
    from marvin.services.scheduled_tasks import TaskHandlerRegistry
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    assert TaskHandlerRegistry.get_handler("reconcile_social_engagement").admin_only is True
    definition = next(d for d in SYSTEM_SCHEDULED_TASKS if d.slug == "reconcile_social_engagement")
    assert definition.schedule_config == {"interval_seconds": 3600} and definition.enabled is True
    done = social_setup.reconcile_all(clean.session)
    assert done["created"] >= 1 and len(tasks(clean)) == 1
    from marvin.services.scheduled_tasks.handlers.social import ReconcileSocialEngagementHandler

    handler = ReconcileSocialEngagementHandler()
    assert handler.execute(SimpleNamespace(group_id=clean.gid), None).startswith("Skipped")  # never from inside a workspace
    assert handler.execute(SimpleNamespace(group_id=None), None) is None  # nothing left to do: quiet


def test_connecting_and_removing_an_integration_through_the_api_makes_and_stops_the_task(clean, api, monkeypatch):
    clean.session.query(IntegrationModel).filter_by(group_id=clean.gid).delete()
    clean.session.commit()
    client = api(ADMIN)
    res = client.post("/api/groups/integrations", json={"provider": "mastodon", "name": "My Mastodon", "config": {}})
    assert res.status_code == 201, res.text
    [task] = tasks(clean)
    assert task.enabled is True and type_count(clean) == 1
    assert client.delete(f"/api/groups/integrations/{res.json()['id']}").status_code == 204
    assert tasks(clean)[0].enabled is False


# ── Social is hidden until something uses it ─────────────────────────────────────────────────────────────────────


def test_social_is_hidden_without_a_social_integration(clean, api):
    clean.session.query(IntegrationModel).filter_by(group_id=clean.gid).delete()
    clean.session.commit()
    body = api(EDITOR).get(f"{API}/summary").json()
    assert body["show"] is False and body["integrations"] == [] and body["new"] == 0
    api(EDITOR).get(f"{API}/summary?visit=true")
    assert tasks(clean) == [] and type_count(clean) == 0  # visiting Social with nothing to show makes nothing


def test_a_disabled_integration_does_not_show_social(clean, api):
    set_enabled(clean, False)
    assert api(EDITOR).get(f"{API}/summary").json()["show"] is False
    set_enabled(clean, True, "m-main")
    body = api(EDITOR).get(f"{API}/summary").json()
    assert body["show"] is True and [i["slug"] for i in body["integrations"]] == ["m-main"]


def test_a_visit_to_social_makes_the_plumbing_a_plain_summary_makes_nothing(clean, api):
    api(EDITOR).get(f"{API}/summary")
    assert tasks(clean) == [] and type_count(clean) == 0  # the sidebar asks on every page: it never writes
    api(EDITOR).get(f"{API}/summary?visit=true")
    assert len(tasks(clean)) == 1 and type_count(clean) == 1


def test_the_summary_counts_new_items_per_network(clean, api):
    social_setup.ensure_rule_type(clean.session, clean.gid)
    se.mode(clean, "off")
    clean.nets["mastodon"].feed = [se.item("a"), se.item("b")]
    clean.nets["bluesky"].feed = [se.item("c", network="bluesky")]
    se.rule(clean, keywords="zzz")
    run_engagement(clean.session, clean.gid, Settings(), now=se.NOW)
    body = api(EDITOR).get(f"{API}/summary").json()
    assert body["new"] == 3
    assert {i["slug"]: i["new"] for i in body["integrations"]} == {"m-main": 2, "b-main": 1, "ig": 0}


# ── the auto-reply switch ────────────────────────────────────────────────────────────────────────────────────────


def mode_of(ws, slug):
    ws.session.expire_all()
    return social_setup.get_mode(ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).one())


def test_the_auto_reply_defaults_to_off_and_an_admin_switches_it_per_network(ws, api):
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    row.state = None
    ws.session.commit()
    assert {i["slug"]: i["autoReply"] for i in api(ADMIN).get(f"{API}/summary").json()["integrations"]}["m-main"] == "off"
    for mode in ("rehearsal", "on", "off"):
        res = api(ADMIN).put(f"{API}/integrations/m-main/auto-reply", json={"mode": mode})
        assert res.status_code == 200 and res.json() == {"integration": "m-main", "autoReply": mode}
        assert mode_of(ws, "m-main") == mode
    assert mode_of(ws, "b-main") == "on"  # the others are untouched (the fixture set them on)


def test_only_an_admin_switches_it_and_a_bad_mode_or_network_is_refused(ws, api):
    for role in (VIEWER, AUTHOR, EDITOR):
        assert api(role).put(f"{API}/integrations/m-main/auto-reply", json={"mode": "off"}).status_code == 403
    assert api(ADMIN).put(f"{API}/integrations/m-main/auto-reply", json={"mode": "maybe"}).status_code == 422
    assert api(ADMIN).put(f"{API}/integrations/nope/auto-reply", json={"mode": "on"}).status_code == 404
    assert mode_of(ws, "m-main") == "on"


def test_a_network_that_cannot_reply_can_only_be_off(ws, api):
    nets = ws.nets["bluesky"]
    nets.actions = tuple(a for a in nets.actions if a.capability != "social.reply")
    assert api(ADMIN).put(f"{API}/integrations/b-main/auto-reply", json={"mode": "on"}).status_code == 409
    assert api(ADMIN).put(f"{API}/integrations/b-main/auto-reply", json={"mode": "off"}).status_code == 200
    body = {i["slug"]: i for i in api(EDITOR).get(f"{API}/summary").json()["integrations"]}
    assert body["b-main"]["canReply"] is False and body["m-main"]["canReply"] is True


# ── a network's rules ────────────────────────────────────────────────────────────────────────────────────────────


def rules_of(client, slug=None):
    res = client.get(f"{API}/rules" + (f"?integration={slug}" if slug else ""))
    assert res.status_code == 200, res.text
    return {r["slug"]: r for r in res.json()["rules"]}


def test_a_network_lists_its_rules_plus_the_all_network_ones(ws, api):
    se.rule(ws, "everyone", networks="")
    se.rule(ws, "masto", networks="m-main")
    se.rule(ws, "masto-by-name", networks="mastodon")
    se.rule(ws, "blue", networks="b-main")
    se.rule(ws, "both", networks="m-main, b-main", status="draft")
    client = api(EDITOR)
    assert set(rules_of(client, "m-main")) == {"everyone", "masto", "masto-by-name", "both"}
    assert set(rules_of(client, "b-main")) == {"everyone", "blue", "both"}
    assert set(rules_of(client, "ig")) == {"everyone"}
    assert set(rules_of(client)) == {"everyone", "masto", "masto-by-name", "blue", "both"}
    one = rules_of(client, "m-main")
    assert one["everyone"]["allNetworks"] is True and one["masto"]["allNetworks"] is False and one["masto"]["networks"] == ["m-main"]
    assert (one["both"]["status"], one["both"]["published"], one["masto"]["published"]) == ("draft", False, True)
    assert one["masto"]["keywords"] == ["price"] and one["masto"]["path"] == f"/workspace/entries/{one['masto']['id']}"


def test_a_trashed_rule_is_not_listed_and_instagrams_older_rules_are_marked(ws, api):
    se.rule(ws, "gone")
    ws.session.query(Entries).filter_by(group_id=ws.gid, slug="gone").update({"status": "trashed"})
    for slug in ("ig-auto-reply",):
        ws.session.add(EntryTypes(session=ws.session, group_id=ws.gid, slug=slug, name=slug, schema_json={"fields": []}))
    ws.session.commit()
    se._entry(ws, "ig-auto-reply", "old-ig", {"post_id": "*", "keywords": "cost", "reply": "DM sent"})
    client = api(EDITOR)
    assert "gone" not in rules_of(client, "ig")
    old = rules_of(client, "ig")["old-ig"]
    assert (old["legacy"], old["networks"], old["allNetworks"], old["replyAs"]) == (True, ["instagram"], False, "private")
    assert "old-ig" not in rules_of(client, "m-main")


def test_a_rule_made_from_a_networks_page_defaults_to_that_network_as_a_draft(ws, api):
    client = api(EDITOR)
    res = client.post(f"{API}/rules", json={"integration": "b-main"})
    assert res.status_code == 201, res.text
    made = res.json()
    assert (made["networks"], made["status"], made["published"], made["allNetworks"]) == (["b-main"], "draft", False, False)
    entry = ws.session.query(Entries).filter_by(id=made["id"]).one()
    assert entry.data_json["networks"] == "b-main" and entry.created_by == ws.uid and entry.entry_type.slug == "social-auto-reply"
    assert set(rules_of(client, "b-main")) == {made["slug"]} and made["slug"] not in rules_of(client, "m-main")
    assert made["slug"] not in [r.id for r in load_rules(ws.session, ws.gid)]  # a draft never fires


def test_a_rule_for_every_network_is_made_with_no_network_named(ws, api):
    client = api(EDITOR)
    for body in (None, {}, {"integration": None}):
        res = client.post(f"{API}/rules", **({"json": body} if body is not None else {}))
        assert res.status_code == 201, res.text
        assert res.json()["networks"] == [] and res.json()["allNetworks"] is True


def test_a_rule_for_an_unknown_or_unconnected_network_is_refused(ws, api):
    assert api(EDITOR).post(f"{API}/rules", json={"integration": "nope"}).status_code == 404
    set_enabled(ws, False, "b-main")
    assert api(EDITOR).post(f"{API}/rules", json={"integration": "b-main"}).status_code == 404
    assert api(EDITOR).get(f"{API}/rules?integration=b-main").status_code == 404


def test_publishing_and_unpublishing_a_rule_is_what_arms_and_disarms_it(ws, api):
    rule_id = api(EDITOR).post(f"{API}/rules", json={"integration": "m-main"}).json()["id"]
    blank = api(EDITOR).put(f"{API}/rules/{rule_id}/published", json={"published": True})
    assert blank.status_code >= 400  # no keywords or reply yet: the entry's own completeness rule holds
    entry = ws.session.query(Entries).filter_by(id=rule_id).one()
    entry.data_json = {**entry.data_json, "keywords": "price", "reply": "Check the link."}
    ws.session.commit()
    assert [r.id for r in load_rules(ws.session, ws.gid)] == []
    res = api(EDITOR).put(f"{API}/rules/{rule_id}/published", json={"published": True})
    assert res.status_code == 200, res.text
    assert res.json()["published"] is True and res.json()["status"] == "published"
    assert [r.reply for r in load_rules(ws.session, ws.gid)] == ["Check the link."]
    back = api(EDITOR).put(f"{API}/rules/{rule_id}/published", json={"published": False})
    assert back.json()["published"] is False and back.json()["status"] == "draft"
    assert load_rules(ws.session, ws.gid) == []


def test_only_a_rule_entry_can_be_published_through_here(ws, api):
    note = EntryTypes(session=ws.session, group_id=ws.gid, slug="note", name="Note", schema_json={"fields": []})
    ws.session.add(note)
    ws.session.commit()
    se._entry(ws, "note", "a-note", {}, status="draft")
    entry = ws.session.query(Entries).filter_by(group_id=ws.gid, slug="a-note").one()
    assert api(EDITOR).put(f"{API}/rules/{entry.id}/published", json={"published": True}).status_code == 404
    assert api(EDITOR).put(f"{API}/rules/{uuid.uuid4()}/published", json={"published": True}).status_code == 404


# ── the replies ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_replies_view_is_the_items_with_a_reply_live_or_rehearsal_with_who_and_when(ws, api):
    se.rule(ws, keywords="price")
    se.mode(ws, "rehearsal", "b-main")
    ws.nets["mastodon"].feed = [se.item("m1", "price?"), se.item("m2", "just saying hi")]
    ws.nets["bluesky"].feed = [se.item("b1", "price?", network="bluesky")]
    run_engagement(ws.session, ws.gid, Settings(), now=se.NOW)
    client = api(EDITOR)
    body = client.get(f"{API}/replies").json()
    assert body["total"] == 2 and {i["integration"] for i in body["items"]} == {"m-main", "b-main"}
    by_integration = {i["integration"]: i for i in body["items"]}
    live, dry = by_integration["m-main"]["reply"], by_integration["b-main"]["reply"]
    assert (live["rehearsal"], live["mode"], live["rule"], live["text"], live["replyId"]) == (
        False,
        "private",
        "r1",
        "Check the link in bio.",
        "r-m1-p",
    )
    assert live["at"] and live["by"] is None and live["ruleEntryId"] == str(ws.session.query(Entries).filter_by(slug="r1").one().id)
    assert (dry["rehearsal"], dry["replyId"]) == (True, None)
    assert client.get(f"{API}/replies?rehearsal=true").json()["total"] == 1
    assert client.get(f"{API}/replies?rehearsal=false").json()["items"][0]["integration"] == "m-main"
    assert client.get(f"{API}/replies?integration=b-main").json()["total"] == 1
    assert client.get(f"{API}").json()["total"] == 3  # the inbox still lists every item, replied or not


def test_a_persons_reply_shows_who_sent_it(ws, api):
    se.rule(ws, keywords="zzz")
    ws.nets["mastodon"].feed = [se.item("m1")]
    run_engagement(ws.session, ws.gid, Settings(), now=se.NOW)
    from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item

    item_id = ws.session.query(Item).filter_by(group_id=ws.gid, item_id="m1").one().id
    assert api(ADMIN).post(f"{API}/{item_id}/reply", json={"text": "hello there"}).status_code == 200
    [row] = api(EDITOR).get(f"{API}/replies").json()["items"]
    assert row["reply"]["text"] == "hello there" and row["reply"]["by"] == str(ws.uid) and row["reply"]["byName"] and row["reply"]["rule"] is None


# ── who may do what ──────────────────────────────────────────────────────────────────────────────────────────────

GATES = [
    ("get", "/replies", None, EDITOR, 200),
    ("get", "/rules", None, EDITOR, 200),
    ("get", "/rules?integration=m-main", None, EDITOR, 200),
    ("post", "/rules", {"integration": "m-main"}, EDITOR, 201),
    ("put", "/integrations/m-main/auto-reply", {"mode": "rehearsal"}, ADMIN, 200),
]
BELOW = {EDITOR: [VIEWER, AUTHOR], ADMIN: [VIEWER, AUTHOR, EDITOR]}


@pytest.mark.parametrize("method, path, body, needed, ok_status", GATES, ids=[f"{m} {p}" for m, p, *_ in GATES])
def test_each_new_route_needs_its_role(ws, api, method, path, body, needed, ok_status):
    for role in BELOW[needed]:
        res = api(role).request(method, API + path, **({"json": body} if body is not None else {}))
        assert res.status_code == 403, (role, res.status_code)
    res = api(needed).request(method, API + path, **({"json": body} if body is not None else {}))
    assert res.status_code == ok_status, res.text


def test_publishing_a_rule_needs_an_editor(ws, api):
    se.rule(ws, "draft-one", status="draft")
    entry = ws.session.query(Entries).filter_by(group_id=ws.gid, slug="draft-one").one()
    for role in (VIEWER, AUTHOR):
        assert api(role).put(f"{API}/rules/{entry.id}/published", json={"published": True}).status_code == 403
    assert api(EDITOR).put(f"{API}/rules/{entry.id}/published", json={"published": True}).status_code == 200
