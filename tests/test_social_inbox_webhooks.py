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
from tests.test_social_engagement import nets, ws  # noqa: F401 — fixtures

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
