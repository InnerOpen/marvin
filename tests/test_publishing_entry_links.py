"""An entry's ``asset`` / ``asset-list`` / ``resource`` / ``resource-list`` data fields hold ids a site can no
longer look up (the publishing API has no asset or resource endpoints), so every entry read serves the
published objects instead: the single read, the list item and ``?expand=full``. Trashed, missing and Ask-scoped
ones are dropped, order is kept, and a value that isn't an id passes through."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from marvin.db.models.platform import Assets, Entries, EntryTypes, Resources
from marvin.services.storage.provider_factory import asset_public_url
from tests.test_publishing_expand import count_queries, make_workspace, site  # noqa: F401 — publishing fixtures

FIELDS = [
    {"key": "video", "type": "embed"},
    {"key": "cover", "type": "asset"},
    {"key": "gallery", "type": "asset-list"},
    {"key": "material", "type": "resource"},
    {"key": "relatedResources", "type": "resource-list"},
]
OUTSIDE_URL = "https://cdn.example.test/outside.jpg"


def _asset(db_session, ws, slug: str) -> Assets:
    return db_session.query(Assets).filter(Assets.group_id == ws.group.id, Assets.slug == slug).one()


def _copy_asset(db_session, source: Assets, slug: str, **changes) -> Assets:
    """Another asset like ``source`` (the publishing fixture only makes four a workspace)."""
    values = {c.name: getattr(source, c.name) for c in Assets.__table__.columns}
    values.update(id=uuid.uuid4(), slug=slug, checksum=uuid.uuid4().hex, storage_key=f"k/{uuid.uuid4().hex}", **changes)
    db_session.execute(Assets.__table__.insert().values(**values))
    return _asset(db_session, SimpleNamespace(group=SimpleNamespace(id=source.group_id)), slug)


def _entries(db_session, ws) -> list[Entries]:
    return [db_session.query(Entries).filter(Entries.group_id == ws.group.id, Entries.slug == s).one() for s in ws.slugs]


def _link(db_session, ws) -> dict:
    """Give the workspace's project type the link fields and every entry some links, good and bad. Returns the rows."""
    db_session.query(EntryTypes).filter(EntryTypes.group_id == ws.group.id, EntryTypes.slug == "project").one().schema_json = {"fields": FIELDS}
    gid = ws.group.id
    waxed = db_session.query(Resources).filter(Resources.group_id == gid, Resources.slug == "waxed-canvas").one()
    made = {"group_id": gid, "resource_type": "material", "created_by": waxed.created_by}
    other = Resources(session=db_session, slug="oiled-cotton", name="Oiled Cotton", **made)
    gone = Resources(session=db_session, slug="old-thread", name="Old Thread", trashed_at=datetime.now(UTC), **made)
    db_session.add_all([other, gone])
    db_session.flush()
    first = _asset(db_session, ws, "gallery-0")
    second = _asset(db_session, ws, "hero-0")
    trashed = _asset(db_session, ws, "suggested-0")
    trashed.trashed_at = datetime.now(UTC)
    ask = _copy_asset(db_session, first, "chat-upload", scope="ask")
    for entry in _entries(db_session, ws):
        entry.data_json = {
            **entry.data_json,
            "cover": str(second.id),
            # order is the field's, not the asset's age or slug; the rest are dropped (trashed, Ask file, no such id)
            "gallery": [str(first.id), str(trashed.id), str(uuid.uuid4()), str(ask.id), str(second.id), OUTSIDE_URL],
            "material": str(waxed.id),
            "relatedResources": [str(other.id), str(gone.id), str(waxed.id)],
        }
    db_session.commit()
    return {"first": first, "second": second, "waxed": waxed, "other": other}


def _asset_slugs(value) -> list:
    return [v if isinstance(v, str) else v["slug"] for v in value]


def _check(data: dict, rows: dict) -> None:
    assert data["cover"]["slug"] == "hero-0" and data["cover"]["publicUrl"] == asset_public_url(rows["second"])
    assert _asset_slugs(data["gallery"]) == ["gallery-0", "hero-0", OUTSIDE_URL]  # in order; trashed, Ask, missing dropped; URL kept
    assert data["gallery"][0]["publicUrl"] == asset_public_url(rows["first"]) and data["gallery"][0]["mimeType"] == "image/jpeg"
    assert data["gallery"][0]["tags"] == ["leather"]
    assert data["material"]["slug"] == "waxed-canvas" and data["material"]["resourceType"] == "material" and data["material"]["tags"] == ["leather"]
    assert [r["slug"] for r in data["relatedResources"]] == ["oiled-cotton", "waxed-canvas"]
    assert data["video"].startswith("https://www.youtube.com/") and "n" in data  # other data is untouched


def test_the_single_read_serves_the_objects(db_session, make_workspace, site):  # noqa: F811
    ws = make_workspace(2)
    rows = _link(db_session, ws)
    client = site(ws)
    body = client.get(f"/api/publish/{ws.group.slug}/entries/{ws.slugs[0]}").json()
    _check(body["data"], rows)


def test_list_items_and_expanded_items_serve_them_too(db_session, make_workspace, site):  # noqa: F811
    ws = make_workspace(2)
    rows = _link(db_session, ws)
    client = site(ws)
    root = f"/api/publish/{ws.group.slug}"
    pages = [
        client.get(f"{root}/entries").json()["data"],
        client.get(f"{root}/entries", params={"expand": "full"}).json()["data"],
        client.get(f"{root}/collections/projects").json()["entries"],
        client.get(f"{root}/collections/projects", params={"expand": "full"}).json()["entries"],
    ]
    for items in pages:
        assert len(items) == 2
        for item in items:
            _check(item["data"], rows)


def test_a_trashed_single_asset_or_resource_is_null(db_session, make_workspace, site):  # noqa: F811
    ws = make_workspace(1)
    rows = _link(db_session, ws)
    rows["second"].trashed_at = datetime.now(UTC)
    rows["waxed"].trashed_at = datetime.now(UTC)
    db_session.commit()
    data = site(ws).get(f"/api/publish/{ws.group.slug}/entries/{ws.slugs[0]}").json()["data"]
    assert data["cover"] is None and data["material"] is None
    assert _asset_slugs(data["gallery"]) == ["gallery-0", OUTSIDE_URL]
    assert [r["slug"] for r in data["relatedResources"]] == ["oiled-cotton"]


def test_values_that_are_not_ids_pass_through(db_session, make_workspace, site):  # noqa: F811
    ws = make_workspace(1)
    _link(db_session, ws)
    resolved = {"slug": "already", "publicUrl": OUTSIDE_URL}
    entry = _entries(db_session, ws)[0]
    entry.data_json = {
        **entry.data_json,
        "cover": resolved,
        "gallery": [resolved, OUTSIDE_URL],
        "material": OUTSIDE_URL,
        "relatedResources": "not-a-list",
    }
    db_session.commit()
    data = site(ws).get(f"/api/publish/{ws.group.slug}/entries/{ws.slugs[0]}").json()["data"]
    assert data["cover"] == resolved and data["gallery"] == [resolved, OUTSIDE_URL]
    assert data["material"] == OUTSIDE_URL and data["relatedResources"] == "not-a-list"


def test_an_entry_without_link_fields_is_served_as_stored(db_session, make_workspace, site):  # noqa: F811
    ws = make_workspace(1)  # the project type here has no link fields; ids in data mean nothing
    entry = _entries(db_session, ws)[0]
    entry.data_json = {**entry.data_json, "gallery": [str(uuid.uuid4())]}
    db_session.commit()
    data = site(ws).get(f"/api/publish/{ws.group.slug}/entries/{ws.slugs[0]}").json()["data"]
    assert data["gallery"] == entry.data_json["gallery"]


def test_a_page_costs_the_same_queries_at_any_size(db_session, make_workspace, site):  # noqa: F811
    counts = []
    for n in (2, 12):
        ws = make_workspace(n)
        _link(db_session, ws)
        client = site(ws)
        with count_queries() as statements:
            items = client.get(f"/api/publish/{ws.group.slug}/entries", params={"limit": 100}).json()["data"]
        assert len(items) == n
        counts.append(len(statements))
    assert counts[0] == counts[1], counts
