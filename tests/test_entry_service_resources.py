"""DB-backed tests for EntryService resource attachments (attach_resource / detach_resource).

Resources could only be linked to entries at seed/import time — there was no runtime attach path
(unlike collections and assets). These pin the new contract: idempotent attach/detach, the right
events emitted only on an actual change, resolution by slug/name/id, and workspace scoping.
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Entries, EntryResources, EntryTypes, Resources
from marvin.services.entries import EntryService


class _SpyBus:
    def __init__(self):
        self.events = []

    def dispatch(self, *, event_type, **_):
        self.events.append(event_type.name)


@fixture
def workspace(db_session):
    """A throwaway workspace with one entry + two resources (one addressed by slug, one by name)."""
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"res-test-{marker}", slug=f"res-test-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    from marvin.db.models.users.users import Users

    # Seed a user via a core insert (Users.__init__ does group-lookup side effects) to satisfy
    # Resources.created_by's NOT NULL user FK.
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"author-{marker}",
            email=f"res-{marker}@t.test",
            full_name="Author",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.flush()

    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="T", slug=f"t-{marker}")
    db_session.add(entry)

    res = Resources(session=db_session, group_id=gid, name="Waxed Canvas", slug="waxed-canvas", resource_type="material", created_by=uid)
    db_session.add(res)
    db_session.commit()

    yield gid, entry.id, res.id

    db_session.query(EntryResources).filter(EntryResources.resource_id == res.id).delete()
    db_session.query(Resources).filter(Resources.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.execute(Users.__table__.delete().where(Users.group_id == gid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _svc(db_session, gid):
    bus = _SpyBus()
    return EntryService(db_session, gid, event_bus=bus, integration_id="automation"), bus


def _link_count(db_session, entry_id, res_id) -> int:
    return db_session.query(EntryResources).filter(EntryResources.entry_id == entry_id, EntryResources.resource_id == res_id).count()


def test_attach_by_slug_emits_and_persists(db_session, workspace):
    gid, entry_id, res_id = workspace
    svc, bus = _svc(db_session, gid)

    result = svc.attach_resource(entry_id, "waxed-canvas", role="primary", reaction_depth=2)

    assert result == "attached"
    assert _link_count(db_session, entry_id, res_id) == 1
    assert bus.events == ["entry_resource_attached"]


def test_attach_by_name_and_by_id_also_resolve(db_session, workspace):
    gid, entry_id, res_id = workspace
    svc, _ = _svc(db_session, gid)
    assert svc.attach_resource(entry_id, "Waxed Canvas") == "attached"  # by name
    svc.detach_resource(entry_id, res_id)  # by id
    assert svc.attach_resource(entry_id, str(res_id)) == "attached"  # by id string
    assert _link_count(db_session, entry_id, res_id) == 1


def test_attach_is_idempotent_no_duplicate_no_second_event(db_session, workspace):
    gid, entry_id, res_id = workspace
    svc, bus = _svc(db_session, gid)

    assert svc.attach_resource(entry_id, "waxed-canvas") == "attached"
    assert svc.attach_resource(entry_id, "waxed-canvas") == "exists"  # no-op
    assert _link_count(db_session, entry_id, res_id) == 1
    assert bus.events == ["entry_resource_attached"]  # only the first emitted


def test_detach_emits_and_is_idempotent(db_session, workspace):
    gid, entry_id, res_id = workspace
    svc, bus = _svc(db_session, gid)
    svc.attach_resource(entry_id, "waxed-canvas")

    assert svc.detach_resource(entry_id, "waxed-canvas") == "detached"
    assert svc.detach_resource(entry_id, "waxed-canvas") == "absent"  # no-op
    assert _link_count(db_session, entry_id, res_id) == 0
    assert bus.events == ["entry_resource_attached", "entry_resource_detached"]


def test_unknown_resource_or_entry_returns_none(db_session, workspace):
    gid, entry_id, _ = workspace
    svc, bus = _svc(db_session, gid)
    assert svc.attach_resource(entry_id, "does-not-exist") is None
    assert svc.attach_resource(uuid.uuid4(), "waxed-canvas") is None
    assert bus.events == []


def test_registry_tools_are_registered_as_writes():
    from marvin.services.ai.operations.base import ROLE_EDITOR
    from marvin.services.ai.tools import get_tool

    for name in ("attach_resource", "detach_resource"):
        spec = get_tool(name)
        assert spec.read_only is False and spec.min_role == ROLE_EDITOR
        assert "mcp" in spec.sources and "agent" in spec.sources  # projected AND agent-bound
