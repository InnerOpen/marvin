"""DB-backed tests: a collection PATCHed to ``is_public=False`` disappears from the publishing API.

The admin UI's "Visible to sites" toggle sends ``is_public`` through the collection update path.
These pin what "private" means to a site: the collection is not listed, its detail 404s, the
``?collection=`` entry filter returns nothing, and entries no longer name it — while the entries
themselves stay published and readable.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes
from marvin.repos.all_repositories import get_repositories
from marvin.routes.publish import publishing_controller as pub
from marvin.schemas.platform.collections import CollectionUpdate

PAGE = 50


class _AllowAll:
    """Publishing permissions stub: everything granted except reading unpublished entries."""

    def require_permission(self, *_):
        return None

    def require_any_permission(self, *_):
        return None

    def has_permission(self, *_):
        return False


@fixture
def workspace(db_session):
    """A workspace with one published entry inside one (public, by default) collection."""
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"pub-priv-{marker}", slug=f"pub-priv-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()

    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="T", slug=f"t-{marker}", status="published")
    db_session.add(entry)
    coll = Collections(session=db_session, group_id=gid, name="Featured", slug="featured")
    db_session.add(coll)
    db_session.flush()
    db_session.add(EntryCollections(entry_id=entry.id, collection_id=coll.id))
    db_session.commit()

    yield SimpleNamespace(group=group, entry_slug=entry.slug, coll_id=coll.id)

    db_session.query(EntryCollections).filter(EntryCollections.collection_id == coll.id).delete()
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _ctx(ws):
    return (None, ws.group, _AllowAll())


def _make_private(db_session, ws):
    get_repositories(db_session, group_id=ws.group.id).collections.update(ws.coll_id, CollectionUpdate(is_public=False))


def _list_collections(db_session, ws):
    return asyncio.run(pub.list_published_collections(context=_ctx(ws), session=db_session, limit=PAGE, offset=0))


def _list_entries(db_session, ws, collection=None):
    return asyncio.run(
        pub.list_published_entries(
            context=_ctx(ws),
            session=db_session,
            entry_type=None,
            collection=collection,
            tag=None,
            slug=None,
            updated_since=None,
            limit=PAGE,
            offset=0,
        )
    )


def _get_entry(db_session, ws):
    return asyncio.run(pub.get_published_entry(slug=ws.entry_slug, context=_ctx(ws), session=db_session))


def test_public_collection_is_served_by_publishing_endpoints(db_session, workspace):
    ws = workspace

    listed = [c.slug for c in _list_collections(db_session, ws).data]
    filtered = [e.slug for e in _list_entries(db_session, ws, collection="featured").data]
    detail = asyncio.run(pub.get_published_collection(collection_slug="featured", context=_ctx(ws), session=db_session))

    assert listed == ["featured"]
    assert filtered == [ws.entry_slug]
    assert detail.slug == "featured"


def test_patch_is_public_false_hides_collection_from_list_and_detail(db_session, workspace):
    ws = workspace
    _make_private(db_session, ws)

    listed = _list_collections(db_session, ws)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pub.get_published_collection(collection_slug="featured", context=_ctx(ws), session=db_session))

    assert listed.data == [] and listed.meta.total == 0
    assert exc.value.status_code == 404


def test_patch_is_public_false_empties_the_collection_entry_filter(db_session, workspace):
    ws = workspace
    _make_private(db_session, ws)

    filtered = _list_entries(db_session, ws, collection="featured")

    assert filtered.data == [] and filtered.meta.total == 0


def test_private_collection_entries_stay_published_without_naming_it(db_session, workspace):
    ws = workspace
    _make_private(db_session, ws)

    listed = _list_entries(db_session, ws).data
    detail = _get_entry(db_session, ws)

    assert [e.slug for e in listed] == [ws.entry_slug]
    assert listed[0].collections == [] and detail.collections == []
