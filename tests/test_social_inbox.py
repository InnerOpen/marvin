"""The Social inbox: the poll keeps what it reads, and a person lists and acts on it.

The fake networks and the workspace are the engine's own (tests/test_social_engagement.py). Held here: the poll persisting items
(one row per item however many reads see it, the account's own skipped, nothing older than the retention window, one batch
insert, a failure that never costs the poll its replies) and the daily prune; the status transitions; the API's list filters,
paging and isolation; each action through the capability the item's network declares, and the refusals (an action the network
doesn't have, a mode it refuses, a network that fails); the roles; a reply written to the reply log so the engine never answers
that comment again; making a rule from an item; and the narrow door itself.
"""

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

# ruff: noqa: E402, F811 — fixtures are imported from the engine's tests
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa
from marvin_integration_sdk import IntegrationError

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.integrations import social_inbox
from marvin.services.integrations import social_inbox_actions as actions
from marvin.services.integrations.social_engagement import Settings, run_engagement
from marvin.services.integrations.social_rules import suggest_keywords
from tests import test_content_role_gates as gates
from tests import test_social_engagement as se

NOW, item, rule, logs = se.NOW, se.item, se.rule, se.logs
ws, nets, _types = se.ws, se.nets, se._types
LIVE, REHEARSAL, ANNOUNCE_ONLY = "on", "rehearsal", "off"  # the auto-reply mode every network is set to for a poll
API = "/api/groups/social-inbox"
ADMIN, EDITOR, VIEWER = WorkspaceRole.ADMIN, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER


def rows(ws, **filters):
    ws.session.expire_all()
    return ws.session.query(Item).filter_by(group_id=ws.gid, **filters).order_by(Item.posted_at).all()


def by_id(ws, integration="m-main"):
    return {r.item_id: r for r in rows(ws, integration_slug=integration)}


def poll(ws, feed, *, settings=LIVE, network="mastodon", now=NOW):
    ws.nets[network].feed = feed
    se.mode(ws, settings)
    return run_engagement(ws.session, ws.gid, Settings(), now=now)


@pytest.fixture
def api(ws):
    """A client signed in as a member with a given role."""
    me = SimpleNamespace(gid=ws.gid, uid=ws.uid, slug="inbox")
    yield lambda role=ADMIN: gates._sign_in(me, role)
    app.dependency_overrides.pop(get_current_user, None)


def seed(ws, feed=None, *, network="mastodon", **kw):
    """Poll once (a rule so the poll reads) and return the stored rows by item id."""
    rule(ws, keywords="zzz-never-matches")
    poll(ws, feed if feed is not None else [item("c1"), item("c2", "Love it", handle="bob")], network=network, **kw)
    return by_id(ws, {"mastodon": "m-main", "bluesky": "b-main", "instagram": "ig"}[network])


# ── the poll keeps what it reads ─────────────────────────────────────────────────────────────────────────────────


def test_the_poll_keeps_each_item_it_reads_with_its_fields(ws):
    stored = seed(ws, [item("c1", "What is the price?", kind="reply", post="p9", handle="alice"), item("c2", "Hi", kind="mention")])
    assert set(stored) == {"c1", "c2"}
    c1 = stored["c1"]
    assert (c1.integration_slug, c1.network, c1.kind, c1.post_id, c1.status) == ("m-main", "x", "reply", "p9", "new")
    assert (c1.author_handle, c1.author_name, c1.author_id) == ("alice", "Alice", "u-alice")
    assert c1.text == "What is the price?" and c1.url == "https://x.example/c/c1" and c1.post_url == "https://x.example/p/p9"
    assert c1.posted_at == NOW - timedelta(hours=1) and c1.first_seen_at == NOW
    assert stored["c2"].kind == "mention"


def test_an_item_read_twice_is_one_row_and_a_later_read_changes_nothing(ws):
    seed(ws, [item("c1", "first words")])
    row = by_id(ws)["c1"]
    row.status = "seen"
    ws.session.commit()
    poll(ws, [item("c1", "first words"), item("c1", "edited words"), item("c3")])  # the cursor passed c1: a re-read, a duplicate in the batch
    stored = by_id(ws)
    assert sorted(stored) == ["c1", "c3"]
    assert (stored["c1"].text, stored["c1"].status) == ("first words", "seen")


def test_the_announce_and_the_reply_reads_of_one_poll_make_one_row_each(ws):
    rule(ws, keywords="price")
    ws.nets["mastodon"].feed = [item("c1", "price?"), item("c2", "price again?")]
    se.mode(ws, "rehearsal")
    run_engagement(ws.session, ws.gid, Settings(), now=NOW)  # replying and announcing both on
    assert sorted(by_id(ws)) == ["c1", "c2"]
    assert ws.session.query(Item).filter_by(group_id=ws.gid).count() == 2


def test_an_announce_only_poll_keeps_items_with_no_rule_at_all(ws):
    ws.nets["mastodon"].feed = [item("c1")]
    se.mode(ws, ANNOUNCE_ONLY)
    run_engagement(ws.session, ws.gid, Settings(), now=NOW)
    assert list(by_id(ws)) == ["c1"]


def test_the_accounts_own_items_are_not_kept(ws):
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    row.config = {"username": "shop", "user_id": "acct-1"}
    ws.session.commit()
    stored = seed(
        ws, [item("c1", handle="shop"), item("c2", handle="@Shop"), item("c3", handle="other", author_id="acct-1"), item("c4", handle="bob")]
    )
    assert sorted(stored) == ["c4"]


def test_items_older_than_the_retention_window_are_not_kept(ws):
    stored = seed(ws, [item("old", age_hours=31 * 24), item("edge", age_hours=29 * 24), item("new")])
    assert sorted(stored) == ["edge", "new"]


def test_one_read_is_one_insert_however_many_items(ws):
    inserts = []

    def watch(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("INSERT INTO SOCIAL_INBOX"):
            inserts.append(statement)

    engine = ws.session.get_bind()
    sa.event.listen(engine, "before_cursor_execute", watch)
    try:
        seed(ws, [item(f"c{i}", handle=f"u{i}") for i in range(40)])
    finally:
        sa.event.remove(engine, "before_cursor_execute", watch)
    assert len(by_id(ws)) == 40
    assert len(inserts) == 1  # a batch, not forty statements


def test_a_failure_keeping_items_never_costs_the_poll_its_replies(ws, monkeypatch):
    monkeypatch.setattr(social_inbox, "_fresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk on fire")))
    rule(ws)
    report = poll(ws, [item("c1")])
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"] and report.sent == 1
    [row] = rows(ws)  # the poll couldn't keep the item, but the reply inserted it: every reply has an item
    assert (row.item_id, row.status, row.reply_rule) == ("c1", "replied", "r1")


def test_the_same_item_id_on_two_integrations_is_two_rows(ws):
    rule(ws, keywords="zzz")
    poll(ws, [item("same")], network="mastodon")
    poll(ws, [item("same")], network="instagram")
    assert {(r.integration_slug, r.item_id) for r in rows(ws)} == {("m-main", "same"), ("ig", "same")}


def test_the_unique_key_is_the_integration_and_the_item(ws):
    seed(ws, [item("c1")])
    existing = by_id(ws)["c1"]
    ws.session.add(Item(session=ws.session, group_id=ws.gid, integration_id=existing.integration_id, integration_slug="m-main", network="x",
                        item_id="c1", kind="comment", text="dup", posted_at=NOW, first_seen_at=NOW))  # fmt: skip
    with pytest.raises(sa.exc.IntegrityError):
        ws.session.commit()
    ws.session.rollback()


# ── what a reply does to the item ────────────────────────────────────────────────────────────────────────────────


def test_a_live_reply_by_a_rule_is_recorded_on_the_item(ws):
    rule(ws, keywords="price")
    poll(ws, [item("c1", "price?"), item("c2", "nice")])
    stored = by_id(ws)
    c1 = stored["c1"]
    assert (c1.status, c1.reply_mode, c1.reply_rehearsal) == ("replied", "private", False)
    assert (c1.reply_rule, c1.reply_text, c1.reply_id, c1.reply_log_slug) == ("r1", "Check the link in bio.", "r-c1-p", None)
    assert c1.replied_at is not None and c1.replied_by is None
    assert (stored["c2"].status, stored["c2"].replied_at, stored["c2"].reply_rule) == ("new", None, None)


def test_a_rehearsal_is_recorded_but_leaves_the_status_and_a_real_reply_replaces_it(ws):
    rule(ws, keywords="price")
    poll(ws, [item("c1", "price?")], settings=REHEARSAL)
    row = by_id(ws)["c1"]
    assert (row.status, row.reply_rehearsal, row.reply_rule, row.reply_id) == ("new", True, "r1", None)
    poll(ws, [item("c1", "price?")])  # switched to live: the rehearsal never counted as answered
    row = by_id(ws)["c1"]
    assert (row.status, row.reply_rehearsal, row.reply_id) == ("replied", False, "r-c1-p")
    poll(ws, [item("c1", "price?")], settings=REHEARSAL)  # a later rehearsal never takes the live record back
    assert by_id(ws)["c1"].reply_rehearsal is False


# ── the status transitions ───────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "current, event, replied, expected",
    [
        ("new", "seen", False, "seen"),
        ("seen", "seen", False, "seen"),
        ("replied", "seen", True, "replied"),
        ("liked", "seen", False, "liked"),
        ("hidden", "seen", False, "hidden"),
        ("new", "liked", False, "liked"),
        ("seen", "liked", False, "liked"),
        ("replied", "liked", True, "replied"),  # a like never downgrades a reply
        ("new", "replied", False, "replied"),
        ("liked", "replied", False, "replied"),
        ("hidden", "replied", False, "hidden"),  # nor does a reply unhide
        ("new", "hidden", False, "hidden"),
        ("replied", "hidden", True, "hidden"),
        ("hidden", "unhidden", False, "seen"),
        ("hidden", "unhidden", True, "replied"),
        ("new", "unhidden", False, "new"),
    ],
)
def test_the_status_transitions(current, event, replied, expected):
    assert social_inbox.next_status(current, event, replied=replied) == expected


def test_an_unknown_event_is_refused():
    with pytest.raises(ValueError):
        social_inbox.next_status("new", "shouted")


# ── the prune ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_prune_drops_what_is_older_than_the_cutoff_and_keeps_the_rest(ws):
    seed(ws, [item("recent"), item("older", age_hours=10 * 24), item("oldest", age_hours=25 * 24)])
    assert social_inbox.prune(ws.session, NOW - timedelta(days=30)) == 0
    assert social_inbox.prune(ws.session, NOW - timedelta(days=20)) == 1
    assert sorted(by_id(ws)) == ["older", "recent"]


def test_the_prune_task_is_a_daily_system_task_with_a_handler_and_a_retention_config():
    from marvin.services.scheduled_tasks import TaskHandlerRegistry
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    (task,) = [d for d in SYSTEM_SCHEDULED_TASKS if d.slug == "prune_social_inbox_items"]
    assert task.schedule_config == {"interval_seconds": 86400} and task.task_config == {"retention_days": 30} and task.enabled
    assert TaskHandlerRegistry.get_handler(task.task_type).admin_only


def test_the_prune_handler_deletes_by_the_tasks_retention_and_refuses_a_workspace(ws):
    from marvin.services.scheduled_tasks.handlers.maintenance import PruneSocialInboxItemsHandler

    seed(ws, [item("recent"), item("aging", age_hours=24 * 6)])
    ws.session.query(Item).filter_by(item_id="aging").update({"posted_at": datetime.now(UTC) - timedelta(days=40)})
    ws.session.commit()
    handler = PruneSocialInboxItemsHandler()
    task = SimpleNamespace(group_id=None, task_config={"retention_days": 30})
    assert "Pruned 1 social inbox item" in handler.execute(task, None)
    assert handler.execute(task, None) is None  # nothing left to say
    assert "disabled" in handler.execute(SimpleNamespace(group_id=None, task_config={"retention_days": 0}), None)
    assert "admin-only" in handler.execute(SimpleNamespace(group_id=ws.gid, task_config={}), None)
    assert sorted(by_id(ws)) == ["recent"]


# ── the list ─────────────────────────────────────────────────────────────────────────────────────────────────────


def listed(client, **params):
    res = client.get(API, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def ids(body):
    return [i["id"] for i in body["items"]]


def test_an_item_a_rule_matched_but_didnt_answer_says_why_with_the_rule(ws, api):
    from marvin.services.integrations import social_inbox

    seed(ws, [item("c1", "What is the price?")])
    integration = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    until = NOW + timedelta(hours=20)
    assert social_inbox.hold(ws.session, integration, "c1", reason="cooldown", rule="r1", until=until, now=NOW)
    ws.session.commit()
    rule_id = ws.session.query(Entries.id).filter_by(group_id=ws.gid, slug="r1").scalar()

    by_item = {i["text"]: i for i in listed(api(ADMIN))["items"]}
    held = by_item["What is the price?"]["held"]
    assert (held["reason"], held["rule"], held["ruleEntryId"]) == ("cooldown", "r1", str(rule_id))
    assert datetime.fromisoformat(held["until"].replace("Z", "+00:00")) == until
    assert all(i["held"] is None for i in listed(api(ADMIN))["items"] if i["text"] != "What is the price?")


@pytest.fixture
def filled(ws):
    """Items on mastodon (x-network items) and bluesky, of every kind and a few statuses, written at different times."""
    rule(ws, keywords="zzz")
    poll(ws, [
        item("m1", "What is the price?", handle="alice", age_hours=5),
        item("m2", "Love this", kind="reply", handle="bob", age_hours=4),
        item("m3", "@shop nice work", kind="mention", handle="carol", age_hours=3),
        item("m4", "Where do I buy it_100%?", handle="dave", age_hours=2),
    ], network="mastodon")  # fmt: skip
    poll(ws, [item("b1", "Great post", handle="erin", network="bsky", age_hours=1)], network="bluesky")
    stored = by_id(ws) | by_id(ws, "b-main")
    stored["m2"].status = "seen"
    stored["m3"].status = "hidden"
    ws.session.commit()
    return stored


def test_the_list_is_newest_first_with_the_fields_a_page_needs(ws, api, filled):
    body = listed(api(EDITOR))
    assert [i["integration"] for i in body["items"]] == ["b-main", "m-main", "m-main", "m-main", "m-main"]
    assert body["total"] == 5 and body["new"] == 3 and (body["limit"], body["offset"]) == (50, 0)
    first = body["items"][0]
    assert (first["network"], first["kind"], first["text"], first["status"]) == ("bsky", "comment", "Great post", "new")
    assert first["author"] == {"id": "u-erin", "handle": "erin", "name": "Erin"} and first["url"].endswith("/c/b1")
    assert first["createdAt"].startswith("2026-10-20T11:00") and first["reply"] is None


def test_the_list_filters_by_integration_network_kind_and_status(ws, api, filled):
    client = api(EDITOR)
    assert ids(listed(client, integration="b-main")) == [str(filled["b1"].id)]
    assert listed(client, network="BSKY")["total"] == 1 and listed(client, network="x")["total"] == 4
    assert listed(client, kind="mention")["total"] == 1 and listed(client, kind="comment")["total"] == 3
    assert listed(client, status="new")["total"] == 3
    assert listed(client, status=["seen", "hidden"])["total"] == 2
    assert listed(client, integration="m-main", kind="comment", status="new")["total"] == 2
    assert client.get(API, params={"kind": "tweet"}).status_code == 422 and client.get(API, params={"status": "done"}).status_code == 422


def test_the_list_searches_text_and_authors_without_treating_wildcards_as_wildcards(ws, api, filled):
    client = api(EDITOR)
    assert listed(client, q="PRICE")["total"] == 1
    assert listed(client, q="carol")["total"] == 1 and listed(client, q="Bob")["total"] == 1  # an author's handle or name
    assert listed(client, q="it_100%")["total"] == 1
    assert listed(client, q="_")["total"] == 1 and listed(client, q="%")["total"] == 1  # literal, not "anything"
    assert listed(client, q="nothing like it")["total"] == 0


def test_the_list_filters_by_when_an_item_was_written_and_pages(ws, api, filled):
    client = api(EDITOR)
    since = (NOW - timedelta(hours=3, minutes=30)).isoformat()
    until = (NOW - timedelta(hours=1, minutes=30)).isoformat()
    assert listed(client, since=since)["total"] == 3
    assert [i["integration"] for i in listed(client, since=since, until=until)["items"]] == ["m-main", "m-main"]
    page1, page2 = listed(client, limit=2), listed(client, limit=2, offset=2)
    assert page1["total"] == 5 and len(page1["items"]) == 2 and len(page2["items"]) == 2
    assert set(ids(page1)).isdisjoint(ids(page2))
    assert client.get(API, params={"limit": 0}).status_code == 422 and client.get(API, params={"limit": 500}).status_code == 422


def test_the_list_never_shows_another_workspaces_items(ws, api, filled, db_session):
    from marvin.db.models.groups.groups import Groups

    other = uuid.uuid4()
    db_session.add(Groups(session=db_session, name=f"o-{other.hex[:6]}", slug=f"o-{other.hex[:6]}"))
    db_session.flush()
    other_group = db_session.query(Groups).filter_by(slug=f"o-{other.hex[:6]}").one()
    integration = IntegrationModel(session=db_session, group_id=other_group.id, provider="mastodon", name="o", slug="o", enabled=True, config={})
    db_session.add(integration)
    db_session.flush()
    db_session.add(Item(session=db_session, group_id=other_group.id, integration_id=integration.id, integration_slug="o", network="x",
                        item_id="theirs", kind="comment", text="secret", posted_at=NOW, first_seen_at=NOW))  # fmt: skip
    db_session.commit()
    try:
        client = api(EDITOR)
        body = listed(client)
        assert body["total"] == 5 and all(i["text"] != "secret" for i in body["items"])
        theirs = db_session.query(Item).filter_by(item_id="theirs").one()
        assert client.post(f"{API}/{theirs.id}/like").status_code == 404
        assert api(ADMIN).delete(f"{API}/{theirs.id}").status_code == 404
    finally:
        db_session.rollback()
        db_session.query(Groups).filter_by(id=other_group.id).delete()  # cascades the integration and the item
        db_session.commit()


def test_each_item_lists_only_what_its_network_offers(ws, api, filled):
    by_text = {i["text"]: i for i in listed(api(EDITOR))["items"]}
    assert by_text["What is the price?"]["actions"] == ["reply", "like", "hide", "delete", "message"]
    assert by_text["What is the price?"]["replyModes"] == ["private", "public"]
    assert by_text["@shop nice work"]["actions"] == ["reply", "like", "message"]  # a mention: nothing to hide or delete under your own post
    assert by_text["Great post"]["actions"] == ["reply", "hide", "delete", "message"]  # bluesky's fake has no like


def test_an_item_whose_integration_is_off_offers_nothing(ws, api, filled):
    ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="b-main").update({"enabled": False})
    ws.session.commit()
    item_ = [i for i in listed(api(EDITOR))["items"] if i["integration"] == "b-main"][0]
    assert item_["actions"] == [] and item_["replyModes"] == []
    assert api(ADMIN).post(f"{API}/{item_['id']}/reply", json={"text": "hi"}).status_code == 409


def test_a_network_can_offer_one_reply_mode_only(ws, api, filled, nets):
    reply = next(a for a in nets["mastodon"].actions if a.capability == "social.reply")
    object.__setattr__(reply, "input_schema", {"properties": {"private": {"type": "boolean", "enum": [False]}}})
    assert actions.reply_modes(nets["mastodon"]) == ["public"]
    mastodon = [i for i in listed(api(EDITOR))["items"] if i["integration"] == "m-main"]
    assert {tuple(i["replyModes"]) for i in mastodon} == {("public",)}
    res = api(ADMIN).post(f"{API}/{mastodon[0]['id']}/reply", json={"text": "hi", "private": True})
    assert res.status_code == 422 and "private reply" in res.json()["detail"] and nets["mastodon"].sent() == []


def test_the_summary_lists_the_networks_with_their_mode_and_new_count(ws, api):
    body = api(EDITOR).get(f"{API}/summary").json()
    assert body["show"] is True and body["new"] == 0  # networks that offer social capabilities exist, nothing kept yet
    by_slug = {i["slug"]: i for i in body["integrations"]}
    assert set(by_slug) == {"m-main", "b-main", "ig"}
    assert (by_slug["m-main"]["autoReply"], by_slug["m-main"]["readsComments"], by_slug["m-main"]["canReply"]) == ("on", True, True)
    assert by_slug["m-main"]["provider"] == "mastodon" and "social.comments" in by_slug["m-main"]["capabilities"]
    assert body["can"] == {
        "seen": True, "like": True, "hide": True, "trash": True, "sort": True, "rule": True, "rules": True, "publish": True,
        "auto_reply": False, "reply": False, "delete": False, "message": False,
    }  # fmt: skip
    assert api(ADMIN).get(f"{API}/summary").json()["can"]["reply"] is True
    assert api(ADMIN).get(f"{API}/summary").json()["can"]["auto_reply"] is True
    assert "engine" not in body


# ── mark seen ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_marking_seen_moves_only_new_items_by_id_or_all_or_one_integration(ws, api, filled):
    client = api(EDITOR)
    assert client.post(f"{API}/seen", json={}).status_code == 422
    assert client.post(f"{API}/seen", json={"ids": [str(filled["m1"].id), str(filled["m3"].id)]}).json() == {"changed": 1}  # m3 is hidden: untouched
    ws.session.expire_all()
    assert (filled["m1"].status, filled["m3"].status) == ("seen", "hidden")
    assert client.post(f"{API}/seen", json={"all": True, "integration": "b-main"}).json() == {"changed": 1}
    assert listed(client)["new"] == 1
    assert client.post(f"{API}/seen", json={"all": True}).json() == {"changed": 1}
    assert listed(client)["new"] == 0 and listed(client, status="new")["total"] == 0


# ── the actions ──────────────────────────────────────────────────────────────────────────────────────────────────


def post(client, ws, cid, action, body=None, *, integration="m-main"):
    row = by_id(ws, integration)[cid]
    return client.post(f"{API}/{row.id}/{action}", json=body) if body is not None else client.post(f"{API}/{row.id}/{action}")


def test_a_private_reply_is_sent_by_the_capability_recorded_on_the_item_and_marks_it_replied(ws, api):
    seed(ws, [item("c1", "What is the price?")])
    res = post(api(ADMIN), ws, "c1", "reply", {"text": "DM sent!"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["replied"], body["private"], body["replyId"]) == (True, True, "r-c1-p")
    assert body["item"]["status"] == "replied" and body["item"]["reply"]["rehearsal"] is False and body["item"]["reply"]["mode"] == "private"
    assert ws.nets["mastodon"].sent() == [{"comment_id": "c1", "text": "DM sent!", "private": True, "dry_run": False}]
    (entry,) = logs(ws, rehearsal=False)
    assert (entry["comment_id"], entry["rule"], entry["mode"], entry["reply"], entry["rehearsal"]) == ("c1", None, "private", "DM sent!", False)
    assert entry["integration"] == "m-main" and entry["by"] == ws.uid and entry["reply_id"] == "r-c1-p"
    assert body["item"]["reply"]["text"] == "DM sent!" and body["item"]["reply"]["by"] == str(ws.uid) and body["item"]["reply"]["rule"] is None
    assert ws.session.query(Entries).filter_by(group_id=ws.gid).filter(Entries.slug.like("social-reply-%")).count() == 0  # no log entry


def test_a_reply_defaults_to_private_and_public_is_asked_for(ws, api):
    seed(ws, [item("c1"), item("c2")])
    post(api(ADMIN), ws, "c1", "reply", {"text": "hello"})
    res = post(api(ADMIN), ws, "c2", "reply", {"text": "hello all", "private": False})
    assert res.json()["private"] is False and res.json()["url"] == "https://mastodon.example/r"
    assert [a["private"] for a in ws.nets["mastodon"].sent()] == [True, False]
    assert {e["comment_id"]: e["mode"] for e in logs(ws)} == {"c1": "private", "c2": "public"}


def test_the_engine_never_answers_a_comment_a_person_replied_to(ws, api):
    rule(ws, keywords="price")
    ws.nets["mastodon"].feed = [item("c1", "price?")]
    se.mode(ws, "rehearsal")
    run_engagement(ws.session, ws.gid, Settings(), now=NOW)  # kept (the rehearsal is recorded on the item)
    assert post(api(ADMIN), ws, "c1", "reply", {"text": "I'll take it from here"}).status_code == 200
    ws.nets["mastodon"].calls.clear()
    ws.nets["mastodon"].feed = [item("c1", "price?"), item("c2", "price too?")]
    se.mode(ws, "on")
    report = run_engagement(ws.session, ws.gid, Settings(), now=NOW)
    sent = [a for a in ws.nets["mastodon"].sent() if a["text"] != "I'll take it from here"]
    assert [a["comment_id"] for a in sent] == ["c2"]
    assert report.skipped["already_replied"] >= 1
    assert by_id(ws)["c1"].replied_by == ws.uid  # the engine's pass left the person's reply on the item


def test_a_comment_the_engine_already_answered_can_still_be_replied_to_and_the_record_follows_the_latest(ws, api):
    rule(ws, keywords="price")
    poll(ws, [item("c1", "price?")])
    assert len(logs(ws, rehearsal=False)) == 1 and logs(ws)[0]["rule"] == "r1"
    res = post(api(ADMIN), ws, "c1", "reply", {"text": "and a follow-up", "private": False})
    assert res.status_code == 200
    [only] = logs(ws, rehearsal=False)
    assert only["reply"] == "and a follow-up" and only["rule"] is None and only["by"] == ws.uid and only["mode"] == "public"
    assert len(ws.nets["mastodon"].sent()) == 2


def test_a_reply_the_network_refuses_or_fails_is_not_recorded_and_changes_nothing(ws, api):
    seed(ws, [item("c1"), item("c2"), item("c3")])
    net = ws.nets["mastodon"]
    net.refuse = {("c1", True): "unsupported"}
    refused = post(api(ADMIN), ws, "c1", "reply", {"text": "x"})
    assert refused.status_code == 422 and "unsupported" in refused.json()["detail"]
    net.refuse = {("c2", True): "unknown"}
    failed = post(api(ADMIN), ws, "c2", "reply", {"text": "x"})
    assert failed.status_code == 502
    assert logs(ws) == [] and {r.status for r in rows(ws)} == {"new"}
    assert post(api(ADMIN), ws, "c3", "reply", {"text": "   "}).status_code == 422  # nothing to say (blank after trimming)
    assert post(api(ADMIN), ws, "c3", "reply", {"text": ""}).status_code == 422


def test_a_dry_run_reply_that_was_not_sent_is_an_error_not_a_reply(ws, api, monkeypatch):
    seed(ws, [item("c1")])
    monkeypatch.setattr(
        type(ws.nets["mastodon"]), "_act", lambda self, key, args: {"replied": False, "network": "mastodon"} if key == "reply" else {}
    )
    res = post(api(ADMIN), ws, "c1", "reply", {"text": "hi"})
    assert res.status_code == 502 and logs(ws) == []


def test_liking_calls_the_capability_and_moves_new_and_seen_items_but_never_a_reply(ws, api):
    seed(ws, [item("c1"), item("c2")])
    assert post(api(EDITOR), ws, "c1", "like").json()["item"]["status"] == "liked"
    assert ws.nets["mastodon"].sent("like") == [{"comment_id": "c1"}]
    post(api(ADMIN), ws, "c2", "reply", {"text": "hi"})
    assert post(api(EDITOR), ws, "c2", "like").json()["item"]["status"] == "replied"


def test_hiding_and_unhiding_go_through_the_capability_and_the_status_follows(ws, api):
    seed(ws, [item("c1"), item("c2")])
    client = api(EDITOR)
    assert post(client, ws, "c1", "hide").json()["item"]["status"] == "hidden"  # no body: hide
    assert ws.nets["mastodon"].sent("hide") == [{"comment_id": "c1", "hidden": True}]
    assert post(client, ws, "c1", "hide", {"hidden": False}).json()["item"]["status"] == "seen"
    assert ws.nets["mastodon"].sent("hide")[-1] == {"comment_id": "c1", "hidden": False}
    post(api(ADMIN), ws, "c2", "reply", {"text": "hi"})
    post(client, ws, "c2", "hide")
    assert post(client, ws, "c2", "hide", {"hidden": False}).json()["item"]["status"] == "replied"  # unhiding an answered comment


def test_deleting_removes_the_comment_on_the_network_and_the_item(ws, api):
    seed(ws, [item("c1"), item("c2")])
    res = api(ADMIN).delete(f"{API}/{by_id(ws)['c1'].id}")
    assert res.status_code == 200 and res.json()["item"] is None
    assert ws.nets["mastodon"].sent("delete") == [{"comment_id": "c1"}] and sorted(by_id(ws)) == ["c2"]


def test_messaging_the_author_sends_to_their_id_and_handle(ws, api):
    seed(ws, [item("c1", handle="alice")])
    res = post(api(ADMIN), ws, "c1", "message", {"text": "Thanks for asking!"})
    assert res.status_code == 200 and res.json()["messageId"] == "m1" and res.json()["item"]["status"] == "seen"
    assert ws.nets["mastodon"].sent("message") == [{"to": {"id": "u-alice", "handle": "alice"}, "text": "Thanks for asking!", "dry_run": False}]
    assert post(api(ADMIN), ws, "c1", "message", {"text": ""}).status_code == 422


def test_an_action_the_network_doesnt_declare_is_refused_before_anything_is_called(ws, api):
    seed(ws, [item("b1", network="bsky")], network="bluesky")  # the fake bluesky has no like
    res = post(api(EDITOR), ws, "b1", "like", integration="b-main")
    assert res.status_code == 422 and "can't like" in res.json()["detail"]
    assert ws.nets["bluesky"].calls == [("comments", ws.nets["bluesky"].calls[0][1])]  # only the poll's own read


def test_a_mention_cant_be_hidden_or_deleted_and_a_message_needs_someone_to_send_to(ws, api):
    seed(ws, [item("c1", kind="mention"), item("c2")])
    assert post(api(EDITOR), ws, "c1", "hide").status_code == 422
    assert api(ADMIN).delete(f"{API}/{by_id(ws)['c1'].id}").status_code == 422
    row = by_id(ws)["c2"]
    row.author_id = row.author_handle = None
    ws.session.commit()
    assert post(api(ADMIN), ws, "c2", "message", {"text": "hi"}).status_code == 422
    assert ws.nets["mastodon"].sent("hide") == [] and ws.nets["mastodon"].sent("delete") == [] and ws.nets["mastodon"].sent("message") == []


def test_a_network_failure_on_like_or_hide_is_a_502_that_leaves_the_status(ws, api, monkeypatch):
    seed(ws, [item("c1")])

    def boom(self, key, args):
        if key in ("like", "hide"):
            raise IntegrationError("rate limited", code="rate_limited")
        return {}

    monkeypatch.setattr(type(ws.nets["mastodon"]), "_act", boom)
    assert post(api(EDITOR), ws, "c1", "like").status_code == 502
    assert post(api(EDITOR), ws, "c1", "hide").status_code == 502
    assert by_id(ws)["c1"].status == "new"


# ── the roles ────────────────────────────────────────────────────────────────────────────────────────────────────

GATES = [
    ("get", "", None, EDITOR),
    ("get", "/summary", None, EDITOR),
    ("post", "/seen", {"all": True}, EDITOR),
    ("post", "/{id}/like", None, EDITOR),
    ("post", "/{id}/hide", None, EDITOR),
    ("post", "/{id}/rule", None, EDITOR),
    ("post", "/{id}/reply", {"text": "hi"}, ADMIN),
    ("post", "/{id}/message", {"text": "hi"}, ADMIN),
    ("delete", "/{id}", None, ADMIN),
]
BELOW = {EDITOR: [VIEWER, WorkspaceRole.AUTHOR], ADMIN: [VIEWER, WorkspaceRole.AUTHOR, EDITOR]}


@pytest.mark.parametrize("method, path, body, needed", GATES, ids=[f"{m} {p or '/'}" for m, p, _, _ in GATES])
def test_each_route_needs_its_role_before_anything_else(ws, api, method, path, body, needed):
    seed(ws, [item("c1")])
    url = API + path.replace("{id}", str(by_id(ws)["c1"].id))
    for role in BELOW[needed]:
        res = api(role).request(method, url, **({"json": body} if body is not None else {}))
        assert res.status_code == 403, (role, res.status_code)
    assert ws.nets["mastodon"].sent("reply") == [] and ws.nets["mastodon"].sent("delete") == []
    ok = api(needed).request(method, url, **({"json": body} if body is not None else {}))
    assert ok.status_code == 200, ok.text


def test_a_role_below_the_gate_gets_403_for_an_unknown_item_too_not_a_404_that_confirms_ids(ws, api):
    assert api(EDITOR).post(f"{API}/{uuid.uuid4()}/reply", json={"text": "x"}).status_code == 403
    assert api(ADMIN).post(f"{API}/{uuid.uuid4()}/reply", json={"text": "x"}).status_code == 404


def test_a_non_member_is_refused(ws, api):
    client = gates._sign_in(SimpleNamespace(gid=ws.gid, uid=ws.uid, slug="out"), None)
    assert client.get(API).status_code in (403, 409)  # no role in the workspace (or no workspace to act in): never a list
    app.dependency_overrides.pop(get_current_user, None)


# ── the narrow door ──────────────────────────────────────────────────────────────────────────────────────────────


def _actor(ws):
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    return actions.InboxActor(ws.session, ws.gid, row, ws.nets["mastodon"])


def test_the_door_runs_only_the_five_human_capabilities_and_only_for_a_named_approver(ws):
    actor = _actor(ws)
    for capability in ("social.comments", "social.repost", "social.post", "image.generate"):
        with pytest.raises(se.EngineCallError, match="can't"):
            actor.act(capability, {"comment_id": "c1"}, approved_by=ws.uid)
    with pytest.raises(se.EngineCallError, match="no approver"):
        actor.act("social.reply", {"comment_id": "c1", "text": "hi"}, approved_by=None)
    with pytest.raises(se.EngineCallError, match="needs `text`"):
        actor.act("social.reply", {"comment_id": "c1"}, approved_by=ws.uid)
    assert ws.nets["mastodon"].calls == []
    assert (
        actor.act("social.reply", {"comment_id": "c1", "text": "hi", "private": True, "dry_run": True}, approved_by=ws.uid)["replied"] is True
    )  # dry_run is not the caller's to set
    assert ws.nets["mastodon"].sent("reply")[0]["dry_run"] is False


def test_the_door_cant_be_pointed_at_another_comment_or_network_from_the_request(ws, api):
    seed(ws, [item("c1")])
    client = api(ADMIN)
    row = by_id(ws)["c1"]
    res = client.post(f"{API}/{row.id}/reply", json={"text": "hi", "comment_id": "someone-elses", "integration": "ig", "capability": "social.repost"})
    assert res.status_code == 200
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"] and ws.nets["instagram"].sent() == []
    assert ws.nets["mastodon"].sent("repost") == []


def test_the_engines_own_door_stays_as_narrow_as_it_was(ws):
    net = se._net(ws)
    for capability in actions.HUMAN_CAPABILITIES - {"social.reply", "social.like", "social.message"}:
        with pytest.raises(se.EngineCallError, match="can't"):
            net.call(capability, {"comment_id": "c1", "text": "x"})
    with pytest.raises(se.EngineCallError, match="messages only to answer"):  # a message only answers a DM a rule matched
        net.call("social.message", {"to": {"id": "u"}, "text": "x"})
    with pytest.raises(se.EngineCallError, match="no way to social.reply"):
        net.call("social.reply", {"comment_id": "c1", "text": "x", "private": True, "dry_run": False})  # no rule: not approved


# ── make a rule from an item ─────────────────────────────────────────────────────────────────────────────────────


def test_make_a_rule_drafts_a_social_auto_reply_entry_from_the_item(ws, api):
    seed(ws, [item("c1", "What is the price of the blue one?", network="instagram")])
    res = post(api(EDITOR), ws, "c1", "rule", {"reply": "Check the link in bio."})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["keywords"] == ["price", "blue", "one"] and body["path"] == f"/workspace/entries/{body['id']}"
    entry = ws.session.query(Entries).filter_by(id=body["id"]).one()
    assert (entry.status, entry.created_by, entry.slug) == ("draft", ws.uid, body["slug"])
    assert entry.data_json == {
        "keywords": "price, blue, one", "reply": "Check the link in bio.", "networks": "m-main", "post": "", "reply_as": "private",
        "also_like": False, "kinds": "comment, reply",
    }  # fmt: skip
    from marvin.services.integrations.social_engagement import load_rules

    assert body["slug"] not in [r.id for r in load_rules(ws.session, ws.gid)]  # a draft never fires


def test_make_a_rule_without_a_reply_leaves_it_for_the_editor_and_makes_the_type_when_missing(ws, api):
    seed(ws, [item("c1", "How much is shipping?")])
    body = post(api(EDITOR), ws, "c1", "rule").json()
    entry = ws.session.query(Entries).filter_by(id=body["id"]).one()
    assert entry.data_json["reply"] == "" and body["keywords"] == ["much", "shipping"]
    ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").update({"slug": "renamed-away"})
    ws.session.commit()
    res = post(api(EDITOR), ws, "c1", "rule")  # the type is made on first need
    assert res.status_code == 200
    assert ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").count() == 1


@pytest.mark.parametrize(
    "text, expected",
    [
        ("What is the price?", ["price"]),
        ("How much does it cost?", ["much", "cost"]),
        ("@shop check https://x.example/p/1 #sale please", ["check", "please"]),
        ("", []),
        ("a an the is it", []),
        ("Shipping shipping SHIPPING to Canada, shipping?", ["shipping", "canada"]),
        ("Is it dog-friendly? I don't know", ["dog-friendly", "don't", "know"]),
    ],
)
def test_keyword_suggestions(text, expected):
    assert suggest_keywords(text) == expected
