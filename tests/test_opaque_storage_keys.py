"""Opaque storage keys and per-workspace public asset domains (services/storage/keys.py,
provider_factory.public_url_for, storage_migrate --rekey / --prune-old):

- new files are stored as <workspace code>/<yyyy>/<mm>/<uuid>.<ext>: no workspace slug, no filename;
  the code is random, stable per workspace and different across workspaces;
- the original name is served as Content-Disposition (ASCII and RFC 5987 non-ASCII), by Marvin and on
  the object where the provider stores it;
- a platform admin can give a workspace its own public domain for remote files (validated, audited at
  platform scope); local files keep the API host;
- --rekey moves old keys to opaque ones (in place or with a provider move), idempotent and resumable,
  old local URLs keep working (then redirect after --prune-old); library files too; the backup mirror,
  export and import work with the new keys.
"""

import hashlib
import io
import uuid
import zipfile
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from fastapi.testclient import TestClient
from marvin_integration_sdk.storage import Setting, StoragePlugin
from marvin_integration_sdk.storage.memory import MemoryBackupTarget, MemoryStorageProvider

from marvin.db.models.users.roles import PlatformRole
from marvin.services.storage import keys, migration, provider_factory
from marvin.services.storage.local_provider import LocalStorageProvider
from tests.test_storage_providers import _EP, _settings, entry_points  # noqa: F401  (fixture)

STORAGE_URL = "/api/admin/storage"


class DomainRemote(MemoryStorageProvider):
    """A stand-in cloud provider that builds its URLs from STORAGE_REMOTE_PUBLIC_URL (as the s3 plugin does)."""

    slug = "cloud"
    settings = (Setting("STORAGE_REMOTE_PUBLIC_URL", default="https://cdn.default.test"),)
    store: dict = {}

    @classmethod
    def from_config(cls, config):
        provider = cls(config["STORAGE_REMOTE_PUBLIC_URL"])
        provider.objects = cls.store
        return provider


CLOUD = StoragePlugin(slug="cloud", name="Cloud", provider=DomainRemote)


@pytest.fixture
def platform(entry_points, monkeypatch, tmp_path):  # noqa: F811
    from marvin.db.db_setup import session_context
    from marvin.db.models.platform.platform_settings import PlatformSettingsModel

    entry_points.append(_EP("cloud", CLOUD))
    DomainRemote.store = {}
    settings = _settings(
        STORAGE_PROVIDER="local", STORAGE_LOCAL_ROOT=tmp_path / "local", STORAGE_LOCAL_PUBLIC_BASE_URL="https://api.example.test/assets"
    )
    monkeypatch.setattr(provider_factory, "_settings", lambda: settings)

    def clear():
        with session_context() as session:
            session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key == provider_factory.UPLOAD_SETTING_KEY).delete()
            session.commit()
        provider_factory.reset_provider_cache()

    clear()
    yield SimpleNamespace(local=LocalStorageProvider(root=tmp_path / "local"), root=tmp_path / "local")
    clear()


@pytest.fixture
def client(platform, monkeypatch):
    """The app, its /assets mount serving the test's local root."""
    from marvin.app import app
    from marvin.services.storage.static import LocalAssetFiles

    mount = next(r.app for r in app.routes if isinstance(getattr(r, "app", None), LocalAssetFiles))
    monkeypatch.setattr(mount, "all_directories", [str(platform.root)])
    platform.root.mkdir(parents=True, exist_ok=True)
    return TestClient(app)


def _make_workspace(db_session, label):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"{label} {marker}", slug=f"{label.lower()}-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Ada Admin",
            username=f"ok-{marker}",
            email=f"ok-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="SUPER_ADMIN",
            admin=True,
        )
    )
    db_session.commit()
    return SimpleNamespace(gid=gid, uid=uid, slug=f"{label.lower()}-{marker}", name=f"{label} {marker}")


def _drop_workspace(db_session, w):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Assets, StorageKeyAliasModel
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users import Users

    db_session.rollback()
    ids = [a for (a,) in db_session.query(Assets.id).filter(Assets.group_id == w.gid)]
    if ids:
        db_session.query(StorageKeyAliasModel).filter(StorageKeyAliasModel.asset_id.in_(ids)).delete()
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id == w.gid).delete()
    db_session.query(Assets).filter(Assets.group_id == w.gid).delete()
    db_session.query(Users).filter(Users.group_id == w.gid).delete()
    db_session.query(Groups).filter(Groups.id == w.gid).delete()
    db_session.commit()


@pytest.fixture
def workspace(db_session, platform):
    w = _make_workspace(db_session, "Opaque")
    yield w
    _drop_workspace(db_session, w)


@pytest.fixture
def other_workspace(db_session, platform):
    w = _make_workspace(db_session, "Other")
    yield w
    _drop_workspace(db_session, w)


def _service(db_session, workspace):
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.assets.asset_storage_service import AssetStorageService

    return AssetStorageService(get_repositories(db_session, group_id=workspace.gid), provider_factory.get_storage_provider())


def _upload(db_session, workspace, name="photo.txt", data=b"hello"):
    from marvin.schemas.platform.assets import AssetUploadRequest

    slug = f"up-{uuid.uuid4().hex[:8]}"
    return _service(db_session, workspace).upload_asset(
        UploadFile(file=io.BytesIO(data), filename=name), AssetUploadRequest(slug=slug, name=name), workspace.gid, workspace.uid
    )


def _code(db_session, workspace):
    from marvin.db.models.groups import Groups

    db_session.expire_all()
    return db_session.get(Groups, workspace.gid).storage_code


def _choose(slug):
    from marvin.db.db_setup import session_context
    from marvin.services.storage.admin import set_upload_provider

    with session_context() as session:
        return set_upload_provider(session, slug)


def _old_asset(db_session, w, local, name, data, provider="local"):
    """An asset stored the way Marvin stored files before opaque keys: <slug>/assets/<yyyy>/<mm>/<uuid>-<name>."""
    from marvin.db.models.platform import Assets

    key = f"{w.slug}/assets/2026/09/{uuid.uuid4()}-{name.lower()}"
    if provider == "local":
        local.put(key, io.BytesIO(data), "image/jpeg")
    else:
        DomainRemote.store[key] = (data, "image/jpeg", None)
    row = Assets(
        session=db_session,
        group_id=w.gid,
        slug=f"old-{uuid.uuid4().hex[:8]}",
        name=name,
        original_filename=name,
        filename=name.rsplit(".", 1)[0],
        extension=name.rsplit(".", 1)[-1],
        file_size=len(data),
        mime_type="image/jpeg",
        asset_type="image",
        checksum=hashlib.sha256(data).hexdigest(),
        storage_provider=provider,
        storage_key=key,
        uploaded_by=w.uid,
    )
    db_session.add(row)
    db_session.commit()
    return row.id, key


# --------------------------------------------------------------------------------------------------
# Key format
# --------------------------------------------------------------------------------------------------


def test_key_helpers():
    code = keys.new_code()
    assert len(code) == 12 and set(code) <= set(keys.CODE_ALPHABET)
    key = keys.new_key(code, "IMG_9750 Orig.JPEG", "image/jpeg")
    assert keys.is_opaque(key, code) and key.endswith(".jpeg") and "img" not in key.lower().split("/")[-1].split(".")[0]
    assert not keys.is_opaque(key, keys.new_code())  # another workspace's
    assert not keys.is_opaque("grace-martin-franklin/assets/2026/09/0e2c…-img.jpeg")
    assert keys.key_extension("photo.Tar.GZ") == "gz"
    assert keys.key_extension("we!rd.p_n-g") == "png"  # reduced to [a-z0-9]
    assert keys.key_extension("noext", "image/jpeg") == "jpg"
    assert keys.key_extension(".hidden") == "" and keys.key_extension(None) == ""
    assert keys.new_key(code, "noext").count(".") == 0
    # A rekey derives the same key from the same seed (resumable), keeping the old key's month.
    old = "ws/assets/2025/03/0e2c-photo.png"
    assert keys.rekeyed(code, old, "asset:1", "photo.png") == keys.rekeyed(code, old, "asset:1", "photo.png")
    assert keys.rekeyed(code, old, "asset:1").startswith(f"{code}/2025/03/") and keys.rekeyed(code, old, "asset:2") != keys.rekeyed(
        code, old, "asset:1"
    )


def test_new_uploads_get_opaque_keys_with_a_stable_code_per_workspace(db_session, workspace, other_workspace):
    a = _upload(db_session, workspace, "My Holiday Photo.JPG", b"one")
    b = _upload(db_session, workspace, "second.png", b"two")
    c = _upload(db_session, other_workspace, "second.png", b"three")
    code, other = _code(db_session, workspace), _code(db_session, other_workspace)
    assert code and other and code != other
    for asset, ws, ext in ((a, workspace, "jpg"), (b, workspace, "png"), (c, other_workspace, "png")):
        assert keys.is_opaque(asset.storage_key, _code(db_session, ws)) and asset.storage_key.endswith(f".{ext}")
        assert ws.slug not in asset.storage_key and "holiday" not in asset.storage_key.lower() and "second" not in asset.storage_key
        assert ws.slug not in asset.public_url and asset.public_url == f"https://api.example.test/assets/{asset.storage_key}"
    assert a.storage_key.split("/")[0] == b.storage_key.split("/")[0] == code  # stable within a workspace
    assert a.original_filename == "My Holiday Photo.JPG"  # the name stays on the row


def test_every_workspace_has_a_storage_code(db_session, workspace):
    from marvin.db.models.groups import Groups

    assert db_session.query(Groups).filter(Groups.storage_code.is_(None)).count() == 0
    # A workspace that somehow has none gets one when it first needs it, and keeps it.
    db_session.query(Groups).filter(Groups.id == workspace.gid).update({"storage_code": None})
    db_session.commit()
    first = keys.workspace_code(db_session, workspace.gid)
    db_session.commit()
    assert first == keys.workspace_code(db_session, workspace.gid) == _code(db_session, workspace)


def test_derivatives_and_imports_get_opaque_keys(db_session, workspace):
    from marvin.db.models.platform import Assets
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    source = _upload(db_session, workspace, "source.png", b"png")
    derived = _service(db_session, workspace).create_derivative(
        source=source, data=b"graded", group_id=workspace.gid, derivation="grade", slug=f"g-{uuid.uuid4().hex[:6]}", name="Graded"
    )
    assert keys.is_opaque(derived.storage_key, _code(db_session, workspace)) and derived.storage_key.endswith(".png")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("files/abcdefghijkl/2026/01/0e2c0e2c-0e2c-4e2c-8e2c-0e2c0e2c0e2c.txt", b"bundle bytes")
    slug = f"logo-{uuid.uuid4().hex[:6]}"
    meta = {"slug": slug, "name": "Logo", "originalFilename": "Logo Final.txt", "extension": "txt", "fileSize": 12, "mimeType": "text/plain"}
    meta |= {"assetType": "document", "storageProvider": "local", "storageKey": "abcdefghijkl/2026/01/0e2c0e2c-0e2c-4e2c-8e2c-0e2c0e2c0e2c.txt"}
    with zipfile.ZipFile(buf) as zf:
        loader = WorkspaceSeedLoader(get_repositories(db_session, group_id=workspace.gid))
        loader._seed_user_id = workspace.uid
        loader._overwrite = False
        assert loader._import_assets([meta], zf) == 1
    db_session.commit()
    row = db_session.query(Assets).filter(Assets.group_id == workspace.gid, Assets.slug == slug).one()
    assert keys.is_opaque(row.storage_key, _code(db_session, workspace))  # under the importing workspace's code
    assert row.original_filename == "Logo Final.txt"


def test_export_and_import_round_trip_with_opaque_keys(db_session, workspace, other_workspace, tmp_path):
    import json

    from marvin.db.models.platform import Assets
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    asset = _upload(db_session, workspace, "Exported Thing.txt", b"exported bytes")
    bundle = WorkspaceExporter(get_repositories(db_session, group_id=workspace.gid)).export_workspace_bundle(temp_dir=tmp_path)
    with zipfile.ZipFile(bundle) as zf:
        assert zf.read(f"files/{asset.storage_key}") == b"exported bytes"
        data = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith(".json"))))
        metas = [a for a in data["assets"] if a["slug"] == asset.slug]
        loader = WorkspaceSeedLoader(get_repositories(db_session, group_id=other_workspace.gid))
        loader._seed_user_id = other_workspace.uid
        loader._overwrite = False
        assert loader._import_assets(metas, zf) == 1
    db_session.commit()
    row = db_session.query(Assets).filter(Assets.group_id == other_workspace.gid, Assets.slug == asset.slug).one()
    assert keys.is_opaque(row.storage_key, _code(db_session, other_workspace)) and row.storage_key != asset.storage_key
    assert row.original_filename == "Exported Thing.txt"
    assert provider_factory.provider_for(row).get(row.storage_key).read() == b"exported bytes"


# --------------------------------------------------------------------------------------------------
# Download names
# --------------------------------------------------------------------------------------------------


def test_content_disposition_ascii_and_non_ascii():
    assert keys.content_disposition("IMG_9750 orig.jpeg") == 'inline; filename="IMG_9750 orig.jpeg"'
    assert keys.content_disposition("Café menu.pdf") == "inline; filename=\"Cafe menu.pdf\"; filename*=UTF-8''Caf%C3%A9%20menu.pdf"
    assert keys.content_disposition("日本.png") == "inline; filename=\".png\"; filename*=UTF-8''%E6%97%A5%E6%9C%AC.png"
    # Quotes, backslashes, control characters and paths never reach the header.
    assert keys.content_disposition('a"b\\c.txt') == 'inline; filename="c.txt"'  # a backslash is a path separator
    assert keys.content_disposition('say "hi".txt') == "inline; filename=\"say _hi_.txt\"; filename*=UTF-8''say%20%22hi%22.txt"
    assert keys.content_disposition("evil\r\nX-Header: 1.txt") == 'inline; filename="evilX-Header: 1.txt"'
    assert keys.content_disposition("../../etc/passwd") == 'inline; filename="passwd"'
    assert keys.content_disposition("") is None and keys.content_disposition(None) is None
    assert keys.object_metadata("a.png", {"alt": "x"}) == {"alt": "x", "content_disposition": 'inline; filename="a.png"'}


def test_uploads_send_the_original_name_to_the_provider(db_session, workspace):
    _choose("cloud")
    asset = _upload(db_session, workspace, "Résumé 2026.pdf", b"%PDF")
    assert DomainRemote.store[asset.storage_key][2]["content_disposition"] == (
        "inline; filename=\"Resume 2026.pdf\"; filename*=UTF-8''R%C3%A9sum%C3%A9%202026.pdf"
    )


@pytest.fixture
def member(workspace):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user
    from marvin.db.models.users.roles import WorkspaceRole

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=True,
        is_superuser=False,
        full_name="Ada Admin",
        username="ada",
        email="a@x.test",
        platform_role=PlatformRole.SUPER_ADMIN,
        workspace_memberships=[SimpleNamespace(group_id=workspace.gid, workspace_role=WorkspaceRole.ADMIN)],
        get_workspace_role=lambda group_id: WorkspaceRole.ADMIN,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_marvin_serves_local_files_inline_under_their_original_name(db_session, workspace, member, client):
    asset = _upload(db_session, workspace, "Café menu.txt", b"menu")
    res = member.get(f"/api/platform/assets/{asset.id}/file", follow_redirects=False)
    assert res.status_code == 200 and res.content == b"menu"
    assert res.headers["content-disposition"] == "inline; filename=\"Cafe menu.txt\"; filename*=UTF-8''Caf%C3%A9%20menu.txt"

    res = client.get(f"/assets/{asset.storage_key}")
    assert res.status_code == 200 and res.content == b"menu"
    assert res.headers["content-disposition"] == "inline; filename=\"Cafe menu.txt\"; filename*=UTF-8''Caf%C3%A9%20menu.txt"


# --------------------------------------------------------------------------------------------------
# Per-workspace public domain
# --------------------------------------------------------------------------------------------------


def test_public_base_url_validation():
    from marvin.services.storage.admin import InvalidPublicBaseURLError, validate_public_base_url

    assert validate_public_base_url("https://assets.client.com/") == "https://assets.client.com"
    assert validate_public_base_url("  https://cdn.client.com/marvin/ ") == "https://cdn.client.com/marvin"
    assert validate_public_base_url("") is None and validate_public_base_url(None) is None
    for bad in (
        "http://assets.client.com",
        "ftp://assets.client.com",
        "assets.client.com",
        "https://",
        "https://user:pw@assets.client.com",
        "https://assets.client.com/?a=1",
        "https://assets.client.com/#x",
        "https://assets client.com",
        "https://bad_host!.com",
        "https://assets.client.com:99999",
        "https://" + "a" * 260 + ".com",
    ):
        with pytest.raises(InvalidPublicBaseURLError):
            validate_public_base_url(bad)
    assert validate_public_base_url("http://localhost:9000/bucket", allow_http=True) == "http://localhost:9000/bucket"


@pytest.fixture
def admin(workspace):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    def _as(role=PlatformRole.SUPER_ADMIN):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=workspace.uid,
            group_id=workspace.gid,
            active_group_id=workspace.gid,
            platform_role=role,
            is_superuser=False,
            admin=True,
            full_name="Ada Admin",
            username="ada",
        )
        return TestClient(app)

    yield _as
    app.dependency_overrides.pop(get_current_user, None)


def _domain_events(db_session, workspace):
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.expire_all()
    return (
        db_session.query(EventLogModel)
        .filter(EventLogModel.workspace_id == workspace.gid, EventLogModel.event_type == "storage_public_domain_changed")
        .order_by(EventLogModel.occurred_at)
        .all()
    )


def test_a_workspace_domain_serves_its_remote_files_only(db_session, workspace, other_workspace, admin):
    from marvin.db.models.platform import Assets
    from marvin.schemas.platform.assets import AssetRead

    local_row = _upload(db_session, workspace, "local.txt", b"on disk")
    _choose("cloud")
    remote = _upload(db_session, workspace, "remote.txt", b"in the cloud")
    elsewhere = _upload(db_session, other_workspace, "theirs.txt", b"theirs")
    assert remote.public_url == f"https://cdn.default.test/{remote.storage_key}"

    client = admin()
    res = client.put(f"{STORAGE_URL}/workspaces/{workspace.gid}", json={"assetPublicBaseUrl": "https://assets.client.test/"})
    assert res.status_code == 200, res.text
    body = res.json()
    mine = next(w for w in body["workspaceSettings"] if w["workspaceId"] == str(workspace.gid))
    assert mine == {
        "workspaceId": str(workspace.gid),
        "workspace": workspace.name,
        "storageCode": _code(db_session, workspace),
        "assetPublicBaseUrl": "https://assets.client.test",
    }

    db_session.expire_all()
    read = {a.id: AssetRead.model_validate(db_session.get(Assets, a.id)) for a in (local_row, remote, elsewhere)}
    assert read[remote.id].public_url == f"https://assets.client.test/{remote.storage_key}"  # same key, the workspace's domain
    assert read[local_row.id].public_url == f"https://api.example.test/assets/{local_row.storage_key}"  # local: the API host
    assert read[elsewhere.id].public_url == f"https://cdn.default.test/{elsewhere.storage_key}"  # another workspace: the default
    # New uploads use it too.
    newer = _upload(db_session, workspace, "newer.txt", b"newer")
    assert newer.public_url == f"https://assets.client.test/{newer.storage_key}"

    # Back to the platform default.
    assert client.put(f"{STORAGE_URL}/workspaces/{workspace.gid}", json={"assetPublicBaseUrl": None}).status_code == 200
    db_session.expire_all()
    assert AssetRead.model_validate(db_session.get(Assets, remote.id)).public_url == f"https://cdn.default.test/{remote.storage_key}"

    from marvin.services.events.event_catalog import get_catalog_entry, is_platform_event

    rows = _domain_events(db_session, workspace)
    assert [r.message_body for r in rows] == [
        f"{workspace.name}: remote assets now served from https://assets.client.test (was the platform default)",
        f"{workspace.name}: remote assets now served from the platform default (was https://assets.client.test)",
    ]
    assert is_platform_event("storage_public_domain_changed") and get_catalog_entry("storage_public_domain_changed").audit_locked


def test_the_download_redirect_and_publishing_api_use_the_workspace_domain(db_session, workspace, member):
    from marvin.app import app
    from marvin.core.dependencies import get_publishing_context
    from marvin.db.db_setup import session_context
    from marvin.services.storage.admin import set_workspace_public_base_url

    _choose("cloud")
    asset = _upload(db_session, workspace, "pub.txt", b"published")
    with session_context() as session:
        set_workspace_public_base_url(session, workspace.gid, "https://assets.client.test")
        session.commit()

    res = member.get(f"/api/platform/assets/{asset.id}/file", follow_redirects=False)
    assert res.status_code in (302, 307) and res.headers["location"] == f"https://assets.client.test/{asset.storage_key}"

    perms = SimpleNamespace(require_permission=lambda *a, **k: None)
    app.dependency_overrides[get_publishing_context] = lambda: (
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=workspace.gid, slug=workspace.slug),
        perms,
    )
    try:
        client = TestClient(app)
        meta = client.get(f"/api/publish/{workspace.slug}/assets/{asset.slug}")
        assert meta.status_code == 200, meta.text
        assert meta.json()["publicUrl"] == f"https://assets.client.test/{asset.storage_key}"
        file = client.get(f"/api/publish/{workspace.slug}/assets/{asset.slug}/file", follow_redirects=False)
        assert file.headers["location"] == f"https://assets.client.test/{asset.storage_key}"
    finally:
        app.dependency_overrides.pop(get_publishing_context, None)


def test_workspace_domain_api_validates_and_is_super_admin_only(db_session, workspace, admin):
    url = f"{STORAGE_URL}/workspaces/{workspace.gid}"
    res = admin().put(url, json={"assetPublicBaseUrl": "https://user:pw@assets.client.test"})
    assert res.status_code == 422 and "user name" in res.json()["detail"]
    assert admin().put(f"{STORAGE_URL}/workspaces/{uuid.uuid4()}", json={"assetPublicBaseUrl": "https://a.client.test"}).status_code == 404
    assert admin(PlatformRole.NONE).put(url, json={"assetPublicBaseUrl": "https://a.client.test"}).status_code == 403
    assert admin().put(url, json={"assetPublicBaseUrl": None}).status_code == 200  # unchanged: no event
    assert _domain_events(db_session, workspace) == []


def test_a_provider_without_a_public_url_setting_keeps_its_own_urls(db_session, workspace, entry_points, caplog):  # noqa: F811
    """The domain only applies where the provider builds URLs from STORAGE_REMOTE_PUBLIC_URL."""
    from marvin.db.db_setup import session_context
    from marvin.services.storage import registry
    from marvin.services.storage.admin import set_workspace_public_base_url
    from tests.test_storage_providers import FAKE_PLUGIN

    entry_points.append(_EP("fake", FAKE_PLUGIN))
    registry.reset()
    provider_factory.reset_provider_cache()
    with session_context() as session:
        set_workspace_public_base_url(session, workspace.gid, "https://assets.client.test")
        session.commit()
    with caplog.at_level("ERROR"):
        url = provider_factory.public_url_for("fakes3", "k/2026/10/x.txt", workspace.gid)
    assert url == "https://cdn.example.test/k/2026/10/x.txt" and "STORAGE_REMOTE_PUBLIC_URL" in caplog.text


# --------------------------------------------------------------------------------------------------
# storage_migrate --rekey
# --------------------------------------------------------------------------------------------------


def test_rekey_in_place_keeps_old_urls_working_until_pruned(db_session, workspace, platform, client):
    from marvin.db.models.platform import Assets, StorageKeyAliasModel

    old = [_old_asset(db_session, workspace, platform.local, f"IMG_{i}.jpeg", f"bytes {i}".encode()) for i in range(3)]
    fresh = _upload(db_session, workspace, "fresh.png", b"already opaque")

    dry = migration.migrate(None, rekey=True, workspace=workspace.slug, dry_run=True)
    assert (dry.moved, dry.rekeyed) == (3, 3)
    assert db_session.query(StorageKeyAliasModel).filter(StorageKeyAliasModel.asset_id.in_([i for i, _ in old])).count() == 0

    report = migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert (report.moved, report.rekeyed, report.failures) == (3, 3, [])
    code = _code(db_session, workspace)
    db_session.expire_all()
    for (asset_id, old_key), i in zip(old, range(3), strict=True):
        row = db_session.get(Assets, asset_id)
        assert row.storage_provider == "local" and keys.is_opaque(row.storage_key, code) and row.storage_key.endswith(".jpeg")
        assert row.storage_key.startswith(f"{code}/2026/09/")  # the old key's month
        assert platform.local.get(row.storage_key).read() == f"bytes {i}".encode()
        assert platform.local.exists(old_key)  # the old copy stays until --prune-old
        alias = db_session.query(StorageKeyAliasModel).filter_by(provider="local", storage_key=old_key).one()
        assert (alias.asset_id, alias.current_key, alias.pruned_at) == (asset_id, row.storage_key, None)
        assert client.get(f"/assets/{old_key}").content == f"bytes {i}".encode()  # still served
    assert db_session.get(Assets, fresh.id).storage_key == fresh.storage_key  # already opaque: untouched

    again = migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert (again.moved, again.passes) == (0, 0)  # idempotent

    pruned = migration.prune_old(workspace=workspace.slug)
    assert (pruned.pruned, pruned.failures) == (3, [])
    db_session.expire_all()
    for asset_id, old_key in old:
        row = db_session.get(Assets, asset_id)
        assert not platform.local.exists(old_key)
        res = client.get(f"/assets/{old_key}", follow_redirects=False)
        assert res.status_code == 302 and res.headers["location"] == f"https://api.example.test/assets/{row.storage_key}"
    assert migration.prune_old(workspace=workspace.slug).pruned == 0


def test_rekey_with_a_move_and_back(db_session, workspace, platform):
    from marvin.db.models.platform import Assets

    old = [_old_asset(db_session, workspace, platform.local, f"P{i}.JPEG", f"photo {i}".encode()) for i in range(2)]
    _choose("cloud")
    report = migration.migrate("cloud", rekey=True, workspace=workspace.slug, verify=True)
    assert (report.moved, report.rekeyed, report.copied, report.failures) == (2, 2, 2, [])
    db_session.expire_all()
    for asset_id, old_key in old:
        row = db_session.get(Assets, asset_id)
        assert row.storage_provider == "cloud" and keys.is_opaque(row.storage_key, _code(db_session, workspace))
        data, _, meta = DomainRemote.store[row.storage_key]
        assert data == platform.local.get(old_key).read()  # bytes equal
        assert meta["content_disposition"] == f'inline; filename="{row.original_filename}"'
        assert row.public_url == f"https://cdn.default.test/{row.storage_key}"
        assert workspace.slug not in row.public_url and "P0" not in row.public_url

    # Back to local: the keys are opaque already, so it is a plain move (no new aliases, same keys).
    back = migration.migrate("local", rekey=True, workspace=workspace.slug)
    assert (back.moved, back.rekeyed, back.failures) == (2, 0, [])
    db_session.expire_all()
    for asset_id, _ in old:
        row = db_session.get(Assets, asset_id)
        assert row.storage_provider == "local" and platform.local.exists(row.storage_key)


def test_an_interrupted_rekey_resumes_on_the_same_keys(db_session, workspace, platform, monkeypatch):
    from marvin.db.models.platform import Assets

    old = [_old_asset(db_session, workspace, platform.local, f"R{i}.jpg", f"resume {i}".encode()) for i in range(3)]
    real_flip, calls = migration._flip, []

    def flaky(session_factory, row, to, url, new_key=None):
        calls.append(row.id)
        if len(calls) == 2:
            raise RuntimeError("killed")
        return real_flip(session_factory, row, to, url, new_key)

    monkeypatch.setattr(migration, "_flip", flaky)
    first = migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert first.moved == 2 and len(first.failures) == 1
    monkeypatch.setattr(migration, "_flip", real_flip)

    second = migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert (second.moved, second.already_there, second.copied, second.failures) == (1, 1, 0, [])  # its copy was there already
    db_session.expire_all()
    stored = {db_session.get(Assets, i).storage_key for i, _ in old}
    on_disk = set(platform.local.iter_keys(_code(db_session, workspace) + "/"))
    assert stored == on_disk  # no stray copies at other keys


def test_uploads_during_a_rekey_are_left_alone_and_old_keys_caught(db_session, workspace, platform, monkeypatch):
    from marvin.db.models.platform import Assets

    _old_asset(db_session, workspace, platform.local, "first.jpg", b"first")
    real_pending, uploaded = migration._pending, []

    def pending(session, to, group_id=None, codes=None):
        rows = real_pending(session, to, group_id, codes)
        if not uploaded:  # an opaque upload and an old-style straggler land during the first pass
            uploaded.append(_upload(db_session, workspace, "during.png", b"during"))
            uploaded.append(_old_asset(db_session, workspace, platform.local, "straggler.jpg", b"straggler"))
        return rows

    monkeypatch.setattr(migration, "_pending", pending)
    report = migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert (report.moved, report.passes, report.failures) == (2, 2, [])
    db_session.expire_all()
    assert db_session.get(Assets, uploaded[0].id).storage_key == uploaded[0].storage_key
    assert keys.is_opaque(db_session.get(Assets, uploaded[1][0]).storage_key, _code(db_session, workspace))


def test_rekey_after_a_move_old_local_copies_and_urls(db_session, workspace, platform, client):
    """Dev's case: files moved to the cloud under their old keys (local copies kept), then rekeyed there.
    --prune-local still finds the local copy at the old key; the old /assets/ URL then redirects to the
    file's opaque URL."""
    from marvin.db.models.platform import Assets

    asset_id, old_key = _old_asset(db_session, workspace, platform.local, "moved.jpg", b"moved bytes")
    _choose("cloud")
    assert migration.migrate("cloud", workspace=workspace.slug).moved == 1  # the earlier move: same key
    report = migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert (report.moved, report.rekeyed) == (1, 1)
    db_session.expire_all()
    row = db_session.get(Assets, asset_id)
    assert row.storage_provider == "cloud" and keys.is_opaque(row.storage_key, _code(db_session, workspace))
    assert old_key in DomainRemote.store and platform.local.exists(old_key)  # both old copies kept

    pruned = migration.prune_local(workspace=workspace.slug)
    assert (pruned.pruned, pruned.failures) == (1, []) and not platform.local.exists(old_key)
    res = client.get(f"/assets/{old_key}", follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == f"https://cdn.default.test/{row.storage_key}"

    assert migration.prune_old(workspace=workspace.slug).pruned == 1 and old_key not in DomainRemote.store
    assert DomainRemote.store[row.storage_key][0] == b"moved bytes"


def test_deleting_a_rekeyed_asset_removes_its_old_copy(db_session, workspace, platform):
    from marvin.db.models.platform import StorageKeyAliasModel

    asset_id, old_key = _old_asset(db_session, workspace, platform.local, "gone.jpg", b"gone")
    migration.migrate(None, rekey=True, workspace=workspace.slug)
    assert platform.local.exists(old_key)
    assert _service(db_session, workspace).delete_asset(asset_id)
    assert not platform.local.exists(old_key)
    assert db_session.query(StorageKeyAliasModel).filter_by(asset_id=asset_id).count() == 0


def test_prune_old_keeps_a_copy_that_does_not_match(db_session, workspace, platform):
    from marvin.db.models.platform import Assets

    asset_id, old_key = _old_asset(db_session, workspace, platform.local, "drift.jpg", b"original")
    migration.migrate(None, rekey=True, workspace=workspace.slug)
    db_session.expire_all()
    platform.local.put(db_session.get(Assets, asset_id).storage_key, io.BytesIO(b"changed since"), "image/jpeg")
    report = migration.prune_old(workspace=workspace.slug)
    assert report.pruned == 0 and "doesn't match" in report.failures[0]
    assert platform.local.exists(old_key)


def test_library_files_are_rekeyed_with_their_pack(db_session, platform, client):
    from marvin.db.models.platform import StorageKeyAliasModel
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import pack_character

    pack_id = uuid.uuid4()
    key = f"_platform/character-packs/{pack_id}/a-idle.gif"
    platform.local.put(key, io.BytesIO(b"GIF89a-idle"), "image/gif")
    url = f"https://api.example.test/assets/{key}"
    pack = CharacterPackModel(
        session=db_session,
        slug=f"pack-{pack_id.hex[:8]}",
        name="Pack",
        pack={"states": {"idle": url}, "files": [{"name": "idle", "key": key, "url": url}]},
    )
    pack.id = pack_id
    db_session.add(pack)
    db_session.commit()
    try:
        report = migration.migrate(None, rekey=True)
        assert report.rekeyed >= 1 and not [f for f in report.failures if str(pack_id) in f]
        db_session.expire_all()
        stored = db_session.get(CharacterPackModel, pack_id).pack
        new_key = stored["files"][0]["key"]
        assert keys.is_opaque(new_key, keys.LIBRARY_CODE) and str(pack_id) not in new_key and new_key.endswith(".gif")
        assert stored["files"][0]["url"] == stored["states"]["idle"] == f"https://api.example.test/assets/{new_key}"
        assert pack_character(db_session.get(CharacterPackModel, pack_id))["states"]["idle"] == f"https://api.example.test/assets/{new_key}"
        res = client.get(f"/assets/{new_key}")
        assert res.content == b"GIF89a-idle" and res.headers["content-disposition"] == 'inline; filename="idle.gif"'

        assert migration.prune_old().pruned >= 1
        res = client.get(f"/assets/{key}", follow_redirects=False)
        assert res.status_code == 302 and res.headers["location"] == f"https://api.example.test/assets/{new_key}"
    finally:
        db_session.query(StorageKeyAliasModel).filter(StorageKeyAliasModel.pack_id == pack_id).delete()
        db_session.query(CharacterPackModel).filter(CharacterPackModel.id == pack_id).delete()
        db_session.commit()


def test_cli_rekey_and_prune_old(db_session, workspace, platform, capsys):
    from marvin.scripts import storage_migrate

    _old_asset(db_session, workspace, platform.local, "cli.jpg", b"cli")
    assert storage_migrate.main(["--rekey", "--workspace", workspace.slug, "--dry-run"]) == 0
    assert storage_migrate.main(["--rekey", "--workspace", workspace.slug]) == 0
    assert storage_migrate.main(["--prune-old", "--workspace", workspace.slug]) == 0
    with pytest.raises(SystemExit):
        storage_migrate.main(["--rekey", "--prune-old"])
    with pytest.raises(SystemExit):
        storage_migrate.main([])


def test_the_backup_mirror_copies_opaque_keys(db_session, workspace, platform, tmp_path):
    from marvin.services.backup_engine import engine as eng

    asset = _upload(db_session, workspace, "mirrored.png", b"mirror me")
    target = MemoryBackupTarget()
    report = eng.Report(target="t")
    eng.backup_assets([platform.local], target, report, dry_run=False, work=tmp_path)
    assert report.failures == [] and f"assets/{asset.storage_key}" in target.list("assets/")
    again = eng.Report(target="t")
    eng.backup_assets([platform.local], target, again, dry_run=False, work=tmp_path)
    assert again.assets_uploaded == 0
