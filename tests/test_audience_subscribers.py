# ruff: noqa: F811  (pytest fixtures imported from test_audience_submissions are used as arguments)
"""Audience › Subscribers: the signup forms' entries read with the mailing list's word for their status (services/audience.py,
routes/groups/audience_controller.py), the per-status counts the sidebar and dashboard read, and Buttondown's workflows still
reaching these internal entries.

Signups are made the way the public form route makes them (the `site` fixture of test_audience_submissions); a status is what the
mailing-list loop leaves on the entry (inbox pending, published confirmed, archived unsubscribed, needs_review a problem).
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import audience
from marvin.services.automation.actions import entry as entry_action
from marvin.services.automation.authz import ROLE_ADMIN
from marvin.services.entries import trash as entry_trash
from marvin.services.entries.entry_service import EntryService
from tests.test_audience_submissions import (  # noqa: F401  (the `site` and `verdict` fixtures)
    API,
    P,
    _back_date,
    _caps,
    _client,
    _sign_in,
    _type,
    site,
    verdict,
    workspace,
)

SUBSCRIBERS = f"{P}/subscribers"


def _set(site, entry, status, **meta):
    """Leave an entry in a status the way the mailing-list loop does (a direct write: the publish gate isn't what is under test)."""
    entry.status = status
    if meta:
        entry.metadata_json = {**(entry.metadata_json or {}), **meta}
    site.session.commit()
    return entry


@pytest.fixture
def readers(site):
    """Five signups of the newsletter form, one per status the loop leaves (and a draft), oldest first, plus a contact message."""
    t = site.types.newsletter
    out = SimpleNamespace(
        ann=site.submit(t, {"name": "Ann Abel", "email": "ann@x.test"})[0],  # pending (inbox)
        bo=site.submit(t, {"name": "Bo Bell", "email": "bo@x.test"})[0],  # confirmed
        cy=site.submit(t, {"email": "cy@y.test"})[0],  # unsubscribed (no name)
        dee=site.submit(t, {"name": "Dee Dunn", "email": "dee@x.test"})[0],  # problem
        eli=site.submit(t, {"name": "Eli Eck", "email": "eli@x.test"})[0],  # draft: anything unsettled is pending
        message=site.submit(site.types.contact, {"name": "Msg", "email": "msg@x.test", "message": "hi"})[0],
    )
    _set(site, out.bo, "published")
    _set(site, out.cy, "archived")
    _set(site, out.dee, "needs_review", review_reasons=["Buttondown · refused — spam firewall"])
    _set(site, out.eli, "draft")
    for entry, hours in ((out.ann, 50), (out.bo, 40), (out.cy, 30), (out.dee, 20), (out.eli, 10)):
        _back_date(site, entry, hours=hours)
    out.site = site
    return out


def _items(res):
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _emails(res):
    return [i["email"] for i in _items(res)]


# ── the summary ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_summary_counts_each_status_and_what_is_waiting(site, readers):
    out = _client(site).get(f"{P}/summary").json()["signups"]
    assert out["show"] is True
    assert (out["pending"], out["confirmed"], out["unsubscribed"], out["problem"]) == (2, 1, 1, 1)  # inbox + draft; published; archived; needs_review
    assert out["waiting"] == 3
    assert [(f["slug"], f["new"]) for f in out["forms"]] == [("newsletter", 3)]
    assert out["integrations"] == []  # only the Subscribers page asks which integrations act on them


def test_the_status_mapping_is_the_mailing_lists_word():
    word = audience.subscriber_status
    assert [word(s) for s in ("inbox", "published", "archived", "needs_review")] == ["pending", "confirmed", "unsubscribed", "problem"]
    assert word("draft") == "pending" and word("approved") == "pending" and word("anything") == "pending"


def test_the_trash_is_not_counted_and_a_message_form_is_not_a_signup(site, readers):
    EntryService(site.session, site.gid, integration_id="test").trash(readers.bo.id)
    out = _client(site).get(f"{P}/summary").json()["signups"]
    assert (out["pending"], out["confirmed"], out["unsubscribed"], out["problem"]) == (2, 0, 1, 1)
    assert audience.signup_forms(site.session, site.gid)[0].slug == "newsletter"


def test_a_signup_form_shows_whatever_its_destination_and_a_form_with_nothing_yet_is_still_shown(workspace, db_session):  # noqa: F811
    assert _sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/summary").json()["signups"]["show"] is False
    _type(db_session, workspace.gid, "message", "Message", _caps(kind="message"))
    assert _sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/summary").json()["signups"]["show"] is False
    _type(db_session, workspace.gid, "list", "The list", _caps(destination="entries", kind="signup"))  # a listed signup form
    out = _sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/summary").json()["signups"]
    assert out["show"] is True and [f["slug"] for f in out["forms"]] == ["list"] and out["waiting"] == 0


# ── the list ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_list_is_the_signups_newest_first_with_who_when_and_where_it_stands(site, readers):
    res = _client(site).get(SUBSCRIBERS)
    items = _items(res)
    assert [i["email"] for i in items] == ["eli@x.test", "dee@x.test", "cy@y.test", "bo@x.test", "ann@x.test"]  # the message isn't one
    by = {i["email"]: i for i in items}
    assert by["ann@x.test"]["name"] == "Ann Abel" and by["cy@y.test"]["name"] is None
    assert {e: by[e]["status"] for e in by} == {
        "ann@x.test": "pending",
        "bo@x.test": "confirmed",
        "cy@y.test": "unsubscribed",
        "dee@x.test": "problem",
        "eli@x.test": "pending",
    }
    assert by["bo@x.test"]["entryStatus"] == "published" and by["ann@x.test"]["form"]["slug"] == "newsletter"
    assert by["dee@x.test"]["reason"] == "Buttondown · refused — spam firewall" and by["dee@x.test"]["reviewReasons"] == [by["dee@x.test"]["reason"]]
    assert by["bo@x.test"]["reason"] is None and by["ann@x.test"]["reviewReasons"] == []
    assert by["ann@x.test"]["signedUpAt"] and by["ann@x.test"]["path"] == f"/workspace/entries/{readers.ann.id}"
    body = res.json()
    assert body["total"] == 5 and body["counts"] == {"pending": 2, "confirmed": 1, "unsubscribed": 1, "problem": 1}
    assert body["can"] == {"act": True, "fullIp": False}


def test_a_spam_held_signup_is_a_problem_with_the_protections_reason(site, verdict):
    held, _ = site.submit(site.types.newsletter, {"email": "bad@example.com"}, flag=True)
    row = _items(_client(site).get(SUBSCRIBERS))[0]
    assert held.status == "needs_review" and row["status"] == "problem" and row["reason"] == "blocked_domain:example.com"


def test_filters_status_search_dates_and_paging(site, readers):
    c = _client(site)
    assert set(_emails(c.get(SUBSCRIBERS, params={"status": "pending"}))) == {"ann@x.test", "eli@x.test"}
    assert set(_emails(c.get(SUBSCRIBERS, params=[("status", "confirmed"), ("status", "problem")]))) == {"bo@x.test", "dee@x.test"}
    assert _emails(c.get(SUBSCRIBERS, params={"status": "unsubscribed"})) == ["cy@y.test"]
    assert c.get(SUBSCRIBERS, params={"status": "nonsense"}).status_code == 422
    # search: email, name (any case), and a piece of either
    assert _emails(c.get(SUBSCRIBERS, params={"q": "BO@X"})) == ["bo@x.test"]
    assert _emails(c.get(SUBSCRIBERS, params={"q": "dunn"})) == ["dee@x.test"]
    assert set(_emails(c.get(SUBSCRIBERS, params={"q": "@x.test"}))) == {"ann@x.test", "bo@x.test", "dee@x.test", "eli@x.test"}
    assert _emails(c.get(SUBSCRIBERS, params={"q": "nobody"})) == []
    assert _emails(c.get(SUBSCRIBERS, params={"q": "msg@x.test"})) == []  # the contact message is not a subscriber
    # dates: a day range on when they signed up
    since = (datetime.now(UTC) - timedelta(hours=35)).isoformat()
    until = (datetime.now(UTC) - timedelta(hours=15)).isoformat()
    assert _emails(c.get(SUBSCRIBERS, params={"since": since})) == ["eli@x.test", "dee@x.test", "cy@y.test"]
    assert _emails(c.get(SUBSCRIBERS, params={"since": since, "until": until})) == ["dee@x.test", "cy@y.test"]
    # paging, the totals counting every match; the counts ignore the filters
    page = c.get(SUBSCRIBERS, params={"limit": 2, "offset": 1, "status": "pending"}).json()
    assert page["total"] == 2 and [i["email"] for i in page["items"]] == ["ann@x.test"] and page["counts"]["problem"] == 1
    assert c.get(SUBSCRIBERS, params={"limit": 0}).status_code == 422


def test_several_signup_forms_filter_by_form_and_the_counts_follow_it(site, readers):
    events = _type(site.session, site.gid, "events", "Event list", _caps(listed=False, kind="signup"), icon="🎟", order=9)
    site.submit(events, {"name": "Fay", "email": "fay@z.test"})
    c = _client(site)
    both = c.get(SUBSCRIBERS).json()
    assert both["total"] == 6 and [f["slug"] for f in both["forms"]] == ["newsletter", "events"] and both["counts"]["pending"] == 3
    only = c.get(SUBSCRIBERS, params={"form": "events"}).json()
    assert [i["email"] for i in only["items"]] == ["fay@z.test"] and only["items"][0]["form"]["name"] == "Event list"
    assert only["counts"] == {"pending": 1, "confirmed": 0, "unsubscribed": 0, "problem": 0}
    assert c.get(SUBSCRIBERS, params={"form": "nope"}).json()["items"] == []
    assert [(f["slug"], f["new"]) for f in c.get(f"{P}/summary").json()["signups"]["forms"]] == [("newsletter", 3), ("events", 1)]


def test_a_form_with_no_email_or_name_field_still_lists_its_signups_by_title(site):
    bare = _type(
        site.session, site.gid, "wait", "Waitlist", {"publishable": False, "submittable": True, "listed": False, "submission": {"kind": "signup"}}
    )
    bare.schema_json = {"fields": [{"key": "handle", "label": "Handle", "type": "text"}]}
    site.session.commit()
    entry = site.submit(bare, {"handle": "@zed"})[0]
    row = _items(_client(site).get(SUBSCRIBERS))[0]
    assert row["id"] == str(entry.id) and row["email"] is None and row["name"] is None and row["title"]


# ── roles ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_editors_and_above_read_and_delete_and_nobody_below_does(site, readers):
    sid = readers.ann.id
    for role in (WorkspaceRole.EDITOR, WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        c = _client(site, role)
        assert c.get(SUBSCRIBERS).status_code == 200 and c.get(f"{SUBSCRIBERS}/{sid}").status_code == 200
    for role in (WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR):
        c = _client(site, role)
        assert c.get(SUBSCRIBERS).status_code == 403
        assert c.get(f"{SUBSCRIBERS}/{sid}").status_code == 403
        assert c.delete(f"{SUBSCRIBERS}/{sid}").status_code == 403
    site.session.expire_all()
    assert site.session.get(Entries, sid).status == "inbox"  # nothing happened


# ── one subscriber ──────────────────────────────────────────────────────────────────────────────────────────────


def test_a_subscriber_in_full_with_the_ip_masked_for_an_editor_and_whole_for_an_admin(site, readers):
    sid = readers.ann.id
    editor = _client(site, WorkspaceRole.EDITOR).get(f"{SUBSCRIBERS}/{sid}").json()["subscriber"]
    assert editor["email"] == "ann@x.test" and editor["status"] == "pending"
    assert [(f["key"], f["value"]) for f in editor["fields"]] == [("name", "Ann Abel"), ("email", "ann@x.test")]
    assert editor["source"]["ip"] == "203.0.113.x" and editor["source"]["ipMasked"] is True
    assert editor["source"]["userAgent"] == "pytest-agent" and editor["source"]["referrer"] == "https://site.test/contact"
    for role in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        full = _client(site, role).get(f"{SUBSCRIBERS}/{sid}").json()["subscriber"]["source"]
        assert full["ip"] == "203.0.113.77" and full["ipMasked"] is False
    assert "ip" not in str(_client(site).get(SUBSCRIBERS).json()["items"]).lower().replace("ipmasked", "")  # the list carries no source at all


def test_a_subscribers_history_is_its_status_changes_from_the_event_log(site, readers):
    sid, now = readers.bo.id, datetime.now(UTC)

    def log(event_type, minutes, **doc):
        site.session.add(
            EventLogModel(
                event_id=uuid.uuid4(),
                event_type=event_type,
                occurred_at=now - timedelta(minutes=minutes),
                workspace_id=site.gid,
                entity_id=sid,
                entity_type="entry",
                integration_id="test",
                event_data={"documentData": doc},
                message_title=event_type,
            )
        )

    log("entry_created", 60)
    log("entry_updated", 50, changedFields=["title"], after={"title": "x"})  # not a status change: says nothing
    log("entry_updated", 40, changedFields=["status"], after={"status": "needs_review"})
    log("entry_published", 30)
    log("entry_archived", 20)
    log("entry_restored", 10)
    site.session.commit()
    history = _client(site).get(f"{SUBSCRIBERS}/{sid}").json()["subscriber"]["history"]
    assert [h["label"] for h in history] == ["Reopened", "Unsubscribed", "Confirmed", "Needs a look", "Signed up"]
    assert _client(site).get(f"{SUBSCRIBERS}/{readers.ann.id}").json()["subscriber"]["history"] == []


def test_only_a_signup_of_this_workspace_is_a_subscriber(site, readers, workspace, db_session):  # noqa: F811
    c = _client(site)
    for entry in (readers.message, site.session.get(Entries, readers.message.id)):  # a message form's submission
        assert c.get(f"{SUBSCRIBERS}/{entry.id}").status_code == 404 and c.delete(f"{SUBSCRIBERS}/{entry.id}").status_code == 404
    assert c.get(f"{SUBSCRIBERS}/{uuid.uuid4()}").status_code == 404
    EntryService(site.session, site.gid, integration_id="test").trash(readers.ann.id)
    assert c.get(f"{SUBSCRIBERS}/{readers.ann.id}").status_code == 404  # the Trash lists it
    site.session.expire_all()
    assert site.session.get(Entries, readers.message.id).status == "inbox"


def test_delete_moves_the_signup_to_the_trash_and_never_unsubscribes_anyone(site, readers):
    c = _client(site)
    sid = readers.bo.id
    res = c.delete(f"{SUBSCRIBERS}/{sid}")
    assert res.status_code == 200 and res.json() == {"subscriber": None}
    site.session.expire_all()
    assert site.session.get(Entries, sid).status == "trashed" and sid in entry_trash.trashed_ids(site.session, site.gid)
    assert "bo@x.test" not in _emails(c.get(SUBSCRIBERS)) and c.get(SUBSCRIBERS).json()["counts"]["confirmed"] == 0
    EntryService(site.session, site.gid, integration_id="test").restore_from_trash(sid)
    assert "bo@x.test" in _emails(c.get(SUBSCRIBERS))
    # there is no subscribe / unsubscribe door here: those stay with the integration
    assert c.post(f"{SUBSCRIBERS}/{sid}/unsubscribe").status_code in (404, 405)
    assert c.put(f"{SUBSCRIBERS}/{sid}").status_code in (404, 405)


# ── the integrations note ───────────────────────────────────────────────────────────────────────────────────────


def _integration(site, provider="buttondown", slug="buttondown", enabled=True):
    row = IntegrationModel(session=site.session, group_id=site.gid, provider=provider, name=slug.title(), slug=slug, enabled=enabled, config={})
    site.session.add(row)
    site.session.commit()
    return row


def _workflow(site, integration, definition, slug="buttondown-subscribe-on-signup"):
    row = WorkspaceAutomationModel(
        session=site.session,
        group_id=site.gid,
        name="Buttondown: subscribe on signup",
        slug=slug,
        enabled=False,
        definition=definition,
        source_integration_id=integration.id if integration else None,
        source_blueprint=slug,
    )
    site.session.add(row)
    site.session.commit()
    return row


SUBSCRIBE = {
    "trigger": {"type": "event", "event": "form_submission_received"},
    "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "newsletter"}],
    "actions": [{"kind": "entry", "op": "set_metadata", "metadata": {"a": "b"}}],
}


def test_the_page_says_which_integration_handles_the_signups_or_none(site, readers):
    c = _client(site)
    assert c.get(SUBSCRIBERS).json()["integrations"] == []  # nothing connected: the page hints to connect one
    bd = _integration(site)
    _workflow(site, bd, SUBSCRIBE)
    assert c.get(SUBSCRIBERS).json()["integrations"] == [{"slug": "buttondown", "name": "Buttondown", "provider": "buttondown"}]
    assert c.get(f"{P}/summary").json()["signups"]["integrations"] == []  # the sidebar's summary skips the lookup


def test_an_integration_is_named_only_when_it_acts_on_a_signup_form(site, readers):
    c = _client(site)
    other = _integration(site, provider="square", slug="square")
    _workflow(site, other, {**SUBSCRIBE, "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "order"}]}, slug="square-orders")
    _workflow(site, None, SUBSCRIBE, slug="by-hand")  # a person's own workflow: not an integration's
    assert c.get(SUBSCRIBERS).json()["integrations"] == []
    off = _integration(site, slug="off", enabled=False)
    _workflow(site, off, SUBSCRIBE, slug="from-a-disabled-one")
    assert c.get(SUBSCRIBERS).json()["integrations"] == []  # a disabled connection isn't connected
    # a step that queries the form by name counts too, as does a condition listing several types
    wf = _integration(site, provider="other", slug="other")
    _workflow(site, wf, {"conditions": [], "actions": [{"kind": "entry", "op": "archive", "entity_query": {"entry_type": "newsletter"}}]}, slug="q")
    assert [i["slug"] for i in c.get(SUBSCRIBERS).json()["integrations"]] == ["other"]


def test_a_provider_whose_blueprint_names_the_signup_type_counts_once_connected(site, readers, monkeypatch):
    from marvin.schemas.platform.blueprints import Blueprint, BlueprintParameter

    declared = Blueprint(
        kind="workflow",
        slug="list-signup",
        name="List: subscribe",
        source="listco",
        parameters=[BlueprintParameter(key="signup_type", label="Signup form", kind="entry_type", default="newsletter")],
        payload={"definition": {"trigger": {"type": "event", "event": "form_submission_received"}, "actions": [{"kind": "entry", "op": "archive"}]}},
    )
    monkeypatch.setattr("marvin.services.blueprints.catalog.list_blueprints", lambda source=None, **kw: [declared] if source == "listco" else [])
    c = _client(site)
    assert c.get(SUBSCRIBERS).json()["integrations"] == []  # not connected yet
    _integration(site, provider="listco", slug="listco")
    assert [i["provider"] for i in c.get(SUBSCRIBERS).json()["integrations"]] == ["listco"]


# ── the dashboard ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_dashboard_counts_signups_that_need_a_look_and_not_pending_ones(site, readers):
    att = _client(site).get(f"{API}/stats/dashboard").json()["attention"]
    assert att["audienceProblems"] == 1 and att["audienceNew"] == 1  # one problem signup; the contact message
    assert att["inbox"] == 0 and att["needsReview"] == 0  # internal entries are in neither
    assert _sign_in(site.ws, WorkspaceRole.VIEWER).get(f"{API}/stats/dashboard").json()["attention"]["audienceProblems"] == 0


# ── Buttondown's workflows still reach the internal signup entries ─────────────────────────────────────────────────


def _step(site, op, subscriber_id):
    """What Buttondown's confirm / unsubscribe workflows do: an entry step that finds the signup by type and the stored subscriber id."""
    step = {
        "kind": "entry",
        "op": op,
        "if_none": "skip",
        "entity_query": {"entry_type": "newsletter", "metadata": {"buttondown_subscriber_id": subscriber_id}},
    }
    return entry_action.run_entry_action(site.session, site.gid, step, {"event": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)


def test_the_buttondown_workflows_find_their_unlisted_signup_and_the_subscribers_page_follows(site, readers):
    site.types.newsletter.capabilities_json = {**site.types.newsletter.capabilities_json, "publishable": True}
    site.session.commit()
    _set(site, readers.ann, "inbox", buttondown_subscriber_id="sub_ann")
    c = _client(site)
    assert site.types.newsletter.capabilities_json["listed"] is False  # internal: out of every content list
    assert c.get(f"{API}/entries").json() == []

    done = _step(site, "publish", "sub_ann")  # subscriber.confirmed
    assert done.get("skipped") is not True
    assert {i["email"]: i["status"] for i in _items(c.get(SUBSCRIBERS))}["ann@x.test"] == "confirmed"

    _step(site, "archive", "sub_ann")  # subscriber.unsubscribed
    assert {i["email"]: i["status"] for i in _items(c.get(SUBSCRIBERS))}["ann@x.test"] == "unsubscribed"
    assert c.get(f"{P}/summary").json()["signups"]["unsubscribed"] == 2

    skipped = _step(site, "publish", "sub_somebody_else")  # a reader who joined elsewhere: a quiet no-op
    assert skipped["skipped"] is True
