"""Deleting a workspace safely (tasks/retire-platform-workspace-plan.md §4, decisions 2026-10-18).

* the preview says what is at stake and when the last backup bundle was made;
* a delete needs the workspace's typed name and a bundle from the last 24 hours, or an explicit skip;
* platform events that mention the workspace survive it (no workspace); the rest of its events go;
* ``workspace_deleted`` is dispatched after the delete, with no workspace and the name in its data;
* the workspace's stored files are recorded, kept for 30 days, then purged by the daily task unless kept; an admin
  can purge now or keep (platform storage and a workspace's own bucket alike).
"""

import hashlib
import io
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select

from marvin.app import app
from marvin.core.config import get_app_dirs
from marvin.core.security import create_access_token
from marvin.db.models.groups import Groups
from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel
from marvin.db.models.platform import Assets, DeletedWorkspaceStorageModel, StorageKeyAliasModel
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.users.users import Users
from marvin.services.secrets.platform import get_platform_secret
from marvin.services.storage import deleted_workspaces, provider_factory
from marvin.services.storage.keys import new_code, new_key
from marvin.services.storage.local_provider import LocalStorageProvider


@pytest.fixture
def backup_dir():
    path = get_app_dirs().BACKUP_DIR
    path.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    def bundle(slug: str, age_hours: float = 0.0) -> Path:
        zip_path = path / f"{slug}-backup-2026-01-01-{uuid.uuid4().hex[:6]}.zip"
        zip_path.write_bytes(b"PK")
        stamp = time.time() - age_hours * 3600
        os.utime(zip_path, (stamp, stamp))
        made.append(zip_path)
        return zip_path

    yield SimpleNamespace(path=path, bundle=bundle)
    for p in made:
        p.unlink(missing_ok=True)


@pytest.fixture
def world(db_session):
    """A super admin and one workspace ("Doomed") with a storage code, and cleanup of whatever a test leaves."""
    marker = uuid.uuid4().hex[:8]
    group = Groups(session=db_session, name=f"Doomed {marker}", slug=f"doomed-{marker}", storage_code=new_code())
    db_session.add(group)
    gid = group.id = uuid.uuid4()
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=None,
            username=f"wd-{marker}",
            email=f"wd-{marker}@t.test",
            full_name="WD Admin",
            password="x",
            is_superuser=True,
            platform_role="SUPER_ADMIN",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token({'sub': str(uid)})}"})
    yield SimpleNamespace(marker=marker, gid=group.id, name=group.name, slug=group.slug, code=group.storage_code, uid=uid, client=client)

    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.execute(sa.delete(DeletedWorkspaceStorageModel).where(DeletedWorkspaceStorageModel.workspace_name.like(f"%{marker}%")))
    db_session.execute(sa.delete(EventLogModel).where(EventLogModel.user_id == uid))
    db_session.execute(sa.delete(EventLogModel).where(EventLogModel.message_title.like(f"%{marker}%")))
    purge_group_dependents(db_session, gid)
    db_session.execute(sa.delete(Groups).where(Groups.id == gid))
    db_session.execute(sa.delete(Users).where(Users.id == uid))
    db_session.commit()


def _delete(world, **params):
    query = {"confirm_name": world.name, **params}
    return world.client.delete(f"/api/admin/groups/{world.gid}", params=query)


def _exists(db_session, gid) -> bool:
    db_session.expire_all()
    return db_session.get(Groups, gid) is not None


# ── the preview ──────────────────────────────────────────────────────────────


def test_preview_counts_what_is_at_stake(world, db_session, backup_dir):
    db_session.add(
        Assets(
            session=db_session, group_id=world.gid, slug="a", name="a.jpg", original_filename="a.jpg", filename="a", extension="jpg",
            file_size=1500, mime_type="image/jpeg", asset_type="image", checksum="x", storage_provider="local",
            storage_key=new_key(world.code, "a.jpg"), uploaded_by=world.uid,
        )
    )  # fmt: skip
    db_session.commit()
    res = world.client.get(f"/api/admin/groups/{world.gid}/delete-preview")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["workspaceName"] == world.name
    assert (body["assets"], body["assetBytes"], body["members"], body["entries"], body["homeUsers"]) == (1, 1500, 0, 0, 0)
    assert body["lastBackupAt"] is None and body["backupIsRecent"] is False
    assert body["storageGraceDays"] == 30 and body["backupMaxAgeHours"] == 24

    backup_dir.bundle(world.slug, age_hours=1)
    body = world.client.get(f"/api/admin/groups/{world.gid}/delete-preview").json()
    assert body["backupIsRecent"] is True and body["lastBackupAt"]
    assert world.client.get(f"/api/admin/groups/{uuid.uuid4()}/delete-preview").status_code == 404


# ── the typed name and the backup rule ───────────────────────────────────────


def test_delete_needs_the_typed_name(world, db_session, backup_dir):
    backup_dir.bundle(world.slug)
    for params in ({}, {"confirm_name": "nope"}, {"confirm_name": world.name.lower()}):
        res = world.client.delete(f"/api/admin/groups/{world.gid}", params=params)
        assert res.status_code == 400 and res.json()["detail"]["code"] == "confirm_name_mismatch", res.text
    assert _exists(db_session, world.gid)
    assert _delete(world).status_code == 200
    assert not _exists(db_session, world.gid)


def test_delete_needs_a_bundle_from_the_last_day_or_an_explicit_skip(world, db_session, backup_dir):
    res = _delete(world)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "backup_required", res.text
    backup_dir.bundle(world.slug, age_hours=25)  # too old
    assert _delete(world).status_code == 409
    backup_dir.bundle(f"{world.slug}-other", age_hours=0)  # another workspace's bundle doesn't count
    assert _delete(world).status_code == 409
    assert _exists(db_session, world.gid)

    res = _delete(world, skip_backup="true")
    assert res.status_code == 200, res.text
    assert not _exists(db_session, world.gid)


def test_a_bundle_made_under_a_former_slug_counts(world, db_session, backup_dir):
    from marvin.services.group.workspace_rename import rename_workspace

    backup_dir.bundle(world.slug, age_hours=2)
    rename_workspace(db_session, db_session.get(Groups, world.gid), name=world.name, slug=f"{world.slug}-v2")
    db_session.commit()
    assert world.client.get(f"/api/admin/groups/{world.gid}/delete-preview").json()["backupIsRecent"] is True


# ── events ───────────────────────────────────────────────────────────────────


def _event(db_session, world, event_type: str, title: str):
    db_session.add(
        EventLogModel(
            id=uuid.uuid4(), event_id=uuid.uuid4(), workspace_id=world.gid, event_type=event_type, occurred_at=datetime.now(UTC),
            integration_id="test", event_data={}, message_title=f"{title} {world.marker}",
        )
    )  # fmt: skip


def test_platform_events_survive_the_delete_and_workspace_events_do_not(world, db_session, backup_dir):
    _event(db_session, world, "backup_completed", "platform")  # a platform event type
    _event(db_session, world, "workspace_activated", "platform-too")
    _event(db_session, world, "entry_published", "ordinary")  # a workspace event type
    db_session.commit()
    assert _delete(world, skip_backup="true").status_code == 200
    db_session.expire_all()
    rows = {r.event_type: r for r in db_session.execute(select(EventLogModel).where(EventLogModel.message_title.like(f"%{world.marker}"))).scalars()}
    assert set(rows) == {"backup_completed", "workspace_activated"}
    assert all(r.workspace_id is None for r in rows.values())


def test_workspace_deleted_is_sent_after_the_delete_with_no_workspace_and_the_name(world, db_session):
    assert _delete(world, skip_backup="true").status_code == 200
    db_session.expire_all()
    row = db_session.execute(
        select(EventLogModel).where(EventLogModel.event_type == "workspace_deleted", EventLogModel.entity_id == world.gid)
    ).scalar_one()
    assert row.workspace_id is None
    assert world.name in row.message_title + (row.message_body or "") + str(row.event_data)
    assert "without a backup" in (row.message_body or "") + row.message_title + str(row.event_data)


# ── stored files: recorded, then purged after the grace period ───────────────


@pytest.fixture
def storage(tmp_path, monkeypatch, db_session, world):
    """Platform storage on a temp directory: three files of the workspace (two under its code, one older-layout key)
    and one of a stranger's under another code."""
    provider = LocalStorageProvider(tmp_path / "files")
    monkeypatch.setattr(provider_factory, "provider_for", lambda asset: provider)
    files: dict[str, bytes] = {}

    def add(key: str, group_id=world.gid, name: str | None = None) -> str:
        data = key.encode()
        provider.put(key, io.BytesIO(data), "image/jpeg")
        files[key] = data
        db_session.add(
            Assets(
                session=db_session, group_id=group_id, slug=uuid.uuid4().hex[:8], name=name or key, original_filename=name or key, filename="f",
                extension="jpg", file_size=len(data), mime_type="image/jpeg", asset_type="image", checksum=hashlib.sha256(data).hexdigest(),
                storage_provider="local", storage_key=key, uploaded_by=world.uid,
            )
        )  # fmt: skip
        return key

    mine = [add(new_key(world.code, "a.jpg")), add(new_key(world.code, "b.jpg"))]
    legacy = add(f"{world.slug}/assets/2025/01/{uuid.uuid4()}-old.jpg")
    db_session.commit()
    other_code = new_code()
    stranger_key = new_key(other_code, "s.jpg")
    provider.put(stranger_key, io.BytesIO(b"stranger"), "image/jpeg")
    return SimpleNamespace(provider=provider, mine=mine, legacy=legacy, stranger=stranger_key)


def _records(db_session, world):
    db_session.expire_all()
    return db_session.execute(select(DeletedWorkspaceStorageModel).where(DeletedWorkspaceStorageModel.workspace_id == world.gid)).scalars().all()


def test_the_files_are_recorded_not_deleted_at_the_delete(world, db_session, storage):
    res = _delete(world, skip_backup="true")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["storageLocations"] == 1 and body["storagePurgeAfter"]
    (row,) = _records(db_session, world)
    assert (row.location, row.prefix, row.object_count, row.state) == ("local", f"{world.code}/", 3, "pending")
    assert row.total_bytes == sum(len(k) for k in [*storage.mine, storage.legacy]) and row.extra_keys == [storage.legacy]
    assert row.workspace_name == world.name and row.deleted_at <= datetime.now(UTC)
    for key in [*storage.mine, storage.legacy, storage.stranger]:
        assert storage.provider.exists(key)  # nothing is deleted yet


def test_nothing_is_purged_inside_the_grace_period_and_everything_after_it(world, db_session, storage):
    _delete(world, skip_backup="true")
    (row,) = _records(db_session, world)
    run = deleted_workspaces.purge_due(db_session, now=row.deleted_at + timedelta(days=29, hours=23))
    assert (run.purged, run.pending) >= (0, 1) and storage.provider.exists(storage.mine[0])
    assert _records(db_session, world)[0].state == "pending"

    run = deleted_workspaces.purge_due(db_session, now=row.deleted_at + timedelta(days=30, minutes=1))
    assert run.purged >= 1
    for key in [*storage.mine, storage.legacy]:
        assert not storage.provider.exists(key)
    assert storage.provider.exists(storage.stranger)  # another workspace's files are never touched
    (row,) = _records(db_session, world)
    assert (row.state, row.purged_objects, row.last_error) == ("purged", 3, None)


def test_keep_means_never_purged(world, db_session, storage):
    _delete(world, skip_backup="true")
    (row,) = _records(db_session, world)
    res = world.client.post(f"/api/admin/storage/deleted-workspaces/{row.id}/keep")
    assert res.status_code == 200 and res.json()["state"] == "kept"
    deleted_workspaces.purge_due(db_session, now=row.deleted_at + timedelta(days=400))
    assert storage.provider.exists(storage.mine[0]) and _records(db_session, world)[0].state == "kept"
    assert world.client.post(f"/api/admin/storage/deleted-workspaces/{row.id}/purge").status_code == 409


def test_the_admin_list_and_purge_now(world, db_session, storage):
    _delete(world, skip_backup="true")
    listed = world.client.get("/api/admin/storage/deleted-workspaces").json()
    mine = [i for i in listed["items"] if i["workspaceId"] == str(world.gid)]
    assert listed["graceDays"] == 30 and len(mine) == 1
    item = mine[0]
    assert (item["workspaceName"], item["objectCount"], item["state"], item["canPurge"]) == (world.name, 3, "pending", True)

    res = world.client.post(f"/api/admin/storage/deleted-workspaces/{item['id']}/purge")
    assert res.status_code == 200 and res.json()["state"] == "purged" and res.json()["purgedObjects"] == 3
    assert not storage.provider.exists(storage.mine[0]) and storage.provider.exists(storage.stranger)
    assert not [i for i in world.client.get("/api/admin/storage/deleted-workspaces").json()["items"] if i["workspaceId"] == str(world.gid)]
    assert world.client.post(f"/api/admin/storage/deleted-workspaces/{uuid.uuid4()}/keep").status_code == 404


def test_the_old_copy_a_rekey_left_is_purged_too(world, db_session, storage):
    old = f"{world.slug}/assets/2024/01/{uuid.uuid4()}-before-rekey.jpg"
    storage.provider.put(old, io.BytesIO(b"old"), "image/jpeg")
    asset_id = db_session.execute(select(Assets.id).where(Assets.group_id == world.gid)).scalars().first()
    db_session.add(StorageKeyAliasModel(session=db_session, provider="local", storage_key=old, current_key=storage.mine[0], asset_id=asset_id))
    db_session.commit()
    _delete(world, skip_backup="true")
    (row,) = _records(db_session, world)
    assert old in row.extra_keys
    deleted_workspaces.purge(db_session, row)
    assert not storage.provider.exists(old)


def test_a_workspace_without_files_records_nothing(world, db_session):
    assert _delete(world, skip_backup="true").json()["storageLocations"] == 0
    assert _records(db_session, world) == []


def test_a_purge_refuses_a_prefix_that_is_not_a_storage_code(world, db_session, storage):
    _delete(world, skip_backup="true")
    (row,) = _records(db_session, world)
    row.prefix = ""  # or anything broader than one workspace's code
    for bad in ("", "a/", "../", f"{world.code[:-1]}/"):
        row.prefix = bad
        if bad == "":
            continue  # no prefix: only the named keys
        with pytest.raises(deleted_workspaces.PurgeError):
            deleted_workspaces.purge(db_session, row)
    assert storage.provider.exists(storage.mine[0]) and storage.provider.exists(storage.stranger)


# ── a workspace's own bucket ─────────────────────────────────────────────────


class FakeBucket(LocalStorageProvider):
    """Stands in for a workspace's own bucket; remembers the keys it was built with."""

    built_with: dict = {}

    @classmethod
    def from_config(cls, config):
        cls.built_with = dict(config)
        return cls(Path(config["root"]))


def test_a_workspace_bucket_is_purged_with_its_keys_copied_to_platform_secrets(world, db_session, monkeypatch, tmp_path):
    from marvin.services.secrets.factory import get_secret_backend
    from marvin.services.storage import workspace as ws

    root = tmp_path / "own-bucket"
    bucket = FakeBucket(root)
    conn = WorkspaceStorageConnectionModel(
        session=db_session, group_id=world.gid, plugin_slug="fake", purpose="assets", label="Own bucket", status="ok",
        settings={"root": str(root)}, secret_refs={"SECRET_KEY": "OWN_BUCKET_KEY"},
    )  # fmt: skip
    db_session.add(conn)
    db_session.commit()
    get_secret_backend().set("OWN_BUCKET_KEY", "s3cr3t-value", world.gid, db_session)
    db_session.commit()

    location = ws.location_for(conn.id)
    key = new_key(world.code, "own.jpg")
    bucket.put(key, io.BytesIO(b"own"), "image/jpeg")
    db_session.add(
        Assets(
            session=db_session, group_id=world.gid, slug="own", name="own.jpg", original_filename="own.jpg", filename="own", extension="jpg",
            file_size=3, mime_type="image/jpeg", asset_type="image", checksum="x", storage_provider=location, storage_key=key, uploaded_by=world.uid,
        )
    )  # fmt: skip
    db_session.commit()

    fake_cls = SimpleNamespace(
        workspace_settings=(
            SimpleNamespace(env="root", secret=False),
            SimpleNamespace(env="SECRET_KEY", secret=True),
        ),
        endpoint_setting=None,
        from_config=FakeBucket.from_config,
    )
    monkeypatch.setattr(ws, "plugin_class", lambda slug, purpose="assets": fake_cls)
    monkeypatch.setattr("marvin_integration_sdk.storage.read_config", lambda declared, values: dict(values))

    try:
        assert _delete(world, skip_backup="true").status_code == 200
        (row,) = _records(db_session, world)
        assert row.location == location and row.label == "Own bucket" and row.connection["settings"] == {"root": str(root)}
        (secret_slug,) = row.connection["secrets"].values()
        assert get_platform_secret(secret_slug) == "s3cr3t-value"  # the workspace's secret went with it; the copy stayed
        assert bucket.exists(key)

        assert deleted_workspaces.purge(db_session, row) == 1
        assert not bucket.exists(key) and FakeBucket.built_with["SECRET_KEY"] == "s3cr3t-value"
        assert get_platform_secret(secret_slug) is None  # the copy is gone with the purge
    finally:
        from marvin.services.secrets.platform import delete_platform_secret

        for r in _records(db_session, world):
            for slug in (r.connection or {}).get("secrets", {}).values():
                delete_platform_secret(slug, db_session)
        db_session.commit()


def test_a_bucket_whose_keys_were_not_kept_cannot_be_purged_and_says_so(world, db_session):
    row = DeletedWorkspaceStorageModel(
        session=db_session, workspace_id=world.gid, workspace_name=f"x {world.marker}", location=f"ws:{uuid.uuid4()}", prefix=f"{world.code}/",
        extra_keys=[], object_count=2, total_bytes=5, connection={"plugin_slug": "s3", "settings": {}, "secrets": {}, "keys_missing": True},
        deleted_at=datetime.now(UTC) - timedelta(days=40), state="pending",
    )  # fmt: skip
    db_session.add(row)
    db_session.commit()
    run = deleted_workspaces.purge_due(db_session)
    assert run.failed >= 1
    db_session.refresh(row)
    assert row.state == "pending" and "can't be reached" in row.last_error
    item = next(i for i in world.client.get("/api/admin/storage/deleted-workspaces").json()["items"] if i["id"] == str(row.id))
    assert item["canPurge"] is False and "can't be reached" in item["lastError"]


def test_the_daily_task_is_a_system_task_that_runs_the_purge(world, db_session, storage):
    from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    task = next(t for t in SYSTEM_SCHEDULED_TASKS if t.slug == "purge_deleted_workspace_storage")
    assert task.schedule_config == {"interval_seconds": 86400} and task.enabled
    handler = TaskHandlerRegistry.get_handler("purge_deleted_workspace_storage")
    assert handler is not None and handler.admin_only
