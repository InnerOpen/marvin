"""The social engagement engine: read comments on every connected network, answer them under published rules.

Fake networks (tests/social_engagement_support.py) shaped like the plugins: `social.comments` with an opaque cursor,
`social.reply` with private / public modes and a dry run, `social.like`. The engine is run directly
(`run_engagement`) with a fixed `now`.
"""

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")


import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationError, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.groups import Groups  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item  # noqa: E402
from marvin.db.models.platform.entries import Entries  # noqa: E402
from marvin.db.models.platform.entry_types import EntryTypes  # noqa: E402
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel  # noqa: E402
from marvin.db.models.users.users import Users  # noqa: E402
from marvin.services.entries.entry_service import EntryService  # noqa: E402
from marvin.services.integrations import social_engagement as engine  # noqa: E402
from marvin.services.integrations import social_setup  # noqa: E402
from marvin.services.integrations.social_engagement import EngineCallError, Settings, run_engagement  # noqa: E402
from marvin.services.integrations.social_rules import SocialRule  # noqa: E402

LIVE = Settings()

# ── fakes ────────────────────────────────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def item(cid, text="What is the price?", *, kind="comment", post="p1", handle="alice", author_id=None, age_hours=1, network="x"):
    return {
        "id": cid, "kind": kind, "post_id": post, "post_url": f"https://{network}.example/p/{post}",
        "author": {"id": author_id or f"u-{handle}", "handle": handle, "name": handle.title()}, "text": text,
        "created_at": (NOW - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z"), "url": f"https://{network}.example/c/{cid}",
        "network": network,
    }  # fmt: skip


def make_network(slug, *, with_like=True, gated=True):
    """A fake network. `feed` is what social.comments reads (the cursor is how many items were read); `refuse` maps
    (comment_id, private) to an IntegrationError code; `fail_comments` makes the read raise."""
    actions = [
        ProviderAction(key="comments", label="Comments", capability="social.comments"),
        ProviderAction(key="reply", label="Reply", capability="social.reply", requires_approval=gated),
        ProviderAction(key="hide", label="Hide", capability="social.hide"),
        ProviderAction(key="delete", label="Delete", capability="social.delete_comment", requires_approval=gated),
        ProviderAction(key="repost", label="Repost", capability="social.repost", requires_approval=gated),
        ProviderAction(key="message", label="Message", capability="social.message", requires_approval=gated),
        ProviderAction(key="refund", label="Not social"),
    ]
    if with_like:
        actions.append(ProviderAction(key="like", label="Like", capability="social.like"))

    class _Net(IntegrationProvider):
        name = f"Fake {slug}"

        def __init__(self):
            self.feed: list[dict] = []
            self.calls: list[tuple[str, dict]] = []
            self.done: list[tuple[str, dict]] = []
            self.refuse: dict = {}
            self.fail_comments: str | None = None
            self.bad_cursor = False

        def sent(self, key="reply"):
            """What the network delivered: the non-dry-run calls that were not refused."""
            return [a for k, a in self.done if k == key]

        def run_action(self, key, args, ctx):
            self.calls.append((key, dict(args)))
            out = self._act(key, args)
            if key != "comments" and not args.get("dry_run"):
                self.done.append((key, dict(args)))
            return out

        def _act(self, key, args):
            if key == "comments":
                if self.fail_comments:
                    raise IntegrationError(self.fail_comments, code="unknown")
                if args.get("since") and self.bad_cursor:
                    raise IntegrationError("cursor rejected", code="invalid_cursor")
                start = int(args["since"]) if args.get("since") else 0
                kinds = args.get("kinds") or ["comment", "reply", "mention"]
                return {"items": [i for i in self.feed[start:] if i["kind"] in kinds][: args.get("limit", 50)], "cursor": str(len(self.feed))}
            if key == "reply":
                code = self.refuse.get((args["comment_id"], args.get("private", True)))
                if code:
                    raise IntegrationError(f"{slug} refused: {code}", code=code)
                if args["dry_run"]:
                    return {"replied": False, "network": slug, "would_reply": {"text": args["text"], "private": args["private"]}}
                return {"replied": True, "reply_id": f"r-{args['comment_id']}-{'p' if args['private'] else 'pub'}", "private": args["private"],
                        "url": None if args["private"] else f"https://{slug}.example/r", "network": slug}  # fmt: skip
            if key == "like":
                return {"liked": True, "network": slug}
            if key == "hide":
                return {"hidden": args.get("hidden", True), "network": slug}
            if key == "delete":
                return {"deleted": True, "network": slug}
            if key == "repost":
                return {"reposted": True, "url": f"https://{slug}.example/b", "network": slug}
            if key == "message":
                if args["dry_run"]:
                    return {"sent": False, "network": slug}
                return {"sent": True, "message_id": "m1", "network": slug}
            raise AssertionError(key)

    _Net.slug = slug
    _Net.actions = tuple(actions)
    return _Net()


@pytest.fixture
def nets(monkeypatch):
    found = {"mastodon": make_network("mastodon"), "bluesky": make_network("bluesky", with_like=False), "instagram": make_network("instagram")}
    for slug, provider in found.items():
        monkeypatch.setitem(INTEGRATION_REGISTRY, slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    return found


@pytest.fixture
def ws(db_session, nets):
    """A workspace with a mastodon, a bluesky and an instagram connection, and a user."""
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"engage-{marker}", slug=f"engage-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=f"u-{marker}", email=f"u-{marker}@t.test", full_name="U", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip
    for slug, provider in (("m-main", "mastodon"), ("b-main", "bluesky"), ("ig", "instagram")):
        # every network is switched on: the tests that rehearse or switch one off say so (`mode`)
        db_session.add(
            IntegrationModel(
                session=db_session, group_id=gid, provider=provider, name=slug, slug=slug, enabled=True, config={},
                state={"social": {"auto_reply": "on"}},
            )
        )  # fmt: skip
    db_session.commit()
    yield type("WS", (), {"gid": gid, "session": db_session, "uid": uid, "nets": nets})
    db_session.rollback()
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.execute(Users.__table__.delete().where(Users.id == uid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@pytest.fixture(autouse=True)
def _types(ws):
    """The workspace has the rule type (Marvin makes it on first need)."""
    social_setup.ensure_rule_type(ws.session, ws.gid)


def _entry(ws, type_slug, slug, data, *, status="published"):
    type_id = ws.session.query(EntryTypes.id).filter_by(group_id=ws.gid, slug=type_slug).scalar()
    EntryService(ws.session, ws.gid, integration_id="test").create(
        {"entry_type_id": type_id, "title": slug, "slug": slug, "status": status, "data_json": data}
    )
    ws.session.commit()


def rule(ws, slug="r1", *, status="published", **data):
    data = {"keywords": "price", "reply": "Check the link in bio.", **data}
    _entry(ws, "social-auto-reply", slug, data, status=status)


def run(ws, settings=LIVE, **kw):
    return run_engagement(ws.session, ws.gid, settings, now=kw.pop("now", NOW))


def logs(ws, *, rehearsal=None):
    """The replies recorded on inbox items, as plain dicts (the item is the reply log)."""
    ws.session.expire_all()
    rows = [
        {
            "comment_id": i.item_id, "integration": i.integration_slug, "rule": i.reply_rule, "mode": i.reply_mode,
            "rehearsal": i.reply_rehearsal, "reply_id": i.reply_id, "reply": i.reply_text, "note": i.reply_note, "by": i.replied_by,
        }
        for i in ws.session.query(Item).filter(Item.group_id == ws.gid, Item.replied_at.isnot(None)).order_by(Item.replied_at, Item.item_id)
    ]  # fmt: skip
    return [r for r in rows if rehearsal is None or r["rehearsal"] is rehearsal]


def mode(ws, value, *slugs):
    """Set the auto-reply mode of these integrations (every one when none is named)."""
    for slug in slugs or ("m-main", "b-main", "ig"):
        social_setup.set_mode(ws.session, ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).one(), value)


def forget_cursor(ws, slug):
    """Drop an integration's read cursors (its auto-reply mode stays)."""
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).one()
    row.state = {"social": {"auto_reply": social_setup.get_mode(row)}}
    ws.session.commit()


def state(ws, slug):
    ws.session.expire_all()
    return ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).one().state


# ── the blueprints core ships ────────────────────────────────────────────────────────────────────────────────────


def test_the_rule_type_is_internal_and_made_by_marvin_not_applied_from_a_blueprint(ws):
    social_setup.ensure_rule_type(ws.session, ws.gid)  # idempotent
    types = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").all()
    assert len(types) == 1
    rule_fields = {f["key"]: f for f in types[0].schema_json["fields"]}
    assert {"keywords", "reply", "networks", "post", "reply_as", "also_like", "kinds"} <= set(rule_fields)
    assert rule_fields["reply_as"]["options"] == ["private", "public", "both"]
    assert types[0].capabilities_json == {"publishable": False, "submittable": False, "routable": False, "listed": False}
    assert ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-reply-log").first() is None  # no log type any more


def test_the_task_settings_have_no_rehearsal_and_the_window_is_clamped():
    assert Settings.from_config({"rehearsal": False, "max_replies": "5"}).max_replies == 5
    assert not hasattr(Settings(), "rehearsal")
    assert Settings.from_config({"max_age_days": 400}).max_age_days == 90 and Settings.from_config({}).max_age_days == 7


# ── matching ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_keywords_match_whole_words_in_any_case_and_multi_word_phrases(ws):
    rule(ws, keywords="Price, how much")
    ws.nets["mastodon"].feed = [
        item("c1", "What's the PRICE?"), item("c2", "priceless!"), item("c3", "so... how   much"), item("c4", "HOW MUCH is it"), item("c5", "nothing")
    ]  # fmt: skip
    report = run(ws)
    assert sorted(a["comment_id"] for a in ws.nets["mastodon"].sent()) == ["c1", "c4"]  # c3 has two spaces: not the phrase
    assert report.skipped["no_match"] == 3 and report.matched == 2


def test_a_draft_rule_never_fires_and_without_rules_no_reply_cursor_moves(ws):
    rule(ws, status="draft")
    ws.nets["mastodon"].feed = [item("c1")]
    run(ws)
    assert ws.nets["mastodon"].sent() == [] and logs(ws) == []
    assert "cursor" not in state(ws, "m-main")["social"] and "rehearsal_cursor" not in state(ws, "m-main")["social"]  # a later rule still sees c1
    rule(ws, "later")
    run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]


def test_a_rule_for_the_comments_post_beats_the_catch_all_and_the_oldest_rule_wins_otherwise(ws):
    rule(ws, "any", reply="generic")
    rule(ws, "second", reply="second generic")
    rule(ws, "one-post", reply="specific", post="p9")
    ws.nets["mastodon"].feed = [item("c1", post="p9"), item("c2", post="p1")]
    run(ws)
    replies = {a["comment_id"]: a["text"] for a in ws.nets["mastodon"].sent()}
    assert replies == {"c1": "specific", "c2": "generic"}
    assert {r["comment_id"]: r["rule"] for r in logs(ws)} == {"c1": "one-post", "c2": "any"}


def test_a_rule_for_this_network_beats_a_rule_for_every_network_whatever_their_age(ws):
    rule(ws, "all-networks", reply="for everyone")  # oldest, no networks
    rule(ws, "mastodon-only", reply="for mastodon", networks="m-main")
    rule(ws, "mastodon-by-name", reply="by name", networks="mastodon")
    ws.nets["mastodon"].feed = [item("c1")]
    ws.nets["bluesky"].feed = [item("c1", network="bluesky")]
    run(ws)
    assert [a["text"] for a in ws.nets["mastodon"].sent()] == ["for mastodon"]  # the oldest network-specific rule
    assert [a["text"] for a in ws.nets["bluesky"].sent()] == ["for everyone"]  # a rule for another network doesn't apply


def test_the_full_precedence_post_then_network_then_all_networks_then_oldest():
    from marvin.services.integrations.social_rules import match_item, rule_from_data

    def make(rid, order, **data):
        return rule_from_data({"keywords": "price", "reply": rid, **data}, id=rid, order=order)

    rules = [
        make("all-1", 0),
        make("all-2", 1),
        make("net-1", 2, networks="m-main"),
        make("post-all", 3, post="p9"),
        make("post-net", 4, post="p9", networks="m-main"),
    ]
    names = {"m-main", "mastodon", "x"}
    hit = lambda item_: match_item(item_, rules, names)[0].id  # noqa: E731
    assert hit({"text": "price", "post_id": "p9"}) == "post-net"  # the post, and the network's
    assert hit({"text": "price", "post_id": "p1"}) == "net-1"  # not that post: the network's rule over every network's
    assert hit({"text": "price", "post_id": "p9"}) == "post-net"
    assert match_item({"text": "price", "post_id": "p1"}, rules[:2] + rules[3:4], names)[0].id == "all-1"  # all-networks: the oldest
    assert match_item({"text": "price", "post_id": "p9"}, [rules[0], rules[3]], names)[0].id == "post-all"  # a post beats every-network


def test_a_rule_names_a_post_by_id_or_url(ws):
    rule(ws, "by-url", post="https://x.example/p/p7/")
    ws.nets["mastodon"].feed = [item("c1", post="p7", network="x"), item("c2", post="p8", network="x")]
    run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]


def test_networks_empty_is_any_else_integration_slugs_or_network_names(ws):
    rule(ws, "only-b", networks="b-main", reply="to bluesky")
    rule(ws, "only-mastodon", networks="Mastodon", reply="to mastodon")
    for provider in ("mastodon", "bluesky"):
        ws.nets[provider].feed = [item("c1")]
    ws.nets["instagram"].feed = [item("c1")]
    run(ws)
    assert [a["text"] for a in ws.nets["bluesky"].sent()] == ["to bluesky"]
    assert [a["text"] for a in ws.nets["mastodon"].sent()] == ["to mastodon"]
    assert ws.nets["instagram"].sent() == []


def test_mentions_are_answered_only_by_a_rule_that_asks_for_them(ws):
    rule(ws, "default", reply="default")
    rule(ws, "with-mentions", kinds="comment, mention", keywords="deal", reply="mentioned")
    ws.nets["mastodon"].feed = [
        item("c1", kind="reply"),
        item("c2", kind="mention"),
        item("c3", "a deal?", kind="mention"),
        item("c4", "a deal?", kind="comment"),
    ]
    run(ws)
    replies = {a["comment_id"]: a["text"] for a in ws.nets["mastodon"].sent()}
    assert replies == {"c1": "default", "c3": "mentioned", "c4": "mentioned"}  # c2 is a mention the default rule doesn't take
    kinds = ws.nets["mastodon"].calls[0][1]["kinds"]
    assert set(kinds) == {"comment", "reply", "mention"}


# ── modes and likes ──────────────────────────────────────────────────────────────────────────────────────────────


def test_private_is_the_default_public_and_both_follow_the_rule(ws):
    rule(ws, "priv", keywords="a1")
    rule(ws, "pub", keywords="a2", reply_as="public")
    rule(ws, "both", keywords="a3", reply_as="both")
    ws.nets["mastodon"].feed = [item("c1", "a1"), item("c2", "a2"), item("c3", "a3")]
    run(ws)
    sent = [(a["comment_id"], a["private"]) for a in ws.nets["mastodon"].sent()]
    assert sent == [("c1", True), ("c2", False), ("c3", True), ("c3", False)]
    by_comment = {r["comment_id"]: r for r in logs(ws)}
    assert {k: v["mode"] for k, v in by_comment.items()} == {"c1": "private", "c2": "public", "c3": "both"}
    assert by_comment["c3"]["reply_id"] == "r-c3-p"  # the private half's id is the one recorded
    assert all(v["rehearsal"] is False for v in by_comment.values())
    assert by_comment["c1"]["integration"] == "m-main"


def test_also_like_likes_after_the_reply_when_the_network_can(ws):
    rule(ws, also_like=True)
    for provider in ("mastodon", "bluesky"):  # bluesky's fake has no like
        ws.nets[provider].feed = [item("c1")]
    report = run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent("like")] == ["c1"]
    assert ws.nets["bluesky"].sent("like") == [] and len(ws.nets["bluesky"].sent()) == 1
    assert report.liked == 1
    assert {slug: len(ws.nets[name].sent("like")) for slug, name in (("m-main", "mastodon"), ("b-main", "bluesky"))} == {"m-main": 1, "b-main": 0}
    assert {r["integration"] for r in logs(ws)} == {"m-main", "b-main"}


def test_no_like_without_also_like_and_none_when_the_reply_failed(ws):
    rule(ws, "plain")
    ws.nets["mastodon"].feed = [item("c1")]
    run(ws)
    assert ws.nets["mastodon"].sent("like") == []
    ws.nets["bluesky"].feed = [item("c9")]
    ws.nets["bluesky"].refuse[("c9", True)] = "rate_limited"
    ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").update({"enabled": False})
    _entry(ws, "social-auto-reply", "liker", {"keywords": "price", "reply": "x", "also_like": True})
    run(ws)
    assert ws.nets["bluesky"].sent("like") == []


# ── dedupe, cursor, window, own account ─────────────────────────────────────────────────────────────────────────


def test_a_comment_is_answered_once_the_item_is_the_dedupe(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item("c1")]
    run(ws)
    forget_cursor(ws, "m-main")
    report = run(ws)
    assert len(ws.nets["mastodon"].sent()) == 1 and report.skipped["already_replied"] == 1 and len(logs(ws)) == 1


def test_old_instagram_and_reply_log_entries_are_not_read_dedupe_is_the_inbox_items_only(ws):
    """Jared's decision (2026-10-21): no legacy compatibility. Instagram's ig-auto-reply entries are not rules, and neither
    ig-reply-log nor social-reply-log entries stop an answer: only a live reply on the inbox item does."""
    for slug in ("ig-auto-reply", "ig-reply-log", "social-reply-log"):
        ws.session.add(EntryTypes(session=ws.session, group_id=ws.gid, slug=slug, name=slug, schema_json={"fields": []}))
    ws.session.commit()
    _entry(ws, "ig-auto-reply", "ig-rule-1", {"post_id": "*", "keywords": "free", "reply": "never sent"})
    _entry(ws, "ig-reply-log", "ig-reply-c1", {"comment_id": "c1", "keyword": "price"})
    _entry(ws, "social-reply-log", "social-reply-c1", {"comment_id": "c1"})
    rule(ws)
    ws.nets["instagram"].feed = [item("c1", network="instagram"), item("c3", "free?", network="instagram")]
    report = run(ws)
    sent = ws.nets["instagram"].sent()
    assert [(a["comment_id"], a["text"]) for a in sent] == [("c1", "Check the link in bio.")]  # c1 had old log entries: still answered
    assert report.skipped["already_replied"] == 0 and report.skipped["no_match"] == 1  # the ig rule never answers "free?"
    assert [r["rule"] for r in logs(ws)] == ["r1"]


def test_a_reply_to_an_item_not_stored_yet_inserts_it_first_and_the_item_is_the_log(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item("c1", age_hours=24 * 40)]  # the inbox never kept it (older than its 30 days)
    run(ws, Settings(max_age_days=60))
    [only] = ws.session.query(Item).filter_by(group_id=ws.gid).all()
    assert (only.item_id, only.status, only.reply_rehearsal, only.reply_rule, only.reply_text) == (
        "c1",
        "replied",
        False,
        "r1",
        "Check the link in bio.",
    )
    assert only.replied_at is not None and only.reply_mode == "private" and only.reply_id == "r-c1-p"
    forget_cursor(ws, "m-main")
    run(ws, Settings(max_age_days=60))
    assert len(ws.nets["mastodon"].sent()) == 1  # answered once


def test_pruning_never_lets_a_comment_be_answered_again(ws):
    """A replied item outlives the 30-day prune (the engine's window is shorter, and a network with no timestamps counts as fresh)."""
    from marvin.services.integrations import social_inbox

    rule(ws)
    no_time = item("c1")
    no_time["created_at"] = None  # counts as fresh forever
    ws.nets["mastodon"].feed = [no_time, item("c2")]
    run(ws)
    ws.session.query(Item).filter_by(group_id=ws.gid).update({"posted_at": NOW - timedelta(days=60)})  # long past retention
    ws.session.commit()
    pruned = social_inbox.prune(ws.session, NOW - timedelta(days=30), keep_replied_after=NOW - timedelta(days=180))
    assert pruned == 0 and len(logs(ws)) == 2  # both replied: kept
    forget_cursor(ws, "m-main")
    run(ws)
    assert len(ws.nets["mastodon"].sent()) == 2  # nothing answered again
    ws.session.query(Item).filter_by(group_id=ws.gid).update({"posted_at": NOW - timedelta(days=200)})
    ws.session.commit()
    assert social_inbox.prune(ws.session, NOW - timedelta(days=30), keep_replied_after=NOW - timedelta(days=180)) == 2  # eventually pruned


def test_prune_drops_unanswered_and_rehearsed_items_at_thirty_days(ws):
    from marvin.services.integrations import social_inbox

    rule(ws)
    mode(ws, "rehearsal", "m-main")
    ws.nets["mastodon"].feed = [item("c1"), item("c2", "nothing relevant")]
    run(ws)  # c1 rehearsed, c2 stored with no reply
    ws.session.query(Item).filter_by(group_id=ws.gid).update({"posted_at": NOW - timedelta(days=45)})
    ws.session.commit()
    assert social_inbox.prune(ws.session, NOW - timedelta(days=30), keep_replied_after=NOW - timedelta(days=180)) == 2


def test_an_enabled_plugin_auto_reply_task_no_longer_holds_the_engine_back(ws):
    """The old 'leave it to the plugin's own task' check is gone (Jared, 2026-10-21): the engine answers by the network's mode."""
    rule(ws)
    ws.nets["instagram"].feed = [item("c1")]
    ws.session.add(ScheduledTaskModel(
        session=ws.session, group_id=ws.gid, name="IG", slug="instagram-auto-reply", enabled=True, schedule_type="interval",
        schedule_config={"interval_seconds": 120}, task_type="run_integration_action", task_config={"integration": "ig", "action": "auto_reply"},
    ))  # fmt: skip
    ws.session.commit()
    run(ws)
    assert len(ws.nets["instagram"].sent()) == 1


def test_the_cursor_is_kept_per_integration_and_passed_back_as_since(ws):
    rule(ws)
    mastodon = ws.nets["mastodon"]
    mastodon.feed = [item("c1"), item("c2")]
    run(ws)
    assert "since" not in mastodon.calls[0][1] and state(ws, "m-main")["social"]["cursor"] == "2"
    assert state(ws, "b-main")["social"]["cursor"] == "0"
    mastodon.feed.append(item("c3"))
    run(ws)
    reads = [a for k, a in mastodon.calls if k == "comments"]
    assert reads[1]["since"] == "2" and state(ws, "m-main")["social"]["cursor"] == "3"
    assert [a["comment_id"] for a in mastodon.sent()] == ["c1", "c2", "c3"]  # c3 only once more


def test_a_cursor_the_plugin_rejects_is_dropped_and_the_read_starts_again(ws):
    rule(ws)
    mastodon = ws.nets["mastodon"]
    mastodon.feed = [item("c1")]
    run(ws)
    mastodon.bad_cursor = True
    mastodon.feed.append(item("c2"))
    report = run(ws)
    reads = [a for k, a in mastodon.calls if k == "comments"]
    assert "since" in reads[1] and "since" not in reads[2]
    assert [a["comment_id"] for a in mastodon.sent()] == ["c1", "c2"] and report.failed == 0  # c1 was not answered twice
    assert state(ws, "m-main")["social"]["cursor"] == "2"


def test_comments_older_than_seven_days_are_left_alone(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item("old", age_hours=24 * 7 + 1), item("new", age_hours=24 * 7 - 1)]
    report = run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["new"] and report.skipped["too_old"] == 1


def test_the_accounts_own_comments_are_skipped_by_handle_or_id_whatever_the_case(ws):
    rule(ws)
    ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").update({"config": {"own_username": "@Me", "page_id": "99"}})
    ws.session.commit()
    ws.nets["mastodon"].feed = [item("c1", handle="me"), item("c2", handle="", author_id="99"), item("c3", handle="alice")]
    report = run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c3"] and report.skipped["own_comment"] == 2


# ── rehearsal ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_rehearsal_asks_the_plugin_for_a_dry_run_records_it_on_the_item_and_sends_nothing(ws):
    rule(ws, also_like=True)
    mode(ws, "rehearsal")
    ws.nets["mastodon"].feed = [item("c1")]
    report = run(ws)
    [(key, args)] = [(k, a) for k, a in ws.nets["mastodon"].calls if k == "reply"]
    assert args["dry_run"] is True and ws.nets["mastodon"].sent() == [] and ws.nets["mastodon"].sent("like") == []
    [entry] = logs(ws)
    assert entry["rehearsal"] is True and entry["reply_id"] is None and entry["rule"] == "r1" and entry["mode"] == "private"
    assert report.rehearsed == 1 and report.sent == 0 and "would reply 1" in report.summary()
    ws.session.expire_all()
    assert ws.session.query(Item).filter_by(group_id=ws.gid, item_id="c1").one().status == "new"  # a dry run doesn't mark it replied
    run(ws)
    assert len(logs(ws)) == 1  # not recorded again every run


def test_switching_to_on_still_answers_what_the_rehearsal_recorded(ws):
    rule(ws)
    mode(ws, "rehearsal")
    ws.nets["mastodon"].feed = [item("c1")]
    run(ws)
    assert state(ws, "m-main")["social"]["rehearsal_cursor"] == "1" and "cursor" not in state(ws, "m-main")["social"]
    mode(ws, "on")
    run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]
    [only] = logs(ws)  # the real reply replaced the rehearsal's record
    assert only["rehearsal"] is False and only["reply_id"] == "r-c1-p"
    ws.session.expire_all()
    assert ws.session.query(Item).filter_by(group_id=ws.gid, item_id="c1").one().status == "replied"


def test_off_is_the_default_the_network_is_read_for_the_inbox_and_the_trigger_but_never_answered(ws):
    rule(ws)
    mode(ws, "off")
    ws.nets["mastodon"].feed = [item("c1")]
    report = run(ws)
    assert ws.nets["mastodon"].sent() == [] and [k for k, _ in ws.nets["mastodon"].calls if k == "reply"] == [] and logs(ws) == []
    ws.session.expire_all()
    assert ws.session.query(Item).filter_by(group_id=ws.gid, item_id="c1").one().status == "new"  # the inbox fills
    assert state(ws, "m-main")["social"]["events_cursor"] == "1"  # and the new-comment trigger's cursor moves
    assert "cursor" not in state(ws, "m-main")["social"] and report.checked == 1 and "m-main" in report.integrations
    assert social_setup.get_mode(ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()) == "off"


def test_an_integration_with_no_mode_set_is_off(ws):
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    row.state = None
    ws.session.commit()
    assert social_setup.get_mode(row) == "off"
    row.state = {"social": {"auto_reply": "banana"}}
    assert social_setup.get_mode(row) == "off"


def test_the_mode_is_per_network(ws):
    rule(ws)
    mode(ws, "on", "m-main")
    mode(ws, "rehearsal", "b-main")
    mode(ws, "off", "ig")
    for name, net in (("mastodon", "x"), ("bluesky", "x"), ("instagram", "instagram")):
        ws.nets[name].feed = [item("c1", network=net)]
    run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]
    assert ws.nets["bluesky"].sent() == [] and [a["dry_run"] for k, a in ws.nets["bluesky"].calls if k == "reply"] == [True]
    assert [k for k, _ in ws.nets["instagram"].calls if k == "reply"] == []
    assert {r["integration"]: r["rehearsal"] for r in logs(ws)} == {"m-main": False, "b-main": True}


def test_a_mode_set_while_a_run_is_in_flight_is_not_overwritten_by_the_run_saving_its_cursor(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item("c1")]
    real = ws.nets["mastodon"].run_action

    def switch_while_reading(key, args, ctx):
        if key == "comments":  # another request switches the mode mid-run
            from marvin.db.db_setup import session_context

            with session_context() as other:
                social_setup.set_mode(other, other.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one(), "off")
        return real(key, args, ctx)

    ws.nets["mastodon"].run_action = switch_while_reading
    run(ws)
    ws.session.expire_all()
    assert social_setup.get_mode(ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()) == "off"


# ── the cap, failures, refusals ─────────────────────────────────────────────────────────────────────────────────


def test_at_most_max_replies_a_run_the_rest_wait_for_the_next(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item(f"c{i}") for i in range(5)]
    first = run(ws, Settings(max_replies=2))
    assert len(ws.nets["mastodon"].sent()) == 2 and first.sent == 2
    assert len(state(ws, "m-main")["social"]["pending"]) == 3
    run(ws, Settings(max_replies=2))
    assert len(ws.nets["mastodon"].sent()) == 4
    run(ws, Settings(max_replies=2))
    assert sorted(a["comment_id"] for a in ws.nets["mastodon"].sent()) == [f"c{i}" for i in range(5)]
    assert state(ws, "m-main")["social"]["pending"] == []


def test_the_cap_is_shared_across_networks(ws):
    rule(ws)
    for provider in ("mastodon", "bluesky"):
        ws.nets[provider].feed = [item("a"), item("b")]
    run(ws, Settings(max_replies=3))
    assert len(ws.nets["bluesky"].sent()) + len(ws.nets["mastodon"].sent()) == 3


def test_one_network_failing_does_not_stop_the_others(ws):
    rule(ws)
    ws.nets["bluesky"].fail_comments = "bluesky is down"
    ws.nets["instagram"].feed = [item("c1")]
    ws.nets["mastodon"].feed = [item("c2")]
    report = run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c2"] and len(ws.nets["instagram"].sent()) == 1
    assert report.failed == 1 and "bluesky is down" in report.summary()
    assert state(ws, "b-main") == {"social": {"auto_reply": "on"}}  # its cursor didn't move


def test_a_failed_reply_is_retried_next_run_then_given_up_after_three_attempts(ws):
    rule(ws)
    mastodon = ws.nets["mastodon"]
    mastodon.feed = [item("c1")]
    mastodon.refuse[("c1", True)] = "rate_limited"
    assert run(ws).failed == 1 and logs(ws) == []
    run(ws)
    del mastodon.refuse[("c1", True)]
    run(ws)
    assert [a["comment_id"] for a in mastodon.sent()] == ["c1"] and len(logs(ws)) == 1
    mastodon.feed.append(item("c2"))
    mastodon.refuse[("c2", True)] = "rate_limited"
    for _ in range(5):
        run(ws)
    assert len([a for k, a in mastodon.calls if k == "reply" and a["comment_id"] == "c2"]) == 3
    assert state(ws, "m-main")["social"]["pending"] == []


def test_an_unsupported_or_refused_reply_skips_the_comment_with_no_retry_and_no_log(ws):
    rule(ws)
    mastodon = ws.nets["mastodon"]
    mastodon.feed = [item("c1"), item("c2")]
    mastodon.refuse[("c1", True)] = "unsupported"
    mastodon.refuse[("c2", True)] = "refused"
    report = run(ws)
    assert logs(ws) == [] and report.failed == 0 and report.skipped["unsupported"] == 1 and report.skipped["refused"] == 1
    assert "c1 skipped" in report.summary()
    run(ws)
    assert len([1 for k, _ in mastodon.calls if k == "reply"]) == 2  # asked once each
    assert state(ws, "m-main")["social"]["pending"] == []


def test_both_with_a_private_mode_the_network_refuses_still_replies_publicly(ws):
    rule(ws, reply_as="both")
    mastodon = ws.nets["mastodon"]
    mastodon.feed = [item("c1")]
    mastodon.refuse[("c1", True)] = "unsupported"
    run(ws)
    [entry] = logs(ws)
    assert entry["mode"] == "public" and [a["private"] for a in mastodon.sent()] == [False]


# ── the narrow approval path ─────────────────────────────────────────────────────────────────────────────────────


def _net(ws):
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    return engine._Network(ws.session, ws.gid, row, ws.nets["mastodon"])


def _rule(**kw):
    return SocialRule(id="r1", keywords=("price",), reply="Approved text", **kw)


def test_only_a_published_rules_own_text_makes_a_reply_approved(ws):
    args = {"comment_id": "c1", "text": "Approved text", "private": True, "dry_run": False}
    net = _net(ws)
    assert engine._rule_approves(_rule(), args)
    assert not engine._rule_approves(_rule(published=False), args)
    assert not engine._rule_approves(None, args)
    assert not engine._rule_approves(_rule(), {**args, "text": "Approved text, edited"})
    for bad_rule, bad_args in ((None, args), (_rule(published=False), args), (_rule(), {**args, "text": "something else"})):
        with pytest.raises(EngineCallError, match="no way to social.reply"):
            net.call("social.reply", bad_args, bad_rule)
    assert ws.nets["mastodon"].calls == []
    assert net.call("social.reply", args, _rule())["replied"] is True


def test_the_engine_has_no_way_to_repost_delete_or_hide_and_messages_only_to_answer_a_dm(ws):
    net = _net(ws)
    with pytest.raises(EngineCallError, match="messages only to answer"):  # a comments rule doesn't approve a message
        net.call("social.message", {"to": {"handle": "a"}, "text": "x"}, _rule())
    for capability, args in (
        ("social.repost", {"post_id": "p"}),
        ("social.delete_comment", {"comment_id": "c"}),
        ("social.hide", {"comment_id": "c"}),
    ):
        with pytest.raises(EngineCallError, match="can't"):
            net.call(capability, args, _rule())
    assert ws.nets["mastodon"].calls == []


def test_a_rule_unpublished_before_the_send_is_not_sent(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item("c1")]
    rules = engine.load_rules(ws.session, ws.gid)
    ws.session.query(Entries).filter_by(group_id=ws.gid, slug="r1").update({"status": "draft"})
    ws.session.commit()
    assert engine._still_published(ws.session, ws.gid, rules[0]) is False
    assert not ws.nets["mastodon"].sent()


def test_a_plugin_that_forgot_requires_approval_changes_nothing_for_the_engine(ws, monkeypatch):
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    lax = make_network("mastodon", gated=False)
    monkeypatch.setitem(INTEGRATION_REGISTRY, "mastodon", lax)
    rule(ws)
    lax.feed = [item("c1")]
    run(ws)
    assert len(lax.sent()) == 1


# ── the scheduled task ───────────────────────────────────────────────────────────────────────────────────────────


def _task(ws, config):
    """A real engine task row (the handler maps an old `rehearsal` setting on it)."""
    task = ScheduledTaskModel(
        session=ws.session, group_id=ws.gid, name="Social engagement", slug=f"social-engagement-{uuid.uuid4().hex[:6]}", enabled=True,
        schedule_type="interval", schedule_config={"interval_seconds": 300}, task_type="social_engagement", task_config=config,
    )  # fmt: skip
    ws.session.add(task)
    ws.session.commit()
    return task


def _task_run(ws, config):
    from marvin.services.scheduled_tasks.handlers.social import SocialEngagementHandler

    task = _task(ws, config)
    return SocialEngagementHandler().execute(task, None)


def test_the_task_is_registered_for_workspaces_only_never_from_a_workflow():
    from marvin.services.automation.actions.handler import AUTOMATION_ALLOWED_HANDLERS
    from marvin.services.scheduled_tasks import TaskHandlerRegistry

    assert TaskHandlerRegistry.is_registered("social_engagement") and "social_engagement" not in AUTOMATION_ALLOWED_HANDLERS


def test_the_task_answers_only_the_networks_switched_on(ws):
    rule(ws)
    mode(ws, "rehearsal")
    ws.nets["mastodon"].feed = [item("c1")]
    summary = _task_run(ws, {})
    assert "would reply 1" in summary and ws.nets["mastodon"].sent() == []
    assert [r["rehearsal"] for r in logs(ws)] == [True]
    mode(ws, "on")
    live = _task_run(ws, {"max_replies": 5})
    assert "replied 1" in live and [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]


def test_an_old_task_wide_rehearsal_setting_is_mapped_onto_the_networks_once(ws):
    rule(ws)
    for slug in ("m-main", "b-main", "ig"):
        row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).one()
        row.state = {"social": {"polled_at": "x"}}  # no mode yet: the engine is as it was
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="ig").one()
    row.state = {"social": {"auto_reply": "off"}}  # one that was set stays
    ws.session.commit()
    ws.nets["mastodon"].feed = [item("c1")]
    task = _task(ws, {"rehearsal": False, "max_replies": 5})
    from marvin.services.scheduled_tasks.handlers.social import SocialEngagementHandler

    SocialEngagementHandler().execute(task, None)
    ws.session.expire_all()
    modes = {r.slug: social_setup.get_mode(r) for r in ws.session.query(IntegrationModel).filter_by(group_id=ws.gid)}
    assert modes == {"m-main": "on", "b-main": "on", "ig": "off"}
    assert (
        "rehearsal" not in ws.session.get(ScheduledTaskModel, task.id).task_config
        and ws.session.get(ScheduledTaskModel, task.id).task_config["max_replies"] == 5
    )
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]  # the old setting was the live one
    # mapped once: a network connected later starts off
    row = IntegrationModel(session=ws.session, group_id=ws.gid, provider="mastodon", name="new", slug="m-new", enabled=True, config={})
    ws.session.add(row)
    ws.session.commit()
    SocialEngagementHandler().execute(task, None)
    ws.session.expire_all()
    assert social_setup.get_mode(ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-new").one()) == "off"


def test_a_legacy_rehearsing_task_maps_to_rehearsal(ws):
    for slug in ("m-main", "b-main", "ig"):
        ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).one().state = None
    ws.session.commit()
    task = _task(ws, {"rehearsal": True})
    assert social_setup.map_legacy_rehearsal(ws.session, ws.gid, task) is True
    ws.session.expire_all()
    assert {social_setup.get_mode(r) for r in ws.session.query(IntegrationModel).filter_by(group_id=ws.gid)} == {"rehearsal"}
    assert social_setup.map_legacy_rehearsal(ws.session, ws.gid, task) is False  # nothing left to map


def test_a_routine_run_with_nothing_to_answer_is_not_worth_a_log_row(ws):
    rule(ws)
    ws.nets["mastodon"].feed = [item("c1", "nothing relevant")]
    first = _task_run(ws, {})
    assert first is None


# ── the pure rules ───────────────────────────────────────────────────────────────────────────────────────────────


def test_a_rule_reads_keywords_as_a_list_or_a_comma_separated_string_and_ignores_the_unusable():
    from marvin.services.integrations.social_rules import rule_from_data

    assert rule_from_data({"keywords": [" Price ", "How Much", ""], "reply": " Hi "}, id="r").keywords == ("price", "how much")
    assert rule_from_data({"keywords": "Price, , cost", "reply": "Hi"}, id="r").keywords == ("price", "cost")
    assert rule_from_data({"keywords": "", "reply": "Hi"}, id="r") is None and rule_from_data({"keywords": "a", "reply": "  "}, id="r") is None
    odd = rule_from_data({"keywords": "a", "reply": "x", "reply_as": "shout", "post": "*", "networks": "@Mastodon, b-main"}, id="r")
    assert (odd.reply_as, odd.post, odd.networks) == ("private", "", frozenset({"mastodon", "b-main"}))


def test_the_window_counts_an_unreadable_time_as_fresh_and_reads_z_suffixed_times():
    from marvin.services.integrations.social_rules import too_old

    assert too_old({"created_at": "2026-10-10T00:00:00Z"}, NOW) and not too_old({"created_at": "2026-10-19T00:00:00Z"}, NOW)
    assert not too_old({"created_at": "garbage"}, NOW) and not too_old({}, NOW)
