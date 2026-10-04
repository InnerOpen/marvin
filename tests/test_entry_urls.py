"""Entry page URLs (services/entry_urls.py): an entry type's page URL pattern + the workspace's
Canonical URL → where the site shows an entry. Optional everywhere; unset means no URL anywhere."""

import json
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pytest import fixture

from marvin.services.entry_urls import best_entry_url, entry_url, normalize_page_url_pattern, normalize_site_url, site_base_url

SITE = "https://gallery.example.com"
ENTRY_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _type(pattern="/works/{slug}", slug="artwork", capabilities=None):
    return SimpleNamespace(page_url_pattern=pattern, slug=slug, capabilities_json=capabilities)


def _entry(slug="blue-heron", entry_type=None, status="published"):
    return SimpleNamespace(id=ENTRY_ID, slug=slug, status=status, entry_type=entry_type if entry_type is not None else _type())


# --- the resolver ---------------------------------------------------------------------------------


def test_entry_url_relative_fills_slug():
    assert entry_url(_entry(), absolute=False) == "/works/blue-heron"


def test_entry_url_absolute_joins_site_url():
    assert entry_url(_entry(), absolute=True, site_url=SITE + "/") == f"{SITE}/works/blue-heron"


def test_entry_url_absolute_without_site_url_returns_none():
    assert entry_url(_entry(), absolute=True, site_url=None) is None


def test_entry_url_absolute_with_relative_site_url_returns_none():
    assert entry_url(_entry(), absolute=True, site_url="gallery.example.com") is None


def test_entry_url_without_pattern_returns_none():
    assert entry_url(_entry(entry_type=_type(pattern=None)), absolute=True, site_url=SITE) is None


def test_entry_url_without_entry_type_returns_none():
    entry = SimpleNamespace(id=ENTRY_ID, slug="x", entry_type=None)
    assert entry_url(entry, absolute=False) is None


def test_entry_url_missing_slug_returns_none():
    assert entry_url(_entry(slug=""), absolute=False) is None


def test_entry_url_fills_id_and_entry_type_placeholders():
    et = _type(pattern="/{entry_type}/{id}")
    assert entry_url(_entry(entry_type=et), absolute=False) == f"/artwork/{ENTRY_ID}"


def test_entry_url_escapes_slug_characters():
    assert entry_url(_entry(slug="a b/c"), absolute=False) == "/works/a%20b%2Fc"


def test_entry_url_full_url_pattern_ignores_site_url():
    et = _type(pattern="https://shop.example.com/p/{slug}")
    assert entry_url(_entry(entry_type=et), absolute=True, site_url=None) == "https://shop.example.com/p/blue-heron"


def test_entry_url_not_routable_type_returns_none():
    et = _type(capabilities={"routable": False})
    assert entry_url(_entry(entry_type=et), absolute=False) is None


def test_entry_url_explicit_entry_type_overrides_relationship():
    entry = SimpleNamespace(id=ENTRY_ID, slug="blue-heron")  # e.g. a Pydantic EntryRead: no relationship
    assert entry_url(entry, absolute=False, entry_type=_type()) == "/works/blue-heron"


def test_entry_url_is_returned_for_unpublished_entries():
    # Status is the caller's concern: a draft's link is where it WILL live.
    assert entry_url(_entry(status="draft"), absolute=False) == "/works/blue-heron"


def test_best_entry_url_is_absolute_with_site_url():
    assert best_entry_url(_entry(), SITE) == f"{SITE}/works/blue-heron"


def test_best_entry_url_falls_back_to_path_without_site_url():
    assert best_entry_url(_entry(), None) == "/works/blue-heron"


# --- validating a pattern -------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_normalize_page_url_pattern_blank_means_no_pattern(value):
    assert normalize_page_url_pattern(value) is None


@pytest.mark.parametrize("value", ["/works/{slug}", " /{entry_type}/{id} ", "https://shop.example.com/p/{slug}"])
def test_normalize_page_url_pattern_accepts_paths_and_full_urls(value):
    assert normalize_page_url_pattern(value) == value.strip()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("works/{slug}", "must start with /"),
        ("/works/{title}", "Unknown placeholder"),
        ("/works/{slug", "unmatched"),
        ("/works/{entry_type}", "{slug} or {id}"),
        ("/about", "{slug} or {id}"),
    ],
)
def test_normalize_page_url_pattern_rejects_unusable_patterns(value, message):
    with pytest.raises(ValueError, match=message):
        normalize_page_url_pattern(value)


def test_normalize_site_url_rejects_relative_values():
    assert normalize_site_url("/site") is None
    assert normalize_site_url(" https://a.example.com/ ") == "https://a.example.com"


def test_entry_type_update_schema_rejects_bad_pattern():
    from marvin.schemas.platform.entry_types import EntryTypeUpdate

    with pytest.raises(ValidationError):
        EntryTypeUpdate(page_url_pattern="/works/{title}")


def test_entry_type_update_schema_blank_pattern_clears():
    from marvin.schemas.platform.entry_types import EntryTypeUpdate

    assert EntryTypeUpdate(pageUrlPattern="  ").model_dump(exclude_unset=True) == {"page_url_pattern": None}


# --- persisted: migration, repository, export/import ----------------------------------------------


@fixture
def gallery(db_session):
    """A workspace with an artwork type (pattern set), a note type (no pattern) and one entry of each."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"url-{marker}", slug=f"url-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    prefs = GroupPreferencesModel(session=db_session, group_id=gid, site_canonical_url=SITE)
    db_session.add(prefs)
    art = EntryTypes(session=db_session, group_id=gid, name="Artwork", slug="artwork", schema_json={}, page_url_pattern="/works/{slug}")
    note = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    db_session.add_all([art, note])
    db_session.flush()
    work = Entries(session=db_session, group_id=gid, entry_type_id=art.id, title="Blue Heron", slug=f"blue-heron-{marker}", status="published")
    memo = Entries(session=db_session, group_id=gid, entry_type_id=note.id, title="Memo", slug=f"memo-{marker}")
    col = Collections(session=db_session, group_id=gid, name="Featured", slug=f"featured-{marker}")
    db_session.add_all([work, memo, col])
    db_session.flush()
    db_session.add_all(
        [
            EntryCollections(entry_id=work.id, collection_id=col.id, sort_order=0),
            EntryCollections(entry_id=memo.id, collection_id=col.id, sort_order=1),
        ]
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, prefs=prefs, art=art, note=note, work=work, memo=memo, col=col)
    db_session.rollback()
    db_session.query(EntryCollections).filter(EntryCollections.collection_id == col.id).delete()
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_migration_adds_nullable_page_url_pattern_column(db_session):
    from sqlalchemy import inspect

    columns = {c["name"]: c for c in inspect(db_session.get_bind()).get_columns("entry_types")}
    assert columns["page_url_pattern"]["nullable"] is True


def test_site_base_url_reads_the_canonical_url(db_session, gallery):
    assert site_base_url(db_session, gallery.gid) == SITE


def test_site_base_url_is_none_without_preferences(db_session):
    assert site_base_url(db_session, uuid.uuid4()) is None


def test_entry_type_page_url_pattern_round_trips_through_repository(db_session, gallery):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.schemas.platform.entry_types import EntryTypeUpdate

    repo = AllRepositories(db_session, group_id=gallery.gid).entry_types
    created = repo.create({"name": "Event", "page_url_pattern": " /events/{slug} "})
    assert repo.get_one(created.id).page_url_pattern == "/events/{slug}"

    repo.update(created.id, EntryTypeUpdate(description="Shows"))  # field not sent → kept
    assert repo.get_one(created.id).page_url_pattern == "/events/{slug}"

    repo.update(created.id, EntryTypeUpdate(page_url_pattern=""))  # blank → cleared
    assert repo.get_one(created.id).page_url_pattern is None


def test_entry_type_repository_rejects_bad_pattern_from_dict_callers(db_session, gallery):
    from fastapi import HTTPException

    from marvin.repos.repository_factory import AllRepositories

    with pytest.raises(HTTPException) as exc:
        AllRepositories(db_session, group_id=gallery.gid).entry_types.create({"name": "Bad", "page_url_pattern": "/x/{title}"})
    assert exc.value.status_code == 400


def test_export_then_import_keeps_page_url_pattern(db_session, gallery):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    repos = AllRepositories(db_session, group_id=gallery.gid)
    exported = {t["slug"]: t for t in WorkspaceExporter(repos)._export_entry_types(include_system=False)}
    assert exported["artwork"]["pageUrlPattern"] == "/works/{slug}"
    assert exported["note"]["pageUrlPattern"] is None

    loader = WorkspaceSeedLoader(repos)
    loader._overwrite = False
    loader._create_entry_type({**exported["artwork"], "slug": "artwork-copy", "name": "Artwork copy"})
    copy = repos.entry_types.multi_query({"slug": "artwork-copy", "group_id": gallery.gid})[0]
    assert copy.page_url_pattern == "/works/{slug}"


def test_import_overwrite_without_the_key_keeps_the_pattern(db_session, gallery):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    repos = AllRepositories(db_session, group_id=gallery.gid)
    loader = WorkspaceSeedLoader(repos)
    loader._overwrite = True
    loader._create_entry_type({"name": "Artwork", "slug": "artwork", "schemaJson": {}})  # an older export
    assert repos.entry_types.get_one(gallery.art.id).page_url_pattern == "/works/{slug}"


# --- AI tools -------------------------------------------------------------------------------------


def _tool(db_session, gid, name, args):
    from marvin.services.ai.tools import ToolContext, get_tool

    return json.loads(get_tool(name).handler(ToolContext(session=db_session, group_id=gid), args))


def test_find_entries_rows_include_url_when_resolvable(db_session, gallery):
    rows = {r["title"]: r for r in _tool(db_session, gallery.gid, "find_entries", {})["entries"]}
    assert rows["Blue Heron"]["url"] == f"{SITE}/works/{gallery.work.slug}"
    assert "url" not in rows["Memo"]  # its type has no pattern → the row is exactly as before


def test_find_entries_url_falls_back_to_path_without_site_url(db_session, gallery):
    gallery.prefs.site_canonical_url = None
    db_session.commit()
    rows = {r["title"]: r for r in _tool(db_session, gallery.gid, "find_entries", {})["entries"]}
    assert rows["Blue Heron"]["url"] == f"/works/{gallery.work.slug}"


def test_get_entry_includes_url(db_session, gallery):
    assert _tool(db_session, gallery.gid, "get_entry", {"id_or_slug": gallery.work.slug})["url"] == f"{SITE}/works/{gallery.work.slug}"


def test_get_entry_omits_url_when_type_has_no_pattern(db_session, gallery):
    assert "url" not in _tool(db_session, gallery.gid, "get_entry", {"id_or_slug": gallery.memo.slug})


def test_get_collection_entries_include_url(db_session, gallery):
    rows = {r["title"]: r for r in _tool(db_session, gallery.gid, "get_collection_entries", {"collection": gallery.col.slug})["entries"]}
    assert rows["Blue Heron"]["url"] == f"{SITE}/works/{gallery.work.slug}"
    assert "url" not in rows["Memo"]


def test_get_entry_type_shows_page_url_pattern_only_when_set(db_session, gallery):
    assert _tool(db_session, gallery.gid, "get_entry_type", {"id_or_slug": "artwork"})["pageUrlPattern"] == "/works/{slug}"
    assert "pageUrlPattern" not in _tool(db_session, gallery.gid, "get_entry_type", {"id_or_slug": "note"})


def test_workspace_preamble_has_entry_links_rule_when_entry_tools_are_bound():
    from marvin.services.ai.agents import workspace_preamble

    text = workspace_preamble("Gallery", ["find_entries"])
    assert "[Title](#)" in text and "`url` from find_entries" in text
    assert "get_entry" not in text  # only bound tools are named
    assert "[Title](#)" not in workspace_preamble("Gallery", ["list_tags"])


# --- admin entry read + publishing API ------------------------------------------------------------


def _admin_get(db_session, gid, entry_id):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.routes.platform.entries_controller import EntriesController

    ctrl = SimpleNamespace(repos=AllRepositories(db_session, group_id=gid), session=db_session, group_id=gid)
    return EntriesController.get_entry(ctrl, entry_id)


def test_admin_entry_read_carries_absolute_page_url(db_session, gallery):
    assert _admin_get(db_session, gallery.gid, gallery.work.id).page_url == f"{SITE}/works/{gallery.work.slug}"


def test_admin_entry_read_page_url_needs_a_site_url(db_session, gallery):
    gallery.prefs.site_canonical_url = None
    db_session.commit()
    assert _admin_get(db_session, gallery.gid, gallery.work.id).page_url is None


def test_published_list_item_carries_url(db_session, gallery):
    from marvin.routes.publish.publishing_controller import _entry_to_list_item

    db_session.refresh(gallery.work)
    assert _entry_to_list_item(gallery.work, "gallery", site_url=SITE).url == f"{SITE}/works/{gallery.work.slug}"
    assert _entry_to_list_item(gallery.work, "gallery").url == f"/works/{gallery.work.slug}"


def test_published_list_item_url_is_null_without_pattern(db_session, gallery):
    from marvin.routes.publish.publishing_controller import _entry_to_list_item

    db_session.refresh(gallery.memo)
    assert _entry_to_list_item(gallery.memo, "gallery", site_url=SITE).url is None


def test_search_content_entry_hits_include_url(db_session, gallery, monkeypatch):
    hits = [
        {"entity_type": "entry", "entity_id": str(gallery.work.id), "title": "Blue Heron", "score": 0.9},
        {"entity_type": "entry", "entity_id": str(gallery.memo.id), "title": "Memo", "score": 0.5},
    ]

    class FakeBuilder:
        def __init__(self, *_): ...

        def with_semantic_search(self, *_args, **_kwargs):
            return self

        def build(self):
            return SimpleNamespace(retrieved=[{"text": "heron"}, {"text": "memo"}])

    monkeypatch.setattr("marvin.services.ai.context.ContextBuilder", FakeBuilder)
    monkeypatch.setattr("marvin.services.ai.embeddings.default_embedding_model", lambda _provider_type: "embed-model")
    monkeypatch.setattr("marvin.services.ai.tools.builtins.resolve_retrieved_sources", lambda _session, _retrieved: hits)
    from marvin.services.ai.tools import ToolContext, get_tool

    ctx = ToolContext(session=db_session, group_id=gallery.gid, provider=SimpleNamespace(provider_type="openai"))
    results = {r["title"]: r for r in json.loads(get_tool("search_content").handler(ctx, {"query": "heron"}))["results"]}
    assert results["Blue Heron"]["url"] == f"{SITE}/works/{gallery.work.slug}"
    assert "url" not in results["Memo"]
