"""Packages: a labelled bundle of blueprints that installs, previews, exports, adopts, switches on and removes.

The contract under test: an install creates what is missing and nothing else, stamps what it creates with the package, starts everything
disabled, and a preview leaves no trace; removing a package ungroups and never deletes content; a file from outside is checked harder than
a blueprint the code ships.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.groups.packages import WorkspacePackageModel
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.schemas.platform.packages import PackageExportRequest, PackageManifest
from marvin.services.blueprints import packages as service
from marvin.services.blueprints.packages import PackageError
from tests._routes import api_routes

WORKFLOW_DEFINITION = {
    "trigger": {"type": "event", "event": "entry_published"},
    "conditions": [],
    "actions": [{"kind": "entry", "op": "set_data", "data": {"status": "sold"}}],
}


def _manifest(slug="story-kit", **changes) -> dict:
    data = {
        "format": 1,
        "slug": slug,
        "name": "Story kit",
        "description": "Types and workflows for stories",
        "version": "2",
        "blueprints": [
            {
                "kind": "entry_type",
                "slug": "beat",
                "name": "Beat",
                "payload": {"name": "Beat", "schema_json": {"fields": [{"key": "text", "label": "Text", "type": "text"}]}},
            },
            {
                "kind": "workflow",
                "slug": "kit-mark-sold",
                "name": "Kit: mark sold",
                "payload": {"name": "Kit: mark sold", "definition": WORKFLOW_DEFINITION},
            },
            {"kind": "workflow", "slug": "kit-other", "name": "Kit: other", "payload": {"name": "Kit: other", "definition": WORKFLOW_DEFINITION}},
        ],
    }
    data.update(changes)
    return data


@fixture
def workspace(db_session):
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"pk-{marker}", slug=f"pk-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )  # fmt: skip
    )
    db_session.commit()
    yield SimpleNamespace(id=gid, user_id=uid)

    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _workflows(db_session, gid):
    db_session.expire_all()
    return db_session.query(WorkspaceAutomationModel).filter_by(group_id=gid).order_by(WorkspaceAutomationModel.slug).all()


# --- the file ---------------------------------------------------------------------------------------------------------------------------


def test_a_package_file_parses_and_a_bad_one_says_what_is_wrong():
    assert service.parse_manifest(json.dumps(_manifest())).name == "Story kit"
    with pytest.raises(PackageError, match="not valid JSON"):
        service.parse_manifest("{nope")
    with pytest.raises(PackageError, match="JSON object"):
        service.parse_manifest("[1, 2]")
    with pytest.raises(PackageError, match="slug"):
        service.parse_manifest(_manifest(slug="Not A Slug!"))
    with pytest.raises(PackageError, match="blueprints"):
        service.parse_manifest(_manifest(blueprints=[]))


def test_a_package_is_capped_in_size():
    with pytest.raises(PackageError, match="larger than"):
        service.parse_manifest("x" * 2_000_001)


@pytest.mark.parametrize("kind", ["playbook", "event_subscription"])
def test_kinds_that_cannot_travel_are_refused(kind):
    blueprint = {"kind": kind, "slug": "x", "name": "X", "payload": {"event_type": "e", "action": "a"}}
    with pytest.raises(PackageError):
        service.parse_manifest(_manifest(blueprints=[blueprint]))


def test_an_id_from_another_workspace_is_refused():
    definition = {**WORKFLOW_DEFINITION, "actions": [{"kind": "entry", "op": "set_data", "data": {"asset": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}}]}
    blueprint = {"kind": "workflow", "slug": "w", "name": "W", "payload": {"name": "W", "definition": definition}}

    with pytest.raises(PackageError, match="belongs to one workspace"):
        service.parse_manifest(_manifest(blueprints=[blueprint]))


def test_a_secret_value_is_refused_but_a_reference_to_one_is_not():
    def with_secret(value):
        definition = {**WORKFLOW_DEFINITION, "actions": [{"kind": "integration", "integration": "x", "action": "y", "args": {"api_key": value}}]}
        return _manifest(blueprints=[{"kind": "workflow", "slug": "w", "name": "W", "payload": {"name": "W", "definition": definition}}])

    with pytest.raises(PackageError, match="secret value"):
        service.parse_manifest(with_secret("sk-live-123"))
    assert service.parse_manifest(with_secret("{{OPENAI_TOKEN}}"))


def test_the_same_blueprint_listed_twice_is_refused():
    one = _manifest()["blueprints"][1]
    with pytest.raises(PackageError, match="listed twice"):
        service.parse_manifest(_manifest(blueprints=[one, one]))


def test_a_file_cannot_claim_an_integration_as_its_source():
    blueprint = {**_manifest()["blueprints"][1], "source": "elevenlabs"}

    assert service.parse_manifest(_manifest(blueprints=[blueprint])).blueprints[0].source == "core"


# --- install, preview ----------------------------------------------------------------------------------------------------------------------


def test_install_creates_what_is_missing_disabled_and_stamped_with_the_package(db_session, workspace):
    manifest = service.parse_manifest(_manifest())

    result = service.install(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    db_session.commit()

    assert (result.created, result.existing, result.blocked) == (3, 0, 0)
    rows = _workflows(db_session, workspace.id)
    assert [r.slug for r in rows] == ["kit-mark-sold", "kit-other"]
    assert all(r.enabled is False and r.source_package == "story-kit" and r.created_by == workspace.user_id for r in rows)
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="beat").count() == 1
    kept = db_session.query(WorkspacePackageModel).filter_by(group_id=workspace.id, slug="story-kit").one()
    assert kept.name == "Story kit" and kept.version == "2" and len(kept.manifest["blueprints"]) == 3


def test_installing_again_leaves_what_exists_alone_and_adds_what_is_missing(db_session, workspace):
    service.install(db_session, workspace.id, service.parse_manifest(_manifest()), actor_id=workspace.user_id)
    db_session.commit()
    row = _workflows(db_session, workspace.id)[0]
    row.name = "Renamed here"
    db_session.commit()
    bigger = _manifest(version="3")
    bigger["blueprints"].append(
        {"kind": "workflow", "slug": "kit-new", "name": "Kit: new", "payload": {"name": "Kit: new", "definition": WORKFLOW_DEFINITION}}
    )

    result = service.install(db_session, workspace.id, service.parse_manifest(bigger), actor_id=workspace.user_id)
    db_session.commit()

    assert (result.created, result.existing) == (1, 3)
    assert {r.slug: r.name for r in _workflows(db_session, workspace.id)}[row.slug] == "Renamed here"
    assert db_session.query(WorkspacePackageModel).filter_by(group_id=workspace.id).one().version == "3"


def test_a_preview_says_what_would_happen_and_leaves_nothing_behind(db_session, workspace):
    service.install(
        db_session, workspace.id, service.parse_manifest(_manifest(blueprints=[_manifest()["blueprints"][2]])), actor_id=workspace.user_id
    )
    db_session.commit()

    result = service.preview(db_session, workspace.id, service.parse_manifest(_manifest(slug="other")), actor_id=workspace.user_id)

    by_slug = {i.slug: i for i in result.items}
    assert by_slug["beat"].status == "create" and by_slug["kit-mark-sold"].status == "create"
    assert by_slug["kit-other"].status == "exists"
    assert "entry_published" in by_slug["kit-mark-sold"].summary and "entry" in by_slug["kit-mark-sold"].summary
    db_session.expire_all()
    assert [r.slug for r in _workflows(db_session, workspace.id)] == ["kit-other"]
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="beat").count() == 0
    assert db_session.query(WorkspacePackageModel).filter_by(group_id=workspace.id, slug="other").count() == 0


def test_a_workflow_that_fails_validation_is_blocked_not_half_installed(db_session, workspace):
    broken = {
        "kind": "workflow",
        "slug": "bad",
        "name": "Bad",
        "payload": {"name": "Bad", "definition": {"trigger": {"type": "telepathy"}, "actions": []}},
    }

    result = service.install(
        db_session, workspace.id, service.parse_manifest(_manifest(blueprints=[broken, _manifest()["blueprints"][1]])), actor_id=workspace.user_id
    )
    db_session.commit()

    assert (result.created, result.blocked) == (1, 1)
    assert [r.slug for r in _workflows(db_session, workspace.id)] == ["kit-mark-sold"]


# --- list, enable, remove ---------------------------------------------------------------------------------------------------------------


def test_the_list_counts_what_a_package_holds_and_enable_switches_on_only_its_workflows(db_session, workspace):
    service.install(db_session, workspace.id, service.parse_manifest(_manifest()), actor_id=workspace.user_id)
    mine = WorkspaceAutomationModel(
        session=db_session,
        group_id=workspace.id,
        name="Mine",
        slug="mine",
        enabled=False,
        definition=WORKFLOW_DEFINITION,
        created_by=workspace.user_id,
    )
    db_session.add(mine)
    db_session.commit()

    [listed] = service.list_packages(db_session, workspace.id)
    assert (listed.slug, listed.workflows, listed.workflows_on, listed.entry_types) == ("story-kit", 2, 0, ["beat"])

    outcome = service.enable(db_session, workspace.id, "story-kit", actor_id=workspace.user_id)

    assert (outcome.switched_on, outcome.already_on) == (2, 0)
    rows = {r.slug: r.enabled for r in _workflows(db_session, workspace.id)}
    assert rows == {"kit-mark-sold": True, "kit-other": True, "mine": False}
    assert service.enable(db_session, workspace.id, "story-kit", actor_id=workspace.user_id).already_on == 2


def test_removing_a_package_ungroups_and_keeps_every_row(db_session, workspace):
    service.install(db_session, workspace.id, service.parse_manifest(_manifest()), actor_id=workspace.user_id)
    db_session.commit()

    assert service.remove(db_session, workspace.id, "story-kit") == 2
    db_session.commit()

    assert [(r.slug, r.source_package) for r in _workflows(db_session, workspace.id)] == [("kit-mark-sold", None), ("kit-other", None)]
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="beat").count() == 1
    assert service.list_packages(db_session, workspace.id) == []
    with pytest.raises(LookupError):
        service.remove(db_session, workspace.id, "story-kit")


# --- export, adopt, round trip --------------------------------------------------------------------------------------------------------------


def _own_content(db_session, gid, uid):
    db_session.add(
        EntryTypes(
            session=db_session, group_id=gid, name="Scene", slug="scene", schema_json={"fields": [{"key": "place", "label": "Place", "type": "text"}]}
        )
    )
    db_session.add(
        WorkspaceAutomationModel(
            session=db_session, group_id=gid, name="Make still", slug="make-still", enabled=True, definition=WORKFLOW_DEFINITION, created_by=uid
        )
    )
    db_session.add(
        Collections(
            session=db_session, group_id=gid, name="Stills", slug="stills", is_smart=True, smart_rules={"entry_types": ["scene"], "match": "all"}
        )
    )
    db_session.commit()


def test_export_builds_a_package_from_the_workspaces_own_content(db_session, workspace):
    _own_content(db_session, workspace.id, workspace.user_id)

    manifest = service.export(
        db_session,
        workspace.id,
        PackageExportRequest(slug="world", name="World", workflows=["make-still"], entry_types=["scene"], collections=["stills"]),
    )

    assert {(b.kind, b.slug) for b in manifest.blueprints} == {("workflow", "make-still"), ("entry_type", "scene"), ("collection", "stills")}
    workflow = next(b for b in manifest.blueprints if b.kind == "workflow")
    assert workflow.payload["definition"] == WORKFLOW_DEFINITION
    assert _workflows(db_session, workspace.id)[0].source_package is None  # not adopted unless asked


def test_adopt_groups_existing_rows_without_recreating_them_and_keeps_the_manifest(db_session, workspace):
    _own_content(db_session, workspace.id, workspace.user_id)
    before = _workflows(db_session, workspace.id)[0].id

    service.export(
        db_session, workspace.id, PackageExportRequest(slug="world", name="World", workflows=["make-still"], collections=["stills"], adopt=True)
    )
    db_session.commit()

    [row] = _workflows(db_session, workspace.id)
    assert row.id == before and row.source_package == "world" and row.enabled is True  # same row, still on
    assert db_session.query(Collections).filter_by(group_id=workspace.id, slug="stills").one().source_package == "world"
    assert service.manifest_of(db_session, workspace.id, "world").name == "World"
    [listed] = service.list_packages(db_session, workspace.id)
    assert (listed.workflows, listed.workflows_on, listed.collections) == (1, 1, 1)


def test_adopting_a_row_that_is_in_another_package_is_refused(db_session, workspace):
    _own_content(db_session, workspace.id, workspace.user_id)
    service.export(db_session, workspace.id, PackageExportRequest(slug="one", name="One", workflows=["make-still"], adopt=True))
    db_session.commit()

    with pytest.raises(PackageError, match="already in another package"):
        service.export(db_session, workspace.id, PackageExportRequest(slug="two", name="Two", workflows=["make-still"], adopt=True))


def test_export_refuses_what_is_not_there_and_an_empty_choice(db_session, workspace):
    with pytest.raises(PackageError, match="no workflow 'ghost'"):
        service.export(db_session, workspace.id, PackageExportRequest(slug="x", name="X", workflows=["ghost"]))
    with pytest.raises(PackageError, match="at least one"):
        service.export(db_session, workspace.id, PackageExportRequest(slug="x", name="X"))


def test_export_refuses_a_workflow_that_carries_an_id(db_session, workspace):
    definition = {**WORKFLOW_DEFINITION, "actions": [{"kind": "entry", "op": "attach_asset", "asset": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}]}
    db_session.add(
        WorkspaceAutomationModel(
            session=db_session,
            group_id=workspace.id,
            name="Has id",
            slug="has-id",
            enabled=False,
            definition=definition,
            created_by=workspace.user_id,
        )
    )
    db_session.commit()

    with pytest.raises(PackageError, match="belongs to one workspace"):
        service.export(db_session, workspace.id, PackageExportRequest(slug="x", name="X", workflows=["has-id"]))


def test_a_package_exported_from_one_workspace_installs_the_same_content_into_another(db_session, workspace):
    from marvin.db.models.users.users import Users

    _own_content(db_session, workspace.id, workspace.user_id)
    manifest = service.export(
        db_session,
        workspace.id,
        PackageExportRequest(slug="world", name="World", workflows=["make-still"], entry_types=["scene"], collections=["stills"]),
    )
    other_id, other_user = uuid.uuid4(), uuid.uuid4()
    marker = other_id.hex[:8]
    other = Groups(session=db_session, name=f"pk-{marker}", slug=f"pk-{marker}")
    other.id = other_id
    db_session.add(other)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=other_user,
            group_id=other_id,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )  # fmt: skip
    )
    db_session.commit()
    try:
        shipped = service.parse_manifest(
            json.dumps(manifest.model_dump(mode="json", by_alias=True))
        )  # through a file, as a download and upload would

        result = service.install(db_session, other_id, shipped, actor_id=other_user)
        db_session.commit()

        assert (result.created, result.blocked) == (3, 0)
        [wf] = _workflows(db_session, other_id)
        assert (wf.slug, wf.enabled, wf.source_package, wf.definition) == (
            "make-still",
            False,
            "world",
            WORKFLOW_DEFINITION,
        )  # off, even though it was on at home
        assert db_session.query(EntryTypes).filter_by(group_id=other_id, slug="scene").one().schema_json["fields"][0]["key"] == "place"
        assert db_session.query(Collections).filter_by(group_id=other_id, slug="stills").one().source_package == "world"
    finally:
        from marvin.services.group.group_purge import purge_group_dependents

        db_session.rollback()
        purge_group_dependents(db_session, other_id)
        db_session.query(Users).filter(Users.group_id == other_id).delete()
        db_session.query(Groups).filter(Groups.id == other_id).delete()
        db_session.commit()


# --- the API ----------------------------------------------------------------------------------------------------------------------------


def test_the_routes_exist_and_need_a_login(client):
    from marvin.app import app

    paths = {(tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.path) for r in api_routes(app) if "/groups/packages" in r.path}
    assert (("GET",), "/api/groups/packages") in paths
    assert (("POST",), "/api/groups/packages/preview") in paths
    assert (("POST",), "/api/groups/packages/install") in paths
    assert (("POST",), "/api/groups/packages/export") in paths
    assert (("GET",), "/api/groups/packages/{slug}/download") in paths
    assert (("POST",), "/api/groups/packages/{slug}/enable") in paths
    assert (("DELETE",), "/api/groups/packages/{slug}") in paths

    assert client.get("/api/groups/packages").status_code in (401, 403)
    assert client.post("/api/groups/packages/install", json=_manifest()).status_code in (401, 403)
    assert client.delete("/api/groups/packages/story-kit").status_code in (401, 403)


def test_the_manifest_round_trips_through_its_own_json():
    manifest = PackageManifest.model_validate(_manifest())

    again = PackageManifest.model_validate(json.loads(json.dumps(manifest.model_dump(mode="json", by_alias=True))))

    assert again == manifest
