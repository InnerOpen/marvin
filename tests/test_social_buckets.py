"""Comment buckets, phase 1 (tasks/social-comment-buckets-plan.md): an inbox item is sorted when first stored — a rule's keyword,
else obvious support — a person can sort or clear it, the inbox filters and counts by bucket, and the new-comment event says it."""

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

# ruff: noqa: E402, F811 — fixtures are imported from the engine's and the inbox's tests
from marvin.services.integrations import social_inbox
from marvin.services.integrations.social_buckets import BUCKETS, heuristic_bucket
from tests import test_social_comment_trigger as trig
from tests import test_social_engagement as se
from tests import test_social_inbox as inbox
from tests.test_social_engagement import _types, nets, ws  # noqa: F401
from tests.test_social_inbox import api  # noqa: F401

ADMIN, EDITOR, VIEWER = inbox.ADMIN, inbox.EDITOR, inbox.VIEWER
item, API = se.item, inbox.API


# ── what costs nothing to sort ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["🔥🔥🔥", "@ada @bea", "❤️ @mashburn", "Love it!", "thank you so much", "great", "yes!!!", "🔥!"])
def test_emoji_tags_and_a_few_words_of_praise_are_support(text):
    assert heuristic_bucket(text) == "support"


@pytest.mark.parametrize(
    "text", ["", "...", "?", "How much?", "price?", "Love this, what size is it?", "Great post but I disagree", "nice work on the lid"]
)
def test_anything_with_more_to_it_stays_unsorted(text):
    assert heuristic_bucket(text) is None


def test_the_six_buckets_are_fixed_and_in_working_order():
    assert BUCKETS == ("keyword", "lead", "question", "feedback", "support", "noise")


# ── sorted when first stored ─────────────────────────────────────────────────────────────────────────────────────


def test_a_polled_item_is_sorted_by_a_rules_keyword_else_as_support_else_left_unsorted(ws):
    se.rule(ws, keywords="price")
    inbox.poll(ws, [item("c1", "What is the price?"), item("c2", "🔥🔥", handle="bob"), item("c3", "Where is this?", handle="cy")])

    rows = inbox.by_id(ws)
    assert (rows["c1"].bucket, rows["c1"].bucket_source) == ("keyword", "rule")
    assert (rows["c2"].bucket, rows["c2"].bucket_source) == ("support", "heuristic") and rows["c2"].bucket_at is not None
    assert (rows["c3"].bucket, rows["c3"].bucket_source, rows["c3"].bucket_at) == (None, None, None)


def test_a_keyword_sorts_an_item_even_on_a_network_whose_auto_reply_is_off(ws):
    se.rule(ws, keywords="price")
    inbox.poll(ws, [item("c1", "price please")], settings=inbox.ANNOUNCE_ONLY)
    assert inbox.by_id(ws)["c1"].bucket == "keyword"


def test_a_draft_rule_sorts_nothing(ws):
    se.rule(ws, keywords="price", status="draft")
    inbox.poll(ws, [item("c1", "price please")])
    assert inbox.by_id(ws)["c1"].bucket is None


def test_an_item_a_webhook_pushed_is_sorted_by_the_rules_too(ws):
    from tests import test_social_inbox_webhooks as hooks

    hooks._dm_rule(ws, keywords="price", networks="instagram", kinds="message")  # names DMs; published before they were sent
    hooks._parser(ws, [hooks._dm("m1", text="whats the price"), hooks._dm("m2", text="❤️", sender="u-bea")])
    social_inbox.keep_webhook_items(ws.session, hooks._ig(ws).id, ws.gid, hooks.PAYLOAD, now=se.NOW)

    by_item = {r.item_id: r for r in hooks._rows(ws)}
    assert (by_item["m1"].bucket, by_item["m2"].bucket) == ("keyword", "support")


def test_the_new_comment_event_carries_the_bucket(ws):
    se.rule(ws, keywords="price")
    net, bus = ws.nets["mastodon"], trig.Bus()
    trig.first_poll(ws, bus)
    net.feed = [trig.fresh("n1", "What is the price?"), trig.fresh("n2", "Where do you ship?", handle="bob")]

    trig.poll(ws, bus)

    assert {s["document_data"].id: s["document_data"].bucket for s in bus.sent} == {"n1": "keyword", "n2": None}
    assert trig.ctx_of(bus.sent[0])["bucket"] == "keyword"


# ── a person sorts; the inbox filters and counts ─────────────────────────────────────────────────────────────────


def test_a_person_sorts_an_item_or_clears_it_and_their_choice_is_theirs(ws, api):
    inbox.seed(ws, [item("c1", "Do you ship to Canada?")])
    res = inbox.post(api(EDITOR), ws, "c1", "bucket", {"bucket": "lead"})
    assert res.status_code == 200, res.text
    assert (res.json()["item"]["bucket"], res.json()["item"]["bucketSource"]) == ("lead", "person")

    cleared = inbox.post(api(EDITOR), ws, "c1", "bucket", {"bucket": None}).json()["item"]
    assert (cleared["bucket"], cleared["bucketSource"]) == (None, "person")  # cleared by a person stays theirs


def test_sorting_needs_an_editor_and_a_known_bucket(ws, api):
    inbox.seed(ws, [item("c1", "hello")])
    assert inbox.post(api(VIEWER), ws, "c1", "bucket", {"bucket": "lead"}).status_code == 403
    assert inbox.post(api(EDITOR), ws, "c1", "bucket", {"bucket": "vip"}).status_code == 422


def test_a_repoll_never_changes_a_bucket_a_person_chose(ws, api):
    se.rule(ws, keywords="price")
    inbox.poll(ws, [item("c1", "What is the price?")])
    inbox.post(api(EDITOR), ws, "c1", "bucket", {"bucket": "lead"})

    inbox.poll(ws, [item("c1", "What is the price?")], now=se.NOW + se.timedelta(minutes=5))

    assert (inbox.by_id(ws)["c1"].bucket, inbox.by_id(ws)["c1"].bucket_source) == ("lead", "person")


def test_the_inbox_filters_by_bucket_or_unsorted_and_counts_every_bucket(ws, api):
    se.rule(ws, keywords="price")
    inbox.poll(ws, [item("c1", "price?"), item("c2", "🔥", handle="bob"), item("c3", "🙌", handle="cy"), item("c4", "Where?", handle="di")])

    body = inbox.listed(api(EDITOR), bucket="support")
    assert sorted(i["text"] for i in body["items"]) == ["🔥", "🙌"]
    assert [i["text"] for i in inbox.listed(api(EDITOR), bucket="unsorted")["items"]] == ["Where?"]
    assert body["buckets"] == {"keyword": 1, "support": 2, "unsorted": 1}  # whatever the bucket filter
    assert api(EDITOR).get(API, params={"bucket": "vip"}).status_code == 422
