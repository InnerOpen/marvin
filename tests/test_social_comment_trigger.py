"""The "new comment" workflow trigger: `social_comment_received`, announced by the engagement poll.

The engine is run directly (`run_engagement`) with a fixed `now` and a recording bus, against the fake networks of
tests/test_social_engagement.py. What is held here: one event per new item, exactly once; no backlog on the first poll; its
own cursor (rehearsal and live replies never change what is announced); the account's own items never announced (so a
workflow's reply can't start the workflow again); the 7-day window; a templated `integration` reply step after an
Approval; hide with none; the trigger's conditions and templates; the event's place in the catalogue.
"""

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from datetime import UTC, datetime, timedelta  # noqa: E402

from fastapi.encoders import jsonable_encoder  # noqa: E402

from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.services.automation.actions.base import AutomationActionError  # noqa: E402
from marvin.services.automation.actions.integration import run_integration_action  # noqa: E402
from marvin.services.automation.authoring import reference_issues  # noqa: E402
from marvin.services.automation.authz import ROLE_ADMIN  # noqa: E402
from marvin.services.automation.context import event_context  # noqa: E402
from marvin.services.automation.matcher import interpolate, matches  # noqa: E402
from marvin.services.integrations.social_engagement import Settings, run_engagement  # noqa: E402
from tests import test_social_engagement as se  # noqa: E402

NOW, item, rule, state = se.NOW, se.item, se.rule, se.state
ws, nets, _types = se.ws, se.nets, se._types  # the fake networks and the workspace, as the engine's own tests have them

EVENTS_ONLY = Settings()
LATER = NOW + timedelta(minutes=10)


def fresh(cid, text="Is this in stock?", **kw):
    """An item written after the first poll (at NOW): what the trigger announces."""
    return item(cid, text, **{"age_hours": -0.05, **kw})


class Bus:
    """What the engine dispatches to: records the events (and fails on the ids it is told to)."""

    def __init__(self, fail_on=()):
        self.sent: list[dict] = []
        self.fail_on = set(fail_on)

    def dispatch(self, **kw):
        if kw["document_data"].id in self.fail_on:
            raise RuntimeError("the bus is down")
        self.sent.append(kw)

    @property
    def ids(self):
        return [k["document_data"].id for k in self.sent]


def poll(ws, bus, settings=EVENTS_ONLY, now=LATER):
    return run_engagement(ws.session, ws.gid, settings, now=now, event_bus=bus)


def first_poll(ws, bus, settings=EVENTS_ONLY):
    """The poll that only notes what is already there (at NOW)."""
    return poll(ws, bus, settings, now=NOW)


def ctx_of(sent: dict) -> dict:
    """The `event` a workflow starting on this dispatch reads (the reaction listener's own builder)."""
    document = jsonable_encoder(sent["document_data"], by_alias=False)
    return event_context(sent["event_type"].name, document, entity_id=sent["entity_id"], entity_type=sent["entity_type"])


# ── what is announced, and when ──────────────────────────────────────────────────────────────────────────────────


def test_the_first_poll_announces_no_backlog_then_each_new_item_once(ws):
    net, bus = ws.nets["mastodon"], Bus()
    net.feed = [item("old1"), item("old2")]
    report = first_poll(ws, bus)
    assert bus.sent == [] and report.announced == 0
    assert state(ws, "m-main")["social"]["events_cursor"] == "2"  # set from the newest items, not left unset

    net.feed += [fresh("n1"), fresh("n2", kind="mention")]
    report = poll(ws, bus)
    assert bus.ids == ["n1", "n2"] and report.announced == 2 and "announced 2" in report.summary()
    poll(ws, bus)
    assert bus.ids == ["n1", "n2"]  # nothing twice
    net.feed.append(fresh("n3"))
    poll(ws, bus)
    assert bus.ids == ["n1", "n2", "n3"]


def test_a_first_poll_that_found_nothing_still_counts_as_the_start(ws):
    """No items means (for some networks) no cursor: the next poll must not mistake the first new item for backlog."""
    net, bus = ws.nets["mastodon"], Bus()
    net.feed = []
    first_poll(ws, bus)
    assert state(ws, "m-main")["social"]["events_started_at"]
    net.feed = [fresh("n1")]
    poll(ws, bus)
    assert bus.ids == ["n1"]


def test_an_item_written_before_the_start_is_not_news_even_when_a_lagging_cursor_returns_it(ws):
    net, bus = ws.nets["mastodon"], Bus()
    net.feed = [item("old1")]
    first_poll(ws, bus)
    ws.session.expire_all()
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    row.state = {"social": {**row.state["social"], "events_cursor": "0"}}  # a cursor behind: old1 comes back
    ws.session.commit()
    net.feed.append(fresh("n1"))
    report = poll(ws, bus)
    assert bus.ids == ["n1"] and report.skipped["event_before_start"] == 0  # already seen on the first poll: passed over silently


def test_the_payload_is_the_normalised_item_with_its_integration(ws):
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("n1", "What is the price?", handle="alice", post="p9", network="mastodon")]
    poll(ws, bus)
    (sent,) = bus.sent
    data = sent["document_data"]
    assert sent["event_type"].name == "social_comment_received" and sent["group_id"] == ws.gid
    assert (data.id, data.kind, data.post_id, data.text, data.network) == ("n1", "comment", "p9", "What is the price?", "mastodon")
    assert (data.author.id, data.author.handle, data.author.name) == ("u-alice", "alice", "Alice")
    assert data.post_url == "https://mastodon.example/p/p9" and data.url == "https://mastodon.example/c/n1" and data.created_at
    row = ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="m-main").one()
    assert data.integration == "m-main" and data.integration_id == row.id
    assert sent["entity_id"] == row.id and sent["entity_type"] == "integration"


def test_every_connected_network_that_reads_comments_is_polled_each_with_its_own_cursor(ws):
    bus = Bus()
    first_poll(ws, bus)
    ws.nets["mastodon"].feed = [fresh("m1")]
    ws.nets["bluesky"].feed = [fresh("b1", network="bluesky")]
    poll(ws, bus)
    assert sorted((k["document_data"].integration, k["document_data"].id) for k in bus.sent) == [("b-main", "b1"), ("m-main", "m1")]
    assert state(ws, "b-main")["social"]["events_cursor"] == "1"


# ── its own cursor, whatever the replies do ──────────────────────────────────────────────────────────────────────


def test_announcing_has_its_own_cursor_in_rehearsal_and_live_alike(ws):
    rule(ws)
    net, bus = ws.nets["mastodon"], Bus()
    se.mode(ws, "rehearsal")
    first_poll(ws, bus)
    net.feed = [fresh("n1", "price?"), fresh("n2", "nothing relevant")]
    poll(ws, bus)
    assert bus.ids == ["n1", "n2"]  # rehearsal announces: announcing is not sending
    social = state(ws, "m-main")["social"]
    assert social["events_cursor"] == social["rehearsal_cursor"] == "2" and "cursor" not in social

    net.feed.append(fresh("n3", "price?"))
    se.mode(ws, "on")
    poll(ws, bus)  # rehearsal off: the live cursor starts at the beginning, the events cursor goes on
    assert bus.ids == ["n1", "n2", "n3"]  # n1 and n2 are not announced again because the live reply cursor re-read them
    assert [a["comment_id"] for a in net.sent()] == ["n1", "n3"]  # the replies read their own cursor from the start: they answer n1 and n3
    social = state(ws, "m-main")["social"]
    assert social["cursor"] == social["events_cursor"] == "3"


def test_replying_does_not_depend_on_announcing_nor_the_other_way_round(ws):
    rule(ws)
    net, bus = ws.nets["mastodon"], Bus()
    se.mode(ws, "off")  # announcing goes on with the replies off
    first_poll(ws, bus)
    net.feed = [fresh("c1", "price?")]
    poll(ws, bus)
    assert bus.ids == ["c1"] and net.sent() == []
    se.mode(ws, "on")
    net.feed.append(fresh("c2", "no keyword here", age_hours=-0.5))
    poll(ws, bus, now=NOW + timedelta(hours=1))
    assert bus.ids == ["c1", "c2"] and [a["comment_id"] for a in net.sent()] == ["c1"]  # c1 is answered now; c2 matches nothing
    social = state(ws, "m-main")["social"]
    assert social["events_cursor"] == social["cursor"] == "2"


def test_one_read_serves_both_jobs_when_their_cursors_agree(ws):
    rule(ws)
    net, bus = ws.nets["mastodon"], Bus()
    net.feed = [fresh("c1", "price?")]
    poll(ws, bus)
    reads = lambda: sum(1 for key, _ in net.calls if key == "comments")  # noqa: E731
    assert reads() == 1  # replying and announcing both stood at "no cursor"
    net.feed.append(fresh("c2", "price?"))
    poll(ws, bus)
    assert reads() == 2


def test_a_dropped_cursor_rereads_the_newest_items_without_announcing_them_twice(ws):
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("n1")]
    poll(ws, bus)
    net.bad_cursor = True
    net.feed.append(fresh("n2"))
    poll(ws, bus)
    assert bus.ids == ["n1", "n2"]


# ── when the poll runs ───────────────────────────────────────────────────────────────────────────────────────────


def test_no_rules_still_reads_and_announces_but_moves_no_reply_cursor(ws):
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("n1")]
    report = poll(ws, bus)
    assert bus.ids == ["n1"] and "m-main" in report.integrations
    assert "cursor" not in state(ws, "m-main")["social"]  # a rule written later still sees what was waiting


def test_announcing_needs_no_rule_and_no_reply_capability(ws):
    net, bus = ws.nets["bluesky"], Bus()
    net.actions = tuple(a for a in net.actions if a.key == "comments")  # a network that can read, not reply
    first_poll(ws, bus)
    net.feed = [fresh("b1", network="bluesky")]
    poll(ws, bus)
    assert bus.ids == ["b1"]
    assert [k for k, _ in net.calls] == ["comments", "comments"]


def test_an_instagram_plugin_task_no_longer_stops_the_replies_or_the_announcing(ws):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    rule(ws, networks="instagram")
    ws.session.add(
        ScheduledTaskModel(
            session=ws.session, group_id=ws.gid, name="IG", slug="ig-auto", enabled=True, schedule_type="interval",
            schedule_config={"interval_seconds": 120}, task_type="run_integration_action", task_config={"integration": "ig", "action": "auto_reply"},
        )
    )  # fmt: skip
    ws.session.commit()
    net, bus = ws.nets["instagram"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("i1", "price?", network="instagram")]
    poll(ws, bus)
    assert bus.ids == ["i1"] and len(net.sent()) == 1
    assert sum(1 for k, _ in net.calls if k == "comments") == 2  # one read per poll: the replies did not read it again


def test_the_task_handler_passes_its_bus_and_always_announces(ws):
    from marvin.services.scheduled_tasks.handlers.social import SocialEngagementHandler

    bus, net = Bus(), ws.nets["mastodon"]
    task = se._task(ws, {})
    handler = SocialEngagementHandler()
    handler.execute(task, bus)

    def written_after_the_first_poll(cid):  # the handler runs on the real clock, not NOW
        made = fresh(cid)
        made["created_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        return made

    net.feed = [written_after_the_first_poll("n1")]
    summary = handler.execute(task, bus)
    assert bus.ids == ["n1"] and "announced 1" in summary
    net.feed.append(written_after_the_first_poll("n2"))
    handler.execute(se._task(ws, {"announce": False}), bus)  # an old `announce: false` is ignored: the inbox and the trigger always run
    assert bus.ids == ["n1", "n2"]


# ── never the account's own, and the window ──────────────────────────────────────────────────────────────────────


def _own_handle(ws, slug="m-main", handle="shop"):
    ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug=slug).update({"config": {"handle": handle}})
    ws.session.commit()


def test_the_accounts_own_items_are_not_announced(ws):
    _own_handle(ws)
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("mine", "thanks all", handle="shop"), fresh("n1", handle="alice")]
    report = poll(ws, bus)
    assert bus.ids == ["n1"] and report.skipped["event_own"] == 1


def test_a_workflows_own_reply_does_not_start_the_workflow_again(ws):
    """The loop: a workflow answers a comment publicly, the network then shows that reply as an item by the account itself."""
    _own_handle(ws)
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("n1")]
    poll(ws, bus)
    (sent,) = bus.sent
    step = {
        "kind": "integration", "integration": "${event.integration}", "capability": "social.reply",
        "args": {"comment_id": "${event.id}", "text": "Yes, in stock.", "private": False},
    }  # fmt: skip
    context = {"event": ctx_of(sent), "steps": {}, "depth": 0, "_approved": True}
    out = run_integration_action(ws.session, ws.gid, step, context, authorizer_role=ROLE_ADMIN)
    assert out["replied"] is True and [a["comment_id"] for a in net.sent()] == ["n1"]
    net.feed.append(fresh(out["reply_id"], "Yes, in stock.", kind="reply", handle="shop"))  # what the network now lists
    report = poll(ws, bus)
    assert bus.ids == ["n1"] and report.skipped["event_own"] == 1 and report.announced == 0


def test_only_items_inside_the_window_are_announced_after_a_long_gap(ws):
    """The task was off for 9 days: what it finds from the gap is announced only while it is within 7 days."""
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    later = NOW + timedelta(days=9)
    net.feed = [
        item("too-old", age_hours=-24),  # written a day after the start, eight days before this poll
        item("in-window", age_hours=-(9 * 24 - 48)),  # two days before this poll
    ]
    report = poll(ws, bus, now=later)
    assert bus.ids == ["in-window"] and report.skipped["event_too_old"] == 1


# ── a workflow answering it ──────────────────────────────────────────────────────────────────────────────────────

APPROVAL = {"kind": "approval", "message": "Send it?"}
REPLY = {
    "kind": "integration", "integration": "${event.integration}", "capability": "social.reply",
    "args": {"comment_id": "${event.id}", "text": "Thanks, ${event.author.handle}!", "private": False},
}  # fmt: skip
HIDE = {"kind": "integration", "integration": "${event.integration}", "capability": "social.hide", "args": {"comment_id": "${event.id}"}}


def _announced(ws, **kw):
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("n1", **kw)]
    poll(ws, bus)
    return net, bus.sent[0]


def _run(ws, sent, step, *, approved=True, dry_run=False):
    context = {"event": ctx_of(sent), "steps": {}, "depth": 0, **({"_approved": True} if approved else {})}
    return run_integration_action(ws.session, ws.gid, step, context, authorizer_role=ROLE_ADMIN, dry_run=dry_run)


def test_a_templated_integration_replies_on_the_connection_the_comment_came_through_after_an_approval(ws):
    net, sent = _announced(ws, handle="alice")
    with pytest.raises(AutomationActionError, match="needs a person's approval"):
        _run(ws, sent, REPLY, approved=False)
    assert net.sent() == []
    out = _run(ws, sent, REPLY)
    assert out["replied"] is True and net.sent() == [{"comment_id": "n1", "text": "Thanks, alice!", "private": False, "dry_run": False}]
    assert ws.nets["bluesky"].sent() == []  # not the other networks
    ahead = {"event": ctx_of(sent), "steps": {}, "depth": 0, "_approval_ahead": True}
    preview = run_integration_action(ws.session, ws.gid, REPLY, ahead, authorizer_role=ROLE_ADMIN, dry_run=True)
    assert preview["integration"] == "m-main" and preview["args"]["text"] == "Thanks, alice!" and len(net.sent()) == 1  # nothing more was sent


def test_a_templated_integration_that_comes_out_empty_or_unknown_is_refused(ws):
    _, sent = _announced(ws)
    with pytest.raises(AutomationActionError, match="came out empty"):
        run_integration_action(
            ws.session,
            ws.gid,
            {**REPLY, "integration": "${event.nothing}"},
            {"event": ctx_of(sent), "steps": {}, "_approved": True},
            authorizer_role=ROLE_ADMIN,
        )
    with pytest.raises(AutomationActionError, match="not found"):
        run_integration_action(
            ws.session,
            ws.gid,
            {**REPLY, "integration": "${event.network}-gone"},
            {"event": ctx_of(sent), "steps": {}, "_approved": True},
            authorizer_role=ROLE_ADMIN,
        )
    action = {"kind": "integration", "integration": "${event.integration}", "action": "reply", "args": {}}
    with pytest.raises(AutomationActionError, match="goes with a `capability` step"):
        run_integration_action(ws.session, ws.gid, action, {"event": ctx_of(sent), "steps": {}, "_approved": True}, authorizer_role=ROLE_ADMIN)


def test_hide_and_like_need_no_approval(ws):
    net, sent = _announced(ws)
    out = _run(ws, sent, HIDE, approved=False)
    assert out["hidden"] is True and net.sent("hide") == [{"comment_id": "n1"}]
    out = _run(ws, sent, {**HIDE, "capability": "social.like"}, approved=False)
    assert out["liked"] is True and net.sent("like") == [{"comment_id": "n1"}]


def _issues(ws, steps, trigger=None):
    definition = {"trigger": trigger or {"type": "event", "event": "social_comment_received"}, "actions": steps}
    return [(i["path"], i["message"]) for i in reference_issues(ws.session, ws.gid, definition)]


def test_save_accepts_a_templated_integration_and_still_asks_for_the_approval_step(ws):
    assert _issues(ws, [APPROVAL, REPLY]) == []
    assert _issues(ws, [HIDE]) == []  # hide and like need none
    [(path, message)] = _issues(ws, [REPLY])
    assert path == "actions[0].capability" and "needs a person's approval" in message


def test_save_refuses_a_templated_integration_that_is_not_a_capability_step_or_lacks_its_arguments(ws):
    named = {"kind": "integration", "integration": "${event.integration}", "action": "reply", "args": {}}
    [(path, message)] = _issues(ws, [APPROVAL, named])
    assert path == "actions[1].integration" and "goes with a `capability` step" in message
    [(path, message)] = _issues(ws, [APPROVAL, {**REPLY, "args": {"text": "x"}}])
    assert path == "actions[1].args" and "comment_id" in message
    assert any("No integration" in m for _, m in _issues(ws, [{**HIDE, "integration": "ghost"}]))  # a typed slug is still checked


# ── the trigger ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_conditions_and_templates_read_the_event(ws):
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("n1", "I want a REFUND please", handle="alice", kind="mention", network="mastodon"), fresh("n2", "love it", kind="reply")]
    poll(ws, bus)
    refund, love = (ctx_of(s) for s in bus.sent)
    context = lambda event: {"event": event, "steps": {}}  # noqa: E731
    conditions = [
        {"field": "event.kind", "op": "eq", "value": "mention"},
        {"field": "event.network", "op": "eq", "value": "mastodon"},
        {"field": "event.text", "op": "contains", "value": "REFUND"},
        {"field": "event.author.handle", "op": "eq", "value": "alice"},
        {"field": "event.integration", "op": "eq", "value": "m-main"},
    ]
    assert matches(conditions, context(refund)) and not matches(conditions, context(love))
    assert not matches([{"field": "event.kind", "op": "in", "value": ["comment", "reply"]}], context(refund))
    assert matches([{"field": "event.kind", "op": "in", "value": "comment, reply"}], context(love))
    assert interpolate("${event.author.handle}: ${event.text} (${event.id}, ${event.integration})", context(refund)) == (
        "alice: I want a REFUND please (n1, m-main)"
    )


def test_a_workflow_starts_on_the_event_and_hides_spam_with_no_approval(ws):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automations_for_event
    from marvin.services.automation.recorder import ExecutionRecorder

    ws.session.add(
        WorkspaceAutomationModel(
            session=ws.session, group_id=ws.gid, name="Hide spam", slug="hide-spam", enabled=True,
            definition={
                "trigger": {"type": "event", "event": "social_comment_received"},
                "conditions": [{"field": "event.text", "op": "contains", "value": "free followers"}],
                "actions": [HIDE],
            },
        )
    )  # fmt: skip
    ws.session.commit()
    net, bus = ws.nets["mastodon"], Bus()
    first_poll(ws, bus)
    net.feed = [fresh("s1", "get free followers now"), fresh("n2", "lovely")]
    poll(ws, bus)
    ran = [run_automations_for_event(ws.session, ws.gid, ctx_of(s), recorder=ExecutionRecorder(ws.session, ws.gid)) for s in bus.sent]
    assert ran == [1, 0] and net.sent("hide") == [{"comment_id": "s1"}]


def test_a_failed_announcement_is_that_items_alone_and_is_not_repeated(ws):
    net, bus = ws.nets["mastodon"], Bus(fail_on={"n2"})
    first_poll(ws, bus)
    net.feed = [fresh("n1"), fresh("n2"), fresh("n3")]
    report = poll(ws, bus)
    assert bus.ids == ["n1", "n3"] and report.failed == 1 and "n2" in report.summary()
    bus.fail_on.clear()
    poll(ws, bus)
    assert bus.ids == ["n1", "n3"]  # claimed before it was sent: at most once


# ── where it sits in the catalogue ───────────────────────────────────────────────────────────────────────────────


def test_the_event_is_a_workflow_trigger_with_the_fields_its_payload_carries():
    from marvin.services.event_bus_service.event_types import EventSocialCommentData
    from marvin.services.events.event_catalog import CATALOG_BY_TYPE, SOCIAL, TRIGGERABLE_EVENT_TYPES, social_fields, trigger_groups

    entry = CATALOG_BY_TYPE["social_comment_received"]
    assert entry.enabled and entry.scope == "workspace" and "social_comment_received" in TRIGGERABLE_EVENT_TYPES
    assert trigger_groups()[SOCIAL] == ["social_comment_received"]
    fields = social_fields("social_comment_received")
    assert set(fields) == {"id", "kind", "text", "author", "post_id", "post_url", "created_at", "url", "network", "integration", "integration_id"}
    assert set(fields) == set(EventSocialCommentData.model_fields) - {"document_type", "operation"}
    assert social_fields("entry_published") == {} and social_fields("scheduled_task_failed") == {}


def test_describe_event_and_the_guide_name_it(db_session, ws):
    import json
    from types import SimpleNamespace

    from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.base import ToolContext
    from marvin.services.automation.authoring import authoring_guide

    user = SimpleNamespace(
        id=ws.uid, group_id=ws.gid, active_group_id=ws.gid, admin=False, is_superuser=False,
        platform_role=PlatformRole.NONE, get_workspace_role=lambda g: WorkspaceRole.ADMIN,
    )  # fmt: skip
    out = json.loads(
        get_tool("describe_event").handler(ToolContext(session=db_session, group_id=ws.gid, user=user), {"event": "social_comment_received"})
    )
    assert out["found"] and out["workflowTrigger"]["triggerable"] is True and "author" in out["workflowTrigger"]["fields"]
    assert "${event.integration}" in out["workflowTrigger"]["note"]
    guide = authoring_guide(db_session, ws.gid, "events")
    events = guide.get("events", guide)
    assert events["triggerable"]["Social"].keys() == {"social_comment_received"}
    assert events["social"]["fields"]["social_comment_received"]["author"] == "object"
    assert "${event.integration}" in events["social"]["note"]
