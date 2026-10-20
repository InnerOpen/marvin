"""Audience: the form's destination (audience | entries) and kind (message | signup), what makes a type internal, and Audience ›
Submissions (services/audience.py, routes/groups/audience_controller.py).

Submissions are made the way the public form route makes them (`_submit_to_entry_type`, with the protection's verdict pinned), so
what the page lists is what a visitor's submission really leaves behind.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_collections import EntryCollections
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from marvin.repos.platform.entry_types import EntryTypesRepository
from marvin.routes.publish import forms_controller
from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition, SubmissionConfig
from marvin.services import audience, dashboard
from marvin.services.ai.embeddings_registry import REGISTRY
from marvin.services.collections.smart_collections import matches_rules, sync_collection
from marvin.services.entries import trash as entry_trash
from marvin.services.entries.entry_service import EntryService, count_by_status
from marvin.services.entries.query import run as run_query
from marvin.services.entry_listing import (
    is_listed_type,
    submission_destination,
    submission_kind,
    unlisted_type_ids,
)
from marvin.services.publish_visibility import is_publishable_type
from marvin.services.push_actions import inbox_count
from marvin.services.security.submission_protection import Verdict
from tests.test_content_role_gates import _sign_in, workspace  # noqa: F401  (the `workspace` fixture)

P = "/api/groups/audience"
API = "/api/platform"
FIELDS = {
    "fields": [
        {"key": "name", "label": "Your name", "type": "text"},
        {"key": "email", "label": "Email", "type": "text"},
        {"key": "message", "label": "Message", "type": "textarea"},
    ]
}


def _caps(listed=None, **submission):
    caps = {"publishable": False, "submittable": True, "submission": submission}
    return caps if listed is None else {**caps, "listed": listed}


def _type(session, gid, slug, name=None, caps=None, icon=None, order=0):
    t = EntryTypes(session=session, group_id=gid, slug=slug, name=name or slug.title(), icon=icon, sort_order=order,
                   schema_json=FIELDS, capabilities_json=caps)  # fmt: skip
    session.add(t)
    session.commit()
    return t


@pytest.fixture
def verdict(monkeypatch):
    """Pin submission protection's verdict: `verdict.flag = True` makes the next submissions suspicious."""
    state = SimpleNamespace(flag=False)
    monkeypatch.setattr(
        forms_controller, "evaluate", lambda policy, data, ip: Verdict(reasons=["blocked_domain:example.com"]) if state.flag else Verdict()
    )
    return state


@pytest.fixture
def site(workspace, db_session, verdict):  # noqa: F811
    """A workspace with: a message form by default (contact), one set explicitly (workshop), a content form (testimonial, destination
    entries, listed), a signup form (newsletter), and an ordinary type (note). The Audience forms are unlisted, as the migration and
    the destination default make them."""
    gid = workspace.gid
    group = db_session.get(Groups, gid)
    types = SimpleNamespace(
        contact=_type(db_session, gid, "contact", "Contact", {"publishable": False, "submittable": True, "listed": False}, icon="✉️", order=1),
        workshop=_type(
            db_session, gid, "workshop", "Workshop enquiry", _caps(listed=False, destination="audience", kind="message"), icon="🛠", order=2
        ),
        testimonial=_type(db_session, gid, "testimonial", "Testimonial", _caps(destination="entries"), order=3),
        newsletter=_type(db_session, gid, "newsletter", "Newsletter", _caps(listed=False, kind="signup", matchField="email"), order=4),
        note=_type(db_session, gid, "note", "Note", None, order=5),
    )
    made = SimpleNamespace(ws=workspace, session=db_session, gid=gid, group=group, types=types)

    def submit(entry_type, data, ip="203.0.113.77", flag=False):
        verdict.flag = flag
        request = SimpleNamespace(headers={"user-agent": "pytest-agent", "referer": "https://site.test/contact"}, client=SimpleNamespace(host=ip))
        caps = CapabilitiesDefinition(**(entry_type.capabilities_json or {}))
        cfg = caps.submission or SubmissionConfig()
        bg = BackgroundTasks()
        response = asyncio.run(forms_controller._submit_to_entry_type(entry_type, cfg, dict(data), request, group, bg, db_session))
        events = [(t.kwargs["event"].event_type.name, t.kwargs["event"].document_data) for t in bg.tasks]
        db_session.expire_all()
        return db_session.get(Entries, response.submission_id), events

    made.submit = submit
    return made


def _client(site, role=WorkspaceRole.EDITOR):
    return _sign_in(site.ws, role)


def _status(site, entry_id):
    site.session.expire_all()
    return site.session.get(Entries, entry_id).status


def _back_date(site, entry, **delta):
    entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(**delta)
    site.session.commit()


# ── the two settings ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_settings_default_to_an_audience_message_form():
    cfg = SubmissionConfig()
    assert (cfg.destination, cfg.kind) == ("audience", "message")
    caps = CapabilitiesDefinition.model_validate({"submittable": True, "submission": {"destination": "entries", "kind": "signup"}})
    assert (caps.submission.destination, caps.submission.kind) == ("entries", "signup")


@pytest.mark.parametrize("bad", [{"destination": "inbox"}, {"kind": "newsletter"}, {"destination": None}])
def test_an_unknown_destination_or_kind_is_refused_on_save(db_session, site, bad):
    repo = EntryTypesRepository(db_session, site.gid)
    with pytest.raises(HTTPException) as e:
        repo.update(site.types.contact.id, {"capabilities": {"submittable": True, "submission": bad}})
    assert e.value.status_code == 400


def test_the_entry_type_api_stores_and_returns_the_settings_as_written(site):
    client = _client(site, WorkspaceRole.ADMIN)
    body = {"capabilities": {"submittable": True, "submission": {"destination": "entries", "kind": "message", "matchField": "email"}}}
    res = client.patch(f"{API}/entry-types/{site.types.contact.id}", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["capabilitiesJson"]["submission"]["destination"] == "entries"
    bad = {"capabilities": {"submittable": True, "submission": {"destination": "x"}}}
    assert client.patch(f"{API}/entry-types/{site.types.contact.id}", json=bad).status_code in (400, 422)


# ── what makes a type internal ──────────────────────────────────────────────────────────────────────────────────


def test_a_form_is_internal_only_by_the_flag_not_by_its_destination():
    def t(caps, slug="x"):
        return SimpleNamespace(slug=slug, capabilities_json=caps)

    audience = {"submittable": True, "submission": {"destination": "audience"}}
    assert is_listed_type(t(audience)) is True  # the destination doesn't unlist: `listed` is its own switch
    assert is_listed_type(t({**audience, "listed": False})) is False
    assert is_listed_type(t({**audience, "listed": True})) is True  # an Audience form switched to listed
    assert is_listed_type(t({"submittable": True})) is True
    assert is_listed_type(t({"submittable": True, "submission": {"destination": "entries"}, "listed": False})) is False
    assert is_listed_type(t(None)) is True and is_listed_type(None) is True
    assert submission_destination(t({"submittable": True})) == "audience" and submission_destination(t({})) is None
    assert (
        submission_kind(t({"submittable": True, "submission": {"kind": "signup"}})) == "signup"
        and submission_kind(t({"submittable": True})) == "message"
    )


def test_the_unlisted_ids_are_the_flagged_forms_not_the_content_forms(site):
    ids = set(unlisted_type_ids(site.session, site.gid))
    t = site.types
    assert ids == {t.contact.id, t.workshop.id, t.newsletter.id}


# ── choosing the destination sets `listed` (a default), which is then its own switch ──────────────────────────────


def _make(site, slug, caps):
    return EntryTypesRepository(site.session, site.gid).create({"name": slug.title(), "slug": slug, "capabilities": caps})


def _listed(site, type_id):
    site.session.expire_all()
    return site.session.get(EntryTypes, type_id).capabilities_json.get("listed", True)


def test_a_new_form_defaults_to_the_audience_and_is_unlisted(site):
    assert _listed(site, _make(site, "enquiry", {"submittable": True, "publishable": False}).id) is False
    assert _listed(site, _make(site, "enq2", {"submittable": True, "submission": {"destination": "audience"}}).id) is False
    assert _listed(site, _make(site, "praise", {"submittable": True, "submission": {"destination": "entries"}}).id) is True
    assert _listed(site, _make(site, "plain", {"publishable": True, "submittable": False}).id) is True  # not a form: untouched
    assert _listed(site, _make(site, "hand", {"submittable": True, "listed": True}).id) is True  # said so itself: respected


def test_switching_the_destination_sets_listed_and_the_switch_can_then_be_flipped_alone(site):
    repo = EntryTypesRepository(site.session, site.gid)
    contact = site.types.contact
    repo.update(contact.id, {"capabilities": _caps(listed=False, destination="entries")})  # entries, listed left as it was: set
    assert _listed(site, contact.id) is True
    repo.update(contact.id, {"capabilities": _caps(listed=True, destination="audience")})
    assert _listed(site, contact.id) is False
    repo.update(contact.id, {"capabilities": _caps(listed=True, destination="audience")})  # only `listed` changes: it is respected
    assert _listed(site, contact.id) is True
    repo.update(contact.id, {"capabilities": _caps(listed=True, destination="audience", successMessage="Thanks")})  # destination unchanged
    assert _listed(site, contact.id) is True
    repo.update(contact.id, {"capabilities": _caps(destination="entries")})  # no `listed` in the request at all
    assert _listed(site, contact.id) is True
    repo.update(contact.id, {"capabilities": _caps(listed=False, destination="entries")})  # changed alongside the destination: respected
    assert _listed(site, contact.id) is False


def test_a_type_that_stops_being_an_audience_form_is_listed_again(site):
    repo = EntryTypesRepository(site.session, site.gid)
    repo.update(site.types.workshop.id, {"capabilities": {"publishable": False, "submittable": False, "listed": False}})
    assert _listed(site, site.types.workshop.id) is True
    repo.update(site.types.note.id, {"capabilities": {"submittable": True}})  # an ordinary type made a form: an Audience form, unlisted
    assert _listed(site, site.types.note.id) is False


def test_a_listed_audience_form_shows_in_both_audience_and_the_content_lists(site, filled):
    repo = EntryTypesRepository(site.session, site.gid)
    c = _client(site)
    assert filled.contact.id not in {e["id"] for e in c.get(f"{API}/entries").json()}
    repo.update(site.types.contact.id, {"capabilities": _caps(listed=True, destination="audience")})  # only the switch
    site.session.expire_all()
    content = {e["id"] for e in c.get(f"{API}/entries").json()}
    assert str(filled.contact.id) in content  # among the content …
    assert str(filled.contact.id) in _ids(c.get(f"{P}/submissions"))  # … and still in Audience
    assert c.get(f"{API}/entries/counts").json()["inbox"] == 3  # the testimonial, the note and the contact entry
    assert {f["slug"] for f in c.get(f"{P}/summary").json()["submissions"]["forms"]} == {"contact", "workshop"}  # the summary doesn't care
    flagged, events = site.submit(site.types.contact, {"name": "More", "email": "m@x.test", "message": "x"})  # the flow is unchanged
    assert flagged.status == "inbox" and "form_submission_received" in [n for n, _ in events]
    assert {e.id for e in run_query(site.session, site.gid, {"entry_type": "contact"}, limit=50).rows} >= {filled.contact.id, flagged.id}


@pytest.fixture
def filled(site):
    """One entry of each type, the forms' ones made by real submissions."""
    t = site.types
    entries = SimpleNamespace(
        contact=site.submit(t.contact, {"name": "Ann", "email": "ann@x.test", "message": "Hello there"})[0],
        workshop=site.submit(t.workshop, {"name": "Bo", "email": "bo@x.test", "message": "A workshop?"})[0],
        testimonial=site.submit(t.testimonial, {"name": "Cy", "email": "cy@x.test", "message": "Great"})[0],
        newsletter=site.submit(t.newsletter, {"email": "dee@x.test"})[0],
    )
    svc = EntryService(site.session, site.gid, integration_id="test")
    entries.note = svc.create({"entry_type_id": t.note.id, "title": "A note", "slug": "a-note", "status": "inbox", "data_json": {}})
    site.session.commit()
    return SimpleNamespace(site=site, **vars(entries))


def test_submissions_land_as_before_an_inbox_entry_with_the_verdict_and_source(site, filled):
    for e in (filled.contact, filled.workshop, filled.newsletter, filled.testimonial):
        assert e.status == "inbox"
    flagged, events = site.submit(site.types.contact, {"name": "Spam", "email": "s@example.com", "message": "buy"}, flag=True)
    assert flagged.status == "needs_review"
    sub = flagged.metadata_json["submission"]
    assert sub["review_reasons"] == ["blocked_domain:example.com"] and sub["ip_address"] == "203.0.113.77"
    assert sub["user_agent"] == "pytest-agent" and sub["referer"] == "https://site.test/contact"
    names = [n for n, _ in events]
    assert "entry_created" in names and "form_submission_received" in names  # the triggers still fire for an internal type
    doc = next(d for n, d in events if n == "form_submission_received")
    assert doc.flagged is True and doc.form_name == "Contact"


def test_a_repeat_from_the_same_person_still_folds_into_one_entry(site, filled):
    again, events = site.submit(site.types.newsletter, {"email": "dee@x.test"})
    assert again.id == filled.newsletter.id and again.metadata_json["submission"]["submission_count"] == 2
    assert next(d for n, d in events if n == "form_submission_received").duplicate is True


def test_internal_submissions_leave_every_list_count_and_the_index_but_a_named_query_finds_them(site, filled):
    s = site.session
    client = _client(site)
    listed = {e["title"] for e in client.get(f"{API}/entries").json()}
    assert listed == {filled.testimonial.title, "A note"}
    assert client.get(f"{API}/entries/counts").json()["inbox"] == 2  # the testimonial and the note
    assert count_by_status(s, site.gid)["total"] == 2
    assert inbox_count(s, site.gid) == 2
    # the default answer of a query leaves them out; naming the type (Buttondown's signup workflow does) finds them
    assert {e.id for e in run_query(s, site.gid, {"status": "inbox"}, limit=50).rows} == {filled.testimonial.id, filled.note.id}
    assert {e.id for e in run_query(s, site.gid, {"entry_type": "newsletter", "status": "inbox"}, limit=50).rows} == {filled.newsletter.id}
    assert {e.id for e in run_query(s, site.gid, {"entry_type": "contact"}, limit=50).rows} == {filled.contact.id}
    assert {e.id for e in run_query(s, site.gid, {"entries": [filled.workshop.slug]}, limit=50).rows} == {filled.workshop.id}
    # publishing and the index
    assert is_publishable_type(site.types.contact) is False and is_publishable_type(site.types.testimonial) is False  # publishable: false anyway
    from marvin.services.ai.embeddings_registry import _entry_listed

    assert _entry_listed(filled.contact) is False and _entry_listed(filled.newsletter) is False and _entry_listed(filled.testimonial) is True
    for e in (filled.contact, filled.testimonial):
        e.status = "published"
    site.session.commit()
    assert REGISTRY["entry"].content_ok(filled.contact) is False and REGISTRY["entry"].content_ok(filled.testimonial) is True  # never indexed
    # dashboard
    rows = {r.slug: r for r in dashboard.by_type_status(s, site.gid)}
    assert {"testimonial", "note"} <= set(rows) and not ({"contact", "workshop", "newsletter"} & set(rows))


def test_smart_collections_hold_content_forms_but_not_audience_forms(site, filled):
    inbox = {"statuses": ["inbox"]}
    assert matches_rules(site.session.get(Entries, filled.contact.id), inbox) is False
    assert matches_rules(site.session.get(Entries, filled.testimonial.id), inbox) is True
    assert matches_rules(site.session.get(Entries, filled.contact.id), {"entry_types": ["contact"]}) is True  # naming the type still holds it
    coll = Collections(session=site.session, group_id=site.gid, name="Inbox", slug="inbox-x", is_smart=True, smart_rules=inbox)
    site.session.add(coll)
    site.session.commit()
    sync_collection(site.session, site.gid, coll)
    site.session.commit()
    held = {r[0] for r in site.session.query(EntryCollections.entry_id).filter_by(collection_id=coll.id)}
    assert held == {filled.testimonial.id, filled.note.id}


def test_the_trash_still_lists_and_counts_a_trashed_submission(site, filled):
    svc = EntryService(site.session, site.gid, integration_id="test")
    svc.trash(filled.contact.id)
    site.session.commit()
    assert filled.contact.id in entry_trash.trashed_ids(site.session, site.gid)


def test_changing_a_forms_destination_moves_its_entries_in_and_out_of_the_collections_at_once(site, filled):
    inbox = Collections(session=site.session, group_id=site.gid, name="Inbox", slug="inbox-y", is_smart=True, smart_rules={"statuses": ["inbox"]})
    site.session.add(inbox)
    site.session.commit()
    sync_collection(site.session, site.gid, inbox)
    site.session.commit()

    def held():
        return {r[0] for r in site.session.query(EntryCollections.entry_id).filter_by(collection_id=inbox.id)}

    assert filled.contact.id not in held() and filled.testimonial.id in held()
    repo = EntryTypesRepository(site.session, site.gid)
    site.session.add(AIEmbeddingModel(session=site.session, group_id=site.gid, entity_type="entry", entity_id=filled.testimonial.id,
                                      chunk_index=0, chunk_text="t", embedding=[1.0, 0.0], model_id="m", dimensions=2))  # fmt: skip
    site.session.commit()
    repo.update(site.types.testimonial.id, {"capabilities": _caps(destination="audience")})  # now a message form
    assert filled.testimonial.id not in held()
    assert site.session.query(AIEmbeddingModel).filter_by(entity_id=filled.testimonial.id).count() == 0
    repo.update(site.types.contact.id, {"capabilities": _caps(destination="entries")})  # now a content form
    assert filled.contact.id in held()


# ── the summary ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_summary_lists_only_the_message_forms_that_exist_with_their_new_counts(site, filled):
    site.submit(site.types.contact, {"name": "Spam", "email": "s@x.test", "message": "buy"}, flag=True)
    out = _client(site).get(f"{P}/summary").json()
    forms = out["submissions"]["forms"]
    assert [(f["slug"], f["name"], f["icon"], f["new"]) for f in forms] == [("contact", "Contact", "✉️", 2), ("workshop", "Workshop enquiry", "🛠", 1)]
    assert out["submissions"]["show"] is True and out["submissions"]["new"] == 3
    assert out["signups"]["show"] is True and [f["slug"] for f in out["signups"]["forms"]] == ["newsletter"]  # for phase 2; not a message form
    assert out["can"] == {"act": True, "fullIp": False}


def test_the_summary_draws_nothing_where_no_form_feeds_it(workspace, db_session):  # noqa: F811
    out = _sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/summary").json()
    assert out["submissions"] == {"show": False, "new": 0, "forms": []} and out["signups"] == {"show": False, "forms": []}
    _type(db_session, workspace.gid, "testimonial", "Testimonial", _caps(destination="entries"))
    _type(db_session, workspace.gid, "note", "Note", None)
    out = _sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/summary").json()
    assert out["submissions"]["show"] is False and out["signups"]["show"] is False
    _type(db_session, workspace.gid, "enquiry", "Enquiry", {"submittable": True})  # a form with nothing in it yet is still a form
    out = _sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/summary").json()
    assert [f["slug"] for f in out["submissions"]["forms"]] == ["enquiry"] and out["submissions"]["new"] == 0


def test_a_handled_submission_is_not_counted_and_a_signup_form_is_not_a_message_form(site, filled):
    EntryService(site.session, site.gid, integration_id="test").set_status(filled.workshop.id, "archived")
    out = _client(site).get(f"{P}/summary").json()["submissions"]
    assert {f["slug"]: f["new"] for f in out["forms"]} == {"contact": 1, "workshop": 0}


def test_the_dashboard_counts_audience_submissions_apart_from_the_inbox(site, filled):
    res = _client(site).get(f"{API}/stats/dashboard")
    assert res.status_code == 200, res.text
    att = res.json()["attention"]
    assert att["audienceNew"] == 2 and att["inbox"] == 2  # contact + workshop; the testimonial and the note
    assert _sign_in(site.ws, WorkspaceRole.VIEWER).get(f"{API}/stats/dashboard").json()["attention"]["audienceNew"] == 0


# ── the list ────────────────────────────────────────────────────────────────────────────────────────────────────


def _ids(res):
    return [i["id"] for i in res.json()["items"]]


def test_the_list_is_the_message_forms_submissions_newest_first_with_labelled_fields(site, filled):
    for entry, hours in ((filled.contact, 5), (filled.workshop, 1)):
        _back_date(site, entry, hours=hours)
    res = _client(site).get(f"{P}/submissions")
    assert res.status_code == 200, res.text
    body = res.json()
    assert _ids(res) == [str(filled.workshop.id), str(filled.contact.id)]  # the content form and the signup form aren't here
    assert (body["total"], body["new"], body["limit"], body["offset"]) == (2, 2, 50, 0)
    first = body["items"][0]
    assert first["form"]["slug"] == "workshop" and first["state"] == "new" and first["status"] == "inbox"
    assert first["fields"][0] == {"key": "name", "label": "Your name", "type": "text", "value": "Bo"}
    assert [f["key"] for f in first["fields"]] == ["name", "email", "message"]
    assert first["path"] == f"/workspace/entries/{filled.workshop.id}"
    assert first["verdict"] == {"flagged": False, "reasons": []}
    assert (
        first["source"]["userAgent"] == "pytest-agent"
        and first["source"]["referrer"] == "https://site.test/contact"
        and first["source"]["count"] == 1
    )


def test_the_list_filters_by_form_status_text_and_date_and_pages(site, filled):
    flagged, _ = site.submit(site.types.contact, {"name": "Spam", "email": "s@x.test", "message": "cheap pills"}, flag=True)
    EntryService(site.session, site.gid, integration_id="test").set_status(filled.workshop.id, "archived")
    for entry, days in ((filled.contact, 10), (filled.workshop, 5), (flagged, 0)):
        _back_date(site, entry, days=days)
    c = _client(site)

    def ids(**params):
        return _ids(c.get(f"{P}/submissions", params=params))

    assert ids(form="contact") == [str(flagged.id), str(filled.contact.id)]
    assert ids(form="workshop") == [str(filled.workshop.id)]
    assert ids(form="testimonial") == [] and ids(form="nope") == []
    assert ids(status="new") == [str(filled.contact.id)]
    assert ids(status="suspicious") == [str(flagged.id)]
    assert ids(status="handled") == [str(filled.workshop.id)]
    assert set(ids(status=["new", "suspicious"])) == {str(flagged.id), str(filled.contact.id)}
    assert ids(q="pills") == [str(flagged.id)]
    assert ids(q="BO@X.TEST") == [str(filled.workshop.id)]  # case-insensitive, in a field value
    assert ids(q="ann") == [str(filled.contact.id)]  # in the title too
    assert ids(q="zzz") == []
    since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    assert ids(since=since) == [str(flagged.id), str(filled.workshop.id)]
    until = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    assert ids(until=until) == [str(filled.contact.id)]
    page = c.get(f"{P}/submissions", params={"limit": 2, "offset": 1}).json()
    assert [i["id"] for i in page["items"]] == [str(filled.workshop.id), str(filled.contact.id)] and page["total"] == 3
    assert c.get(f"{P}/submissions", params={"limit": 0}).status_code == 422
    assert c.get(f"{P}/submissions", params={"status": "bogus"}).status_code == 422


def test_a_suspicious_submission_carries_the_protections_reasons(site, filled):
    flagged, _ = site.submit(site.types.contact, {"name": "Spam", "email": "s@x.test", "message": "x"}, flag=True)
    item = _client(site).get(f"{P}/submissions/{flagged.id}").json()["submission"]
    assert item["state"] == "suspicious" and item["verdict"] == {"flagged": True, "reasons": ["blocked_domain:example.com"]}


def test_a_status_a_workflow_set_shows_as_handled_and_is_not_lost(site, filled):
    EntryService(site.session, site.gid, integration_id="test").set_status(filled.contact.id, "approved")
    item = _client(site).get(f"{P}/submissions/{filled.contact.id}").json()["submission"]
    assert (item["state"], item["status"]) == ("handled", "approved")
    assert _ids(_client(site).get(f"{P}/submissions", params={"status": "handled"})) == [str(filled.contact.id)]


def test_a_repeat_is_counted_on_the_source(site, filled):
    site.session.get(EntryTypes, site.types.contact.id).capabilities_json = _caps(matchField="email")
    site.session.commit()
    site.submit(site.types.contact, {"name": "Ann", "email": "ann@x.test", "message": "again"})
    entry = site.session.get(Entries, filled.contact.id)
    assert entry.metadata_json["submission"]["submission_count"] == 2
    src = _client(site).get(f"{P}/submissions/{filled.contact.id}").json()["submission"]["source"]
    assert src["count"] == 2 and src["lastReceivedAt"]


# ── roles and the IP ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR])
def test_below_editor_nothing_is_readable_or_actionable(site, filled, role):
    c = _client(site, role)
    sid = filled.contact.id
    for method, path in (
        ("GET", f"{P}/summary"),
        ("GET", f"{P}/submissions"),
        ("GET", f"{P}/submissions/{sid}"),
        ("POST", f"{P}/submissions/{sid}/handled"),
        ("POST", f"{P}/submissions/{sid}/reopen"),
        ("DELETE", f"{P}/submissions/{sid}"),
    ):
        assert c.request(method, path).status_code == 403, (method, path)
    assert _status(site, sid) == "inbox"  # nothing happened


def test_an_editor_sees_the_ip_masked_and_an_admin_whole(site, filled):
    editor = _client(site, WorkspaceRole.EDITOR).get(f"{P}/submissions/{filled.contact.id}").json()["submission"]["source"]
    assert editor["ip"] == "203.0.113.x" and editor["ipMasked"] is True
    for role in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        full = _client(site, role).get(f"{P}/submissions/{filled.contact.id}").json()["submission"]["source"]
        assert full["ip"] == "203.0.113.77" and full["ipMasked"] is False
    listed = _client(site, WorkspaceRole.EDITOR).get(f"{P}/submissions").json()["items"]
    assert all(i["source"]["ip"] == "203.0.113.x" for i in listed)
    assert _client(site, WorkspaceRole.ADMIN).get(f"{P}/summary").json()["can"]["fullIp"] is True


def test_masking_ipv4_ipv6_and_junk():
    assert audience.mask_ip("203.0.113.77") == "203.0.113.x"
    assert audience.mask_ip("2001:db8:85a3::8a2e:370:7334") == "2001:0db8:85a3::x"
    assert audience.mask_ip("not an ip") == "hidden" and audience.mask_ip(None) is None and audience.mask_ip("") is None


def test_a_submission_with_no_client_info_has_an_empty_source(site):
    entry = EntryService(site.session, site.gid, integration_id="test").create(
        {"entry_type_id": site.types.contact.id, "title": "bare", "slug": "bare", "status": "inbox", "data_json": {"name": "Zed"}}
    )
    src = _client(site).get(f"{P}/submissions/{entry.id}").json()["submission"]["source"]
    assert src["ip"] is None and src["ipMasked"] is False and src["userAgent"] is None and src["count"] == 1


# ── actions ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_mark_handled_then_reopen(site, filled):
    c = _client(site)
    sid = filled.contact.id
    handled = c.post(f"{P}/submissions/{sid}/handled")
    assert handled.status_code == 200 and handled.json()["submission"]["state"] == "handled"
    assert _status(site, sid) == "archived"
    assert {f["slug"]: f["new"] for f in c.get(f"{P}/summary").json()["submissions"]["forms"]}["contact"] == 0
    assert c.post(f"{P}/submissions/{sid}/handled").status_code == 200  # again: nothing changes
    reopened = c.post(f"{P}/submissions/{sid}/reopen")
    assert reopened.json()["submission"]["state"] == "new" and _status(site, sid) == "inbox"


def test_not_spam_clears_a_suspicious_one_to_new(site, filled):
    flagged, _ = site.submit(site.types.contact, {"name": "Maybe", "email": "m@x.test", "message": "hm"}, flag=True)
    res = _client(site).post(f"{P}/submissions/{flagged.id}/reopen")
    assert res.json()["submission"]["state"] == "new" and _status(site, flagged.id) == "inbox"


def test_delete_moves_it_to_the_trash_where_it_can_be_restored(site, filled):
    c = _client(site)
    sid = filled.contact.id
    res = c.delete(f"{P}/submissions/{sid}")
    assert res.status_code == 200 and res.json() == {"submission": None}
    assert _status(site, sid) == "trashed"
    assert str(sid) not in _ids(c.get(f"{P}/submissions"))
    assert sid in entry_trash.trashed_ids(site.session, site.gid)
    assert c.get(f"{P}/submissions/{sid}").status_code == 404 and c.post(f"{P}/submissions/{sid}/handled").status_code == 404
    EntryService(site.session, site.gid, integration_id="test").restore_from_trash(sid)
    assert str(sid) in _ids(c.get(f"{P}/submissions"))


def test_an_action_changes_the_entry_the_way_the_editor_does_so_workflows_see_it(site, filled, monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        "marvin.services.event_bus_service.event_bus_service.EventBusService.dispatch", lambda self, **kw: dispatched.append(kw["event_type"].name)
    )
    _client(site).post(f"{P}/submissions/{filled.contact.id}/handled")
    assert {"entry_updated", "entry_archived"} <= set(dispatched)


def test_only_a_message_form_submission_of_this_workspace_can_be_acted_on(site, filled, workspace, db_session):  # noqa: F811
    c = _client(site)
    for entry in (filled.testimonial, filled.newsletter, filled.note):  # a content form, a signup form, an ordinary entry
        assert c.get(f"{P}/submissions/{entry.id}").status_code == 404
        assert c.post(f"{P}/submissions/{entry.id}/handled").status_code == 404
        assert c.delete(f"{P}/submissions/{entry.id}").status_code == 404
    assert _status(site, filled.testimonial.id) == "inbox"
    assert c.get(f"{P}/submissions/{uuid.uuid4()}").status_code == 404


def test_other_workspaces_submissions_are_out_of_reach(site, filled):
    group = Groups(session=site.session, name="other-ws-aud", slug="other-ws-aud")
    site.session.add(group)
    site.session.flush()
    other_gid = group.id
    t = _type(site.session, other_gid, "contact", "Contact", {"submittable": True})
    e = EntryService(site.session, other_gid, integration_id="test").create(
        {"entry_type_id": t.id, "title": "theirs", "slug": "theirs", "status": "inbox", "data_json": {"name": "Them"}}
    )
    try:
        c = _client(site)
        assert c.get(f"{P}/submissions/{e.id}").status_code == 404
        assert c.post(f"{P}/submissions/{e.id}/handled").status_code == 404
        assert str(e.id) not in _ids(c.get(f"{P}/submissions"))
        assert _status(site, e.id) == "inbox"
    finally:
        from marvin.services.group.group_purge import purge_group_dependents

        site.session.rollback()
        purge_group_dependents(site.session, other_gid)
        site.session.query(Groups).filter(Groups.id == other_gid).delete()
        site.session.commit()


def test_the_openapi_describes_the_audience_routes():
    spec = TestClient(app).get("/openapi.json").json()
    paths = {p for p in spec["paths"] if "/groups/audience" in p}
    assert {p.split("/groups/audience")[1] for p in paths} == {
        "/summary",
        "/submissions",
        "/submissions/{submission_id}",
        "/submissions/{submission_id}/handled",
        "/submissions/{submission_id}/reopen",
    }
    assert json.dumps(spec).count("AudienceSubmission") > 0
