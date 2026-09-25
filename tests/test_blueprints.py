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
    assert len(items) >= 7
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
    assert any("mime_types" in r for r in rules)


def test_core_ships_only_collections_and_names_nobodys_content():
    """Naming content is the workspace owner's business. Core must not invent entry types, and
    must not hardcode a slug it cannot know — where a rule needs one, it asks via a parameter."""
    core = list_blueprints(source="core")
    assert {b.kind for b in core} == {"collection"}
    assert core, "core catalog should not be empty"

    for blueprint in core:
        assert not blueprint.requires, f"{blueprint.slug} hardcodes a dependency instead of asking"
        declared = {p.key for p in blueprint.parameters}
        for slug in blueprint.payload.get("smart_rules", {}).get("entry_types", []):
            assert slug.strip("{} ") in declared, f"{blueprint.slug} names an entry type the workspace never chose"


def test_parameterised_blueprints_exist_and_ask_for_a_picker():
    parameterised = [b for b in list_blueprints(source="core") if b.parameters]
    assert parameterised, "an entry-type rule can only be demonstrated generically via a parameter"
    for blueprint in parameterised:
        assert all(p.kind in ("entry_type", "collection", "text", "number") for p in blueprint.parameters)
        assert "{{" in blueprint.slug, f"{blueprint.slug} would collide for every type it is applied to"


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
    blueprint = get_blueprint("recently-published")
    assert already_applied(db_session, workspace, blueprint) is False
    apply_blueprint(db_session, workspace, blueprint)
    db_session.commit()
    assert already_applied(db_session, workspace, blueprint) is True


def test_parameters_fill_the_slug_name_and_rules(db_session, workspace):
    db_session.add(EntryTypes(session=db_session, group_id=workspace, name="Whatever They Called It", slug="whatever"))
    db_session.commit()

    result = apply_blueprint(db_session, workspace, get_blueprint("all-{{entry_type}}"), {"entry_type": "whatever"})
    db_session.commit()

    assert result.created is True
    assert result.slug == "all-whatever"
    col = db_session.query(Collections).filter_by(group_id=workspace, slug="all-whatever").one()
    assert col.name == "All whatever"
    assert col.smart_rules["entry_types"] == ["whatever"]


def test_the_same_blueprint_applies_once_per_type(db_session, workspace):
    for slug in ("alpha", "beta"):
        db_session.add(EntryTypes(session=db_session, group_id=workspace, name=slug.title(), slug=slug))
    db_session.commit()
    blueprint = get_blueprint("all-{{entry_type}}")

    first = apply_blueprint(db_session, workspace, blueprint, {"entry_type": "alpha"})
    second = apply_blueprint(db_session, workspace, blueprint, {"entry_type": "beta"})
    repeat = apply_blueprint(db_session, workspace, blueprint, {"entry_type": "alpha"})
    db_session.commit()

    assert (first.created, second.created) == (True, True)
    assert repeat.created is False and "already exists" in repeat.detail


def test_a_parameter_must_name_content_this_workspace_has(db_session, workspace):
    blueprint = get_blueprint("all-{{entry_type}}")
    result = apply_blueprint(db_session, workspace, blueprint, {"entry_type": "not-a-type-here"})
    assert result.created is False
    assert "no entry type 'not-a-type-here'" in result.detail
    assert db_session.query(Collections).filter_by(group_id=workspace).count() == 0


def test_a_missing_required_parameter_is_refused_not_guessed(db_session, workspace):
    result = apply_blueprint(db_session, workspace, get_blueprint("all-{{entry_type}}"))
    assert result.created is False
    assert "required" in result.detail


def test_applied_is_false_for_a_parameterised_blueprint_until_parameters_are_known(db_session, workspace):
    db_session.add(EntryTypes(session=db_session, group_id=workspace, name="Thing", slug="thing"))
    db_session.commit()
    blueprint = get_blueprint("all-{{entry_type}}")

    assert already_applied(db_session, workspace, blueprint) is False
    apply_blueprint(db_session, workspace, blueprint, {"entry_type": "thing"})
    db_session.commit()
    assert already_applied(db_session, workspace, blueprint) is False  # slug unknown without params
    assert already_applied(db_session, workspace, blueprint, {"entry_type": "thing"}) is True


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
    """A provider bundle: its collection depends on the entry type the same provider brings."""
    entry_type = Blueprint(
        kind="entry_type",
        slug="provider-thing",
        name="Provider thing",
        source="someprovider",
        payload={"name": "Provider thing", "schema_json": {"fields": []}},
    )
    collection = Blueprint(
        kind="collection",
        slug="all-provider-things",
        name="All provider things",
        source="someprovider",
        requires=["entry_type:provider-thing"],
        payload={"name": "All provider things", "is_smart": True, "smart_rules": {"entry_types": ["provider-thing"]}},
    )
    # deliberately the wrong order — apply_many must sort it out
    results = apply_many(db_session, workspace, [collection, entry_type])
    db_session.commit()

    assert [r.kind for r in results] == ["entry_type", "collection"]
    assert all(r.created for r in results)
    assert db_session.query(Collections).filter_by(group_id=workspace, slug="all-provider-things").one()


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


# --- the API surface ------------------------------------------------------------------------------


def test_blueprint_endpoints_are_registered():
    # Guards the easy regression: writing a controller and forgetting to include its router.
    from marvin.app import app

    paths = {(tuple(sorted(r.methods)), r.path) for r in app.routes if "blueprint" in getattr(r, "path", "")}
    assert (("GET",), "/api/groups/blueprints") in paths
    assert (("GET",), "/api/groups/blueprints/categories") in paths
    assert (("GET",), "/api/groups/blueprints/{slug}") in paths
    assert (("POST",), "/api/groups/blueprints/{slug}/apply") in paths
    assert (("POST",), "/api/groups/blueprints/apply") in paths


def test_categories_route_is_not_shadowed_by_the_slug_route():
    # /categories must be declared before /{slug} or it resolves as a blueprint named "categories".
    from marvin.app import app

    order = [r.path for r in app.routes if "blueprint" in getattr(r, "path", "")]
    assert order.index("/api/groups/blueprints/categories") < order.index("/api/groups/blueprints/{slug}")


def test_blueprint_endpoints_require_authentication(client):
    assert client.get("/api/groups/blueprints").status_code in (401, 403)
    assert client.get("/api/groups/blueprints/recently-published").status_code in (401, 403)
    assert client.get("/api/groups/blueprints/categories").status_code in (401, 403)
    assert client.post("/api/groups/blueprints/recently-published/apply").status_code in (401, 403)
    assert client.post("/api/groups/blueprints/apply", json=["recently-published"]).status_code in (401, 403)


# --- provider-contributed blueprints ---------------------------------------------------------------


def test_provider_declared_content_joins_the_catalog_under_its_own_category(monkeypatch):
    """Consumer 2: a provider may never touch the database, so it declares and the core offers."""
    sdk = pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

    class _P(sdk.IntegrationProvider):
        slug = "fakeprov"
        name = "Fake Prov"
        content = (
            sdk.ContentBlueprint(kind="entry_type", slug="fp-log", name="FP log", payload={"name": "FP log"}),
            sdk.ContentBlueprint(
                kind="collection",
                slug="fp-all",
                name="FP all",
                requires=("entry_type:fp-log",),
                payload={"name": "FP all", "is_smart": True, "smart_rules": {"entry_types": ["fp-log"]}},
            ),
        )

    monkeypatch.setitem(sdk.INTEGRATION_REGISTRY, "fakeprov", _P())

    mine = list_blueprints(source="fakeprov")
    assert [b.slug for b in mine] == ["fp-log", "fp-all"]
    # filed under the provider so the catalog stays legible as providers multiply
    assert {b.category for b in mine} == {"Fake Prov"}
    assert list_blueprints(source="core") and all(b.source == "core" for b in list_blueprints(source="core"))


def test_a_malformed_provider_declaration_does_not_empty_the_catalog(monkeypatch):
    sdk = pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

    class _Bad(sdk.IntegrationProvider):
        slug = "badprov"
        name = "Bad Prov"
        content = ({"kind": "collection"},)  # no slug, no name

    monkeypatch.setitem(sdk.INTEGRATION_REGISTRY, "badprov", _Bad())

    assert list_blueprints(source="badprov") == []
    assert list_blueprints(source="core"), "one bad provider must not take the catalog down"


def test_applying_a_provider_bundle_orders_and_creates_everything(db_session, workspace, monkeypatch):
    sdk = pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

    class _P(sdk.IntegrationProvider):
        slug = "bundleprov"
        name = "Bundle Prov"
        content = (
            sdk.ContentBlueprint(
                kind="collection",
                slug="bp-all",
                name="BP all",
                requires=("entry_type:bp-log",),
                payload={"name": "BP all", "is_smart": True, "smart_rules": {"entry_types": ["bp-log"]}},
            ),
            sdk.ContentBlueprint(kind="entry_type", slug="bp-log", name="BP log", payload={"name": "BP log"}),
        )

    monkeypatch.setitem(sdk.INTEGRATION_REGISTRY, "bundleprov", _P())

    results = apply_many(db_session, workspace, list_blueprints(source="bundleprov"))
    db_session.commit()

    assert all(r.created for r in results), [r.detail for r in results]
    assert db_session.query(EntryTypes).filter_by(group_id=workspace, slug="bp-log").one()
    assert db_session.query(Collections).filter_by(group_id=workspace, slug="bp-all").one()


def test_core_never_duplicates_a_system_collection_slug():
    """Every workspace already gets locked workflow collections (inbox/drafts/...). A blueprint
    sharing one of those slugs could never be applied, and would advertise something Marvin
    already provides."""
    from marvin.services.collections.system_collections import SYSTEM_COLLECTION_SLUGS

    clashes = [b.slug for b in list_blueprints(source="core") if b.slug in SYSTEM_COLLECTION_SLUGS]
    assert clashes == [], f"core blueprints collide with system collections: {clashes}"
