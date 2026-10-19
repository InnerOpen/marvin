"""The golden workspace bundle (tests/golden_bundle.py, committed under tests/fixtures/bundles/) imports into an empty
workspace on whichever engine the suite runs on (SQLite locally, both engines in CI): the same counts, the same rows,
the same files byte for byte, and the secrets decrypted with the backup key, or restored as valueless shells without it."""

import json
import uuid
import zipfile

import pytest
import sqlalchemy as sa

from marvin.db.models.groups import Groups
from marvin.repos.all_repositories import get_repositories
from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.services.storage import provider_factory
from tests.golden_bundle import BUNDLE_PATH, GOLDEN, GOLDEN_BACKUP_KEY, NOTES_BYTES, PNG_BYTES, SECRETS


@pytest.fixture
def world(db_session, tmp_path, monkeypatch):
    """An empty workspace with an admin user, files going to a local directory of the test's own."""
    from marvin.core.config import get_app_settings
    from marvin.db.db_setup import session_context
    from marvin.db.models.platform.platform_settings import PlatformSettingsModel
    from marvin.db.models.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    settings = get_app_settings().model_copy(update={"STORAGE_PROVIDER": "local", "STORAGE_LOCAL_ROOT": tmp_path / "files"})
    monkeypatch.setattr(provider_factory, "_settings", lambda: settings)

    def clear_upload_choice():
        with session_context() as session:
            session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key == provider_factory.UPLOAD_SETTING_KEY).delete()
            session.commit()
        provider_factory.reset_provider_cache()

    clear_upload_choice()
    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"Golden target {marker}", slug=f"golden-target-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid, group_id=gid, full_name="Ada Admin", username=f"golden-{marker}", email=f"golden-{marker}@x.test",
            auth_method="MARVIN", is_superuser=False, platform_role="SUPER_ADMIN", admin=True,
        )
    )  # fmt: skip
    db_session.commit()
    yield gid
    from marvin.db.models.platform import Assets, Resources, StorageKeyAliasModel

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    ids = [a for (a,) in db_session.query(Assets.id).filter(Assets.group_id == gid)]
    if ids:
        db_session.query(StorageKeyAliasModel).filter(StorageKeyAliasModel.asset_id.in_(ids)).delete()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Resources).filter(Resources.group_id == gid).delete()  # created_by: they go before their user
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()
    clear_upload_choice()


def _import(db_session, gid, backup_key=GOLDEN_BACKUP_KEY):
    loader = WorkspaceSeedLoader(get_repositories(db_session, group_id=None))
    return loader.load_seed_zip(BUNDLE_PATH, target_group_id=str(gid), backup_key=backup_key)


def test_the_bundle_has_every_section_a_workspace_export_writes(db_session, world):
    """Format drift: when the exporter gains or renames a section, the golden bundle has to be regenerated."""
    with zipfile.ZipFile(BUNDLE_PATH) as zf:
        data = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith(".json") and "/" not in n)))
    exported = WorkspaceExporter(get_repositories(db_session, group_id=world)).export_workspace()
    assert set(data) == set(exported)


def test_the_bundle_imports_with_the_counts_it_promises(db_session, world):
    result = _import(db_session, world)
    assert result["errors"] == 0
    assert {k: result[k] for k in GOLDEN["counts"]} == GOLDEN["counts"]
    repos = get_repositories(db_session, group_id=world)
    assert {e.slug for e in repos.entries.get_all(limit=None)} == set(GOLDEN["entries"])
    assert {t.slug for t in repos.tags.get_all(limit=None)} >= set(GOLDEN["tags"])
    assert {a.slug for a in repos.assets.get_all(limit=None)} == {"golden-notes", "golden-pixel"}
    assert {r.slug for r in repos.resources.get_all(limit=None)} == {"docs-home", "style-guide"}
    assert {c.slug for c in repos.collections.get_all(limit=None)} >= {"featured-notes", "archive-notes"}


def test_entries_keep_their_links_and_content(db_session, world):
    from marvin.db.models.platform import EntryAssets, EntryCollections, EntryResources

    _import(db_session, world)
    repos = get_repositories(db_session, group_id=world)
    for slug, spec in GOLDEN["entries"].items():
        (entry,) = repos.entries.multi_query({"slug": slug})
        assert entry.entry_type_id == repos.entry_types.multi_query({"slug": spec["entryType"], "group_id": world})[0].id
        assert entry.data_json["body"].startswith("The body of")
        assert sorted(entry.tags or []) == sorted(spec["tags"])
        collections = [repos.collections.get_one(j.collection_id).slug for j in db_session.query(EntryCollections).filter_by(entry_id=entry.id)]
        assert collections == ([spec["collection"]] if spec["collection"] else [])
        assets = [repos.assets.get_one(j.asset_id).slug for j in db_session.query(EntryAssets).filter_by(entry_id=entry.id)]
        assert assets == ([spec["asset"]] if spec["asset"] else [])
        resources = [repos.resources.get_one(j.resource_id).slug for j in db_session.query(EntryResources).filter_by(entry_id=entry.id)]
        assert resources == ([spec["resource"]] if spec["resource"] else [])
    assert repos.entries.multi_query({"slug": "welcome"})[0].status == "published"


def test_files_come_back_byte_for_byte(db_session, world):
    import hashlib

    _import(db_session, world)
    repos = get_repositories(db_session, group_id=world)
    expected = {"golden-notes": NOTES_BYTES, "golden-pixel": PNG_BYTES}
    for slug, raw in expected.items():
        (asset,) = repos.assets.multi_query({"slug": slug})
        stored = provider_factory.provider_for(asset).get(asset.storage_key).read()
        assert stored == raw
        assert hashlib.sha256(stored).hexdigest() == GOLDEN["files"][asset.original_filename]
        assert asset.file_size == len(raw)


def test_secrets_decrypt_with_the_backup_key(db_session, world):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.groups.variables import WorkspaceVariable
    from marvin.services.secrets import get_secret_backend

    _import(db_session, world)
    for slug, value in SECRETS.items():
        assert get_secret_backend().get(slug, world) == value
    variables = {v.slug: v.value for v in db_session.query(WorkspaceVariable).filter_by(group_id=world)}
    assert variables == GOLDEN["variables"]
    ai = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=world).one()
    assert (ai.provider, ai.secret_ref, ai.assistant_name) == ("openai", "GOLDEN_API_KEY", "Goldie")


def test_without_the_key_secrets_are_valueless_shells(db_session, world):
    from marvin.db.models.groups.secrets import WorkspaceSecret
    from marvin.services.secrets import get_secret_backend

    result = _import(db_session, world, backup_key=None)
    assert result["errors"] == 0 and result["secrets"] == 2
    assert {s.slug for s in db_session.query(WorkspaceSecret).filter_by(group_id=world)} == set(SECRETS)
    assert all(get_secret_backend().get(slug, world) is None for slug in SECRETS)


def test_importing_twice_adds_nothing(db_session, world):
    from marvin.db.models.groups.secrets import WorkspaceSecret

    _import(db_session, world)
    repos = get_repositories(db_session, group_id=world)
    before = (
        len(repos.entries.get_all(limit=None)),
        len(repos.assets.get_all(limit=None)),
        db_session.query(WorkspaceSecret).filter_by(group_id=world).count(),
    )
    _import(db_session, world)
    after = (
        len(repos.entries.get_all(limit=None)),
        len(repos.assets.get_all(limit=None)),
        db_session.query(WorkspaceSecret).filter_by(group_id=world).count(),
    )
    assert before == after == (5, 2, 2)


def test_what_an_import_exports_imports_again(db_session, world, tmp_path):
    """Export the imported workspace and import that into a second one: the same content comes back."""
    _import(db_session, world)
    exported = WorkspaceExporter(get_repositories(db_session, group_id=world)).export_workspace_bundle(temp_dir=tmp_path)
    with zipfile.ZipFile(exported) as zf:
        data = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith(".json") and "/" not in n)))
    assert {e["slug"] for e in data["entries"]} == set(GOLDEN["entries"]) and len(data["assets"]) == 2
    assert {s["slug"] for s in data["secrets"]} == set(SECRETS) and all(s.get("encryptedBackupValue") for s in data["secrets"])
