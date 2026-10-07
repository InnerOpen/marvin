"""Where new uploads go is a platform admin's choice (Admin → Storage), with STORAGE_PROVIDER as the
default: switching sends new uploads elsewhere and back without touching existing rows; a choice that
stops being available falls back with a warning instead of stopping the app; changing it is audited at
platform scope; character-library files resolve per file like assets do; and /assets/<key> redirects
to a file that moved to another provider."""

import io
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from fastapi.testclient import TestClient

from marvin.db.models.users.roles import PlatformRole
from marvin.services.storage import provider_factory, registry
from marvin.services.storage.local_provider import LocalStorageProvider
from tests.test_storage_providers import _EP, FAKE_PLUGIN, FakeRemote, _settings, entry_points  # noqa: F401  (fixture)

STORAGE_URL = "/api/admin/storage"


@pytest.fixture
def platform(entry_points, monkeypatch, tmp_path):  # noqa: F811
    """STORAGE_PROVIDER=local, the fake remote plugin installed, no admin choice stored (before or after)."""
    entry_points.append(_EP("fake", FAKE_PLUGIN))
    settings = _settings(
        STORAGE_PROVIDER="local", STORAGE_LOCAL_ROOT=tmp_path / "local", STORAGE_LOCAL_PUBLIC_BASE_URL="https://api.example.test/assets"
    )
    monkeypatch.setattr(provider_factory, "_settings", lambda: settings)
    _clear_choice()
    yield SimpleNamespace(settings=settings, local_root=tmp_path / "local", entry_points=entry_points)
    _clear_choice()


def _clear_choice():
    from marvin.db.db_setup import session_context
    from marvin.db.models.platform.platform_settings import PlatformSettingsModel

    with session_context() as session:
        session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key == provider_factory.UPLOAD_SETTING_KEY).delete()
        session.commit()
    provider_factory.reset_provider_cache()


@pytest.fixture
def workspace(db_session, platform):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Assets
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"Switch {marker}", slug=f"switch-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Ada Admin",
            username=f"sw-{marker}",
            email=f"sw-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="SUPER_ADMIN",
            admin=True,
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, slug=f"switch-{marker}")
    db_session.rollback()
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id == gid).delete()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _upload(db_session, workspace, name="photo.txt", data=b"hello"):
    from marvin.repos.all_repositories import get_repositories
    from marvin.schemas.platform.assets import AssetUploadRequest
    from marvin.services.assets.asset_storage_service import AssetStorageService

    service = AssetStorageService(get_repositories(db_session, group_id=workspace.gid), provider_factory.get_storage_provider())
    slug = f"{name.split('.')[0]}-{uuid.uuid4().hex[:6]}"
    return service.upload_asset(
        UploadFile(file=io.BytesIO(data), filename=name), AssetUploadRequest(slug=slug, name=name), workspace.gid, workspace.uid
    )


def _choose(slug):
    from marvin.db.db_setup import session_context
    from marvin.services.storage.admin import set_upload_provider

    with session_context() as session:
        return set_upload_provider(session, slug)


# --------------------------------------------------------------------------------------------------
# The choice
# --------------------------------------------------------------------------------------------------


def test_uploads_follow_storage_provider_until_an_admin_chooses(platform):
    target = provider_factory.upload_target()
    assert (target.env_default, target.chosen, target.effective, target.error) == ("local", None, "local", None)
    assert isinstance(provider_factory.get_storage_provider(), LocalStorageProvider)


def test_switching_sends_new_uploads_elsewhere_and_back(db_session, workspace):
    from marvin.db.models.platform import Assets
    from marvin.schemas.platform.assets import AssetRead

    before = _upload(db_session, workspace, "before.txt", b"on disk")
    assert before.storage_provider == "local"

    assert _choose("fakes3") == (None, "fakes3")
    during = _upload(db_session, workspace, "during.txt", b"in the cloud")
    assert during.storage_provider == "fakes3"
    assert FakeRemote.store[during.storage_key][0] == b"in the cloud"
    assert during.public_url == f"https://cdn.example.test/{during.storage_key}"

    assert _choose("local") == ("fakes3", "local")  # back any time
    after = _upload(db_session, workspace, "after.txt", b"on disk again")
    assert after.storage_provider == "local"

    # Existing rows are untouched and each still serves from where it lives.
    db_session.expire_all()
    rows = {r.id: AssetRead.model_validate(r) for r in db_session.query(Assets).filter(Assets.group_id == workspace.gid)}
    assert rows[before.id].storage_provider == "local" and rows[before.id].public_url.startswith("https://api.example.test/assets/")
    assert rows[during.id].storage_provider == "fakes3" and rows[during.id].public_url.startswith("https://cdn.example.test/")
    assert provider_factory.provider_for(rows[during.id]).get(during.storage_key).read() == b"in the cloud"
    assert provider_factory.provider_for(rows[before.id]).get(before.storage_key).read() == b"on disk"


def test_only_an_available_provider_can_be_chosen(platform):
    from marvin.services.storage.admin import UnavailableProviderError

    with pytest.raises(UnavailableProviderError, match="'r2'"):
        _choose("r2")
    with pytest.raises(UnavailableProviderError, match="STORAGE_S3_BUCKET"):
        _choose("s3")  # installed (core's), not configured
    assert provider_factory.chosen_upload_provider() is None


def test_an_unavailable_choice_falls_back_to_storage_provider(platform, caplog):
    _choose("fakes3")
    assert provider_factory.upload_target().effective == "fakes3"

    # The plugin is uninstalled afterwards (Helm values changed): new uploads fall back, loudly.
    platform.entry_points.clear()
    registry.reset()
    provider_factory.reset_provider_cache()
    with caplog.at_level("ERROR"):
        target = provider_factory.upload_target()
    assert (target.chosen, target.effective) == ("fakes3", "local")
    assert "'fakes3'" in target.error
    assert "unavailable" in caplog.text
    assert isinstance(provider_factory.get_storage_provider(), LocalStorageProvider)
    provider_factory.validate_storage_config()  # startup checks STORAGE_PROVIDER only: no exception


# --------------------------------------------------------------------------------------------------
# Admin API
# --------------------------------------------------------------------------------------------------


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


def _logged_changes(db_session, workspace):
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.expire_all()
    return (
        db_session.query(EventLogModel)
        .filter(EventLogModel.workspace_id == workspace.gid, EventLogModel.event_type == "storage_provider_changed")
        .order_by(EventLogModel.occurred_at)
        .all()
    )


def test_admin_storage_page_data(db_session, workspace, admin):
    _upload(db_session, workspace, "a.txt", b"12345")
    res = admin().get(STORAGE_URL)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["envDefault"], body["uploadProvider"], body["effectiveProvider"], body["warning"]) == ("local", None, "local", None)
    providers = {p["slug"]: p for p in body["providers"]}
    assert providers["local"]["available"] and providers["local"]["source"] == "builtin"
    assert providers["fakes3"]["available"] and providers["fakes3"]["source"] == "fake"
    assert not providers["s3"]["available"] and "STORAGE_S3_BUCKET" in providers["s3"]["error"]
    assert providers["local"]["assets"] >= 1 and providers["local"]["bytes"] >= 5
    mine = [w for w in body["workspaces"] if w["workspaceId"] == str(workspace.gid)]
    assert mine == [{"workspaceId": str(workspace.gid), "workspace": f"Switch {workspace.gid.hex[:8]}", "provider": "local", "assets": 1, "bytes": 5}]


def test_admin_switches_and_it_is_audited_at_platform_scope(db_session, workspace, admin):
    from marvin.services.events.event_catalog import get_catalog_entry, is_platform_event

    client = admin()
    res = client.put(STORAGE_URL, json={"uploadProvider": "fakes3"})
    assert res.status_code == 200, res.text
    assert res.json()["effectiveProvider"] == "fakes3"
    assert _upload(db_session, workspace).storage_provider == "fakes3"

    assert client.put(STORAGE_URL, json={"uploadProvider": "fakes3"}).status_code == 200  # no change: no event
    res = client.put(STORAGE_URL, json={"uploadProvider": None})
    assert res.json()["uploadProvider"] is None and res.json()["effectiveProvider"] == "local"

    rows = _logged_changes(db_session, workspace)
    assert [r.message_body for r in rows] == [
        "New uploads now go to fakes3 (was STORAGE_PROVIDER)",
        "New uploads now go to local (STORAGE_PROVIDER) (was fakes3)",
    ]
    entry = get_catalog_entry("storage_provider_changed")
    assert is_platform_event("storage_provider_changed") and entry.audit_locked


def test_admin_api_refuses_unavailable_providers_and_non_super_admins(db_session, workspace, admin):
    res = admin().put(STORAGE_URL, json={"uploadProvider": "r2"})
    assert res.status_code == 422 and "'r2'" in res.json()["detail"]
    assert admin(PlatformRole.NONE).get(STORAGE_URL).status_code == 403
    assert admin(PlatformRole.NONE).put(STORAGE_URL, json={"uploadProvider": "fakes3"}).status_code == 403
    assert _logged_changes(db_session, workspace) == []


def test_admin_page_warns_about_a_fallback(db_session, workspace, admin, platform):
    _choose("fakes3")
    platform.entry_points.clear()
    registry.reset()
    provider_factory.reset_provider_cache()
    body = admin().get(STORAGE_URL).json()
    assert (body["uploadProvider"], body["effectiveProvider"]) == ("fakes3", "local")
    assert "unavailable" in body["warning"]


# --------------------------------------------------------------------------------------------------
# /assets/<key> after a move
# --------------------------------------------------------------------------------------------------


def test_assets_mount_redirects_a_moved_file(db_session, workspace, client):
    from marvin.db.models.platform import Assets

    _choose("fakes3")
    asset = _upload(db_session, workspace, "moved.txt", b"elsewhere")
    res = client.get(f"/assets/{asset.storage_key}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == f"https://cdn.example.test/{asset.storage_key}"

    db_session.query(Assets).filter(Assets.id == asset.id).update({"storage_provider": "local"})
    db_session.commit()
    assert client.get(f"/assets/{asset.storage_key}", follow_redirects=False).status_code == 404  # a local row that isn't on disk
    assert client.get("/assets/nobody/assets/never.txt", follow_redirects=False).status_code == 404


# --------------------------------------------------------------------------------------------------
# Character-library files resolve per file
# --------------------------------------------------------------------------------------------------


def _image(name="idle"):
    from marvin.services.ai.character import CharacterImage

    return CharacterImage(name=name, data=b"GIF89a-" + name.encode(), mime_type="image/gif", extension="gif")


def test_library_files_record_and_use_their_own_provider(platform):
    from marvin.services.ai.character_library import library_store
    from marvin.services.storage.keys import LIBRARY_CODE, is_opaque

    pack_id = uuid.uuid4()
    _choose("fakes3")
    store = library_store(pack_id)
    new = store.put(_image(), "idle.gif", "a")
    # An opaque key: the platform prefix, the month and a UUID; neither the pack nor the name.
    assert new["provider"] == "fakes3" and new["url"] == f"https://cdn.example.test/{new['key']}"
    assert is_opaque(new["key"], LIBRARY_CODE) and "idle" not in new["key"] and str(pack_id) not in new["key"]
    assert FakeRemote.store[new["key"]][2] == {"content_disposition": 'inline; filename="idle.gif"'}

    # A file stored before files recorded a provider lives on local disk, wherever uploads go now.
    local = LocalStorageProvider(root=platform.local_root)
    legacy_key = f"_platform/character-packs/{pack_id}/old-idle.gif"
    local.put(legacy_key, io.BytesIO(b"GIF89a-old"), "image/gif")
    legacy = {"name": "old", "key": legacy_key, "url": f"https://api.example.test/assets/{legacy_key}"}

    store.delete(legacy)
    assert not local.exists(legacy_key)
    store.delete({**new})
    assert new["key"] not in FakeRemote.store


def test_character_urls_are_resolved_when_read(db_session, platform):
    from marvin.services.ai.character_library import resolve, with_current_urls

    key = f"_platform/character-packs/{uuid.uuid4()}/a-idle.gif"
    old_url = f"https://api.example.test/assets/{key}"
    stored = {"states": {"idle": old_url, "thinking": "https://elsewhere.test/x.gif"}, "files": [{"name": "idle", "key": key, "url": old_url}]}
    assert with_current_urls(stored) is stored  # nothing moved: the stored JSON as it is

    moved = {**stored, "files": [{**stored["files"][0], "provider": "fakes3"}]}
    current = with_current_urls(moved)
    assert current["states"] == {"idle": f"https://cdn.example.test/{key}", "thinking": "https://elsewhere.test/x.gif"}
    assert current["files"][0]["url"] == f"https://cdn.example.test/{key}"
    assert moved["files"][0]["url"] == old_url  # never rewritten in place
    assert resolve(db_session, moved)["states"]["idle"] == f"https://cdn.example.test/{key}"

    # A state saved back from an earlier read (the remote URL) follows the file when it moves back.
    saved_back = {**stored, "states": {"idle": f"https://cdn.example.test/{key}?X-Amz-Expires=600"}}
    assert with_current_urls(saved_back)["states"]["idle"] == old_url


def test_workspace_character_files_follow_their_asset_row(db_session, workspace):
    from marvin.db.models.platform import Assets
    from marvin.services.ai.character_library import resolve

    asset = _upload(db_session, workspace, "idle.gif", b"GIF89a")
    stored_url = asset.public_url
    character = {"states": {"idle": stored_url}, "files": [{"name": "idle", "assetId": str(asset.id), "url": stored_url}]}
    assert resolve(db_session, character) is character

    FakeRemote.store[asset.storage_key] = (b"GIF89a", "image/gif", None)
    db_session.query(Assets).filter(Assets.id == asset.id).update({"storage_provider": "fakes3"})
    db_session.commit()
    assert resolve(db_session, character)["states"]["idle"] == f"https://cdn.example.test/{asset.storage_key}"


def test_imported_bytes_record_the_provider_they_were_stored_on(db_session, workspace):
    """A bundle's asset says where it lived ("local"); its bytes go where uploads go now, and the row
    must say so, or its URL points at a file that isn't there."""
    import zipfile

    from marvin.db.models.platform import Assets
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    _choose("fakes3")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("files/old-ws/assets/2026/01/x-logo.txt", b"bundle bytes")
    slug = f"logo-{uuid.uuid4().hex[:6]}"
    meta = {"slug": slug, "name": "Logo", "originalFilename": "logo.txt", "extension": "txt", "fileSize": 12, "mimeType": "text/plain"}
    meta |= {"assetType": "document", "storageProvider": "local", "storageKey": "old-ws/assets/2026/01/x-logo.txt"}
    with zipfile.ZipFile(buf) as zf:
        loader = WorkspaceSeedLoader(get_repositories(db_session, group_id=workspace.gid))
        loader._seed_user_id = workspace.uid
        loader._overwrite = False
        assert loader._import_assets([meta], zf) == 1
    db_session.commit()
    row = db_session.query(Assets).filter(Assets.group_id == workspace.gid, Assets.slug == slug).one()
    assert row.storage_provider == "fakes3"
    assert FakeRemote.store[row.storage_key][0] == b"bundle bytes"
