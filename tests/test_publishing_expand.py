"""DB-backed tests for ``?expand=full`` on the publishing list endpoints.

A site that needs asset roles or resources used to read every list item again through the
single-entry endpoint: one request per entry, ~470 for one site build. With ``expand=full`` the
collection read, the entries list and a resource's entries return each entry in the single-read
shape. These pin that an expanded item IS the single read, that a page costs a fixed number of
queries whatever its size, that the plain response is untouched, and that expanding never shows
more than the single read would.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from marvin.app import app
from marvin.core.dependencies import get_publishing_context
from marvin.core.permissions import PermissionChecker, Permissions
from marvin.db.db_setup import engine
from marvin.db.models.groups import Groups
from marvin.db.models.platform import (
    Assets,
    AssetTags,
    Collections,
    Entries,
    EntryAssets,
    EntryCollections,
    EntryResources,
    EntryTags,
    EntryTypes,
    Resources,
    ResourceTags,
    Tags,
)
from marvin.db.models.users.users import Users
from marvin.routes.publish import publishing_controller as pub
from marvin.schemas.publishing import PublishedEntryListItem

SITE_TOKEN = {Permissions.READ_PUBLISHED_ENTRIES: True, Permissions.READ_COLLECTIONS: True, Permissions.READ_RESOURCES: True}


@contextmanager
def count_queries() -> Iterator[list[str]]:
    """Every SQL statement the engine runs inside the block."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _insert(db_session, model, **values):
    values.setdefault("id", uuid.uuid4())
    db_session.execute(model.__table__.insert().values(**values))
    return values["id"]


@pytest.fixture
def make_workspace(db_session) -> Iterator[Callable[[int], SimpleNamespace]]:
    """Build a workspace whose ``projects`` collection holds ``n`` published entries, each with a
    hero and a gallery asset (tagged), a pending AI-suggested asset, a tagged resource, an entry tag,
    a media link and a membership in a private collection. Plus a draft and an entry of a
    non-publishable type, both in ``projects``."""
    created: list = []

    def build(n: int) -> SimpleNamespace:
        gid = uuid.uuid4()
        marker = gid.hex[:8]
        created.append(gid)
        group = Groups(session=db_session, name=f"pub-exp-{marker}", slug=f"pub-exp-{marker}")
        group.id = gid
        db_session.add(group)
        db_session.flush()

        uid = _insert(
            db_session,
            Users,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )

        project = _insert(
            db_session,
            EntryTypes,
            group_id=gid,
            name="Project",
            slug="project",
            schema_json={"fields": [{"key": "video", "type": "embed"}]},
        )
        private_type = _insert(
            db_session,
            EntryTypes,
            group_id=gid,
            name="Inquiry",
            slug="inquiry",
            schema_json={},
            capabilities_json={"publishable": False},
        )
        projects = _insert(db_session, Collections, group_id=gid, name="Projects", slug="projects", is_public=True, sort_order=0)
        hidden = _insert(db_session, Collections, group_id=gid, name="Hidden", slug="hidden", is_public=False, sort_order=1)
        tag = _insert(db_session, Tags, group_id=gid, name="Leather", slug="leather")

        def asset(slug: str) -> uuid.UUID:
            aid = _insert(
                db_session,
                Assets,
                group_id=gid,
                slug=slug,
                name=slug.title(),
                original_filename=f"{slug}.jpg",
                filename=slug,
                extension="jpg",
                file_size=10,
                mime_type="image/jpeg",
                asset_type="image",
                checksum=uuid.uuid4().hex,
                storage_provider="local",
                storage_key=f"k/{uuid.uuid4().hex}",
                uploaded_by=uid,
            )
            _insert(db_session, AssetTags, asset_id=aid, tag_id=tag)
            return aid

        material = _insert(
            db_session,
            Resources,
            group_id=gid,
            slug="waxed-canvas",
            name="Waxed Canvas",
            resource_type="material",
            created_by=uid,
        )
        _insert(db_session, ResourceTags, resource_id=material, tag_id=tag)

        base = datetime(2026, 1, 1, tzinfo=UTC)
        slugs = []
        for i in range(n):
            slug = f"p{i}-{marker}"
            slugs.append(slug)
            eid = _insert(
                db_session,
                Entries,
                group_id=gid,
                entry_type_id=project,
                title=f"Project {i}",
                slug=slug,
                status="published",
                published_at=base + timedelta(days=i),
                summary="s",
                data_json={"video": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "n": i},
                metadata_json={"featured": i == 0},
            )
            _insert(db_session, EntryCollections, entry_id=eid, collection_id=projects, sort_order=n - i, role="item")
            _insert(db_session, EntryCollections, entry_id=eid, collection_id=hidden, sort_order=0)
            _insert(db_session, EntryAssets, entry_id=eid, asset_id=asset(f"hero-{i}"), position=0, role="hero")
            _insert(db_session, EntryAssets, entry_id=eid, asset_id=asset(f"gallery-{i}"), position=1, role="gallery")
            _insert(
                db_session,
                EntryAssets,
                entry_id=eid,
                asset_id=asset(f"suggested-{i}"),
                position=2,
                metadata_json={"suggested": True},
            )
            _insert(db_session, EntryResources, entry_id=eid, resource_id=material, position=0, role="primary-material")
            _insert(db_session, EntryTags, entry_id=eid, tag_id=tag)

        draft = _insert(db_session, Entries, group_id=gid, entry_type_id=project, title="Draft", slug=f"draft-{marker}", status="draft")
        _insert(db_session, EntryCollections, entry_id=draft, collection_id=projects, sort_order=99)
        _insert(db_session, EntryResources, entry_id=draft, resource_id=material, position=0)
        inquiry = _insert(
            db_session,
            Entries,
            group_id=gid,
            entry_type_id=private_type,
            title="Inquiry",
            slug=f"inquiry-{marker}",
            status="published",
            published_at=base,
        )
        _insert(db_session, EntryCollections, entry_id=inquiry, collection_id=projects, sort_order=98)
        db_session.commit()

        return SimpleNamespace(group=SimpleNamespace(id=gid, slug=group.slug), slugs=slugs, draft=f"draft-{marker}", inquiry=f"inquiry-{marker}")

    yield build

    for gid in created:
        entry_ids = [e.id for e in db_session.query(Entries.id).filter(Entries.group_id == gid)]
        for junction in (EntryAssets, EntryResources, EntryCollections, EntryTags):
            db_session.execute(junction.__table__.delete().where(junction.entry_id.in_(entry_ids)))
        asset_ids = [a.id for a in db_session.query(Assets.id).filter(Assets.group_id == gid)]
        db_session.execute(AssetTags.__table__.delete().where(AssetTags.asset_id.in_(asset_ids)))
        resource_ids = [r.id for r in db_session.query(Resources.id).filter(Resources.group_id == gid)]
        db_session.execute(ResourceTags.__table__.delete().where(ResourceTags.resource_id.in_(resource_ids)))
        for model in (Entries, Assets, Resources, Tags, Collections, EntryTypes, Users):
            db_session.execute(model.__table__.delete().where(model.group_id == gid))
        db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@pytest.fixture
def site(client: TestClient) -> Iterator[Callable[..., TestClient]]:
    """A client whose requests carry a site token of the given workspace and permissions.

    Token validation and the workspace match live in ``get_publishing_context`` and don't depend
    on ``expand``; overriding it pins the permissions each test needs."""

    def as_token(ws: SimpleNamespace, permissions: dict | None = None) -> TestClient:
        checker = PermissionChecker(SITE_TOKEN if permissions is None else permissions)
        app.dependency_overrides[get_publishing_context] = lambda: (None, ws.group, checker)
        return client

    yield as_token
    app.dependency_overrides.pop(get_publishing_context, None)


def _get(client: TestClient, path: str, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _single(client: TestClient, ws, slug: str) -> dict:
    return _get(client, f"/api/publish/{ws.group.slug}/entries/{slug}")


# ── an expanded item is the single read ─────────────────────────────────────────────────────────


def test_expanded_collection_items_equal_the_single_read(make_workspace, site):
    ws = make_workspace(3)
    client = site(ws)

    body = _get(client, f"/api/publish/{ws.group.slug}/collections/projects", expand="full")

    assert [e["slug"] for e in body["entries"]] == ws.slugs[::-1]  # by junction sort_order
    assert body["entryCount"] == 3
    for item in body["entries"]:
        single = _single(client, ws, item["slug"])
        assert single["order"] is None
        order = item.pop("order")
        single.pop("order")
        assert item == single
        assert isinstance(order, int)


def test_expanded_entries_list_items_equal_the_single_read(make_workspace, site):
    ws = make_workspace(3)
    client = site(ws)

    body = _get(client, f"/api/publish/{ws.group.slug}/entries", collection="projects", expand="full", limit=2, offset=1)

    assert body["meta"] == {"total": 3, "page": 1, "limit": 2, "offset": 1}
    assert [e["slug"] for e in body["data"]] == [ws.slugs[1], ws.slugs[0]]  # published_at desc, then paged
    for item in body["data"]:
        assert item == _single(client, ws, item["slug"])


def test_expanded_resource_entries_equal_the_single_read(make_workspace, site):
    ws = make_workspace(2)
    client = site(ws)

    body = _get(client, f"/api/publish/{ws.group.slug}/resources/waxed-canvas/entries", expand="full")

    assert sorted(e["slug"] for e in body) == sorted(ws.slugs)
    for item in body:
        assert item == _single(client, ws, item["slug"])


def test_expanded_item_has_what_a_list_item_lacks(make_workspace, site):
    """The point of expanding: placements with roles, resources, every public membership, embeds."""
    ws = make_workspace(1)
    client = site(ws)

    (item,) = _get(client, f"/api/publish/{ws.group.slug}/collections/projects", expand="full")["entries"]

    assert "assetSlugs" not in item and "resourceSlugs" not in item and "featuredAsset" not in item
    assert [(a["role"], a["asset"]["slug"], a["asset"]["tags"]) for a in item["assets"]] == [
        ("hero", "hero-0", ["leather"]),
        ("gallery", "gallery-0", ["leather"]),
    ]
    assert [(r["role"], r["resource"]["slug"], r["resource"]["tags"]) for r in item["resources"]] == [
        ("primary-material", "waxed-canvas", ["leather"])
    ]
    assert [c["collection"]["slug"] for c in item["collections"]] == ["projects"]
    assert item["data"]["n"] == 0 and item["tags"] == ["leather"]
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in item["embeds"]


# ── bounded queries ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("collections/projects", {"expand": "full"}),
        ("entries", {"expand": "full", "limit": 100}),
        ("entries", {"collection": "projects", "expand": "full", "limit": 100}),
        ("resources/waxed-canvas/entries", {"expand": "full"}),
    ],
)
def test_expanded_page_costs_the_same_queries_at_any_size(make_workspace, site, path, params):
    """A fixed number of queries per page: 2 entries or 12, with their assets, resources, tags
    and embeds. A lazy load per entry or per attachment would scale with the page."""
    counts = []
    for n in (2, 12):
        ws = make_workspace(n)
        client = site(ws)
        with count_queries() as statements:
            body = _get(client, f"/api/publish/{ws.group.slug}/{path}", **params)
        entries = body["entries"] if isinstance(body, dict) and "entries" in body else body["data"] if isinstance(body, dict) else body
        assert len(entries) == n
        counts.append(len(statements))

    assert counts[0] == counts[1], counts
    assert counts[1] <= 20, counts


def test_single_read_query_count_is_unchanged_by_attachments(make_workspace, site):
    ws = make_workspace(1)
    client = site(ws)

    with count_queries() as statements:
        _single(client, ws, ws.slugs[0])

    assert len(statements) <= 16, statements


# ── without expand: unchanged ───────────────────────────────────────────────────────────────────

LIST_ITEM_KEYS = set(PublishedEntryListItem(slug="s", title="t", entry_type="e", status="published").model_dump(by_alias=True))


def test_plain_responses_are_list_items(make_workspace, site):
    ws = make_workspace(2)
    client = site(ws)
    root = f"/api/publish/{ws.group.slug}"

    collection = _get(client, f"{root}/collections/projects")["entries"]
    entries = _get(client, f"{root}/entries", collection="projects")["data"]
    by_resource = _get(client, f"{root}/resources/waxed-canvas/entries")

    for items in (collection, entries, by_resource):
        assert items
        for item in items:
            assert set(item) == LIST_ITEM_KEYS
            assert item["assetSlugs"] == [s for s in item["assetSlugs"] if not s.startswith("suggested")]
            assert sorted(item["assetSlugs"]) == sorted([f"hero-{item['data']['n']}", f"gallery-{item['data']['n']}"])
            assert item["resourceSlugs"] == ["waxed-canvas"]
            assert item["featuredAsset"]["slug"] == f"hero-{item['data']['n']}"
            assert "assets" not in item and "resources" not in item


def test_plain_collection_still_serves_drafts_to_a_read_all_token(make_workspace, site):
    """Unchanged: a ``read:all_entries`` token sees a collection's drafts in the plain list."""
    ws = make_workspace(1)
    client = site(ws, {**SITE_TOKEN, Permissions.READ_ALL_ENTRIES: True})

    plain = _get(client, f"/api/publish/{ws.group.slug}/collections/projects")

    assert ws.draft in [e["slug"] for e in plain["entries"]]


def test_unknown_expand_value_is_rejected(make_workspace, site):
    ws = make_workspace(1)
    client = site(ws)

    response = client.get(f"/api/publish/{ws.group.slug}/collections/projects", params={"expand": "everything"})

    assert response.status_code == 422


# ── visibility and permissions match the single read ────────────────────────────────────────────


def test_expanded_collection_serves_only_what_the_single_read_serves(make_workspace, site):
    """Drafts and non-publishable types are out — even for a ``read:all_entries`` token, since the
    single read 404s them — and so are private collections and AI-suggested assets."""
    ws = make_workspace(2)
    client = site(ws, {**SITE_TOKEN, Permissions.READ_ALL_ENTRIES: True})
    root = f"/api/publish/{ws.group.slug}"

    expanded = _get(client, f"{root}/collections/projects", expand="full")
    by_resource = _get(client, f"{root}/resources/waxed-canvas/entries", expand="full")
    listed = _get(client, f"{root}/entries", expand="full", limit=100)

    for items in (expanded["entries"], by_resource, listed["data"]):
        assert sorted(e["slug"] for e in items) == sorted(ws.slugs)
        for item in items:
            assert all(c["collection"]["slug"] != "hidden" for c in item["collections"])
            assert all(not a["asset"]["slug"].startswith("suggested") for a in item["assets"])
    assert expanded["entryCount"] == 2
    for hidden in (ws.draft, ws.inquiry):
        assert client.get(f"{root}/entries/{hidden}").status_code == 404


@pytest.mark.parametrize(
    ("path", "permission"),
    [("collections/projects", Permissions.READ_COLLECTIONS), ("resources/waxed-canvas/entries", Permissions.READ_RESOURCES)],
)
def test_expanding_needs_the_single_read_permission(make_workspace, site, path, permission):
    ws = make_workspace(1)
    client = site(ws, {permission: True})
    url = f"/api/publish/{ws.group.slug}/{path}"

    assert client.get(url).status_code == 200
    assert client.get(url, params={"expand": "full"}).status_code == 403


def test_expanded_entries_list_needs_its_usual_permission(make_workspace, site):
    ws = make_workspace(1)
    client = site(ws, {Permissions.READ_COLLECTIONS: True})

    assert client.get(f"/api/publish/{ws.group.slug}/entries", params={"expand": "full"}).status_code == 403


def test_another_workspace_entries_never_appear(make_workspace, site):
    """A token is scoped to its own workspace: same collection slug elsewhere, none of its entries."""
    mine = make_workspace(1)
    theirs = make_workspace(2)
    client = site(mine)

    expanded = _get(client, f"/api/publish/{mine.group.slug}/collections/projects", expand="full")

    assert [e["slug"] for e in expanded["entries"]] == mine.slugs
    assert not set(theirs.slugs) & {e["slug"] for e in expanded["entries"]}


# ── the cap on unpaginated endpoints ────────────────────────────────────────────────────────────


def test_collection_past_the_cap_comes_back_unexpanded(make_workspace, site, monkeypatch):
    """Past ``PUBLISHING_MAX_EXPANDED_ENTRIES`` the response is the plain list, as from a server
    without ``expand``, so a client falls back to per-entry reads instead of failing."""
    monkeypatch.setattr(pub.settings, "PUBLISHING_MAX_EXPANDED_ENTRIES", 2)
    ws = make_workspace(3)
    client = site(ws)
    root = f"/api/publish/{ws.group.slug}"

    over = _get(client, f"{root}/collections/projects", expand="full")["entries"]
    by_resource = _get(client, f"{root}/resources/waxed-canvas/entries", expand="full")

    for items in (over, by_resource):
        assert len(items) == 3
        assert all("assetSlugs" in item and "assets" not in item for item in items)


def test_expanded_entries_page_keeps_the_page_size_cap(make_workspace, site):
    ws = make_workspace(1)
    client = site(ws)

    response = client.get(f"/api/publish/{ws.group.slug}/entries", params={"expand": "full", "limit": 101})

    assert response.status_code == 422
