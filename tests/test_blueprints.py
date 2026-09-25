"""Blueprints: the catalog, and the upsert semantics every consumer depends on.

The contract under test is "create what is missing, never overwrite what exists" — a workspace may
have customised its copy, and applying twice (or applying a newer provider's blueprint over an
older install) must be safe.
"""

import uuid

import pytest
from pytest import fixture

from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_collections import EntryCollections
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.schemas.platform.blueprints import Blueprint
from marvin.services.blueprints import (
    already_applied,
    apply_blueprint,
    apply_many,
    categories,
    get_blueprint,
    list_blueprints,
    missing_requirements,
)


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"bp-{marker}", slug=f"bp-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.commit()

    yield gid

    db_session.query(EntryCollections).filter(
        EntryCollections.collection_id.in_(db_session.query(Collections.id).filter(Collections.group_id == gid))
    ).delete(synchronize_session=False)
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Collections).filter(Collections.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


# --- catalog -------------------------------------------------------------------------------------


def test_core_catalog_is_well_formed_and_grouped():
    items = list_blueprints()
    assert len(items) >= 8
    assert all(b.source == "core" or b.source for b in items)
    assert len({(b.source, b.slug) for b in items}) == len(items)  # unique per source
    assert "Editorial" in categories()


def test_catalog_filters_by_kind_and_category():
    assert {b.kind for b in list_blueprints(kind="collection")} == {"collection"}
    assert {b.category for b in list_blueprints(category="Media")} == {"Media"}
    assert get_blueprint("recently-published").kind == "collection"
    assert get_blueprint("no-such-blueprint") is None


def test_catalog_advertises_the_rules_people_would_not_find_alone():
    # The catalog's whole reason to exist: surface dimensions that are otherwise folklore.
    rules = [b.payload.get("smart_rules", {}) for b in list_blueprints(kind="collection")]
    assert any("published_within_days" in r for r in rules)
    assert any("created_within_days" in r for r in rules)
    assert any(b.payload.get("target_type") == "asset" for b in list_blueprints(kind="collection"))


# --- applying ------------------------------------------------------------------------------------


def test_applying_a_collection_creates_it_and_materializes_membership(db_session, workspace):
    et = EntryTypes(session=db_session, group_id=workspace, name="Note", slug="note")
    db_session.add(et)
    db_session.flush()
    db_session.add(Entries(session=db_session, group_id=workspace, entry_type_id=et.id, title="Fresh", slug="fresh", status="draft"))
    db_session.commit()

    result = apply_blueprint(db_session, workspace, get_blueprint("new-this-week"))
    db_session.commit()

    assert result.created is True
    col = db_session.query(Collections).filter_by(group_id=workspace, slug="new-this-week").one()
    assert col.is_smart is True
    # membership is materialized on apply — an empty new collection would look broken
    assert [e.slug for e in col.entries] == ["fresh"]


def test_applying_twice_never_overwrites(db_session, workspace):
    blueprint = get_blueprint("recently-published")
    assert apply_blueprint(db_session, workspace, blueprint).created is True
    db_session.commit()

    col = db_session.query(Collections).filter_by(group_id=workspace, slug="recently-published").one()
    col.name = "My tweaked name"
    col.smart_rules = {"statuses": ["published"], "published_within_days": 10, "match": "all"}
    db_session.commit()

    second = apply_blueprint(db_session, workspace, blueprint)
    db_session.commit()

    assert second.created is False
    assert "already exists" in second.detail
    db_session.refresh(col)
    assert col.name == "My tweaked name"
    assert col.smart_rules["published_within_days"] == 10


def test_already_applied_reports_the_workspace_state(db_session, workspace):
    blueprint = get_blueprint("faq")
    assert already_applied(db_session, workspace, blueprint) is False
    apply_blueprint(db_session, workspace, blueprint)
    db_session.commit()
    assert already_applied(db_session, workspace, blueprint) is True


def test_applying_an_entry_type_carries_its_schema(db_session, workspace):
    apply_blueprint(db_session, workspace, get_blueprint("changelog-entry"))
    db_session.commit()

    et = db_session.query(EntryTypes).filter_by(group_id=workspace, slug="changelog-entry").one()
    assert [f["key"] for f in et.schema_json["fields"]] == ["version", "released_on", "change_kind", "notes"]


def test_unmet_requirements_block_application(db_session, workspace):
    blueprint = Blueprint(
        kind="collection",
        slug="needs-a-type",
        name="Needs a type",
        requires=["entry_type:nowhere-to-be-found"],
        payload={"name": "Needs a type", "is_smart": True, "smart_rules": {"statuses": ["published"]}},
    )

    assert missing_requirements(db_session, workspace, blueprint) == ["entry_type:nowhere-to-be-found"]
    result = apply_blueprint(db_session, workspace, blueprint)
    assert result.created is False
    assert "needs entry_type:nowhere-to-be-found" in result.detail
    assert db_session.query(Collections).filter_by(group_id=workspace, slug="needs-a-type").first() is None


def test_requirements_are_satisfied_once_the_dependency_exists(db_session, workspace):
    blueprint = Blueprint(
        kind="collection",
        slug="notes-only",
        name="Notes only",
        requires=["entry_type:note"],
        payload={"name": "Notes only", "is_smart": True, "smart_rules": {"entry_types": ["note"]}},
    )
    assert apply_blueprint(db_session, workspace, blueprint).created is False

    db_session.add(EntryTypes(session=db_session, group_id=workspace, name="Note", slug="note"))
    db_session.commit()

    assert missing_requirements(db_session, workspace, blueprint) == []
    assert apply_blueprint(db_session, workspace, blueprint).created is True
    db_session.commit()


def test_apply_many_creates_entry_types_before_what_references_them(db_session, workspace):
    collection = Blueprint(
        kind="collection",
        slug="all-faqs",
        name="All FAQs",
        requires=["entry_type:faq"],
        payload={"name": "All FAQs", "is_smart": True, "smart_rules": {"entry_types": ["faq"]}},
    )
    # deliberately the wrong order — apply_many must sort it out
    results = apply_many(db_session, workspace, [collection, get_blueprint("faq")])
    db_session.commit()

    assert [r.kind for r in results] == ["entry_type", "collection"]
    assert all(r.created for r in results)
    assert db_session.query(Collections).filter_by(group_id=workspace, slug="all-faqs").one()


def test_applying_a_scheduled_task_gets_a_next_run(db_session, workspace):
    blueprint = Blueprint(
        kind="scheduled_task",
        slug="tidy-up",
        name="Tidy up",
        payload={
            "name": "Tidy up",
            "enabled": False,
            "schedule_type": "interval",
            "schedule_config": {"interval_seconds": 3600},
            "task_type": "remove_orphaned_assets",
            "task_config": {"auto_delete": False},
        },
    )
    assert apply_blueprint(db_session, workspace, blueprint).created is True
    db_session.commit()

    task = db_session.query(ScheduledTaskModel).filter_by(group_id=workspace, slug="tidy-up").one()
    # via the repository, so next_run_at is computed — a raw insert would leave it null and the
    # scheduler would never pick the task up
    assert task.next_run_at is not None
    assert task.enabled is False


def test_a_blueprint_cannot_smuggle_a_workspace_id():
    with pytest.raises(ValueError):
        Blueprint(kind="collection", slug="x", name="X", payload={"name": "X", "group_id": str(uuid.uuid4())})
