"""Internal entry types (``capabilities.listed: false``, services/entry_listing.py): helper content a feature owns — the Social
auto-reply rules — that stays out of every place entries are listed, counted, searched or indexed, and is still reached by naming
its type (or the entry). One test per path the audit touched.
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
from marvin.services.entry_listing import INTERNAL_SLUGS, is_listed_type, unlisted_entry_ids, unlisted_type_ids  # noqa: E402
from marvin.services.publish_visibility import is_publishable_type  # noqa: E402
from marvin.services.push_actions import inbox_count  # noqa: E402
from tests import test_content_role_gates as gates  # noqa: E402
from tests import test_social_engagement as se  # noqa: E402

ws, nets, _types = se.ws, se.nets, se._types
API = "/api/platform"


@pytest.fixture
def content(ws):
    """The workspace with a normal type and entries, the rule type (internal), and a legacy Instagram type with no flag at all."""
    session, gid = ws.session, ws.gid
    note = EntryTypes(session=session, group_id=gid, slug="note", name="Note", schema_json={"fields": []})
    legacy = EntryTypes(session=session, group_id=gid, slug="ig-reply-log", name="IG Reply Log", schema_json={"fields": []})
    session.add_all([note, legacy])
    session.commit()
    made = {}
    service = EntryService(session, gid, integration_id="test")
    for key, type_slug, status in (
        ("note_draft", "note", "draft"), ("note_pub", "note", "published"), ("note_inbox", "note", "inbox"),
        ("rule_draft", "social-auto-reply", "draft"), ("rule_pub", "social-auto-reply", "published"),
        ("rule_inbox", "social-auto-reply", "inbox"), ("iglog_pub", "ig-reply-log", "published"),
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


def test_a_type_is_internal_by_the_flag_or_by_a_core_slug():
    assert is_listed_type(None) is True
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json=None)) is True
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json={"publishable": False})) is True  # not publishable is not unlisted
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json={"listed": False})) is False
    assert is_listed_type(SimpleNamespace(slug="note", capabilities_json={"listed": True})) is True
    for slug in ("social-auto-reply", "social-reply-log", "ig-auto-reply", "ig-reply-log"):
        assert slug in INTERNAL_SLUGS and is_listed_type(SimpleNamespace(slug=slug, capabilities_json=None)) is False  # legacy: no flag stored


def test_the_capabilities_schema_accepts_the_flag():
    from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition

    assert CapabilitiesDefinition(listed=False).listed is False and CapabilitiesDefinition().listed is True


def test_the_unlisted_ids_cover_the_flag_and_the_slugs(content):
    flagged = EntryTypes(session=content.session, group_id=content.gid, slug="secret", name="S", schema_json={"fields": []},
                         capabilities_json={"listed": False})  # fmt: skip
    content.session.add(flagged)
    content.session.commit()
    slugs = {t.slug for t in content.session.query(EntryTypes).filter(EntryTypes.id.in_(unlisted_type_ids(content.session, content.gid)))}
    assert slugs == {"social-auto-reply", "ig-reply-log", "secret"}


def test_the_publishing_api_never_serves_an_internal_type_even_one_marked_publishable():
    assert is_publishable_type(SimpleNamespace(slug="x", capabilities_json={"publishable": True, "listed": False})) is False
    assert is_publishable_type(SimpleNamespace(slug="ig-auto-reply", capabilities_json=None)) is False
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
    assert found({"entry_type": "ig-reply-log"}) == {"iglog_pub"}  # a legacy type, internal by its slug


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


# ── the dashboard, the Trash, the overview ───────────────────────────────────────────────────────────────────────


def test_the_dashboard_pipeline_and_ages_leave_out_internal_types(content):
    rows = {r.slug: r for r in dashboard.by_type_status(content.session, content.gid)}
    assert "note" in rows and "social-auto-reply" not in rows and "ig-reply-log" not in rows
    assert (rows["note"].draft, rows["note"].published, rows["note"].inbox) == (1, 1, 1)
    assert dashboard.oldest_entry_days(content.session, content.gid, "draft", datetime.now(UTC)) is not None
    week = dashboard.published_by_week(content.session, content.gid, datetime.now(UTC))
    assert "social-auto-reply" not in week.model_dump_json() and "ig-reply-log" not in week.model_dump_json()
    assert sum(sum(w.by_type.values()) for w in week.weeks) == 1  # the one published note, not the two published internal entries


def test_the_trash_counts_leave_out_internal_entries_but_emptying_it_removes_them(content):
    svc = EntryService(content.session, content.gid, integration_id="test")
    svc.trash(content.note_pub.id)
    svc.trash(content.rule_pub.id)
    content.session.commit()
    assert len(entry_trash.trashed_ids(content.session, content.gid)) == 2
    assert len(entry_trash.trashed_ids(content.session, content.gid, listed_only=True)) == 1
    from marvin.services import trash

    assert trash.counts(content.session, content.gid)["entries"] == 1
    assert entry_trash.empty_trash(content.session, content.gid) == 2  # nothing is left behind in a hidden corner


def test_the_assistants_overview_counts_only_listed_content(content):
    from marvin.services.ai.tools import builtins_overview

    ctx = ToolContext(session=content.session, group_id=content.gid, user=None, provider=None)
    out = json.loads(builtins_overview.workspace_overview(ctx, {}))
    assert "social-auto-reply" not in json.dumps(out) and "ig-reply-log" not in json.dumps(out)
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
