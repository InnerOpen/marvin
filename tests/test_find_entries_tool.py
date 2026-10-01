"""find_entries (services/ai/tools/builtins.py): the entry_type filter accepts either slug spelling."""

import json
import uuid

from pytest import fixture

from marvin.services.ai.tools import ToolContext, get_tool


@fixture
def ws(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"fe-{marker}", slug=f"fe-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Bench note", slug="bench-note", schema_json={})
    db_session.add(et)
    db_session.flush()
    for i in range(2):
        db_session.add(Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=f"Note {i}", slug=f"note-{marker}-{i}"))
    db_session.flush()
    yield gid
    db_session.rollback()


def test_find_entries_accepts_underscore_or_hyphen_type_slugs(db_session, ws):
    ctx = ToolContext(session=db_session, group_id=ws)
    run = get_tool("find_entries").handler
    assert json.loads(run(ctx, {"entry_type": "bench-note"}))["count"] == 2
    assert json.loads(run(ctx, {"entry_type": "bench_note"}))["count"] == 2  # the model's spelling
    assert json.loads(run(ctx, {"entry_type": " Bench_Note "}))["count"] == 2
    assert json.loads(run(ctx, {"entry_type": "project"}))["count"] == 0
