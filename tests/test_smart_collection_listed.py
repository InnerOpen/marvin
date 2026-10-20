"""The smart-collection ``listed`` rule (``any`` | ``listed`` | ``unlisted``): which kind of entry type a smart collection gathers.

``any`` (the default) is today's behaviour: listed types, plus an internal type only when the rules name it. ``listed`` keeps only
listed types (naming an internal one matches nothing). ``unlisted`` keeps only internal types, all of them without naming each, and
combines with the other rules. See services/collections/smart_collections.py and services/entry_listing.py.

Built on the fixtures of test_internal_entry_types: a listed ``note`` type (note_draft / note_pub / note_inbox) and two internal types,
``social-auto-reply`` (rule_draft / rule_pub / rule_inbox) and ``social-reply-log`` (iglog_pub).
"""

import asyncio

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from marvin.db.models.groups.groups import Groups  # noqa: E402
from marvin.db.models.platform.collections import Collections  # noqa: E402
from marvin.db.models.platform.entries import Entries  # noqa: E402
from marvin.db.models.platform.entry_collections import EntryCollections  # noqa: E402
from marvin.db.models.platform.entry_tags import EntryTags  # noqa: E402
from marvin.db.models.platform.entry_types import EntryTypes  # noqa: E402
from marvin.db.models.platform.tags import Tags  # noqa: E402
from marvin.repos.platform.entry_types import EntryTypesRepository  # noqa: E402
from marvin.routes.publish import publishing_controller as pub  # noqa: E402
from marvin.schemas.platform.collections import CollectionCreate, CollectionUpdate, SmartRulesPreviewRequest  # noqa: E402
from marvin.services.collections.smart_collections import (  # noqa: E402
    has_rules,
    ignored_keys,
    matches_rules,
    matching_items,
    sync_collection,
    sync_entry,
)
from marvin.services.entry_listing import hidden_type_ids, listed_mode  # noqa: E402
from tests import test_internal_entry_types as base  # noqa: E402
from tests.test_internal_entry_types import API, NOTES, _entry  # noqa: E402

content, client = base.content, base.client  # the fixtures of the internal-types tests, reused as they are
ws, nets, _types = base.ws, base.nets, base._types

RULES = {"social-auto-reply": {"rule_draft", "rule_pub", "rule_inbox"}, "social-reply-log": {"iglog_pub"}}
INTERNAL = {"rule_draft", "rule_pub", "rule_inbox", "iglog_pub"}
ALL = NOTES | INTERNAL
KEYS = sorted(ALL)


def _slugs(content, rules) -> set[str]:
    return {e.slug for e in matching_items(content.session, content.gid, rules)}


def _tag(content, slug, *keys):
    tag = Tags(session=content.session, group_id=content.gid, name=slug, slug=slug)
    content.session.add(tag)
    content.session.flush()
    for key in keys:
        content.session.add(EntryTags(entry_id=getattr(content, key).id, tag_id=tag.id))
    content.session.commit()


def _smart(content, slug, rules, **extra) -> Collections:
    collection = Collections(session=content.session, group_id=content.gid, name=slug, slug=slug, is_smart=True, smart_rules=rules, **extra)
    content.session.add(collection)
    content.session.commit()
    return collection


def _members(content, collection) -> set[str]:
    content.session.expire_all()
    rows = content.session.query(Entries.slug).join(EntryCollections, EntryCollections.entry_id == Entries.id)
    return {r[0] for r in rows.filter(EntryCollections.collection_id == collection.id)}


def _set_listed(content, slug, listed):
    """Flip a type's `listed` through the repository, the way the entry type editor does (it syncs the type's entries)."""
    repo = EntryTypesRepository(content.session, content.gid)
    row = content.session.query(EntryTypes).filter_by(group_id=content.gid, slug=slug).one()
    repo.update(row.id, {"capabilities": {**(row.capabilities_json or {}), "listed": listed}})
    content.session.expire_all()


# ── each value ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_any_is_the_default_and_keeps_todays_behaviour(content):
    status = {"statuses": ["published"]}
    for rules in (status, {**status, "listed": "any"}, {**status, "listed": None}):
        assert _slugs(content, rules) == {"note_pub"}  # an internal entry stays out unless its type is named
    assert _slugs(content, {"entry_types": ["social-auto-reply"], "listed": "any"}) == RULES["social-auto-reply"]
    assert _slugs(content, {"entry_types": ["social-auto-reply"]}) == RULES["social-auto-reply"]
    assert listed_mode({}) == listed_mode({"listed": None}) == listed_mode({"listed": "any"}) == "any"


def test_listed_keeps_only_entries_of_listed_types(content):
    assert _slugs(content, {"statuses": ["published", "draft"], "listed": "listed"}) == {"note_pub", "note_draft"}
    assert _slugs(content, {"entry_types": ["note"], "listed": "listed"}) == NOTES
    # as under `any`, a listed collection never holds an internal entry, whatever else matches (`match: any` included)
    assert _slugs(content, {"statuses": ["draft"], "entry_types": ["note"], "match": "any", "listed": "listed"}) == {
        "note_draft",
        "note_inbox",
        "note_pub",
    }


def test_naming_an_internal_type_under_listed_matches_nothing(content):
    assert _slugs(content, {"entry_types": ["social-auto-reply"], "listed": "listed"}) == set()
    assert _slugs(content, {"entry_types": ["social-auto-reply", "social-reply-log"], "statuses": ["published"], "listed": "listed"}) == set()
    # naming a listed type beside it still gathers that one, and only that one
    assert _slugs(content, {"entry_types": ["social-auto-reply", "note"], "match": "any", "listed": "listed"}) == NOTES


def test_unlisted_gathers_every_internal_entry_without_naming_the_types(content):
    assert _slugs(content, {"listed": "unlisted"}) == INTERNAL
    assert _slugs(content, {"listed": "unlisted", "match": "any"}) == INTERNAL
    assert _slugs(content, {"listed": "unlisted", "entry_types": ["social-auto-reply"]}) == RULES["social-auto-reply"]  # naming still narrows
    assert _slugs(content, {"listed": "unlisted", "entry_types": ["note"]}) == set()  # a listed type is never unlisted


def test_listed_alone_is_not_a_rule_but_unlisted_alone_is(content):
    assert _slugs(content, {"listed": "listed"}) == set()  # it narrows; on its own it must not sweep in the workspace
    assert _slugs(content, {"listed": "any"}) == set()
    assert has_rules({"listed": "unlisted"}) is True
    assert has_rules({"listed": "listed"}) is False and has_rules({"listed": "any", "match": "any"}) is False
    assert has_rules({"listed": "listed", "statuses": ["draft"]}) is True


# ── combined with the other rules ────────────────────────────────────────────────────────────────────────────────


def test_unlisted_combines_with_status_rules(content):
    assert _slugs(content, {"listed": "unlisted", "statuses": ["draft"]}) == {"rule_draft"}
    assert _slugs(content, {"listed": "unlisted", "statuses": ["published", "inbox"]}) == {"rule_pub", "rule_inbox", "iglog_pub"}
    assert _slugs(content, {"listed": "listed", "statuses": ["inbox"]}) == {"note_inbox"}


def test_unlisted_combines_with_tag_rules(content):
    _tag(content, "pinned", "rule_pub", "note_pub", "iglog_pub")
    assert _slugs(content, {"listed": "unlisted", "tags": ["pinned"]}) == {"rule_pub", "iglog_pub"}
    assert _slugs(content, {"listed": "listed", "tags": ["pinned"]}) == {"note_pub"}
    assert _slugs(content, {"listed": "unlisted", "tags": ["pinned"], "statuses": ["published"], "entry_types": ["social-auto-reply"]}) == {
        "rule_pub"
    }
    assert _slugs(content, {"tags": ["pinned"]}) == {"note_pub"}  # `any`: internal entries stay out


def test_the_gate_narrows_whatever_match_is(content):
    _tag(content, "pinned", "rule_inbox", "note_inbox")
    anything = {"statuses": ["draft"], "tags": ["pinned"], "match": "any"}
    assert _slugs(content, {**anything, "listed": "unlisted"}) == {"rule_draft", "rule_inbox"}  # draft OR pinned, among internal entries
    assert _slugs(content, {**anything, "listed": "listed"}) == {"note_draft", "note_inbox"}


def test_a_trashed_entry_is_out_unless_the_rules_ask_for_the_trash(content):
    _entry(content, "rule_pub").status = "trashed"
    content.session.commit()
    assert "rule_pub" not in _slugs(content, {"listed": "unlisted"})
    assert _slugs(content, {"listed": "unlisted", "statuses": ["trashed"]}) == {"rule_pub"}
    assert _slugs(content, {"listed": "listed", "statuses": ["trashed"]}) == set()


def test_an_unrecognised_value_matches_nothing_rather_than_widening(content):
    for bad in ("unlist", "", "LISTED", True, 1, ["listed"]):
        assert listed_mode({"listed": bad}) is None
        assert matches_rules(_entry(content, "note_pub"), {"statuses": ["published"], "listed": bad}) is False
        assert matches_rules(_entry(content, "rule_pub"), {"statuses": ["published"], "listed": bad}) is False


def test_the_rule_is_for_entries_only(content):
    assert ignored_keys({"listed": "unlisted"}, "asset") == ["listed"]
    assert ignored_keys({"listed": "unlisted"}, "entry") == []
    assert has_rules({"listed": "unlisted"}, "asset") is False


# ── the resync, and the collection's own listing ─────────────────────────────────────────────────────────────────


def test_resync_materialises_each_value(content):
    every = {"statuses": ["draft", "published", "inbox"]}
    cases = {
        "c-any": ({**every}, NOTES),
        "c-listed": ({**every, "listed": "listed"}, NOTES),
        "c-unlisted": ({**every, "listed": "unlisted"}, INTERNAL),
        "c-unlisted-all": ({"listed": "unlisted"}, INTERNAL),
        "c-named": ({"entry_types": ["social-auto-reply"]}, RULES["social-auto-reply"]),
        "c-named-listed": ({"entry_types": ["social-auto-reply"], "listed": "listed"}, set()),
    }
    made = {slug: _smart(content, slug, rules) for slug, (rules, _) in cases.items()}
    for collection in made.values():
        sync_collection(content.session, content.gid, collection)
    content.session.commit()
    for slug, (_, expected) in cases.items():
        assert _members(content, made[slug]) == expected, slug
    # a second pass changes nothing, and a changed rule re-evaluates
    assert sync_collection(content.session, content.gid, made["c-listed"]) == 0
    made["c-listed"].smart_rules = {**every, "listed": "unlisted"}
    sync_collection(content.session, content.gid, made["c-listed"])
    content.session.commit()
    assert _members(content, made["c-listed"]) == INTERNAL


def test_saving_the_rules_through_the_api_resyncs_and_the_page_lists_the_members(content, client):
    created = client.post(f"{API}/collections", json={"name": "Hidden", "isSmart": True, "smartRules": {"listed": "unlisted"}})
    assert created.status_code in (200, 201), created.text
    cid = created.json()["id"]
    listing = client.get(f"{API}/collections/{cid}/entries")
    assert {e["slug"] for e in listing.json()} == INTERNAL  # the page doesn't hide the internal types it was asked to gather
    patched = client.patch(f"{API}/collections/{cid}", json={"smartRules": {"listed": "unlisted", "statuses": ["draft"]}})
    assert patched.status_code == 200, patched.text
    assert {e["slug"] for e in client.get(f"{API}/collections/{cid}/entries").json()} == {"rule_draft"}
    listed_only = client.patch(f"{API}/collections/{cid}", json={"smartRules": {"listed": "listed", "statuses": ["draft"]}})
    assert listed_only.status_code == 200
    assert {e["slug"] for e in client.get(f"{API}/collections/{cid}/entries").json()} == {"note_draft"}


def test_the_collection_page_hides_internal_types_a_listed_rule_names_and_keeps_those_unlisted_gathers(content):
    named_listed = _smart(content, "nl", {"entry_types": ["social-auto-reply"], "listed": "listed"})
    named = _smart(content, "n", {"entry_types": ["social-auto-reply"]})
    unlisted = _smart(content, "u", {"listed": "unlisted"})
    plain = _smart(content, "p", {"statuses": ["published"]})
    hidden = lambda c: set(hidden_type_ids(content.session, content.gid, c))  # noqa: E731
    internal_ids = {t.id for t in content.session.query(EntryTypes).filter_by(group_id=content.gid) if t.slug.startswith("social-")}
    assert hidden(named_listed) == internal_ids  # naming doesn't un-hide a type under `listed`
    assert hidden(plain) == internal_ids
    assert hidden(unlisted) == set()
    assert len(hidden(named)) == 1  # `any`: the named type is un-hidden, the other stays hidden


def test_the_preview_counts_the_entries_a_save_would_hold(content, client):
    res = client.post(f"{API}/collections/preview", json={"targetType": "entry", "smartRules": {"listed": "unlisted", "statuses": ["published"]}})
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 2 and res.json()["note"] is None
    only_listed = client.post(f"{API}/collections/preview", json={"targetType": "entry", "smartRules": {"listed": "listed"}})
    assert only_listed.json()["total"] == 0 and "No rules" in only_listed.json()["note"]


# ── toggling a type's `listed` flag ──────────────────────────────────────────────────────────────────────────────


def test_toggling_a_type_moves_its_entries_in_and_out_of_the_listed_and_unlisted_collections(content):
    unlisted = _smart(content, "tog-unlisted", {"listed": "unlisted", "statuses": ["draft", "published", "inbox"]})
    listed = _smart(content, "tog-listed", {"listed": "listed", "statuses": ["draft", "published", "inbox"]})
    plain = _smart(content, "tog-any", {"statuses": ["draft", "published", "inbox"]})
    for collection in (unlisted, listed, plain):
        sync_collection(content.session, content.gid, collection)
    content.session.commit()
    assert _members(content, unlisted) == INTERNAL and _members(content, listed) == NOTES and _members(content, plain) == NOTES

    _set_listed(content, "social-auto-reply", True)  # the rule type becomes listed
    assert _members(content, unlisted) == RULES["social-reply-log"]  # its entries leave `unlisted` …
    assert _members(content, listed) == NOTES | RULES["social-auto-reply"]  # … join `listed` …
    assert _members(content, plain) == NOTES | RULES["social-auto-reply"]  # … and the ordinary collections, as a listed type

    _set_listed(content, "social-auto-reply", False)  # and back
    assert _members(content, unlisted) == INTERNAL
    assert _members(content, listed) == NOTES
    assert _members(content, plain) == NOTES


def test_a_type_listed_from_the_start_never_enters_an_unlisted_collection(content):
    unlisted = _smart(content, "tog-u2", {"listed": "unlisted"})
    sync_collection(content.session, content.gid, unlisted)
    content.session.commit()
    note_type = content.session.query(EntryTypes).filter_by(group_id=content.gid, slug="note").one()
    EntryTypesRepository(content.session, content.gid).update(note_type.id, {"capabilities": {"listed": False}})  # a normal type goes internal
    content.session.expire_all()
    assert _members(content, unlisted) == ALL
    for key in NOTES:  # an entry saved later follows the type, through the per-entry sync the event bus runs
        sync_entry(content.session, content.gid, _entry(content, key))
    content.session.commit()
    assert _members(content, unlisted) == ALL


# ── validation ───────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["any", "listed", "unlisted", None])
def test_the_schemas_accept_the_three_values_and_absence(value):
    rules = {"statuses": ["draft"], "listed": value}
    assert CollectionCreate(name="C", is_smart=True, smart_rules=rules).smart_rules == rules
    assert CollectionUpdate(smart_rules=rules).smart_rules == rules
    assert SmartRulesPreviewRequest(smart_rules=rules).smart_rules == rules
    assert CollectionCreate(name="C", is_smart=True, smart_rules={"statuses": ["draft"]}).smart_rules == {"statuses": ["draft"]}
    assert CollectionCreate(name="C").smart_rules is None


@pytest.mark.parametrize("bad", ["internal", "", "Listed", 1, True, ["unlisted"], {"mode": "unlisted"}])
def test_the_schemas_refuse_any_other_value(bad):
    for build in (
        lambda: CollectionCreate(name="C", is_smart=True, smart_rules={"listed": bad}),
        lambda: CollectionUpdate(smart_rules={"listed": bad}),
        lambda: SmartRulesPreviewRequest(smart_rules={"listed": bad}),
    ):
        with pytest.raises(ValidationError) as e:
            build()
        assert "listed" in str(e.value)


def test_the_api_answers_422_for_a_bad_value_and_stores_nothing(content, client):
    created = client.post(f"{API}/collections", json={"name": "Bad", "isSmart": True, "smartRules": {"listed": "sometimes"}})
    assert created.status_code == 422
    assert content.session.query(Collections).filter_by(group_id=content.gid, name="Bad").count() == 0
    ok = _smart(content, "keep", {"listed": "unlisted"})
    assert client.patch(f"{API}/collections/{ok.id}", json={"smartRules": {"listed": "nope"}}).status_code == 422
    content.session.refresh(ok)
    assert ok.smart_rules == {"listed": "unlisted"}
    assert client.post(f"{API}/collections/preview", json={"smartRules": {"listed": 3}}).status_code == 422


# ── the publishing API never serves an internal entry, through such a collection or any other ───────────────────────────────


class _AllowAll:
    """Publishing permissions stub: every permission granted, reading unpublished entries included."""

    def require_permission(self, *_):
        return None

    def require_any_permission(self, *_):
        return None

    def has_permission(self, *_):
        return True


def _publish_ctx(content):
    return (None, content.session.get(Groups, content.gid), _AllowAll())


def _served(content, slug) -> dict:
    ctx = _publish_ctx(content)
    session = content.session
    detail = asyncio.run(pub.get_published_collection(collection_slug=slug, context=ctx, session=session))
    filtered = asyncio.run(
        pub.list_published_entries(
            context=ctx, session=session, entry_type=None, collection=slug, tag=None, slug=None, updated_since=None, limit=50, offset=0
        )
    )
    index = asyncio.run(pub.list_published_collections(context=ctx, session=session, limit=50, offset=0))
    return {
        "detail": {e.slug for e in detail.entries},
        "detail_count": detail.entry_count,
        "filter": {e.slug for e in filtered.data},
        "listed": slug in {c.slug for c in index.data},  # the collection itself is still listed: only its internal entries are held back
    }


@pytest.mark.parametrize(
    "rules",
    [
        {"listed": "unlisted"},
        {"listed": "unlisted", "statuses": ["published"]},
        {"entry_types": ["social-auto-reply"]},  # naming the internal type
        {"entry_types": ["social-auto-reply", "note"], "statuses": ["published"], "match": "any"},
    ],
)
def test_a_visible_collection_never_leaks_internal_entries_through_the_publishing_api(content, rules):
    collection = _smart(content, "pub-smart", rules, is_public=True)
    sync_collection(content.session, content.gid, collection)
    content.session.commit()
    gathered = _members(content, collection)
    assert gathered & INTERNAL, "the collection must hold internal entries for this test to mean anything"
    served = _served(content, "pub-smart")
    assert not served["detail"] & INTERNAL and not served["filter"] & INTERNAL
    assert served["detail"] == gathered - INTERNAL  # the publishable types only, even for a read-all token
    assert served["filter"] <= served["detail"]  # (the entries list serves published ones only)
    assert served["detail_count"] == len(served["detail"])
    assert served["listed"] is True


def test_a_visible_unlisted_collection_serves_no_entries(content):
    collection = _smart(content, "pub-unlisted", {"listed": "unlisted"}, is_public=True)
    sync_collection(content.session, content.gid, collection)
    content.session.commit()
    assert _members(content, collection) == INTERNAL
    served = _served(content, "pub-unlisted")
    assert served == {"detail": set(), "detail_count": 0, "filter": set(), "listed": True}


def test_a_type_marked_publishable_is_still_never_served_once_internal(content):
    row = content.session.query(EntryTypes).filter_by(group_id=content.gid, slug="social-auto-reply").one()
    row.capabilities_json = {"publishable": True, "listed": False}  # an explicit `publishable` doesn't override internal
    content.session.commit()
    collection = _smart(content, "pub-forced", {"listed": "unlisted"}, is_public=True)
    sync_collection(content.session, content.gid, collection)
    content.session.commit()
    assert _served(content, "pub-forced")["detail"] == set()
    with pytest.raises(HTTPException) as e:  # nor by reading one of its entries by slug
        asyncio.run(pub.get_published_entry(slug="rule_pub", context=_publish_ctx(content), session=content.session))
    assert e.value.status_code == 404


def test_listing_a_type_again_serves_it_only_if_it_is_publishable_too(content):
    listed = _smart(content, "pub-listed", {"listed": "listed", "statuses": ["published"]}, is_public=True)
    sync_collection(content.session, content.gid, listed)
    content.session.commit()
    assert _served(content, "pub-listed")["detail"] == {"note_pub"}
    _set_listed(content, "social-auto-reply", True)  # the Social rule type is listed now, but still `publishable: false`
    assert _members(content, listed) == {"note_pub", "rule_pub"}
    assert _served(content, "pub-listed")["detail"] == {"note_pub"}
    row = content.session.query(EntryTypes).filter_by(group_id=content.gid, slug="social-auto-reply").one()
    row.capabilities_json = {**row.capabilities_json, "publishable": True}
    content.session.commit()
    assert _served(content, "pub-listed")["detail"] == {"note_pub", "rule_pub"}


def test_a_workflow_query_naming_a_collection_gets_what_it_holds_internal_entries_included(content):
    from marvin.services.entries.query import run as run_query

    unlisted = _smart(content, "helpers", {"listed": "unlisted"})
    sync_collection(content.session, content.gid, unlisted)
    content.session.commit()

    def found(spec):
        return {e.slug for e in run_query(content.session, content.gid, spec, limit=100).rows}

    assert found({"collection": "helpers"}) == INTERNAL
    assert found({"collection": "helpers", "status": "published"}) == {"rule_pub", "iglog_pub"}
    assert found({"status": "published"}) == {"note_pub"}  # without the collection, internal entries stay out
