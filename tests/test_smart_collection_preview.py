"""POST /api/platform/collections/preview — evaluates unsaved smart rules with the same code that
materializes membership, so the editor's "Run Query" count is what a save would produce."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.services.collections.smart_collections import sync_collection

PREVIEW = "/api/platform/collections/preview"


def _workspace(db_session, prefix: str):
    """A workspace with recipes and pages; returns its id."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"{prefix}-{marker}", slug=f"{prefix}-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    recipe = EntryTypes(session=db_session, group_id=gid, name="Recipe", slug="recipe", schema_json={})
    page = EntryTypes(session=db_session, group_id=gid, name="Page", slug="page", schema_json={})
    db_session.add_all([recipe, page])
    db_session.flush()
    rows = [
        (recipe, "Soup", "published", {"minutes": "45"}),
        (recipe, "Bread", "published", {"minutes": "240"}),
        (recipe, "Salad", "draft", {"minutes": "10"}),
        (page, "About", "published", {}),
    ]
    now = datetime.now(UTC).replace(tzinfo=None)
    for i, (etype, title, status, data) in enumerate(rows):
        e = Entries(session=db_session, group_id=gid, entry_type_id=etype.id, title=title, slug=f"e{i}-{marker}", status=status, data_json=data)
        e.created_at = now - timedelta(minutes=len(rows) - i)  # later rows are newer
        db_session.add(e)
    db_session.commit()
    return gid


def _drop(db_session, gid):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes

    db_session.rollback()
    coll_ids = [c.id for c in db_session.query(Collections.id).filter(Collections.group_id == gid)]
    if coll_ids:
        db_session.query(EntryCollections).filter(EntryCollections.collection_id.in_(coll_ids)).delete(synchronize_session=False)
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@fixture
def kitchens(db_session):
    """Two workspaces with identical content; the caller is signed in to the first."""
    mine, theirs = _workspace(db_session, "pv"), _workspace(db_session, "pv-other")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), group_id=mine, active_group_id=mine, admin=False, is_superuser=False
    )
    yield mine, theirs
    app.dependency_overrides.pop(get_current_user, None)
    _drop(db_session, mine)
    _drop(db_session, theirs)


def _preview(rules, target_type="entry", **extra):
    res = TestClient(app).post(PREVIEW, json={"targetType": target_type, "smartRules": rules, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def test_preview_matches_what_materialization_adds(db_session, kitchens):
    from marvin.db.models.platform import Collections, EntryCollections

    mine, _ = kitchens
    rules = {"entry_types": ["recipe"], "statuses": ["published"]}

    preview = _preview(rules)

    collection = Collections(session=db_session, group_id=mine, name="Live recipes", slug="live-recipes", is_smart=True, smart_rules=rules)
    db_session.add(collection)
    db_session.flush()
    sync_collection(db_session, mine, collection)
    db_session.commit()
    members = {str(r.entry_id) for r in db_session.query(EntryCollections).filter_by(collection_id=collection.id)}
    assert preview["total"] == len(members) == 2 and {i["id"] for i in preview["items"]} == members


def test_preview_lists_titles_newest_first_up_to_the_limit(kitchens):
    preview = _preview({"statuses": ["published"]}, limit=2)

    assert preview["total"] == 3 and [i["label"] for i in preview["items"]] == ["About", "Bread"]


def test_preview_evaluates_field_conditions_like_a_workflow_query(kitchens):
    preview = _preview({"entry_types": ["recipe"], "where": [{"field": "minutes", "op": "gt", "value": 30}]})

    assert sorted(i["label"] for i in preview["items"]) == ["Bread", "Soup"]


def test_empty_rules_preview_matches_nothing_and_says_so(kitchens):
    for rules in (None, {}, {"match": "any"}):
        preview = _preview(rules)
        assert (preview["total"], preview["items"], bool(preview["note"])) == (0, [], True)


def test_preview_names_workflow_query_keys_it_ignores(kitchens):
    preview = _preview({"entry_type": "recipe", "status": "published"})

    assert (preview["total"], preview["ignoredKeys"]) == (0, ["entry_type", "status"])


def test_preview_counts_only_the_callers_workspace(kitchens):
    preview = _preview({"entry_types": ["recipe", "page"]})

    assert preview["total"] == 4  # each workspace has 4 entries; the other one's are not counted


def test_preview_saves_nothing(db_session, kitchens):
    from marvin.db.models.platform import Collections

    mine, _ = kitchens
    _preview({"entry_types": ["recipe"]})

    assert db_session.query(Collections).filter(Collections.group_id == mine).count() == 0


def test_preview_rejects_an_unknown_target_type(kitchens):
    res = TestClient(app).post(PREVIEW, json={"targetType": "tag", "smartRules": {"tags": ["x"]}})

    assert res.status_code == 422
