"""The shared entry query (services/entries/query.py) behind find_entries, workflow targets and bulk
agent actions. Fixtures are concrete (a shop of works); the query itself knows no field names."""

import uuid
from datetime import UTC, datetime, timedelta

from pytest import fixture

from marvin.services.entries.query import number_like, run

NOW = datetime.now(UTC)


@fixture
def shop(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Collections, Entries, EntryTypes
    from marvin.db.models.platform.entry_collections import EntryCollections

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"q-{marker}", slug=f"q-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    work = EntryTypes(session=db_session, group_id=gid, name="Work", slug="work", schema_json={})
    page = EntryTypes(session=db_session, group_id=gid, name="Page", slug="page", schema_json={})
    db_session.add_all([work, page])
    db_session.flush()
    small = Collections(session=db_session, group_id=gid, name="Small", slug="small")
    db_session.add(small)
    db_session.flush()
    rows = [
        ("Blue Hour", "published", {"status": "available", "price": "$450", "size": "8 x 10"}, 3, True),
        ("Between Lives", "published", {"status": "available", "price": "$1,170"}, 2, False),
        ("Axis", "published", {"status": "available", "price": "$1400"}, 1, False),
        ("Unpriced", "published", {"status": "available"}, 4, True),
        ("Gone", "published", {"status": "sold", "price": "$900"}, 5, False),
        ("Draft Idea", "draft", {"status": "available", "price": "$75"}, 0, False),
    ]
    for i, (title, publish, data, days_ago, in_small) in enumerate(rows):
        e = Entries(session=db_session, group_id=gid, entry_type_id=work.id, title=title, slug=f"w{i}-{marker}", status=publish, data_json=data)
        e.created_at = (NOW - timedelta(days=days_ago)).replace(tzinfo=None)
        db_session.add(e)
        db_session.flush()
        if in_small:
            db_session.add(EntryCollections(entry_id=e.id, collection_id=small.id))
    db_session.add(Entries(session=db_session, group_id=gid, entry_type_id=page.id, title="About", slug=f"about-{marker}", status="published"))
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(EntryCollections).filter(EntryCollections.collection_id == small.id).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _titles(result):
    return [e.title for e in result.rows]


def test_number_like_reads_prices_written_as_text():
    assert [number_like(v) for v in ("$1,170", "450", 12.5, "8 x 10", "n/a", True, None)] == [1170.0, 450.0, 12.5, 8.0, None, None, None]


def test_most_expensive_available_work_in_one_query(db_session, shop):
    result = run(
        db_session,
        shop,
        {"entry_type": "work", "status": "published", "fields": {"status": "available"}, "sort": {"by": "price", "direction": "desc"}},
        limit=1,
    )
    assert _titles(result) == ["Axis"] and result.total == 4  # 4 available+published; the unpriced one sorts last


def test_where_compares_number_like_text(db_session, shop):
    result = run(db_session, shop, {"entry_type": "work", "where": [{"field": "price", "op": "gt", "value": 1000}]})
    assert sorted(_titles(result)) == ["Axis", "Between Lives"]


def test_where_missing_finds_works_without_a_value(db_session, shop):
    result = run(db_session, shop, {"entry_type": "work", "where": [{"field": "price", "op": "missing"}]})
    assert _titles(result) == ["Unpriced"]


def test_where_combines_with_in_and_neq(db_session, shop):
    spec = {
        "entry_type": "work",
        "where": [{"field": "status", "op": "in", "value": ["sold", "available"]}, {"field": "price", "op": "neq", "value": "$450"}],
    }
    assert "Blue Hour" not in _titles(run(db_session, shop, spec))


def test_group_by_counts_over_the_whole_match(db_session, shop):
    result = run(db_session, shop, {"entry_type": "work", "group_by": "status"}, limit=1)
    assert result.groups == {"available": 5, "sold": 1} and len(result.rows) == 1


def test_publish_status_is_a_distinct_built_in(db_session, shop):
    result = run(db_session, shop, {"entry_type": "work", "group_by": "publish_status"})
    assert result.groups == {"published": 5, "draft": 1}


def test_collection_filter(db_session, shop):
    assert sorted(_titles(run(db_session, shop, {"collection": "small"}))) == ["Blue Hour", "Unpriced"]


def test_created_date_range(db_session, shop):
    after = (NOW - timedelta(days=2, hours=12)).isoformat()
    assert sorted(_titles(run(db_session, shop, {"entry_type": "work", "created_after": after}))) == ["Axis", "Between Lives", "Draft Idea"]


def test_column_sort_and_offset_page_through(db_session, shop):
    first = run(db_session, shop, {"entry_type": "work", "sort": {"by": "title"}}, limit=2)
    second = run(db_session, shop, {"entry_type": "work", "sort": {"by": "title"}}, limit=2, offset=2)
    assert _titles(first) == ["Axis", "Between Lives"] and _titles(second) == ["Blue Hour", "Draft Idea"] and first.total == 6


def test_a_field_value_as_publish_status_returns_a_note(db_session, shop):
    result = run(db_session, shop, {"status": "available"})
    assert result.total == 0 and "not a publish status" in result.note


def test_an_unknown_op_is_reported_not_silently_matched(db_session, shop):
    result = run(db_session, shop, {"entry_type": "work", "where": [{"field": "price", "op": "approximately", "value": 1}]})
    assert result.unknown_ops == ["approximately"] and result.total == 6


def test_entry_type_accepts_either_spelling_and_lists(db_session, shop):
    assert run(db_session, shop, {"entry_types": ["Work", "page"]}).total == 7


# --- the surfaces share it ---------------------------------------------------------------------


def test_workflow_targets_use_the_shared_query(db_session, shop):
    from marvin.services.automation.selector import resolve_target_entities

    entities, total = resolve_target_entities(db_session, shop, {"query": {"entry_type": "work", "where": [{"field": "price", "op": "missing"}]}}, {})
    assert total == 1 and entities[0].title == "Unpriced"


def test_bulk_agent_actions_select_by_fields(db_session, shop):
    from types import SimpleNamespace

    from marvin.services.ai.tools.builtins_actions import _resolve_targets

    ctx = SimpleNamespace(session=db_session, group_id=shop)
    ids, err = _resolve_targets(ctx, "entry", {"filter": {"entry_types": ["work"], "fields": {"status": "sold"}}})
    assert err is None and len(ids) == 1


def test_find_entries_returns_groups_and_metadata(db_session, shop):
    import json

    from marvin.services.ai.tools import ToolContext, get_tool

    ctx = ToolContext(session=db_session, group_id=shop)
    out = json.loads(get_tool("find_entries").handler(ctx, {"entry_type": "work", "group_by": "status", "limit": 2}))
    assert out["groups"] == {"available": 5, "sold": 1} and out["count"] == 6 and out["returned"] == 2
