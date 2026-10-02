"""The `set_data` workflow step: merge into an entry's schema fields, validated by its entry type.

Built for the Square loop — a sale flips an artwork's `status` field to `sold`. Fields read
data_json before metadata_json, so set_metadata could never change it.
"""

import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.entry import run_entry_action
from marvin.services.automation.authz import ROLE_ADMIN


def test_set_data_merges_templated_values_into_data_json(monkeypatch):
    import marvin.services.entries as entries_mod

    eid = uuid.uuid4()
    orm = SimpleNamespace(group_id="G", data_json={"title_note": "keep", "status": "available"})
    saved = {}

    class _Svc:
        def __init__(self, *a, **k): ...

        def update(self, entry_id, data, *, reaction_depth=0):
            saved.update(data=data)
            return object()

    monkeypatch.setattr(entries_mod, "EntryService", _Svc)
    ctx = {"event": {"entry_id": str(eid), "payload": {"state": "sold"}}, "steps": {}, "depth": 0}
    out = run_entry_action(
        SimpleNamespace(get=lambda model, i: orm),
        "G",
        {"kind": "entry", "op": "set_data", "data": {"status": "${event.payload.state}"}},
        ctx,
        authorizer_role=ROLE_ADMIN,
    )
    assert saved["data"] == {"data_json": {"title_note": "keep", "status": "sold"}}
    assert out["merged"] == {"status": "sold"}


def test_set_data_refuses_when_everything_resolved_empty():
    with pytest.raises(AutomationActionError):
        run_entry_action(
            None,
            "G",
            {"kind": "entry", "op": "set_data", "data": {"status": "${steps.none.output.x}"}},
            {"event": {"entry_id": str(uuid.uuid4())}, "steps": {}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
        )


def test_set_data_dry_run_reports_without_writing():
    out = run_entry_action(
        None,
        "G",
        {"kind": "entry", "op": "set_data", "data": {"status": "sold"}},
        {"event": {"entry_id": str(uuid.uuid4())}, "steps": {}, "depth": 0},
        authorizer_role=ROLE_ADMIN,
        dry_run=True,
    )
    assert out["dry_run"] and out["would_merge"] == {"status": "sold"}


@fixture
def artwork(db_session):
    """A workspace with an `artwork` type whose `status` is a select, and one available artwork."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"art-{marker}", slug=f"art-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    schema = {"fields": [{"key": "status", "label": "Status", "type": "select", "options": ["available", "sold", "archive"]}]}
    et = EntryTypes(session=db_session, group_id=gid, name="Artwork", slug="artwork", schema_json=schema)
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(
        session=db_session,
        group_id=gid,
        entry_type_id=et.id,
        title="Weightless Hour",
        slug=f"wh-{marker}",
        data_json={"status": "available"},
        status="published",
    )
    db_session.add(entry)
    db_session.commit()
    yield SimpleNamespace(group_id=gid, entry_id=entry.id)

    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)  # entries, types and the event-log rows the update wrote
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _set_status(db_session, artwork, value):
    return run_entry_action(
        db_session,
        artwork.group_id,
        {"kind": "entry", "op": "set_data", "data": {"status": value}},
        {"event": {"entry_id": str(artwork.entry_id)}, "steps": {}, "depth": 0},
        authorizer_role=ROLE_ADMIN,
    )


def test_set_data_sold_is_stored_on_the_artwork(db_session, artwork):
    from marvin.db.models.platform import Entries

    _set_status(db_session, artwork, "sold")

    db_session.expire_all()
    assert db_session.get(Entries, artwork.entry_id).data_json["status"] == "sold"


def test_set_data_value_outside_the_select_options_is_rejected(db_session, artwork):
    with pytest.raises(AutomationActionError, match="rejected"):
        _set_status(db_session, artwork, "gone-fishing")
