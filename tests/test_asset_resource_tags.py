"""Tags on assets and resources (Phase 2): repo tag_ids handling, read-schema slugs, and that
backup/restore carries asset_tags / resource_tags round-trip.

Mirrors the entry tag guards — the shared vocabulary now spans entries, assets, and resources.
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Assets, AssetTags, Resources, ResourceTags, Tags
from marvin.repos.all_repositories import get_repositories
from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.schemas.platform import AssetRead, AssetUpdate, ResourceRead, ResourceUpdate, TagCreate


@fixture
def workspace(db_session):
    """A throwaway workspace with a user, one asset, and one resource; cleaned up after."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"ar-{marker}", slug=f"ar-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    # Insert the user via a core insert — the ORM Users.__init__ has heavy side effects
    # (group-name lookup, notifier seeding) we don't want in a unit test.
    import sqlalchemy as sa

    uid = uuid.uuid4()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Test User",
            username=f"u-{marker}",
            email=f"u-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=True,
        )
    )
    db_session.flush()

    asset = Assets(
        session=db_session,
        group_id=gid,
        slug=f"asset-{marker}",
        name="Asset",
        original_filename="a.jpg",
        filename="a.jpg",
        extension="jpg",
        file_size=1,
        mime_type="image/jpeg",
        asset_type="image",
        checksum="x",
        storage_provider="local",
        storage_key=f"key-{marker}",
        uploaded_by=uid,
    )
    resource = Resources(
        session=db_session,
        group_id=gid,
        slug=f"res-{marker}",
        name="Resource",
        resource_type="material",
        created_by=uid,
    )
    db_session.add_all([asset, resource])
    db_session.commit()

    yield gid, asset.id, resource.id, marker

    for j, col, ids in ((AssetTags, AssetTags.asset_id, [asset.id]), (ResourceTags, ResourceTags.resource_id, [resource.id])):
        db_session.query(j).filter(col.in_(ids)).delete(synchronize_session=False)
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Resources).filter(Resources.group_id == gid).delete()
    db_session.query(Tags).filter(Tags.group_id == gid).delete()
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_asset_tag_ids_replace_and_read_slugs(db_session, workspace):
    gid, asset_id, _, _ = workspace
    repos = get_repositories(db_session, group_id=gid)
    waxed = repos.tags.create(TagCreate(name="Waxed"))
    denim = repos.tags.create(TagCreate(name="Denim"))

    repos.assets.update(asset_id, AssetUpdate(tag_ids=[waxed.id, denim.id]))
    asset = db_session.get(Assets, asset_id)
    assert set(asset.tag_names) == {"waxed", "denim"}
    assert set(AssetRead.model_validate(asset).tags) == {"waxed", "denim"}

    repos.assets.update(asset_id, AssetUpdate(tag_ids=[waxed.id]))  # replace, not append
    assert db_session.get(Assets, asset_id).tag_names == ["waxed"]
    repos.assets.update(asset_id, AssetUpdate(tag_ids=[]))  # empty clears
    assert db_session.get(Assets, asset_id).tag_names == []


def test_resource_tag_ids_replace_and_read_slugs(db_session, workspace):
    gid, _, resource_id, _ = workspace
    repos = get_repositories(db_session, group_id=gid)
    leather = repos.tags.create(TagCreate(name="Leather"))

    repos.resources.update(resource_id, ResourceUpdate(tag_ids=[leather.id]))
    resource = db_session.get(Resources, resource_id)
    assert resource.tag_names == ["leather"]
    assert ResourceRead.model_validate(resource).tags == ["leather"]


def test_export_includes_asset_and_resource_tags(db_session, workspace):
    gid, asset_id, resource_id, marker = workspace
    repos = get_repositories(db_session, group_id=gid)
    leather = repos.tags.create(TagCreate(name="Leather"))
    repos.assets.update(asset_id, AssetUpdate(tag_ids=[leather.id]))
    repos.resources.update(resource_id, ResourceUpdate(tag_ids=[leather.id]))

    data = WorkspaceExporter(repos).export_workspace()
    exported_asset = next(a for a in data["assets"] if a["slug"] == f"asset-{marker}")
    exported_resource = next(r for r in data["resources"] if r["slug"] == f"res-{marker}")
    assert exported_asset["tags"] == ["leather"]
    assert exported_resource["tags"] == ["leather"]


def test_resource_suggestion_stage_and_apply_links_real_tags(db_session, workspace):
    """A staged generate-tags suggestion on a resource applies as real tags (union)."""
    from marvin.db.models.platform import Resources

    gid, _, resource_id, _ = workspace
    repos = get_repositories(db_session, group_id=gid)
    leather = repos.tags.create(TagCreate(name="Leather"))
    repos.resources.update(resource_id, ResourceUpdate(tag_ids=[leather.id]))  # existing curated tag

    # Stage (what _write_back does in suggest-only mode), then apply.
    repos.resources.stage_suggestion(resource_id, {"tags": ["Waxed", "leather"], "_meta": {"operation": "generate-tags"}})
    assert db_session.get(Resources, resource_id).suggestion_json["tags"] == ["Waxed", "leather"]

    repos.resources.apply_suggestion(resource_id)
    resource = db_session.get(Resources, resource_id)
    assert set(resource.tag_names) == {"leather", "waxed"}  # union, deduped
    assert resource.suggestion_json is None  # cleared after apply


def test_asset_apply_fields_tags_target_links_real_tags(db_session, workspace):
    """apply_fields with the "tags" target links real tags on an asset (the auto-apply path)."""
    from marvin.db.models.platform import Assets

    gid, asset_id, _, _ = workspace
    repos = get_repositories(db_session, group_id=gid)
    repos.assets.apply_fields(asset_id, {"tags": ["Denim", "Selvedge"], "_meta": {"operation": "generate-tags"}})
    assert set(db_session.get(Assets, asset_id).tag_names) == {"denim", "selvedge"}


def test_import_relinks_resource_tags(db_session, workspace):
    gid, _, _, marker = workspace
    repos = get_repositories(db_session, group_id=gid)

    payload = {
        "tags": [{"name": "Leather", "slug": "leather", "color": None}],
        "resources": [
            {"slug": f"res-{marker}", "name": "Resource", "resourceType": "material", "tags": ["leather", "suede"]},
        ],
    }
    WorkspaceSeedLoader(repos)._load_data(payload, overwrite=True, target_group_id=str(gid))

    resource = db_session.query(Resources).filter(Resources.group_id == gid, Resources.slug == f"res-{marker}").one()
    assert set(resource.tag_names) == {"leather", "suede"}  # 'suede' auto-created from the link
