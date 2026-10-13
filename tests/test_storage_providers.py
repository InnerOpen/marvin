"""Storage providers: the SDK conformance kit on the built-in local provider, the registry (built-ins,
plugins by slug, unknown slugs refused), and per-row resolution serving local and remote rows side by
side."""

import importlib.metadata
import io
import uuid
from types import SimpleNamespace

import pytest
from marvin_integration_sdk.storage import Setting, StorageConfigError, StoragePlugin
from marvin_integration_sdk.storage.memory import MemoryStorageProvider
from marvin_integration_sdk.storage.testing import StorageProviderContract

from marvin.core.config import get_app_settings
from marvin.services.storage import provider_factory, registry
from marvin.services.storage.local_provider import LocalStorageProvider


class TestLocalProviderConformance(StorageProviderContract):
    @pytest.fixture
    def provider(self, tmp_path):
        return LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")


def test_local_iter_keys_skips_symlinks(tmp_path):
    store = LocalStorageProvider(root=tmp_path / "store")
    store.put("ws/assets/a.txt", io.BytesIO(b"a"), "text/plain")
    (tmp_path / "outside.txt").write_text("secret")
    (tmp_path / "store" / "ws" / "assets" / "link.txt").symlink_to(tmp_path / "outside.txt")
    assert list(store.iter_keys("ws/")) == ["ws/assets/a.txt"]


# --------------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------------


class FakeRemote(MemoryStorageProvider):
    """A stand-in cloud provider: one shared object store, URLs on a CDN host."""

    slug = "fakes3"
    settings = (Setting("FAKES3_PUBLIC_URL", default="https://cdn.example.test"),)
    store: dict = {}

    @classmethod
    def from_config(cls, config):
        provider = cls(config["FAKES3_PUBLIC_URL"])
        provider.objects = cls.store
        return provider


class _EP:
    def __init__(self, name, exported, dist="marvin-storage-fake", version="0.1.0"):
        self.name, self._exported = name, exported
        self.dist = SimpleNamespace(name=dist, version=version)

    def load(self):
        if isinstance(self._exported, Exception):
            raise self._exported
        return self._exported


@pytest.fixture
def entry_points(monkeypatch):
    """Install stand-in `marvin.storage_providers` entry points; the registry reloads around the test."""
    real = importlib.metadata.entry_points
    installed: list[_EP] = []

    def fake(group=None, **kw):
        return list(installed) if group == "marvin.storage_providers" else real(group=group, **kw)

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    registry.reset()
    provider_factory.reset_provider_cache()
    FakeRemote.store = {}
    yield installed
    registry.reset()
    provider_factory.reset_provider_cache()


FAKE_PLUGIN = StoragePlugin(slug="fakes3", name="Fake S3", provider=FakeRemote)


def _settings(**update):
    return get_app_settings().model_copy(update=update)


def test_local_is_built_in(entry_points):
    assert registry.plugins()["local"].provider is LocalStorageProvider
    assert registry.source_of("local") == registry.BUILTIN
    assert registry.load_plugins() == []  # built-ins are not installed packages


def test_unknown_provider_is_refused_with_what_is_available(entry_points):
    with pytest.raises(StorageConfigError) as err:
        provider_factory.validate_storage_config(_settings(STORAGE_PROVIDER="r2"))
    assert "'r2'" in str(err.value)
    assert "local" in str(err.value)


def test_plugin_registers_by_slug(entry_points):
    entry_points.append(_EP("fake", FAKE_PLUGIN))
    [report] = registry.load_plugins()
    assert (report.ok, report.slugs, report.distribution, report.version) == (True, ["fakes3"], "marvin-storage-fake", "0.1.0")
    provider = provider_factory.get_storage_provider(_settings(STORAGE_PROVIDER="fakes3"))
    assert isinstance(provider, FakeRemote)
    assert provider.get_public_url("k") == "https://cdn.example.test/k"


def test_entry_point_may_export_a_factory(entry_points):
    entry_points.append(_EP("fake", lambda: FAKE_PLUGIN))
    assert registry.load_plugins()[0].ok
    assert "fakes3" in registry.plugins()


def test_a_plugin_can_not_replace_local(entry_points):
    entry_points.append(_EP("evil", StoragePlugin(slug="local", name="Not local", provider=FakeRemote)))
    [report] = registry.load_plugins()
    assert not report.ok and "built in" in report.error
    assert registry.plugins()["local"].provider is LocalStorageProvider


def test_s3_comes_only_from_its_plugin(entry_points):
    """Core's own S3 provider was removed in storage slice 7: `s3` is the marvin-storage-s3 plugin's."""
    registry.load_plugins(force=True)
    assert "s3" not in registry.plugins()
    entry_points.append(_EP("s3", StoragePlugin(slug="s3", name="S3 plugin", provider=FakeRemote)))
    assert registry.load_plugins(force=True)[0].ok
    assert registry.plugins()["s3"].provider is FakeRemote
    assert registry.source_of("s3") == "s3"


def test_broken_plugins_are_reported_not_fatal(entry_points):
    entry_points += [_EP("boom", ImportError("no module named cloud")), _EP("odd", object()), _EP("fake", FAKE_PLUGIN)]
    reports = {r.name: r for r in registry.load_plugins()}
    assert not reports["boom"].ok and "no module named cloud" in reports["boom"].error
    assert not reports["odd"].ok and "StoragePlugin" in reports["odd"].error
    assert reports["fake"].ok


def test_s3_without_its_plugin_says_no_plugin_provides_it(entry_points):
    registry.load_plugins(force=True)
    with pytest.raises(StorageConfigError, match="no installed storage plugin provides it"):
        provider_factory.get_storage_provider(_settings(STORAGE_PROVIDER="s3", STORAGE_S3_BUCKET=None))


# --------------------------------------------------------------------------------------------------
# Per-row resolution
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def remote_active(entry_points, monkeypatch, tmp_path):
    """New uploads go to the fake remote; local rows still live under tmp_path/local."""
    entry_points.append(_EP("fake", FAKE_PLUGIN))
    settings = _settings(
        STORAGE_PROVIDER="fakes3", STORAGE_LOCAL_ROOT=tmp_path / "local", STORAGE_LOCAL_PUBLIC_BASE_URL="https://api.example.test/assets"
    )
    monkeypatch.setattr(provider_factory, "_settings", lambda: settings)
    local = LocalStorageProvider(root=tmp_path / "local", public_base_url="https://api.example.test/assets")
    local.put("ws/assets/old.txt", io.BytesIO(b"from disk"), "text/plain")
    FakeRemote.store["ws/assets/new.txt"] = (b"from the cloud", "text/plain", None)
    return local


def test_provider_for_resolves_each_row(remote_active):
    assert isinstance(provider_factory.provider_for(SimpleNamespace(storage_provider="local")), LocalStorageProvider)
    assert isinstance(provider_factory.provider_for(SimpleNamespace(storage_provider="fakes3")), FakeRemote)
    assert isinstance(provider_factory.provider_for(SimpleNamespace()), FakeRemote)  # no row slug: the active one
    assert provider_factory.provider_for("local") is provider_factory.provider_for("local")  # built once


def test_a_row_on_an_uninstalled_provider_says_so(remote_active):
    with pytest.raises(StorageConfigError, match="'gone'"):
        provider_factory.provider_for(SimpleNamespace(storage_provider="gone"))


@pytest.fixture
def workspace(db_session, remote_active):
    """A workspace with one local and one remote asset row."""
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Assets
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"Store {marker}", slug=f"store-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Store User",
            username=f"s-{marker}",
            email=f"s-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=True,
        )
    )
    rows = {}
    for slug, provider, key in (("old", "local", "ws/assets/old.txt"), ("new", "fakes3", "ws/assets/new.txt")):
        row = Assets(
            session=db_session,
            group_id=gid,
            slug=f"{slug}-{marker}",
            name=slug,
            original_filename=f"{slug}.txt",
            filename=slug,
            extension="txt",
            file_size=1,
            mime_type="text/plain",
            asset_type="document",
            checksum="x",
            storage_provider=provider,
            storage_key=key,
            uploaded_by=uid,
        )
        db_session.add(row)
        rows[slug] = row
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, old=rows["old"].id, new=rows["new"].id)
    db_session.rollback()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_asset_urls_follow_each_rows_provider(db_session, workspace):
    from marvin.db.models.platform import Assets
    from marvin.schemas.platform.assets import AssetRead

    assert AssetRead.model_validate(db_session.get(Assets, workspace.old)).public_url == "https://api.example.test/assets/ws/assets/old.txt"
    assert AssetRead.model_validate(db_session.get(Assets, workspace.new)).public_url == "https://cdn.example.test/ws/assets/new.txt"


def test_download_serves_local_and_remote_rows_side_by_side(workspace):
    from fastapi.testclient import TestClient

    from marvin.app import app
    from marvin.core.dependencies import get_current_user
    from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=True,
        is_superuser=False,
        full_name="Store User",
        email="s@x.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=workspace.gid, workspace_role=WorkspaceRole.ADMIN)],
        get_workspace_role=lambda group_id: WorkspaceRole.ADMIN,
    )
    try:
        client = TestClient(app)
        local = client.get(f"/api/platform/assets/{workspace.old}/file", follow_redirects=False)
        assert local.status_code == 200, local.text
        assert local.content == b"from disk"
        remote = client.get(f"/api/platform/assets/{workspace.new}/file", follow_redirects=False)
        assert remote.status_code in (302, 307)
        assert remote.headers["location"] == "https://cdn.example.test/ws/assets/new.txt"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_delete_and_reads_use_the_rows_provider(db_session, workspace, remote_active):
    from marvin.db.models.platform import Assets
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.assets.asset_storage_service import AssetStorageService

    service = AssetStorageService(get_repositories(db_session, group_id=workspace.gid), provider_factory.get_storage_provider())
    assert service._get_provider_name() == "fakes3"  # what new uploads record
    assert service.read_bytes(db_session.get(Assets, workspace.old)) == b"from disk"
    assert service.read_bytes(db_session.get(Assets, workspace.new)) == b"from the cloud"
    assert service.delete_asset(workspace.old)
    assert not remote_active.exists("ws/assets/old.txt")
    assert "ws/assets/new.txt" in FakeRemote.store  # the remote store is untouched


def test_admin_plugins_lists_installed_storage_plugins(entry_points):
    from marvin.services import plugins

    entry_points.append(_EP("fake", FAKE_PLUGIN))
    [(report, found)] = plugins._storage_sources()
    assert report.distribution == "marvin-storage-fake"
    assert found == [FAKE_PLUGIN]
