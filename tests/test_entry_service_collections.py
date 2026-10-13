"""DB-backed tests for EntryService collection membership (add_to_collection / remove_from_collection).

The membership mutation + its events were extracted out of the entry controller into EntryService so
the automation `entry` action (add_to_collection / remove_from_collection) can reuse them. These pin
the contract the controller and the automation action both depend on: idempotent add/remove, the
right events emitted only on an actual change, and resolution by slug/name/id within the workspace.
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes
from marvin.services.entries import EntryService


class _SpyBus:
    def __init__(self):
        self.events = []

    def dispatch(self, *, event_type, **_):
        self.events.append(event_type.name)


@fixture
def workspace(db_session):
    """A throwaway workspace with one entry + two collections (one addressed by slug, one by name)."""
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"col-test-{marker}", slug=f"col-test-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="T", slug=f"t-{marker}")
    db_session.add(entry)

    coll = Collections(session=db_session, group_id=gid, name="Featured Posts", slug="featured")
    db_session.add(coll)
    db_session.commit()

    yield gid, entry.id, coll.id

    db_session.query(EntryCollections).filter(EntryCollections.collection_id == coll.id).delete()
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _svc(db_session, gid):
    bus = _SpyBus()
    return EntryService(db_session, gid, event_bus=bus, integration_id="automation"), bus


def _member_count(db_session, entry_id, coll_id) -> int:
    return db_session.query(EntryCollections).filter(EntryCollections.entry_id == entry_id, EntryCollections.collection_id == coll_id).count()


def test_add_to_collection_by_slug_emits_and_persists(db_session, workspace):
    gid, entry_id, coll_id = workspace
    svc, bus = _svc(db_session, gid)

    result = svc.add_to_collection(entry_id, "featured", reaction_depth=2)

    assert result == "added"
    assert _member_count(db_session, entry_id, coll_id) == 1
    assert bus.events == ["entry_added_to_collection"]


def test_add_by_name_and_by_id_also_resolve(db_session, workspace):
    gid, entry_id, coll_id = workspace
    svc, _ = _svc(db_session, gid)
    assert svc.add_to_collection(entry_id, "Featured Posts") == "added"  # by name
    svc.remove_from_collection(entry_id, coll_id)  # by id (uuid)
    assert svc.add_to_collection(entry_id, str(coll_id)) == "added"  # by id string
    assert _member_count(db_session, entry_id, coll_id) == 1


def test_add_is_idempotent_no_duplicate_no_second_event(db_session, workspace):
    gid, entry_id, coll_id = workspace
    svc, bus = _svc(db_session, gid)

    assert svc.add_to_collection(entry_id, "featured") == "added"
    assert svc.add_to_collection(entry_id, "featured") == "exists"  # no-op
    assert _member_count(db_session, entry_id, coll_id) == 1
    assert bus.events == ["entry_added_to_collection"]  # only the first emitted


def test_remove_emits_and_is_idempotent(db_session, workspace):
    gid, entry_id, coll_id = workspace
    svc, bus = _svc(db_session, gid)
    svc.add_to_collection(entry_id, "featured")

    assert svc.remove_from_collection(entry_id, "featured") == "removed"
    assert svc.remove_from_collection(entry_id, "featured") == "absent"  # no-op
    assert _member_count(db_session, entry_id, coll_id) == 0
    assert bus.events == ["entry_added_to_collection", "entry_removed_from_collection"]


def test_unknown_collection_returns_none(db_session, workspace):
    gid, entry_id, _ = workspace
    svc, bus = _svc(db_session, gid)
    assert svc.add_to_collection(entry_id, "does-not-exist") is None
    assert bus.events == []


def test_unknown_entry_returns_none(db_session, workspace):
    gid, _, _ = workspace
    svc, _ = _svc(db_session, gid)
    assert svc.add_to_collection(uuid.uuid4(), "featured") is None
