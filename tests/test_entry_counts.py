"""count_by_status (services/entries/entry_service.py): the sidebar inbox badge's query."""

import uuid

from pytest import fixture

from marvin.services.entries.entry_service import count_by_status


@fixture
def ws(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid, other = uuid.uuid4(), uuid.uuid4()
    for g in (gid, other):
        row = Groups(session=db_session, name=f"cnt-{g.hex[:8]}", slug=f"cnt-{g.hex[:8]}")
        row.id = g
        db_session.add(row)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et_other = EntryTypes(session=db_session, group_id=other, name="Note", slug="note", schema_json={})
    db_session.add_all([et, et_other])
    db_session.flush()
    for i, st in enumerate(["inbox", "inbox", "inbox", "draft", "published"]):
        db_session.add(Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=f"E{i}", slug=f"e-{gid.hex[:8]}-{i}", status=st))
    db_session.add(Entries(session=db_session, group_id=other, entry_type_id=et_other.id, title="X", slug=f"x-{other.hex[:8]}", status="inbox"))
    db_session.flush()
    yield gid, other
    db_session.rollback()


def test_count_by_status_is_zero_filled_workspace_scoped_and_totalled(db_session, ws):
    gid, other = ws
    counts = count_by_status(db_session, gid)
    assert counts["inbox"] == 3 and counts["draft"] == 1 and counts["published"] == 1
    assert counts["needs_review"] == 0 and counts["approved"] == 0 and counts["archived"] == 0 and counts["processing"] == 0
    assert counts["total"] == 5
    assert count_by_status(db_session, other) == {**{k: 0 for k in counts if k != "total"}, "inbox": 1, "total": 1}
