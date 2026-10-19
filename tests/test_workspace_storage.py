"""A workspace's own bucket ("bring your own storage", slice 1: services/storage/workspace.py).

The platform keeps its storage (a local directory here); one workspace keeps its files in its own bucket through a
stand-in plugin with the same contract as marvin-storage-s3. New rows record `ws:<connection id>`; nothing ever
falls back to the platform's storage; the provider is built from the connection's own values only.
"""

import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from marvin_integration_sdk.storage import Setting, StorageConfigError, StoragePlugin
from marvin_integration_sdk.storage.memory import MemoryBackupTarget, MemoryStorageProvider

from marvin.services.storage import provider_factory
from marvin.services.storage import workspace as ws_storage
from marvin.services.storage.workspace import WorkspaceStorageUnavailable
from tests.test_opaque_storage_keys import _drop_workspace, _make_workspace, platform  # noqa: F401  (fixture)
from tests.test_storage_providers import _EP, entry_points  # noqa: F401  (fixture)

R2 = "https://acct.r2.cloudflarestorage.com"


class BucketProvider(MemoryStorageProvider):
    """A bucket per name, shared across instances, so a rebuilt provider sees the same files."""

    slug = "bucket"
    buckets: dict = {}
    settings = (Setting("B_BUCKET", required=True), Setting("B_ENDPOINT"), Setting("B_KEY_ID"), Setting("B_KEY", secret=True), Setting("B_PUBLIC"))
    workspace_settings = (
        Setting("B_BUCKET", required=True),
        Setting("B_ENDPOINT"),
        Setting("B_KEY_ID", required=True),  # like S3's access key ID: required, not secret
        Setting("B_KEY", secret=True, required=True),
        Setting("B_PUBLIC", required=True),
    )
    endpoint_setting = "B_ENDPOINT"
    public_url_setting = "B_PUBLIC"

    @classmethod
    def from_config(cls, config):
        provider = cls.buckets.setdefault(config["B_BUCKET"], cls(public_base_url=config["B_PUBLIC"]))
        provider.key_used = (config["B_KEY_ID"], config["B_KEY"])
        return provider


class BucketTarget(MemoryBackupTarget):
    """The stand-in plugin's backup target: a bucket per name, shared across instances."""

    slug = "bucket"
    buckets: dict = {}
    settings = (Setting("T_BUCKET", required=True), Setting("T_ENDPOINT"), Setting("T_KEY", secret=True))
    workspace_settings = (Setting("T_BUCKET", required=True), Setting("T_ENDPOINT"), Setting("T_KEY", secret=True, required=True))
    endpoint_setting = "T_ENDPOINT"

    @classmethod
    def from_config(cls, config):
        return cls.buckets.setdefault(config["T_BUCKET"], cls())


@pytest.fixture
def byo(entry_points, platform, db_session, monkeypatch):  # noqa: F811
    """A workspace, the stand-in plugin installed, its key as a workspace secret, the policy on."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel, WorkspaceStorageSettingsModel
    from marvin.services.platform_settings import PlatformSettingsService
    from marvin.services.secrets import resolver

    entry_points.append(_EP("bucket", StoragePlugin(slug="bucket", name="Bucket", provider=BucketProvider, target=BucketTarget)))
    BucketProvider.buckets, BucketTarget.buckets = {}, {}
    secrets = {"their-key": "k-123", "their-key-id": "id-9"}
    monkeypatch.setattr(resolver, "resolve_secret", lambda slug, group_id=None: secrets.get(slug))
    PlatformSettingsService(db_session).set(ws_storage.POLICY_KEY, {"allowed": True, "allowed_plugins": ["bucket"]})
    ws_storage.reset_cache()
    w = _make_workspace(db_session, "Byo")
    yield SimpleNamespace(workspace=w, secrets=secrets)
    db_session.rollback()
    db_session.query(WorkspaceStorageSettingsModel).filter_by(group_id=w.gid).delete()
    db_session.query(WorkspaceStorageConnectionModel).filter_by(group_id=w.gid).delete()
    PlatformSettingsService(db_session).set(ws_storage.POLICY_KEY, {})
    db_session.commit()
    _drop_workspace(db_session, w)
    ws_storage.reset_cache()


def _connect(db_session, gid, *, status="ok", bucket="theirs", endpoint=R2, mode="workspace", key_ref="their-key"):
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel, WorkspaceStorageSettingsModel

    conn = WorkspaceStorageConnectionModel(
        session=db_session,
        group_id=gid,
        plugin_slug="bucket",
        settings={"B_BUCKET": bucket, "B_ENDPOINT": endpoint, "B_PUBLIC": "https://files.example.com"},
        secret_refs={"B_KEY": key_ref, "B_KEY_ID": "their-key-id"},  # the key ID kept as a secret too
        status=status,
    )
    db_session.add(conn)
    db_session.flush()
    row = db_session.query(WorkspaceStorageSettingsModel).filter_by(group_id=gid).one_or_none()
    if row is None:
        row = WorkspaceStorageSettingsModel(session=db_session, group_id=gid)
        db_session.add(row)
    row.credential_mode, row.active_connection_id = mode, conn.id
    db_session.commit()
    ws_storage.reset_cache()
    return conn


def _upload(db_session, gid, uid, data=b"theirs"):
    from marvin.repos.all_repositories import get_repositories
    from marvin.schemas.platform.assets import AssetUploadRequest
    from marvin.services.assets.asset_storage_service import AssetStorageService

    service = AssetStorageService.for_workspace(get_repositories(db_session, group_id=gid))
    slug = f"byo-{uuid.uuid4().hex[:8]}"
    return service.upload_asset(UploadFile(file=io.BytesIO(data), filename="note.txt"), AssetUploadRequest(slug=slug, name="note"), gid, uid)


def test_a_workspace_without_its_own_storage_uploads_to_the_platform(byo, db_session, platform):  # noqa: F811
    asset = _upload(db_session, byo.workspace.gid, byo.workspace.uid)
    assert asset.storage_provider == "local" and platform.local.exists(asset.storage_key)


def test_uploads_go_to_the_workspace_bucket_and_are_read_and_served_from_it(byo, db_session, platform):  # noqa: F811
    conn = _connect(db_session, byo.workspace.gid)
    asset = _upload(db_session, byo.workspace.gid, byo.workspace.uid)

    assert asset.storage_provider == f"ws:{conn.id}"
    bucket = BucketProvider.buckets["theirs"]
    assert bucket.exists(asset.storage_key) and bucket.key_used == ("id-9", "k-123")  # both from workspace secrets
    assert not platform.local.exists(asset.storage_key)
    with provider_factory.provider_for(asset.storage_provider).get(asset.storage_key) as fh:
        assert fh.read() == b"theirs"
    assert provider_factory.asset_public_url(asset) == f"https://files.example.com/{asset.storage_key}"


def test_switching_back_to_the_platform_leaves_old_rows_readable(byo, db_session, platform):  # noqa: F811
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    _connect(db_session, byo.workspace.gid)
    old = _upload(db_session, byo.workspace.gid, byo.workspace.uid, b"before")
    db_session.query(WorkspaceStorageSettingsModel).filter_by(group_id=byo.workspace.gid).update({"credential_mode": "platform"})
    db_session.commit()

    new = _upload(db_session, byo.workspace.gid, byo.workspace.uid, b"after")
    assert new.storage_provider == "local"
    with provider_factory.provider_for(old.storage_provider).get(old.storage_key) as fh:
        assert fh.read() == b"before"


@pytest.mark.parametrize(
    "case, expected",
    [
        ("policy_off", "switched off"),
        ("unverified", "no verified connection"),
        ("missing_key", "can't be reached"),
        ("lan_endpoint", "can't be reached"),
    ],
)
def test_a_workspace_in_its_own_mode_never_falls_back_to_the_platform(byo, db_session, platform, case, expected):  # noqa: F811
    from marvin.services.platform_settings import PlatformSettingsService

    _connect(
        db_session,
        byo.workspace.gid,
        status="unverified" if case == "unverified" else "ok",
        key_ref="gone" if case == "missing_key" else "their-key",
        endpoint="http://minio.lan:9000" if case == "lan_endpoint" else R2,
    )
    if case == "policy_off":
        PlatformSettingsService(db_session).set(ws_storage.POLICY_KEY, {"allowed": False, "allowed_plugins": ["bucket"]})
    before = sorted(p.name for p in platform.root.rglob("*")) if platform.root.exists() else []

    with pytest.raises(WorkspaceStorageUnavailable, match=expected):
        _upload(db_session, byo.workspace.gid, byo.workspace.uid)
    assert (sorted(p.name for p in platform.root.rglob("*")) if platform.root.exists() else []) == before


def test_a_connection_to_the_platforms_own_bucket_is_refused(byo, db_session, monkeypatch):
    monkeypatch.setenv("B_BUCKET", "theirs")
    monkeypatch.setenv("B_ENDPOINT", R2)
    _connect(db_session, byo.workspace.gid)
    with pytest.raises(WorkspaceStorageUnavailable, match="platform's own bucket"):
        _upload(db_session, byo.workspace.gid, byo.workspace.uid)


def test_a_plugin_whose_workspace_declaration_is_unsound_is_refused():
    class Loose(BucketProvider):
        workspace_settings = (Setting("B_BUCKET", required=True), Setting("B_KEY", secret=True), Setting("B_ENDPOINT"), Setting("B_PUBLIC"))

    conn = ws_storage._Connection("c", str(uuid.uuid4()), "loose", {"B_BUCKET": "x"}, {}, "ok", 1)
    registry_plugin = StoragePlugin(slug="loose", name="Loose", provider=Loose)
    from marvin.services.storage import registry

    registry.load_plugins()
    registry._plugins["loose"] = registry_plugin
    try:
        with pytest.raises(StorageConfigError, match="B_KEY is secret but not required"):
            ws_storage.build_connection_provider(conn, "known")
    finally:
        registry._plugins.pop("loose", None)


@pytest.mark.parametrize(
    "endpoint, policy, ok",
    [
        (None, "known", True),  # AWS's default endpoint
        (R2, "known", True),
        ("https://s3.us-west-004.backblazeb2.com", "known", True),
        ("https://minio.example.com", "known", False),
        ("https://minio.example.com", "any", True),
        ("https://127.0.0.1:9000", "public", False),
        ("http://acct.r2.cloudflarestorage.com", "known", False),  # https only in production
        ("ftp://acct.r2.cloudflarestorage.com", "any", False),
    ],
)
def test_endpoint_policy(endpoint, policy, ok):
    if ok:
        ws_storage.check_endpoint(endpoint, policy, production=True)
    else:
        with pytest.raises(StorageConfigError):
            ws_storage.check_endpoint(endpoint, policy, production=True)


def test_the_policy_is_off_by_default(db_session):
    from marvin.services.platform_settings import PlatformSettingsService

    PlatformSettingsService(db_session).set(ws_storage.POLICY_KEY, {})
    pol = ws_storage.policy(db_session)
    assert (pol.allowed, pol.endpoint_policy, pol.allowed_plugins) == (False, "known", ("s3",))


def test_a_new_upload_joins_the_asset_smart_collections_it_matches(byo, db_session):
    """The asset repository joins them on create. (A second, broken join in the upload service logged a warning on
    every upload from 2026-10-12; it was removed after the BYO live check on dev showed it.)"""
    from marvin.db.models.platform import CollectionAssets, Collections

    coll = Collections(
        session=db_session,
        group_id=byo.workspace.gid,
        name="Notes",
        slug=f"notes-{uuid.uuid4().hex[:6]}",
        target_type="asset",
        is_smart=True,
        smart_rules={"mime_types": ["text/plain"]},
    )
    db_session.add(coll)
    db_session.commit()
    try:
        asset = _upload(db_session, byo.workspace.gid, byo.workspace.uid)
        assert db_session.query(CollectionAssets).filter_by(collection_id=coll.id, asset_id=asset.id).count() == 1
    finally:
        db_session.rollback()
        db_session.query(CollectionAssets).filter_by(collection_id=coll.id).delete()
        db_session.query(Collections).filter_by(id=coll.id).delete()
        db_session.commit()
