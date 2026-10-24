"""A network that pushes: a delivery to an integration's own incoming webhook becomes Social inbox items, through the
integration's `inbox_items_from_webhook` (core never reads the network's payload). Kept as the poll's items are —
deduplicated with them, the account's own skipped — with the kinds a poll can't read (a message, a story reply…) and what an
item carried (`attachments`). A failure there never fails the delivery. An item that came in by direct message is answered
only by a message, recorded on the item as its reply.

The fake networks and the workspace are the engine's own (tests/test_social_engagement.py)."""

# ruff: noqa: F811 — `ws` / `nets` are fixtures, not redefinitions
import uuid
from datetime import UTC, datetime, timedelta

from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item
from marvin.services.integrations import social_inbox
from marvin.services.integrations import social_inbox_actions as actions
from tests import test_social_engagement as se
from tests.test_social_engagement import _types, nets, ws  # noqa: F401 — fixtures

PAYLOAD = {"object": "instagram", "entry": [{"id": "acct"}]}


def _dm(mid="mid-1", *, kind="message", text="Love this", sender="u-alice", when=None):
    when = when or datetime.now(UTC) - timedelta(minutes=1)
    return {
        "id": mid, "kind": kind, "author": {"id": sender, "handle": "", "name": ""}, "text": text,
        "created_at": when.isoformat(), "network": "instagram",
        "attachments": [{"type": "ig_post", "url": "https://cdn.example/p.jpg", "title": "A caption", "extra": "dropped"}],
    }  # fmt: skip


def _ig(ws):
    return ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="ig").one()


def _parser(ws, items):
    """The fake Instagram turns any delivery into `items` (and remembers what it was handed)."""
    seen = []

    def parse(payload, ctx):
        seen.append(payload)
        return items

    ws.nets["instagram"].inbox_items_from_webhook = parse
    return seen


def _rows(ws):
    ws.session.expire_all()
    return ws.session.query(Item).filter_by(group_id=ws.gid).order_by(Item.item_id).all()


def test_a_delivery_becomes_inbox_items_with_their_kind_and_attachments(ws):
    seen = _parser(ws, [_dm(), _dm("mid-2", kind="story_reply", text="Nice story")])

    kept = social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD)

    assert kept == 2 and seen == [PAYLOAD]
    first, second = _rows(ws)
    assert (first.kind, first.text, first.integration_slug) == ("message", "Love this", "ig")
    assert first.attachments == [{"type": "ig_post", "url": "https://cdn.example/p.jpg", "title": "A caption"}]  # only the known keys
    assert second.kind == "story_reply"


def test_the_same_item_twice_or_the_accounts_own_is_not_kept_again(ws):
    row = _ig(ws)
    row.config = {"user_id": "me"}
    ws.session.commit()
    _parser(ws, [_dm(), _dm("mid-own", sender="me")])

    social_inbox.keep_webhook_items(ws.session, row.id, ws.gid, PAYLOAD)
    again = social_inbox.keep_webhook_items(ws.session, row.id, ws.gid, PAYLOAD)

    assert again == 0 and [r.item_id for r in _rows(ws)] == ["mid-1"]


def test_an_unknown_kind_is_kept_as_a_comment(ws):
    _parser(ws, [_dm(kind="telepathy")])

    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD)

    assert _rows(ws)[0].kind == "comment"


def test_a_plugin_that_fails_or_a_connection_switched_off_keeps_nothing_and_never_raises(ws):
    def broken(payload, ctx):
        raise ValueError("unexpected payload")

    ws.nets["instagram"].inbox_items_from_webhook = broken
    assert social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD) == 0

    _parser(ws, [_dm()])
    row = _ig(ws)
    row.enabled = False
    ws.session.commit()
    assert social_inbox.keep_webhook_items(ws.session, row.id, ws.gid, PAYLOAD) == 0
    assert _rows(ws) == []


def _hook(ws, *, installed_by=None):
    token = f"tok-{uuid.uuid4().hex}"
    ws.session.add(
        WorkspaceIncomingWebhookModel(
            session=ws.session, group_id=ws.gid, name="Inbox", slug=f"inbox-{token[-6:]}", enabled=True, token=token,
            source_integration_id=installed_by,
        )
    )  # fmt: skip
    ws.session.commit()
    return token


def test_a_delivery_to_an_integrations_own_webhook_lands_in_the_inbox(ws, client):
    _parser(ws, [_dm()])

    response = client.post(f"/api/hooks/{_hook(ws, installed_by=_ig(ws).id)}", json=PAYLOAD)

    assert response.status_code == 202
    assert [r.kind for r in _rows(ws)] == ["message"]


def test_a_webhook_no_integration_installed_never_reaches_the_inbox(ws, client):
    _parser(ws, [_dm()])

    client.post(f"/api/hooks/{_hook(ws)}", json=PAYLOAD)

    assert _rows(ws) == []


def test_a_direct_message_offers_only_a_message_back_and_records_it_as_the_reply(ws):
    _parser(ws, [_dm()])
    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD)
    (dm,) = _rows(ws)

    assert actions.offers(dm, ws.nets["instagram"]) == {"actions": ["message"], "reply_modes": []}

    actions.message(ws.session, ws.gid, dm, text="Thanks — glad you like it", user_id=ws.uid)

    ws.session.expire_all()
    dm = ws.session.get(Item, dm.id)
    assert (dm.status, dm.reply_mode, dm.reply_text, dm.reply_id) == ("replied", "message", "Thanks — glad you like it", "m1")
    assert ws.nets["instagram"].sent("message")[-1]["to"] == {"id": "u-alice"}


def test_a_comment_still_offers_its_usual_actions(ws):
    _parser(ws, [{**se.item("c9", network="instagram"), "created_at": datetime.now(UTC).isoformat()}])
    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD)

    assert "reply" in actions.offers(_rows(ws)[0], ws.nets["instagram"])["actions"]


# ── a workflow's Run integration step: `social.inbox_items` (a webhook the integration didn't create) ─────────────


def _offers_inbox_items(ws, items):
    """The fake Instagram gains a `social.inbox_items` action answering `items` (and remembering its arguments)."""
    from marvin_integration_sdk import ProviderAction

    net = ws.nets["instagram"]
    net.actions = (*net.actions, ProviderAction(key="inbox_items", label="Inbox items", capability="social.inbox_items"))
    calls, real = [], net.run_action

    def run_action(key, args, ctx):
        if key != "inbox_items":
            return real(key, args, ctx)
        calls.append(dict(args))
        return {"items": items}

    net.run_action = run_action
    return calls


def _step(ws, **extra):
    from marvin.services.automation.actions import run_action

    step = {"kind": "integration", "integration": "ig", "capability": "social.inbox_items", "args": {"payload": "${event.payload}"}, **extra}
    return run_action(ws.session, ws.gid, step, {"event": {"payload": PAYLOAD}})


def test_a_step_hands_the_integration_the_delivery_and_keeps_what_it_returns(ws):
    calls = _offers_inbox_items(ws, [_dm(), _dm("mid-2")])

    out = _step(ws)

    assert calls == [{"payload": PAYLOAD}]
    assert (out["count"], out["kept"]) == (2, 2) and [r.item_id for r in _rows(ws)] == ["mid-1", "mid-2"]
    assert _step(ws)["kept"] == 0  # the same delivery again keeps nothing new


def test_the_step_must_name_its_integration(ws):
    import pytest

    from marvin.services.automation.actions import AutomationActionError

    _offers_inbox_items(ws, [_dm()])
    with pytest.raises(AutomationActionError, match="name its `integration`"):
        _step(ws, integration=None)


def test_the_editor_warns_when_the_webhook_feeding_it_isnt_signed(ws):
    from marvin.services.automation.authoring import inbox_items_warnings

    token = _hook(ws)
    slug = ws.session.query(WorkspaceIncomingWebhookModel).filter_by(token=token).one().slug
    definition = {
        "trigger": {"type": "incoming_webhook", "webhook": slug},
        "actions": [{"kind": "integration", "integration": "ig", "capability": "social.inbox_items", "args": {"payload": "${event.payload}"}}],
    }

    (warning,) = inbox_items_warnings(ws.session, ws.gid, definition)
    assert "isn't signed" in warning["message"] and warning["path"] == "actions[0].capability"

    hook = ws.session.query(WorkspaceIncomingWebhookModel).filter_by(token=token).one()
    hook.signing_secret_ref = "INBOX_KEY"
    ws.session.commit()
    assert inbox_items_warnings(ws.session, ws.gid, definition) == []


# ── direct messages a poll reads (Mastodon, Bluesky): asked for only where the plugin declares them ───────────────


def _declares_messages(ws, network="mastodon"):
    """The fake network's `social.comments` declares the kinds it reads, `message` among them."""
    from marvin_integration_sdk import ProviderAction

    net = ws.nets[network]
    kinds = {"kinds": {"type": "array", "items": {"type": "string", "enum": ["comment", "reply", "mention", "message"]}}}
    comments = ProviderAction(key="comments", label="Comments", capability="social.comments", input_schema={"type": "object", "properties": kinds})
    net.actions = (comments, *(a for a in net.actions if a.key != "comments"))
    return net


def test_a_poll_asks_only_for_the_direct_kinds_a_plugin_declares():
    from marvin.services.integrations.social_engagement import poll_kinds

    assert poll_kinds(se.make_network("plain")) == ["comment", "reply", "mention"]


def test_a_poll_keeps_a_direct_message_announces_no_comment_for_it_and_no_rule_answers_it(ws):
    from marvin.services.integrations.social_engagement import Settings, run_engagement
    from tests.test_social_comment_trigger import Bus

    net = _declares_messages(ws)
    se.rule(ws, keywords="price")
    later = se.NOW + timedelta(minutes=5)
    net.feed = []
    run_engagement(ws.session, ws.gid, Settings(), now=se.NOW, event_bus=Bus())  # the first poll notes the backlog
    net.feed = [
        {**se.item("dm1", "What is the price?", kind="message", network="mastodon", age_hours=-0.05)},
        {**se.item("c1", "What is the price?", network="mastodon", age_hours=-0.05)},
    ]
    bus = Bus()

    run_engagement(ws.session, ws.gid, Settings(), now=later, event_bus=bus)

    asked = [args.get("kinds") for key, args in net.calls if key == "comments"]
    assert asked and all("message" in k for k in asked)
    assert {r.item_id: r.kind for r in _rows(ws)} == {"dm1": "message", "c1": "comment"}
    assert bus.ids == ["c1"]  # social_comment_received is for comments
    assert [a["comment_id"] for a in net.sent("reply")] == ["c1"]  # the rule answered the comment, never the message


def _dm_rule(ws, slug="r1", *, published=None, **data):
    """A published rule (its publish time a day before the engine's clock unless given): a rule answers only the direct messages
    written after it was published."""
    from marvin.db.models.platform.entries import Entries

    se.rule(ws, slug, **data)
    entry = ws.session.query(Entries).filter_by(group_id=ws.gid, slug=slug).one()
    entry.published_at = (published or se.NOW - timedelta(days=1)).replace(tzinfo=None)
    ws.session.commit()


# ── auto-reply to direct messages: only a rule that names them, answered by a message ────────────────────────────


def _run(ws, now):
    from marvin.services.integrations.social_engagement import Settings, run_engagement

    return run_engagement(ws.session, ws.gid, Settings(), now=now)


def test_a_rule_that_names_messages_answers_a_polled_dm_with_a_message(ws):
    net = _declares_messages(ws)
    _dm_rule(ws, keywords="price", kinds="comment, reply, message")
    net.feed = [se.item("dm1", "What is the price?", kind="message", network="mastodon", handle="ada")]

    _run(ws, se.NOW)

    (sent,) = net.sent("message")
    assert sent["to"] == {"id": "u-ada", "handle": "ada"} and sent["dry_run"] is False
    assert net.sent("reply") == []  # never a comment reply
    (dm,) = _rows(ws)
    assert (dm.status, dm.reply_mode, dm.reply_rehearsal, dm.reply_id) == ("replied", "message", False, "m1")

    _run(ws, se.NOW + timedelta(minutes=5))
    assert len(net.sent("message")) == 1  # answered once


def test_a_rule_answers_a_dm_a_webhook_brought(ws):
    _dm_rule(ws, keywords="price", kinds="message")
    _parser(ws, [_dm(text="Love it, what's the price?", sender="u-bea", when=se.NOW - timedelta(hours=1))])
    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD, now=se.NOW)

    _run(ws, se.NOW)

    assert [m["to"] for m in ws.nets["instagram"].sent("message")] == [{"id": "u-bea"}]
    assert _rows(ws)[0].reply_mode == "message"


def test_rehearsal_records_the_dm_answer_but_sends_nothing(ws):
    net = _declares_messages(ws)
    _dm_rule(ws, keywords="price", kinds="message")
    se.mode(ws, "rehearsal", "m-main")
    net.feed = [se.item("dm1", "price?", kind="message", network="mastodon")]

    _run(ws, se.NOW)

    assert net.sent("message") == [] and [a["dry_run"] for k, a in net.calls if k == "message"] == [True]
    assert _rows(ws)[0].reply_rehearsal is True


def test_the_engine_cannot_message_without_a_rule_that_answers_dms(ws):
    import pytest

    from marvin.services.integrations.social_engagement import EngineCallError, _Network
    from marvin.services.integrations.social_rules import rule_from_data

    net = _Network(ws.session, ws.gid, _ig(ws), ws.nets["instagram"])
    comments_only = rule_from_data({"keywords": "price", "reply": "Hi"}, id="r")
    for rule in (None, comments_only):
        with pytest.raises(EngineCallError, match="messages only to answer"):
            net.call("social.message", {"to": {"id": "u"}, "text": "Hi"}, rule)


# ── the inbox's Trash: out of the inbox, restorable, never answered; nothing on the network changes ─────────────


def test_trash_moves_an_item_out_of_the_inbox_and_restore_brings_back_its_status(ws):
    _parser(ws, [_dm()])
    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD)
    (dm,) = _rows(ws)
    dm.status = "seen"
    ws.session.commit()

    actions.trash(ws.session, ws.gid, dm, trashed=True)

    inbox, _ = social_inbox.query(ws.session, ws.gid)
    trash, _ = social_inbox.query(ws.session, ws.gid, trashed=True)
    assert inbox == [] and [r.item_id for r in trash] == ["mid-1"]
    assert ws.nets["instagram"].calls == []  # Marvin only

    actions.trash(ws.session, ws.gid, dm, trashed=False)
    inbox, _ = social_inbox.query(ws.session, ws.gid)
    assert [(r.item_id, r.status) for r in inbox] == [("mid-1", "seen")]


def test_a_trashed_item_isnt_new_and_no_rule_answers_it(ws):
    se.rule(ws, keywords="price", kinds="message")
    _parser(ws, [_dm(text="price?", when=se.NOW - timedelta(hours=1))])
    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD, now=se.NOW)
    (dm,) = _rows(ws)
    actions.trash(ws.session, ws.gid, dm, trashed=True)

    _run(ws, se.NOW)

    assert ws.nets["instagram"].sent("message") == []
    assert social_inbox.new_count(ws.session, ws.gid) == 0


def test_a_poll_never_brings_a_trashed_comment_back(ws):
    net = ws.nets["mastodon"]
    net.feed = [se.item("c1", "hello", network="mastodon")]
    _run(ws, se.NOW)
    (c1,) = [r for r in _rows(ws) if r.item_id == "c1"]
    actions.trash(ws.session, ws.gid, c1, trashed=True)

    _run(ws, se.NOW + timedelta(minutes=5))

    inbox, _ = social_inbox.query(ws.session, ws.gid)
    assert "c1" not in [r.item_id for r in inbox]


# ── the cut-off and the cool-down ─────────────────────────────────────────────────────────────────────────────────


def _webhook_dms(ws, *dms):
    _parser(ws, list(dms))
    social_inbox.keep_webhook_items(ws.session, _ig(ws).id, ws.gid, PAYLOAD, now=se.NOW)


def test_a_new_rule_never_answers_a_dm_written_before_it_was_published(ws):
    _dm_rule(ws, keywords="price", kinds="message", published=se.NOW - timedelta(minutes=30))
    _webhook_dms(
        ws, _dm("old", text="price?", when=se.NOW - timedelta(hours=2)), _dm("new", text="price?", sender="u-bea", when=se.NOW - timedelta(minutes=5))
    )

    _run(ws, se.NOW)

    assert [m["to"] for m in ws.nets["instagram"].sent("message")] == [{"id": "u-bea"}]


def test_only_a_persons_newest_dm_is_answered_and_their_earlier_ones_are_covered(ws):
    _dm_rule(ws, keywords="price", kinds="message")
    _webhook_dms(
        ws,
        _dm("m1", text="whats the price", when=se.NOW - timedelta(minutes=9)),
        _dm("m2", text="Whats the price", when=se.NOW - timedelta(minutes=2)),
    )

    _run(ws, se.NOW)

    assert len(ws.nets["instagram"].sent("message")) == 1
    rows = {r.item_id: r for r in _rows(ws)}
    assert rows["m2"].reply_note is None and rows["m2"].status == "replied"
    assert rows["m1"].status == "replied" and "newer message" in rows["m1"].reply_note
    _run(ws, se.NOW + timedelta(minutes=5))
    assert len(ws.nets["instagram"].sent("message")) == 1  # nothing left for a rule to answer


def test_the_cool_down_holds_a_persons_next_dm_and_zero_turns_it_off(ws):
    _dm_rule(ws, keywords="price", kinds="message", cooldown_hours=24)
    _webhook_dms(ws, _dm("m1", text="price?", when=se.NOW - timedelta(minutes=30)))
    _run(ws, se.NOW)
    _webhook_dms(ws, _dm("m2", text="and the price in blue?", when=se.NOW + timedelta(minutes=10)))

    _run(ws, se.NOW + timedelta(minutes=15))
    assert len(ws.nets["instagram"].sent("message")) == 1  # held: answered 15 minutes ago

    from marvin.db.models.platform.entries import Entries

    entry = ws.session.query(Entries).filter_by(group_id=ws.gid, slug="r1").one()
    entry.data_json = {**entry.data_json, "cooldown_hours": 0}
    ws.session.commit()
    _run(ws, se.NOW + timedelta(minutes=20))
    assert len(ws.nets["instagram"].sent("message")) == 2


def _held(ws, item_id):
    ws.session.expire_all()
    return next(r for r in _rows(ws) if r.item_id == item_id).held


def test_a_dm_the_cool_down_holds_says_so_until_when_once_and_a_reply_clears_it(ws):
    _dm_rule(ws, keywords="price", kinds="message", cooldown_hours=24)
    _webhook_dms(ws, _dm("m1", text="price?", when=se.NOW - timedelta(minutes=30)))
    _run(ws, se.NOW)
    answered_at = next(r for r in _rows(ws) if r.item_id == "m1").replied_at
    _webhook_dms(ws, _dm("m2", text="and the price in blue?", when=se.NOW + timedelta(minutes=10)))

    _run(ws, se.NOW + timedelta(minutes=15))
    held = _held(ws, "m2")
    assert (held["reason"], held["rule"], held["note"]) == ("cooldown", "r1", None)
    assert datetime.fromisoformat(held["until"]) == answered_at + timedelta(hours=24)
    _run(ws, se.NOW + timedelta(minutes=20))
    assert _held(ws, "m2")["at"] == held["at"]  # every run re-checks it; it is written once

    from marvin.db.models.platform.entries import Entries

    entry = ws.session.query(Entries).filter_by(group_id=ws.gid, slug="r1").one()
    entry.data_json = {**entry.data_json, "cooldown_hours": 0}
    ws.session.commit()
    _run(ws, se.NOW + timedelta(minutes=25))
    assert _held(ws, "m2") is None and _held(ws, "m1") is None  # answered now: nothing held it back


def test_a_persons_own_reply_from_the_inbox_starts_the_cool_down_too(ws):
    """The case that hid it: a person answered the DM by hand, then the sender wrote again — a rule's match was held, silently."""
    _dm_rule(ws, keywords="price", kinds="message", cooldown_hours=24)
    _webhook_dms(ws, _dm("m1", text="hello", when=se.NOW - timedelta(minutes=8)))
    (first,) = _rows(ws)
    social_inbox.record_reply(
        ws.session, _ig(ws), first, mode="message", rehearsal=False, reply_id="x", text="Test", when=se.NOW - timedelta(minutes=7)
    )
    _webhook_dms(ws, _dm("m2", text="Whats the price", when=se.NOW - timedelta(minutes=3)))

    _run(ws, se.NOW)

    assert ws.nets["instagram"].sent("message") == []
    assert _held(ws, "m2")["reason"] == "cooldown"


def test_a_dm_the_network_refuses_says_so_with_the_networks_words(ws):
    _dm_rule(ws, keywords="price", kinds="message")
    ws.nets["instagram"].refuse[("message", "u-alice")] = "unsupported"
    _webhook_dms(ws, _dm("m1", text="price?", when=se.NOW - timedelta(minutes=5)))

    report = _run(ws, se.NOW)

    held = _held(ws, "m1")
    assert held["reason"] == "refused" and "refused: unsupported" in held["note"] and held["until"] is None
    assert report.skipped["unsupported"] == 1


def test_an_unmatched_dm_is_not_held(ws):
    _dm_rule(ws, keywords="price", kinds="message")
    _webhook_dms(ws, _dm("m1", text="hello there", when=se.NOW - timedelta(minutes=5)))
    _run(ws, se.NOW)
    assert _held(ws, "m1") is None  # no rule matched: there is nothing to explain


def test_an_existing_rule_type_gains_the_cool_down_field(ws):
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.integrations.social_setup import ensure_rule_type

    rule_type = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").one()
    rule_type.schema_json = {"fields": [f for f in rule_type.schema_json["fields"] if f["key"] != "cooldown_hours"]}
    ws.session.commit()

    ensure_rule_type(ws.session, ws.gid)

    ws.session.refresh(rule_type)
    keys = [f["key"] for f in rule_type.schema_json["fields"]]
    assert keys[-1] == "cooldown_hours" and keys.count("cooldown_hours") == 1
