"""A workflow run over a query of entries sees each entry's fields, and can narrow the query by them.

Regression: target rows were bound as a lean ref (id, type, status, title, slug), so a condition such
as `entry.data.status == available` never matched on a query run; and the query could only filter
by metadata, so "every available artwork" pulled every artwork and hit the 250-entry cap.
"""

import uuid
from types import SimpleNamespace

from pytest import fixture

from tests.workflow_fakes import fake_workflow


class _Session:
    """get() returns the entry with that id, like session.get(Entries, id)."""

    def __init__(self, entries):
        self._by_id = {e.id: e for e in entries}

    def get(self, _model, entry_id):
        return self._by_id.get(entry_id)

    def query(self, *_columns):
        # Only the workspace's Canonical URL (`${site.url}`) is queried here: none configured.
        return SimpleNamespace(filter=lambda *_: SimpleNamespace(scalar=lambda: None))


def _entry(slug, **data):
    return SimpleNamespace(
        id=uuid.uuid4(),
        group_id="G",
        entry_type=SimpleNamespace(slug="artwork"),
        status="published",
        title=slug.title(),
        slug=slug,
        summary=None,
        data_json=data,
        metadata_json={},
        entry_assets=[],
    )


def test_target_rows_are_matched_on_their_fields(monkeypatch):
    from marvin.services.automation import engine, selector

    rows = [_entry("open", status="available", price="$45"), _entry("gone", status="sold"), _entry("unpriced", status="available")]
    monkeypatch.setattr(selector, "resolve_target_entities", lambda *a, **k: (rows, len(rows)))
    seen = []

    def runner(session, group_id, action, context, **kw):
        seen.append((context["entry"]["slug"], context["entry"]["data"].get("price")))
        return {}

    auto = fake_workflow(
        slug="sell-online",
        enabled=True,
        group_id="G",
        definition={
            "trigger": {"type": "manual"},
            "target": {"entity": "entry", "query": {"entry_type": "artwork"}},
            "conditions": [
                {"field": "entry.data.status", "op": "eq", "value": "available"},
                {"field": "entry.data.price", "op": "exists"},
            ],
            "actions": [{"kind": "entry", "op": "set_data", "data": {"sellOnline": True}}],
        },
    )

    res = engine.run_automation_now(_Session(rows), "G", auto, run_action=runner)

    assert res["ran"] == 1 and seen == [("open", "$45")]


# --- the query's `data` filter, against the database ----------------------------------------------


@fixture
def artworks(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"tgt-{gid.hex[:8]}", slug=f"tgt-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Artwork", slug="artwork", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    for slug, status in (("a", "available"), ("b", "available"), ("c", "sold")):
        e = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=slug, slug=slug, data_json={"status": status})
        e.id = uuid.uuid4()
        db_session.add(e)
    db_session.commit()
    yield gid
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_query_narrows_by_an_entry_field(db_session, artworks):
    from marvin.services.automation.selector import resolve_target_entities

    entities, total = resolve_target_entities(db_session, artworks, {"query": {"entry_type": "artwork", "data": {"status": "available"}}}, {})

    assert total == 2 and {e.slug for e in entities} == {"a", "b"}


def test_a_field_filter_that_resolved_to_nothing_matches_nothing(db_session, artworks):
    from marvin.services.automation.selector import resolve_target_entities

    _, total = resolve_target_entities(db_session, artworks, {"query": {"entry_type": "artwork", "data": {"status": ""}}}, {})

    assert total == 0


# --- typed-in text meets typed fields ------------------------------------------------------------

ARTWORK_SCHEMA = {
    "fields": [
        {"key": "sellOnline", "label": "Sell online", "type": "boolean"},
        {"key": "shippingFee", "label": "Shipping fee", "type": "number"},
        {"key": "status", "label": "Status", "type": "text"},
    ]
}


def test_set_fields_converts_text_to_the_fields_type():
    from marvin.services.automation.actions.entry import _typed_like_schema

    patch = {"sellOnline": "true", "shippingFee": "45", "status": "available", "note": "1"}

    out = _typed_like_schema(patch, SimpleNamespace(schema_json=ARTWORK_SCHEMA))

    assert out == {"sellOnline": True, "shippingFee": 45, "status": "available", "note": "1"}


def test_set_fields_leaves_unconvertible_text_for_validation_to_reject():
    from marvin.services.automation.actions.entry import _typed_like_schema

    assert _typed_like_schema({"sellOnline": "maybe"}, SimpleNamespace(schema_json=ARTWORK_SCHEMA)) == {"sellOnline": "maybe"}


def test_conditions_compare_typed_text_with_a_checkbox_or_number():
    from marvin.services.automation.matcher import matches

    ctx = {"entry": {"data": {"sellOnline": True, "price": 45, "status": "available"}}}

    assert matches([{"field": "entry.data.sellOnline", "op": "eq", "value": "true"}], ctx)
    assert not matches([{"field": "entry.data.sellOnline", "op": "neq", "value": "true"}], ctx)
    assert matches([{"field": "entry.data.price", "op": "eq", "value": "45"}], ctx)
    assert not matches([{"field": "entry.data.status", "op": "eq", "value": "true"}], ctx)
