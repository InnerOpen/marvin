"""The Assets and Resources libraries are filtered, sorted and paged in SQL (GET /assets, GET /resources, the Trash's
lists), and reading a page costs the same handful of statements however many rows it holds.

The pages used to ask for every asset or resource (787 assets live) and filter, sort and count them in the browser's
server: resources and Ask files were even loaded whole and picked in Python, and each row lazy-loaded its tags. Now
`limit`/`offset` cut a page in SQL, `X-Total-Count` says how many match in all, the filters the pages offer
(`searchable`, `trashed`, the resource filters) are SQL too, and tags come in one query for the page. Without the new
parameters every list answers as before.

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
from marvin.db.models.users.roles import WorkspaceRole
from tests.test_trash import _make_workspace

A = "/api/platform/assets"
R = "/api/platform/resources"
T = "/api/platform/trash"
BASE = datetime(2026, 1, 1, tzinfo=UTC)


@fixture
def lib(db_session):
    """A committed workspace with two tags, and makers for assets and resources."""
    from types import SimpleNamespace

    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.resources import Resources
    from marvin.db.models.platform.tags import Tags
    from marvin.db.models.users.roles import PlatformRole, workspace_role_has_higher_or_equal_privilege
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    w = _make_workspace(db_session, "libpaging")
    marker = w.gid.hex[:8]
    red = Tags(session=db_session, group_id=w.gid, name="Red", slug=f"red-{marker}")
    red.id = uuid.uuid4()
    blue = Tags(session=db_session, group_id=w.gid, name="Blue", slug=f"blue-{marker}")
    blue.id = uuid.uuid4()
    db_session.add_all([red, blue])
    db_session.commit()

    def asset(n: int, *, name=None, mime="image/png", alt="alt", trashed=False, scope="library", source=None, size=1) -> str:
        a = Assets(
            session=db_session, group_id=w.gid, slug=f"a{n}-{uuid.uuid4().hex[:6]}", name=name or f"A{n:03d}", original_filename="a.png",
            filename="a.png", extension="png", file_size=size, mime_type=mime, asset_type="image" if mime.startswith("image/") else "document",
            checksum="c", storage_provider="local", storage_key=f"libpaging/{marker}/{n}-{uuid.uuid4().hex[:6]}", uploaded_by=w.users["editor"],
            alt_text=alt, origin="derived" if source else "upload", source_asset_id=uuid.UUID(source) if source else None,
        )  # fmt: skip
        a.id = uuid.uuid4()
        a.scope = scope
        a.created_at = BASE + timedelta(minutes=n)
        a.trashed_at = datetime(2026, 6, 1) if trashed else None
        a.tags = [red, blue]
        db_session.add(a)
        db_session.commit()
        return str(a.id)

    def resource(n: int, *, name=None, kind="supplier", url=None, external_id=None, description=None, trashed=False, tag=True) -> str:
        r = Resources(
            session=db_session, group_id=w.gid, slug=f"r{n}-{uuid.uuid4().hex[:6]}", name=name or f"R{n:03d}", resource_type=kind, url=url,
            external_id=external_id, description=description, created_by=w.users["editor"],
        )  # fmt: skip
        r.id = uuid.uuid4()
        r.trashed_at = datetime(2026, 6, 1) if trashed else None
        r.tags = [red] if tag else []
        db_session.add(r)
        db_session.commit()
        return str(r.id)

    def sign_in(role=WorkspaceRole.EDITOR) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=w.users["editor"], group_id=w.gid, active_group_id=w.gid, admin=False, is_superuser=False, full_name="editor",
            email="editor@t.test", platform_role=PlatformRole.NONE, workspace_memberships=[SimpleNamespace(group_id=w.gid, workspace_role=role)],
            get_workspace_role=lambda g: role if str(g) == str(w.gid) else None,
            has_workspace_role=lambda g, req: str(g) == str(w.gid) and workspace_role_has_higher_or_equal_privilege(role, req),
        )  # fmt: skip
        return TestClient(app)

    yield SimpleNamespace(gid=w.gid, asset=asset, resource=resource, sign_in=sign_in, red=red, blue=blue, session=db_session)
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    purge_group_dependents(db_session, w.gid)
    db_session.query(Resources).filter(Resources.group_id == w.gid).delete()
    db_session.query(Assets).filter(Assets.group_id == w.gid).delete()
    db_session.query(Users).filter(Users.group_id == w.gid).delete()
    db_session.query(Groups).filter(Groups.id == w.gid).delete()
    db_session.commit()


def _ids(res) -> list[str]:
    assert res.status_code == 200, res.text
    return [row["id"] for row in res.json()]


def _total(res) -> int:
    return int(res.headers["x-total-count"])


# --- Assets -------------------------------------------------------------------------------------------------------


def test_limit_and_offset_page_the_assets_with_the_total_and_past_the_end(lib):
    ids = [lib.asset(n) for n in range(7)]  # A000..A006: by name
    client = lib.sign_in()
    pages = [client.get(A, params={"limit": 3, "offset": off}) for off in (0, 3, 6, 9)]
    assert [_ids(p) for p in pages] == [ids[0:3], ids[3:6], ids[6:7], []]  # the last page is partial, past the end is empty
    assert {_total(p) for p in pages} == {7}
    whole = client.get(A)
    assert _ids(whole) == ids and _total(whole) == 7  # no limit: all of them, as before
    assert client.get(A, params={"limit": 0}).status_code == 422
    assert client.get(A, params={"offset": -1}).status_code == 422


def test_filters_and_sort_carry_across_pages_and_the_total_counts_the_matches(lib):
    big = [lib.asset(n, size=100 + n) for n in range(5)]
    lib.asset(10, mime="application/pdf", size=999)  # the largest, but not an image
    client = lib.sign_in()
    params = {"asset_type": "image", "sort": "largest", "limit": 2}
    paged = [i for off in (0, 2, 4) for i in _ids(client.get(A, params={**params, "offset": off}))]
    assert paged == big[::-1]
    assert _total(client.get(A, params=params)) == 5
    assert _ids(client.get(A, params={"q": "A003"})) == [big[3]]


def test_the_same_sort_key_still_pages_in_one_stable_order(lib):
    ids = [lib.asset(n, name="Same", size=5) for n in range(5)]
    client = lib.sign_in()
    for sort in ("name", "largest"):
        paged = [i for off in range(0, 5, 2) for i in _ids(client.get(A, params={"sort": sort, "limit": 2, "offset": off}))]
        assert sorted(paged) == sorted(ids) and len(paged) == 5
        assert paged == _ids(client.get(A, params={"sort": sort}))


def test_searchable_picks_the_pictures_search_cant_find(lib):
    bare = lib.asset(1, alt=None)
    blank = lib.asset(2, alt="   ")
    described = lib.asset(3)
    document = lib.asset(4, mime="application/pdf", alt=None)  # not a picture: search finds it by name
    client = lib.sign_in()
    res = client.get(A, params={"searchable": "false", "limit": 1})
    assert _total(res) == 2 and _ids(res) == [bare]
    assert _ids(client.get(A, params={"searchable": "false"})) == [bare, blank]
    assert _ids(client.get(A, params={"searchable": "true"})) == [described, document]


def test_the_trash_pages_with_the_filters_and_keeps_ask_files_and_versions(lib):
    original = lib.asset(1)
    lib.asset(2)
    version = lib.asset(3, trashed=True, source=original)  # a trashed version of an original still in the library
    ask = lib.asset(4, trashed=True, scope="ask")  # deleted from the Ask files page: the Trash is where it comes back from
    gone = [lib.asset(n, trashed=True) for n in range(5, 8)]
    client = lib.sign_in()
    trash = [version, ask, *gone]
    pages = [client.get(A, params={"trashed": "true", "limit": 2, "offset": off}) for off in (0, 2, 4, 6)]
    assert [_ids(p) for p in pages] == [trash[0:2], trash[2:4], trash[4:5], []]
    assert {_total(p) for p in pages} == {5}
    assert _ids(client.get(A, params={"trashed": "true", "q": "A006"})) == [gone[1]]
    assert _ids(client.get(A, params={"trashed": "true", "sort": "newest", "limit": 1})) == [gone[-1]]
    assert _total(client.get(A, params={"limit": 1})) == 2  # the library leaves the Trash out


def test_the_trash_lists_page_and_answer_as_before_without_params(lib):
    ids = [lib.asset(n, trashed=True) for n in range(4)]
    lib.asset(9)
    rids = [lib.resource(n, trashed=True) for n in range(3)]
    client = lib.sign_in()
    whole = client.get(f"{T}/assets")
    assert _ids(whole) == ids[::-1] and _total(whole) == 4  # by name, Z first, as it always was
    page = client.get(f"{T}/assets", params={"limit": 2, "offset": 2})
    assert _ids(page) == ids[::-1][2:4] and _total(page) == 4
    assert _ids(client.get(f"{T}/resources")) == rids[::-1]
    assert _ids(client.get(f"{T}/resources", params={"limit": 1, "offset": 1})) == [rids[1]]


def test_ask_files_page_newest_first_with_the_total(lib):
    asks = [lib.asset(n, scope="ask") for n in range(4)]
    lib.asset(9)
    lib.asset(10, scope="ask", trashed=True)
    client = lib.sign_in()
    whole = client.get(A, params={"scope": "ask"})
    assert _ids(whole) == asks[::-1] and _total(whole) == 4
    res = client.get(A, params={"scope": "ask", "limit": 1})
    assert _ids(res) == [asks[-1]] and _total(res) == 4


def test_the_counts_on_the_page_agree_with_the_lists(lib):
    """'The Trash (N)' and the Ask files button read a one-row page's total: the same rows the lists show."""
    for n in range(3):
        lib.asset(n, trashed=True)
    lib.asset(5, trashed=True, scope="ask")
    lib.asset(6, scope="ask")
    client = lib.sign_in()
    assert _total(client.get(A, params={"trashed": "true", "limit": 1})) == len(_ids(client.get(f"{T}/assets"))) == 4
    assert _total(client.get(A, params={"scope": "ask", "limit": 1})) == 1


# --- Resources ----------------------------------------------------------------------------------------------------


def test_resources_answer_as_before_without_params(lib):
    ids = [lib.resource(n) for n in range(4)]
    lib.resource(9, trashed=True)
    res = lib.sign_in().get(R)
    assert _ids(res) == ids[::-1] and _total(res) == 4  # by name, Z first, as it always was
    assert res.json()[0]["tags"] == [lib.red.slug]


def test_resources_filter_sort_and_page_in_sql(lib):
    hammer = lib.resource(1, name="Hammer", kind="tool", url="https://h.test")
    acme = lib.resource(2, name="Acme", kind="supplier", description="Sells hammers", external_id="SUP-1")
    lib.resource(3, name="Bolt", kind="supplier", tag=False)
    lib.resource(4, name="Hammer old", kind="tool", trashed=True)
    client = lib.sign_in()
    assert _ids(client.get(R, params={"q": "hammer", "sort": "name"})) == [acme, hammer]  # the description counts
    assert _ids(client.get(R, params={"resource_type": "tool"})) == [hammer]
    assert _ids(client.get(R, params={"has_url": "true"})) == [hammer]
    assert len(_ids(client.get(R, params={"has_url": "false"}))) == 2
    assert _ids(client.get(R, params={"has_external_id": "true"})) == [acme]
    assert sorted(_ids(client.get(R, params={"tag": lib.red.slug}))) == sorted([hammer, acme])
    assert _ids(client.get(R, params={"tag": "no-such-tag"})) == []  # a stale link matches nothing, not an error
    by_type = client.get(R, params={"sort": "type", "limit": 2})
    assert [r["name"] for r in by_type.json()] == ["Acme", "Bolt"] and _total(by_type) == 3
    trash = client.get(R, params={"trashed": "true", "q": "hammer"})
    assert [r["name"] for r in trash.json()] == ["Hammer old"] and _total(trash) == 1


def test_resources_page_without_overlap_and_past_the_end_in_one_stable_order(lib):
    ids = [lib.resource(n, name="Same") for n in range(5)]
    client = lib.sign_in()
    pages = [client.get(R, params={"sort": "name", "limit": 2, "offset": off}) for off in (0, 2, 4, 6)]
    paged = [i for p in pages for i in _ids(p)]
    assert sorted(paged) == sorted(ids) and len(paged) == 5 and _ids(pages[-1]) == []
    assert paged == _ids(client.get(R, params={"sort": "name"}))
    assert {_total(p) for p in pages} == {5}


# --- Statements per page ------------------------------------------------------------------------------------------


def _statements(fn) -> int:
    """SQL statements ``fn`` runs, but the storage choice's read: it is cached for a few seconds, so whether it runs is timing."""
    count = [0]

    def on_execute(_conn, _cursor, statement, *_a, **_k):
        count[0] += "platform_settings" not in statement

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        res = fn()
        assert res.status_code == 200, res.text
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
    return count[0]


@pytest.mark.parametrize(
    "path, params, make",
    [
        (A, {"versions": "false"}, lambda lib, n: lib.asset(n)),
        (A, {"limit": 50}, lambda lib, n: lib.asset(n)),
        (A, {"trashed": "true", "limit": 50}, lambda lib, n: lib.asset(n, trashed=True)),
        (A, {"scope": "ask"}, lambda lib, n: lib.asset(n, scope="ask")),
        (f"{T}/assets", {}, lambda lib, n: lib.asset(n, trashed=True)),
        (R, {}, lambda lib, n: lib.resource(n)),
        (R, {"sort": "name", "limit": 50}, lambda lib, n: lib.resource(n)),
        (f"{T}/resources", {}, lambda lib, n: lib.resource(n, trashed=True)),
    ],
    ids=["assets", "assets-page", "assets-trash", "ask-files", "trash-assets", "resources", "resources-page", "trash-resources"],
)
def test_a_page_costs_the_same_statements_however_many_rows_it_holds(lib, path, params, make):
    """Tags (and an asset's versions count) come in one query for the page, never one per row."""
    client = lib.sign_in()
    for n in range(2):
        make(lib, n)
    few = _statements(lambda: client.get(path, params=params))
    for n in range(2, 12):
        make(lib, n)
    many = _statements(lambda: client.get(path, params=params))
    assert many == few
    first = client.get(path, params=params).json()[0]
    assert first["tags"]
