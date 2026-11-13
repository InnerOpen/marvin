"""The entry list is filtered and paged in SQL (GET /entries, GET /collections/{id}/entries), and reading a page costs the
same handful of statements however many entries it holds.

`GET /entries` used to load every entry of the workspace (the Trash and internal types too), drop those in Python, and
validate each row with three lazy loads of relationships it then threw away; the live list took 6 s. Now the Trash and
internal types are left out by the query, `limit`/`offset`/`entry_type_id` narrow it, `X-Total-Count` says how many in all,
and what EntryRead reads is loaded up front (selectin), so the statement count doesn't grow with the page.

HTTP tests commit for real (the app opens its own sessions) and purge the workspace afterwards.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import event

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.db_setup import engine
from marvin.db.models.platform import Entries, EntryAssets, EntryCollections, EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from tests.test_trash import _make_workspace

E = "/api/platform/entries"
BASE = datetime(2026, 1, 1, tzinfo=UTC)


@fixture
def lib(db_session):
    """A committed workspace: a listed type, an internal (unlisted) one, a collection, an asset and a tag to attach."""
    from types import SimpleNamespace

    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.tags import Tags
    from marvin.db.models.users.roles import PlatformRole, workspace_role_has_higher_or_equal_privilege
    from marvin.db.models.users.users import Users
    from marvin.services.collections.system_collections import seed_system_workflow_collections
    from marvin.services.group.group_purge import purge_group_dependents

    w = _make_workspace(db_session, "paging")
    marker = w.gid.hex[:8]
    seed_system_workflow_collections(db_session, w.gid)
    internal = EntryTypes(session=db_session, group_id=w.gid, name="Rule", slug=f"rule-{marker}", schema_json={}, capabilities_json={"listed": False})
    internal.id = uuid.uuid4()
    col = Collections(session=db_session, group_id=w.gid, slug=f"shelf-{marker}", name="Shelf")
    col.id = uuid.uuid4()
    tag = Tags(session=db_session, group_id=w.gid, name="Red", slug=f"red-{marker}")
    tag.id = uuid.uuid4()
    db_session.add_all([internal, col, tag])
    db_session.flush()
    assets = []
    for i in range(3):
        a = Assets(session=db_session, group_id=w.gid, slug=f"a{i}-{marker}", name=f"A{i}", original_filename="a.png", filename="a.png",
                   extension="png", file_size=1, mime_type="image/png", asset_type="image", checksum="c", storage_provider="local",
                   storage_key=f"paging/{marker}/a{i}.png", uploaded_by=w.users["editor"])  # fmt: skip
        a.id = uuid.uuid4()
        a.tags = [tag]
        assets.append(a)
    db_session.add_all(assets)
    db_session.commit()

    def entry(n: int, status="draft", entry_type=None, attach=False):
        e = Entries(
            session=db_session, group_id=w.gid, entry_type_id=(entry_type or w.entry_type).id, title=f"E{n:03d}", slug=f"e{n}-{uuid.uuid4().hex[:8]}"
        )
        e.id = uuid.uuid4()
        e.status = status
        e.created_by = w.users["editor"]
        e.created_at = BASE + timedelta(minutes=n)  # entry n is the n-th newest from the bottom
        db_session.add(e)
        db_session.flush()
        if attach:
            db_session.add(EntryCollections(entry_id=e.id, collection_id=col.id, sort_order=n))
            for p, a in enumerate(assets[:2]):
                db_session.add(EntryAssets(entry_id=e.id, asset_id=a.id, position=p))
            e.tags = [tag]
        db_session.commit()
        return str(e.id)

    def sign_in(role=WorkspaceRole.EDITOR) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=w.users["editor"], group_id=w.gid, active_group_id=w.gid, admin=False, is_superuser=False, full_name="editor",
            email="editor@t.test", platform_role=PlatformRole.NONE, workspace_memberships=[SimpleNamespace(group_id=w.gid, workspace_role=role)],
            get_workspace_role=lambda g: role if str(g) == str(w.gid) else None,
            has_workspace_role=lambda g, req: str(g) == str(w.gid) and workspace_role_has_higher_or_equal_privilege(role, req),
        )  # fmt: skip
        return TestClient(app)

    yield SimpleNamespace(gid=w.gid, entry=entry, sign_in=sign_in, internal=internal, listed=w.entry_type, collection=col, session=db_session)
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    purge_group_dependents(db_session, w.gid)
    db_session.query(Assets).filter(Assets.group_id == w.gid).delete()
    db_session.query(Users).filter(Users.group_id == w.gid).delete()
    db_session.query(Groups).filter(Groups.id == w.gid).delete()
    db_session.commit()


def _ids(res) -> list[str]:
    return [e["id"] for e in res.json()]


def test_the_list_leaves_out_the_trash_and_internal_types_newest_first_with_the_total(lib):
    kept = [lib.entry(n) for n in range(4)]
    lib.entry(10, status="trashed")
    lib.entry(11, entry_type=lib.internal)
    res = lib.sign_in().get(E)
    assert res.status_code == 200
    assert _ids(res) == kept[::-1]
    assert res.headers["x-total-count"] == "4"


def test_limit_and_offset_page_the_list_without_overlap_and_past_the_end(lib):
    ids = [lib.entry(n) for n in range(7)][::-1]  # newest first
    client = lib.sign_in()
    pages = [client.get(E, params={"limit": 3, "offset": off}) for off in (0, 3, 6, 9)]
    assert [_ids(p) for p in pages] == [ids[0:3], ids[3:6], ids[6:7], []]  # the last page is partial, past the end is empty
    assert {p.headers["x-total-count"] for p in pages} == {"7"}
    assert client.get(E, params={"limit": 0}).status_code == 422
    assert client.get(E, params={"offset": -1}).status_code == 422


def test_the_same_created_at_still_pages_in_one_stable_order(lib):
    ids = [lib.entry(5) for _ in range(5)]  # all created at the same moment
    client = lib.sign_in()
    paged = [i for off in range(0, 5, 2) for i in _ids(client.get(E, params={"limit": 2, "offset": off}))]
    assert sorted(paged) == sorted(ids) and len(paged) == 5
    assert paged == _ids(client.get(E))


def test_entry_type_id_narrows_the_list_and_names_an_internal_type(lib):
    listed = lib.entry(1)
    rule = lib.entry(2, entry_type=lib.internal)
    lib.entry(3, entry_type=lib.internal, status="trashed")
    client = lib.sign_in()
    assert _ids(client.get(E, params={"entry_type_id": str(lib.listed.id)})) == [listed]
    res = client.get(E, params={"entry_type_id": str(lib.internal.id)})
    assert _ids(res) == [rule] and res.headers["x-total-count"] == "1"  # named, it is listed; its trashed one still is not


def test_the_list_never_loads_a_trashed_row(lib):
    """The regression: the Trash used to be loaded whole and thrown away in Python."""
    for n in range(3):
        lib.entry(n)
    for n in range(10, 15):
        lib.entry(n, status="trashed")
    loaded: list[str] = []

    def on_load(target, _ctx):
        loaded.append(target.status)

    event.listen(Entries, "load", on_load)
    try:
        assert len(_ids(lib.sign_in().get(E))) == 3
    finally:
        event.remove(Entries, "load", on_load)
    assert loaded and "trashed" not in loaded


def _statements(fn) -> int:
    """SQL statements ``fn`` runs, but the storage choice's read: it is cached for a few seconds, so whether it runs is timing."""
    count = [0]

    def on_execute(_conn, _cursor, statement, *_a, **_k):
        count[0] += "platform_settings" not in statement

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        assert fn().status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
    return count[0]


@pytest.mark.parametrize(
    "call",
    [
        lambda c, lib: c.get(E),
        lambda c, lib: c.post(f"{E}/query", json={"spec": {}, "limit": 100}),
        lambda c, lib: c.get(f"/api/platform/collections/{lib.collection.id}/entries"),
    ],
    ids=["list", "query", "collection"],
)
def test_a_page_costs_the_same_statements_however_many_entries_it_holds(lib, call):
    """What EntryRead reads (collections, assets and their tags, tags) comes in a few queries for the page, never per entry."""
    client = lib.sign_in()
    for n in range(2):
        lib.entry(n, attach=True)
    few = _statements(lambda: call(client, lib))
    for n in range(2, 12):
        lib.entry(n, attach=True)
    many = _statements(lambda: call(client, lib))
    assert many == few
    body = call(client, lib).json()
    first = (body["entries"] if isinstance(body, dict) else body)[0]
    assert len(first["assets"]) == 2 and first["assets"][0]["tags"] and first["tags"] and first["collections"][0]["slug"].startswith("shelf-")


def test_counts_by_type_count_as_the_list_does(lib):
    for n in range(3):
        lib.entry(n)
    lib.entry(5, status="trashed")
    lib.entry(6, entry_type=lib.internal)
    res = lib.sign_in().get(f"{E}/counts/by-type")
    assert res.status_code == 200
    assert res.json() == {str(lib.listed.id): 3}


def test_collection_entries_page_in_collection_order_with_the_total(lib):
    ids = [lib.entry(n, attach=True) for n in range(5)]  # sort_order n
    lib.session.query(Entries).filter(Entries.id == uuid.UUID(ids[1])).update({"status": "trashed"})
    lib.session.commit()
    shown = [ids[0], ids[2], ids[3], ids[4]]
    client = lib.sign_in()
    url = f"/api/platform/collections/{lib.collection.id}/entries"
    pages = [client.get(url, params={"limit": 3, "offset": off}) for off in (0, 3, 6)]
    assert [_ids(p) for p in pages] == [shown[0:3], shown[3:4], []]
    assert {p.headers["x-total-count"] for p in pages} == {"4"}
    whole = client.get(url)
    assert _ids(whole) == shown and whole.headers["x-total-count"] == "4"  # no limit: all of them, as before


def test_the_upload_provider_is_built_once_per_settings_not_per_asset_url():
    """Every asset URL in a list asks for the provider; building a remote one makes a boto3 client (~20 ms), which made a
    1,300-entry list take 16 s on S3."""
    from marvin.core.config import get_app_settings
    from marvin.services.storage import provider_factory

    settings = get_app_settings()
    assert provider_factory.get_storage_provider(settings) is provider_factory.get_storage_provider(settings)
