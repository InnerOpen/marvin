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


# --- an artwork's own fields vs the publish status --------------------------------------------------
# Regression: asked for "the most expensive available work", an agent passed status="available" (the
# artwork's field) as the publish status, got 0, and reported there were no available works.


@fixture
def shop(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"shop-{marker}", slug=f"shop-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Artwork", slug="artwork", schema_json={})
    db_session.add(et)
    db_session.flush()
    works = [
        ("Blue Hour", {"status": "available", "price": "$450", "size": "8 x 10", "sellOnline": True, "order": 2}),
        ("Between Lives", {"status": "available", "price": "$1,170", "size": "24 x 30", "sellOnline": False, "order": 1}),
        ("Gone", {"status": "sold", "price": "$900", "sellOnline": False, "order": 3}),
    ]
    for i, (title, data) in enumerate(works):
        db_session.add(
            Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=title, slug=f"w-{marker}-{i}", status="published", data_json=data)
        )
    db_session.commit()
    yield gid
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _find(db_session, gid, **args):
    return json.loads(get_tool("find_entries").handler(ToolContext(session=db_session, group_id=gid), args))


def test_fields_filter_matches_the_entry_types_own_status(db_session, shop):
    out = _find(db_session, shop, entry_type="artwork", fields={"status": "available"})

    assert out["count"] == 2


def test_include_fields_returns_values_to_compare(db_session, shop):
    out = _find(db_session, shop, entry_type="artwork", fields={"status": "available"}, include_fields=["price", "size"])

    prices = {e["title"]: e["fields"]["price"] for e in out["entries"]}
    assert prices == {"Blue Hour": "$450", "Between Lives": "$1,170"}


def test_a_field_value_passed_as_publish_status_says_how_to_ask(db_session, shop):
    out = _find(db_session, shop, entry_type="artwork", status="available")

    assert out["count"] == 0 and 'fields, e.g. {"status": "available"}' in out["note"]


def test_typed_text_matches_checkbox_and_number_fields(db_session, shop):
    assert _find(db_session, shop, entry_type="artwork", fields={"sellOnline": "true"})["count"] == 1
    assert _find(db_session, shop, entry_type="artwork", fields={"sellOnline": True})["count"] == 1
    assert _find(db_session, shop, entry_type="artwork", fields={"order": "2"})["count"] == 1


def test_a_number_or_true_against_a_text_field_just_does_not_match(db_session, shop):
    # On Postgres a cast of "$450"/"available" to float/boolean would raise; it must simply not match.
    assert _find(db_session, shop, entry_type="artwork", fields={"price": "450"})["count"] == 0
    assert _find(db_session, shop, entry_type="artwork", fields={"status": "true"})["count"] == 0
