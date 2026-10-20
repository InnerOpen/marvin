"""Internal entry types (``capabilities.listed: false`` and nothing else, services/entry_listing.py): helper content a feature owns —
the Social auto-reply rules, an Audience form's submissions — that stays out of every place entries are listed, counted, searched
or indexed, and is still reached by naming its type (or the entry). One test per path the audit touched.
"""

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

import json  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel  # noqa: E402
from marvin.db.models.platform.collections import Collections  # noqa: E402
from marvin.db.models.platform.entries import Entries  # noqa: E402
from marvin.db.models.platform.entry_types import EntryTypes  # noqa: E402
from marvin.db.models.users.roles import WorkspaceRole  # noqa: E402
from marvin.services import dashboard  # noqa: E402
from marvin.services.ai import embeddings as emb  # noqa: E402
from marvin.services.ai.embeddings_registry import REGISTRY  # noqa: E402
from marvin.services.ai.tools import builtins  # noqa: E402
from marvin.services.ai.tools.base import ToolContext  # noqa: E402
from marvin.services.collections.smart_collections import matches_rules, sync_collection  # noqa: E402
from marvin.services.entries import trash as entry_trash  # noqa: E402
from marvin.services.entries.entry_service import EntryService, count_by_status  # noqa: E402
from marvin.services.entries.query import run as run_query  # noqa: E402
from marvin.services.entry_listing import is_listed_type, unlisted_entry_ids, unlisted_type_ids  # noqa: E402
from marvin.services.publish_visibility import is_publishable_type  # noqa: E402
from marvin.services.push_actions import inbox_count  # noqa: E402
from tests import test_content_role_gates as gates  # noqa: E402
from tests import test_social_engagement as se  # noqa: E402

ws, nets, _types = se.ws, se.nets, se._types
API = "/api/platform"


@pytest.fixture
def content(ws):
    """The workspace with a normal type and entries, the rule type (internal), and the retired reply-log type (flagged by the migration)."""
    session, gid = ws.session, ws.gid
    note = EntryTypes(session=session, group_id=gid, slug="note", name="Note", schema_json={"fields": []})
    legacy = EntryTypes(session=session, group_id=gid, slug="social-reply-log", name="Social reply log", schema_json={"fields": []},
                        capabilities_json={"listed": False})  # fmt: skip
    session.add_all([note, legacy])
    session.commit()
    made = {}
    service = EntryService(session, gid, integration_id="test")
    for key, type_slug, status in (
        ("note_draft", "note", "draft"), ("note_pub", "note", "published"), ("note_inbox", "note", "inbox"),
        ("rule_draft", "social-auto-reply", "draft"), ("rule_pub", "social-auto-reply", "published"),
        ("rule_inbox", "social-auto-reply", "inbox"), ("iglog_pub", "social-reply-log", "published"),
    ):  # fmt: skip
        type_id = session.query(EntryTypes.id).filter_by(group_id=gid, slug=type_slug).scalar()
        data = {"keywords": "price", "reply": "hi"} if type_slug == "social-auto-reply" else {}
        made[key] = service.create({"entry_type_id": type_id, "title": key, "slug": key, "status": status, "data_json": data})
    session.commit()
    return SimpleNamespace(ws=ws, session=session, gid=gid, **made)


@pytest.fixture
def client(content):
    me = SimpleNamespace(gid=content.gid, uid=content.ws.uid, slug="listing")
    yield gates._sign_in(me, WorkspaceRole.ADMIN)
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    app.dependency_overrides.pop(get_current_user, None)


NOTES = {"note_draft", "note_pub", "note_inbox"}


# ── what makes a type internal ───────────────────────────────────────────────────────────────────────────────────


def test_a_type_is_internal_by_the_flag_and_nothing_else():
    assert is_listed_type(None) is True
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json=None)) is True
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json={"publishable": False})) is True  # not publishable is not unlisted
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json={"listed": False})) is False
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json={"listed": True})) is True
    for slug in ("social-auto-reply", "social-reply-log"):  # no slug rule any more: the migration set the flag on the stored types
        assert is_listed_type(SimpleNamespace(slug=slug, capabilities_json=None)) is True
        assert is_listed_type(SimpleNamespace(slug=slug, capabilities_json={"listed": False})) is False
    form = {"submittable": True, "submission": {"destination": "audience"}}  # a form's destination is not the listing rule
    assert is_listed_type(SimpleNamespace(slug="contact", capabilities_json=form)) is True
    assert is_listed_type(SimpleNamespace(slug="contact", capabilities_json={**form, "listed": False})) is False


def test_the_capabilities_schema_accepts_the_flag():
    from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition

    assert CapabilitiesDefinition(listed=False).listed is False and CapabilitiesDefinition().listed is True


def test_the_unlisted_ids_are_the_flagged_types(content):
    flagged = EntryTypes(session=content.session, group_id=content.gid, slug="secret", name="S", schema_json={"fields": []},
                         capabilities_json={"listed": False})  # fmt: skip
    content.session.add(flagged)
    content.session.commit()
    slugs = {t.slug for t in content.session.query(EntryTypes).filter(EntryTypes.id.in_(unlisted_type_ids(content.session, content.gid)))}
    assert slugs == {"social-auto-reply", "social-reply-log", "secret"}


def test_the_publishing_api_never_serves_an_internal_type_even_one_marked_publishable():
    assert is_publishable_type(SimpleNamespace(slug="x", capabilities_json={"publishable": True, "listed": False})) is False
    assert is_publishable_type(SimpleNamespace(slug="social-reply-log", capabilities_json={"listed": False})) is False
    assert is_publishable_type(SimpleNamespace(slug="note", capabilities_json={})) is True


# ── lists and counts ─────────────────────────────────────────────────────────────────────────────────────────────


def test_all_entries_leaves_out_internal_types(client):
    slugs = {e["slug"] for e in client.get(f"{API}/entries").json()}
    assert slugs == NOTES


def test_the_counts_leave_out_internal_types(content, client):
    counts = client.get(f"{API}/entries/counts").json()
    assert (counts["draft"], counts["published"], counts["inbox"], counts["total"]) == (1, 1, 1, 3)
    assert count_by_status(content.session, content.gid)["total"] == 3
    assert inbox_count(content.session, content.gid) == 1  # the app icon's badge


def test_a_query_names_an_internal_type_to_find_it_and_never_reaches_it_otherwise(content):
    def found(spec):
        return {e.slug for e in run_query(content.session, content.gid, spec, limit=100).rows}

    assert found({}) == NOTES
    assert found({"status": "draft"}) == {"note_draft"}
    assert found({"status": "published"}) == {"note_pub"}
    assert found({"text": "rule"}) == set()
    assert found({"entry_type": "social-auto-reply"}) == {"rule_draft", "rule_pub", "rule_inbox"}
    assert found({"entry_type": "social-auto-reply", "status": "published"}) == {"rule_pub"}
    assert found({"entry_types": ["note", "social-auto-reply"]}) == NOTES | {"rule_draft", "rule_pub", "rule_inbox"}
    assert found({"entries": ["rule_pub"]}) == {"rule_pub"}  # the entry itself, by name
    assert found({"entry_type": "social-reply-log"}) == {"iglog_pub"}  # a legacy type, internal by its slug


def test_the_entries_search_route_and_the_assistants_find_entries_agree(content, client):
    body = client.post(f"{API}/entries/query", json={"spec": {"status": "draft"}}).json()
    assert {e["slug"] for e in body["entries"]} == {"note_draft"} and body["total"] == 1
    ctx = ToolContext(session=content.session, group_id=content.gid, user=None, provider=None)
    assert {e["slug"] for e in json.loads(builtins.find_entries(ctx, {"query": "_"}))["entries"]} == {"note_draft", "note_pub", "note_inbox"}
    named = json.loads(builtins.find_entries(ctx, {"entry_type": "social-auto-reply", "limit": 50}))
    assert {e["slug"] for e in named["entries"]} == {"rule_draft", "rule_pub", "rule_inbox"}


def test_a_workflow_target_names_the_type_to_reach_the_rules(content):
    """The workflow engine's "run on a query of entries" is this same query: all entries never include internal ones."""
    from marvin.services.entries.query import build

    q, _ = build(content.session, content.gid, {"status": "published"})
    assert {e.slug for e in q.all()} == {"note_pub"}
    q, _ = build(content.session, content.gid, {"entry_types": ["social-auto-reply"], "status": "published"})
    assert {e.slug for e in q.all()} == {"rule_pub"}


# ── collections and the status lists ─────────────────────────────────────────────────────────────────────────────


def _entry(content, key):
    return content.session.get(Entries, getattr(content, key).id)


def test_the_status_collections_never_hold_an_internal_entry_but_a_collection_naming_the_type_does(content):
    drafts = {"statuses": ["draft"]}
    assert matches_rules(_entry(content, "note_draft"), drafts) is True
    assert matches_rules(_entry(content, "rule_draft"), drafts) is False
    assert matches_rules(_entry(content, "iglog_pub"), {"statuses": ["published"]}) is False
    assert matches_rules(_entry(content, "rule_draft"), {"statuses": ["draft"], "match": "any", "entry_types": ["note"]}) is False  # even "any"
    assert matches_rules(_entry(content, "rule_draft"), {"entry_types": ["social-auto-reply"]}) is True
    assert matches_rules(_entry(content, "rule_draft"), {"entry_types": ["social-auto-reply"], "statuses": ["draft"]}) is True


def test_syncing_a_smart_collection_drops_internal_entries(content):
    everything = Collections(session=content.session, group_id=content.gid, name="Drafts", slug="drafts-x", is_smart=True,
                             smart_rules={"statuses": ["draft", "published"], "match": "all"})  # fmt: skip
    content.session.add(everything)
    content.session.commit()
    sync_collection(content.session, content.gid, everything)
    content.session.commit()
    from marvin.db.models.platform.entry_collections import EntryCollections

    member_ids = {r[0] for r in content.session.query(EntryCollections.entry_id).filter_by(collection_id=everything.id)}
    assert member_ids == {content.note_draft.id, content.note_pub.id}


def test_a_collection_page_lists_internal_entries_only_when_its_rules_name_the_type(content, client):
    from marvin.db.models.platform.entry_collections import EntryCollections

    manual = Collections(session=content.session, group_id=content.gid, name="Mixed", slug="mixed", is_smart=False)
    naming = Collections(session=content.session, group_id=content.gid, name="Rules", slug="rules-x", is_smart=True,
                         smart_rules={"entry_types": ["social-auto-reply"]})  # fmt: skip
    content.session.add_all([manual, naming])
    content.session.commit()
    for coll in (manual, naming):
        for key in ("note_pub", "rule_pub"):
            content.session.add(EntryCollections(entry_id=getattr(content, key).id, collection_id=coll.id, sort_order=0))
    content.session.commit()
    assert {e["slug"] for e in client.get(f"{API}/collections/{manual.id}/entries").json()} == {"note_pub"}
    assert {e["slug"] for e in client.get(f"{API}/collections/{naming.id}/entries").json()} == {"note_pub", "rule_pub"}
    ctx = ToolContext(session=content.session, group_id=content.gid, user=None, provider=None)
    assert {e["slug"] for e in json.loads(builtins.get_collection_entries(ctx, {"collection": "mixed"}))["entries"]} == {"note_pub"}


# ── the dashboard, the Trash (lists them, so a rule can be restored), the overview ──────────────────────────────────────────


def test_the_dashboard_pipeline_and_ages_leave_out_internal_types(content):
    rows = {r.slug: r for r in dashboard.by_type_status(content.session, content.gid)}
    assert "note" in rows and "social-auto-reply" not in rows and "social-reply-log" not in rows
    assert (rows["note"].draft, rows["note"].published, rows["note"].inbox) == (1, 1, 1)
    assert dashboard.oldest_entry_days(content.session, content.gid, "draft", datetime.now(UTC)) is not None
    week = dashboard.published_by_week(content.session, content.gid, datetime.now(UTC))
    assert "social-auto-reply" not in week.model_dump_json() and "social-reply-log" not in week.model_dump_json()
    assert sum(sum(w.by_type.values()) for w in week.weeks) == 1  # the one published note, not the two published internal entries


def _seed_trash(content):
    """The workspace's system collections (the Trash is one), with the current entries materialized."""
    from marvin.services.collections.system_collections import seed_system_workflow_collections

    seed_system_workflow_collections(content.session, content.gid)
    content.session.commit()


def _sync(content, *keys):
    from marvin.services.collections.smart_collections import sync_entry

    for key in keys:
        content.session.refresh(_entry(content, key))
        sync_entry(content.session, content.gid, _entry(content, key))
    content.session.commit()


def _trash_page(content, client) -> set[str]:
    """What the Trash page lists: the entries of the system `trash` collection."""
    from marvin.db.models.platform.collections import Collections

    trash_id = content.session.query(Collections.id).filter_by(group_id=content.gid, slug="trash").scalar()
    return {e["slug"] for e in client.get(f"{API}/collections/{trash_id}/entries").json()}


def test_the_trash_lists_and_counts_internal_entries_and_emptying_it_removes_them(content, client):
    _seed_trash(content)
    svc = EntryService(content.session, content.gid, integration_id="test")
    for key in ("note_pub", "rule_pub", "iglog_pub"):
        svc.trash(getattr(content, key).id)
    content.session.commit()
    _sync(content, "note_pub", "rule_pub", "iglog_pub")
    assert len(entry_trash.trashed_ids(content.session, content.gid)) == 3
    from marvin.services import trash

    assert trash.counts(content.session, content.gid)["entries"] == 3
    assert client.get(f"{API}/entries/trash").json()["count"] == 3
    assert _trash_page(content, client) == {"note_pub", "rule_pub", "iglog_pub"}
    # every other list, count and search still leaves them out
    assert {e["slug"] for e in client.get(f"{API}/entries").json()} == NOTES - {"note_pub"}
    assert client.get(f"{API}/entries/counts").json()["total"] == 2
    assert {e.slug for e in run_query(content.session, content.gid, {"status": "trashed"}, limit=100).rows} == {"note_pub"}
    assert entry_trash.empty_trash(content.session, content.gid) == 3  # nothing is left behind in a hidden corner


def test_a_trashed_rule_is_in_no_collection_but_the_trash(content, client):
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections

    _seed_trash(content)
    _sync(content, "rule_draft")
    EntryService(content.session, content.gid, integration_id="test").trash(content.rule_draft.id)
    content.session.commit()
    _sync(content, "rule_draft")
    by_id = {c.id: c.slug for c in content.session.query(Collections).filter_by(group_id=content.gid)}
    held = {by_id[r.collection_id] for r in content.session.query(EntryCollections).filter_by(entry_id=content.rule_draft.id)}
    assert held == {"trash"}
    # the Trash shows it (and its sidebar count); the other status collections never listed it
    counts = {c["slug"]: c["entryCount"] for c in client.get(f"{API}/collections").json()}
    assert counts["trash"] == 1 and counts["drafts"] == 1  # the draft is note_draft


def test_restoring_a_trashed_rule_puts_it_back_among_the_rules_unpublished(content, client):
    _seed_trash(content)
    svc = EntryService(content.session, content.gid, integration_id="test")
    svc.trash(content.rule_pub.id)
    svc.trash(content.rule_draft.id)
    content.session.commit()
    _sync(content, "rule_pub", "rule_draft")
    assert client.post(f"{API}/entries/{content.rule_pub.id}/restore").json()["status"] == "draft"  # published comes back as a draft
    assert client.post(f"{API}/entries/{content.rule_draft.id}/restore").json()["status"] == "draft"  # the others as they were
    content.session.expire_all()
    assert _trash_page(content, client) == set()
    assert client.get(f"{API}/entries/trash").json()["count"] == 0
    # back where its page looks for rules (by naming the type), and still out of All entries
    named = {e.slug for e in run_query(content.session, content.gid, {"entry_type": "social-auto-reply", "status": "draft"}, limit=100).rows}
    assert {"rule_pub", "rule_draft"} <= named
    assert {e["slug"] for e in client.get(f"{API}/entries").json()} == NOTES
    assert client.post(f"{API}/entries/{content.rule_pub.id}/restore").status_code == 409  # not in the Trash any more


def test_the_assistants_overview_counts_only_listed_content(content):
    from marvin.services.ai.tools import builtins_overview

    ctx = ToolContext(session=content.session, group_id=content.gid, user=None, provider=None)
    out = json.loads(builtins_overview.workspace_overview(ctx, {}))
    assert "social-auto-reply" not in json.dumps(out) and "social-reply-log" not in json.dumps(out)
    assert out["entries"]["total"] == 3 and [t["slug"] for t in out["entries"]["byType"]] == ["note"]


# ── search and the AI index ──────────────────────────────────────────────────────────────────────────────────────


def test_an_internal_entry_is_never_indexed(content):
    desc = REGISTRY["entry"]
    assert desc.content_ok(_entry(content, "note_pub")) is True
    assert desc.content_ok(_entry(content, "rule_pub")) is False and desc.content_ok(_entry(content, "iglog_pub")) is False
    from marvin.services.event_bus_service.event_types import EventTypes

    assert desc.should_index(_entry(content, "rule_pub"), EventTypes.entry_published, False) is False
    assert desc.should_index(_entry(content, "note_pub"), EventTypes.entry_published, False) is True


def test_semantic_search_never_returns_an_internal_entry_whatever_an_older_index_holds(content):
    for key in ("note_pub", "rule_pub"):
        content.session.add(
            AIEmbeddingModel(session=content.session, group_id=content.gid, entity_type="entry", entity_id=getattr(content, key).id,
                             chunk_index=0, chunk_text=key, embedding=[1.0, 0.0], model_id="m", dimensions=2)
        )  # fmt: skip
    content.session.commit()
    hits = emb.search_embeddings(content.session, content.gid, [1.0, 0.0], limit=10, entity_types=["entry"], model="m")
    assert {h["entity_id"] for h in hits} == {str(content.note_pub.id)}
    assert unlisted_entry_ids(content.session, content.gid) >= {content.rule_pub.id, content.iglog_pub.id}


def test_the_assistants_search_content_drops_internal_entries(content, monkeypatch):
    for key in ("note_pub", "rule_pub"):
        content.session.add(
            AIEmbeddingModel(session=content.session, group_id=content.gid, entity_type="entry", entity_id=getattr(content, key).id,
                             chunk_index=0, chunk_text=key, embedding=[1.0, 0.0], model_id="m", dimensions=2)
        )  # fmt: skip
    content.session.commit()

    class Embedder:
        def embed(self, texts, model=None):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("marvin.services.ai.embeddings.embedder_for", lambda provider: (Embedder(), "m"))
    ctx = ToolContext(session=content.session, group_id=content.gid, user=None, provider=None)
    out = json.loads(builtins.search_content(ctx, {"query": "anything"}))
    assert {r["entityId"] for r in out["results"]} <= {str(content.note_pub.id)}


# ── listed is one switch: turning it on shows the entries everywhere, and what uses them keeps working ──────────────────────────


def _list_the_rule_type(content):
    rule_type = content.session.query(EntryTypes).filter_by(group_id=content.gid, slug="social-auto-reply").one()
    rule_type.capabilities_json = {**(rule_type.capabilities_json or {}), "listed": True}
    content.session.commit()


def test_a_listed_rule_type_shows_its_entries_in_every_list_and_count(content, client):
    _list_the_rule_type(content)
    assert {e["slug"] for e in client.get(f"{API}/entries").json()} == NOTES | {"rule_draft", "rule_pub", "rule_inbox"}
    assert client.get(f"{API}/entries/counts").json()["inbox"] == 2  # a note and a rule
    assert {e.slug for e in run_query(content.session, content.gid, {"status": "inbox"}, limit=50).rows} == {"note_inbox", "rule_inbox"}
    assert matches_rules(_entry(content, "rule_draft"), {"statuses": ["draft"]}) is True
    assert REGISTRY["entry"].content_ok(_entry(content, "rule_pub")) is True
    assert "social-auto-reply" in {r.slug for r in dashboard.by_type_status(content.session, content.gid)}


def test_social_keeps_working_when_its_rule_type_is_listed(content):
    from marvin.services.integrations import social_rule_entries

    _list_the_rule_type(content)
    assert {r.slug for r in social_rule_entries.list_rules(content.session, content.gid)} >= {
        "rule_draft",
        "rule_pub",
    }  # found by type, listed or not
    from marvin.services.integrations import social_setup

    social_setup.ensure_rule_type(content.session, content.gid)  # finds the type as it is: still one, still listed
    types = content.session.query(EntryTypes).filter_by(group_id=content.gid, slug="social-auto-reply").all()
    assert len(types) == 1 and types[0].capabilities_json["listed"] is True


def test_the_engine_still_answers_with_a_listed_rule_type(ws):
    se.rule(ws, keywords="price", reply="Check the link in bio.")
    rule_type = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="social-auto-reply").one()
    rule_type.capabilities_json = {**rule_type.capabilities_json, "listed": True}
    ws.session.commit()
    ws.nets["mastodon"].feed = [se.item("c1", "What is the price?")]
    se.run(ws)
    assert [a["comment_id"] for a in ws.nets["mastodon"].sent()] == ["c1"]
