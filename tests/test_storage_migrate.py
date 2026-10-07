"""Moving stored files between providers without a freeze (services/storage/migration.py,
scripts/storage_migrate.py): copy, verify, repoint each row; idempotent and resumable; stragglers
uploaded meanwhile caught by another pass; races left alone; source copies never deleted, local copies
pruned only when the remote copy matches; and the backup mirror reading every provider in use."""

import hashlib
import io
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from marvin_integration_sdk.storage.memory import MemoryBackupTarget, MemoryStorageProvider

from marvin.services.storage import migration, provider_factory
from marvin.services.storage.local_provider import LocalStorageProvider
from tests.test_storage_providers import _EP, FAKE_PLUGIN, FakeRemote, _settings, entry_points  # noqa: F401  (fixture)


@pytest.fixture
def world(entry_points, monkeypatch, tmp_path, db_session):  # noqa: F811
    """A workspace with three local assets on disk; uploads go to local (STORAGE_PROVIDER), the fake
    remote plugin installed."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Assets
    from marvin.db.models.users import Users

    entry_points.append(_EP("fake", FAKE_PLUGIN))
    settings = _settings(
        STORAGE_PROVIDER="local", STORAGE_LOCAL_ROOT=tmp_path / "local", STORAGE_LOCAL_PUBLIC_BASE_URL="https://api.example.test/assets"
    )
    monkeypatch.setattr(provider_factory, "_settings", lambda: settings)
    provider_factory.reset_provider_cache()
    local = LocalStorageProvider(root=tmp_path / "local")

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"Move {marker}", slug=f"move-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Mover",
            username=f"mv-{marker}",
            email=f"mv-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=True,
        )
    )
    w = SimpleNamespace(gid=gid, uid=uid, slug=f"move-{marker}", local=local, ids=[], db=db_session)
    for i in range(3):
        add_asset(w, f"file-{i}.txt", f"bytes of file {i}".encode() * (i + 1))
    db_session.commit()
    yield w
    db_session.rollback()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()
    provider_factory.reset_provider_cache()


def add_asset(w, name, data, provider="local", commit=False):
    from marvin.db.models.platform import Assets

    key = f"{w.slug}/assets/2026/10/{uuid.uuid4()}-{name}"
    if provider == "local":
        w.local.put(key, io.BytesIO(data), "text/plain")
    else:
        FakeRemote.store[key] = (data, "text/plain", None)
    row = Assets(
        session=w.db,
        group_id=w.gid,
        slug=f"{name.split('.')[0]}-{uuid.uuid4().hex[:6]}",
        name=name,
        original_filename=name,
        filename=name.split(".")[0],
        extension="txt",
        file_size=len(data),
        mime_type="text/plain",
        asset_type="document",
        checksum=hashlib.sha256(data).hexdigest(),
        storage_provider=provider,
        storage_key=key,
        uploaded_by=w.uid,
    )
    w.db.add(row)
    w.db.flush()
    w.ids.append(row.id)
    if commit:
        w.db.commit()
    return row


def rows(w):
    from marvin.db.models.platform import Assets

    w.db.expire_all()
    return {r.id: r for r in w.db.query(Assets).filter(Assets.group_id == w.gid)}


def test_dry_run_changes_nothing(world):
    report = migration.migrate("fakes3", workspace=world.slug, dry_run=True)
    assert (report.copied, report.moved, report.copied_bytes) == (3, 3, sum(r.file_size for r in rows(world).values()))
    assert {r.storage_provider for r in rows(world).values()} == {"local"}
    assert FakeRemote.store == {}


def test_migrate_to_remote_and_back(world):
    from marvin.schemas.platform.assets import AssetRead

    report = migration.migrate("fakes3", workspace=world.slug, verify=True)
    assert (report.moved, report.copied, report.already_there, report.failures, report.passes) == (3, 3, 0, [], 1)
    for row in rows(world).values():
        assert row.storage_provider == "fakes3"
        assert row.public_url == f"https://cdn.example.test/{row.storage_key}"
        assert FakeRemote.store[row.storage_key][0] == world.local.get(row.storage_key).read()  # local copy kept
        assert AssetRead.model_validate(row).public_url == f"https://cdn.example.test/{row.storage_key}"

    again = migration.migrate("fakes3", workspace=world.slug)
    assert (again.moved, again.copied, again.passes) == (0, 0, 0)  # idempotent

    back = migration.migrate("local", workspace=world.slug)
    assert (back.moved, back.copied, back.already_there) == (3, 0, 3)  # the local copies were never deleted
    assert {r.storage_provider for r in rows(world).values()} == {"local"}
    assert all(r.public_url.startswith("https://api.example.test/assets/") for r in rows(world).values())


def test_an_interrupted_run_resumes(world, monkeypatch):
    real = migration._flip
    calls = []

    def crash_on_second(*args, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(*args, **kw)

    monkeypatch.setattr(migration, "_flip", crash_on_second)
    with pytest.raises(KeyboardInterrupt):
        migration.migrate("fakes3", workspace=world.slug)
    monkeypatch.setattr(migration, "_flip", real)
    assert sorted(r.storage_provider for r in rows(world).values()) == ["fakes3", "local", "local"]

    report = migration.migrate("fakes3", workspace=world.slug)
    assert (report.moved, report.copied, report.already_there) == (2, 1, 1)  # the copied-but-not-flipped one isn't uploaded again
    assert {r.storage_provider for r in rows(world).values()} == {"fakes3"}


def test_uploads_during_the_run_are_caught_by_another_pass(world, monkeypatch):
    real = migration.copy_file
    late = []

    def upload_meanwhile(*args, **kw):
        if not late:  # someone uploads while the first file copies; uploads still went to local
            late.append(add_asset(world, "late.txt", b"uploaded meanwhile", commit=True))
        return real(*args, **kw)

    monkeypatch.setattr(migration, "copy_file", upload_meanwhile)
    report = migration.migrate("fakes3", workspace=world.slug)
    assert (report.moved, report.passes) == (4, 2)
    assert {r.storage_provider for r in rows(world).values()} == {"fakes3"}
    assert FakeRemote.store[late[0].storage_key][0] == b"uploaded meanwhile"


def test_a_row_deleted_while_copying_is_left_alone(world, monkeypatch):
    from marvin.db.models.platform import Assets

    victim = world.ids[0]
    victim_key = rows(world)[victim].storage_key
    real = migration.copy_file

    def delete_meanwhile(source, target, key, *args, **kw):
        result = real(source, target, key, *args, **kw)
        if key == victim_key:  # deleted (with its file) after the copy, before the row is repointed
            world.db.query(Assets).filter(Assets.id == victim).delete()
            world.db.commit()
        return result

    monkeypatch.setattr(migration, "copy_file", delete_meanwhile)
    report = migration.migrate("fakes3", workspace=world.slug)
    assert (report.moved, report.raced) == (2, 1)
    assert victim_key not in FakeRemote.store  # its copy went with it


def test_a_copy_that_does_not_match_is_not_used(world, monkeypatch):
    class Corrupting(FakeRemote):
        def put(self, storage_key, file_data, content_type, metadata=None):
            return super().put(storage_key, io.BytesIO(file_data.read() + b"!"), content_type, metadata)

    target = Corrupting("https://cdn.example.test")
    target.objects = FakeRemote.store
    monkeypatch.setattr(
        provider_factory, "_provider", lambda slug, settings: target if slug == "fakes3" else provider_factory._local_provider(settings)
    )
    report = migration.migrate("fakes3", workspace=world.slug)
    assert report.moved == 0 and len(report.failures) == 3
    assert "doesn't match" in report.failures[0]
    assert {r.storage_provider for r in rows(world).values()} == {"local"}


def test_stale_row_checksums_are_reported_not_fatal(world):
    from marvin.db.models.platform import Assets

    world.db.query(Assets).filter(Assets.id == world.ids[0]).update({"checksum": "0" * 64})
    world.db.commit()
    report = migration.migrate("fakes3", workspace=world.slug)
    assert (report.moved, report.checksum_mismatches) == (3, 1)


def test_prune_local_deletes_only_verified_copies(world):
    migration.migrate("fakes3", workspace=world.slug)
    keys = [r.storage_key for r in rows(world).values()]
    tampered = keys[0]
    FakeRemote.store[tampered] = (b"not the same", "text/plain", None)
    stays_local = add_asset(world, "local.txt", b"still local", commit=True)

    dry = migration.prune_local(workspace=world.slug, dry_run=True)
    assert dry.pruned == 2 and all(world.local.exists(k) for k in keys)

    report = migration.prune_local(workspace=world.slug)
    assert report.pruned == 2 and report.pruned_bytes > 0
    assert len(report.failures) == 1 and tampered in report.failures[0]
    assert world.local.exists(tampered)  # its remote copy doesn't match: kept
    assert not any(world.local.exists(k) for k in keys[1:])
    assert world.local.exists(stays_local.storage_key)


def test_library_files_move_with_their_pack(world, db_session):
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import pack_character

    pack_id = uuid.uuid4()
    key = f"_platform/character-packs/{pack_id}/a-idle.gif"
    world.local.put(key, io.BytesIO(b"GIF89a-idle"), "image/gif")
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
        report = migration.migrate("fakes3")  # a full run (library files aren't any workspace's)
        assert report.library_files >= 1
        assert not [f for f in report.failures if str(pack_id) in f]
        db_session.expire_all()
        stored = db_session.get(CharacterPackModel, pack_id).pack
        assert stored["files"][0]["provider"] == "fakes3"
        assert stored["files"][0]["url"] == stored["states"]["idle"] == f"https://cdn.example.test/{key}"
        assert FakeRemote.store[key] == (b"GIF89a-idle", "image/gif", None)
        assert pack_character(db_session.get(CharacterPackModel, pack_id))["states"]["idle"] == f"https://cdn.example.test/{key}"
        assert world.local.exists(key)

        back = migration.migrate("local")
        assert not [f for f in back.failures if str(pack_id) in f]
        db_session.expire_all()
        assert db_session.get(CharacterPackModel, pack_id).pack["files"][0]["provider"] == "local"
    finally:
        db_session.query(CharacterPackModel).filter(CharacterPackModel.id == pack_id).delete()
        db_session.commit()


def test_cli(world, capsys):
    from marvin.scripts import storage_migrate

    assert storage_migrate.main(["--to", "fakes3", "--workspace", world.slug, "--dry-run"]) == 0
    assert storage_migrate.main(["--to", "nowhere", "--workspace", world.slug]) == 2
    assert storage_migrate.main(["--to", "fakes3", "--workspace", "no-such-workspace"]) == 2
    assert storage_migrate.main(["--to", "fakes3", "--workspace", world.slug, "--verify"]) == 0
    assert storage_migrate.main(["--prune-local", "--workspace", world.slug]) == 0
    assert {r.storage_provider for r in rows(world).values()} == {"fakes3"}


# --------------------------------------------------------------------------------------------------
# Backups read every provider in use
# --------------------------------------------------------------------------------------------------


def test_the_mirror_reads_every_provider_once_per_key(tmp_path):
    from marvin.services.backup_engine import engine as eng

    local, remote = MemoryStorageProvider(), MemoryStorageProvider()
    for key, data in (("ws/assets/a.txt", b"a"), ("ws/assets/both.txt", b"same")):
        local.objects[key] = (data, "text/plain", None)
    for key, data in (("ws/assets/both.txt", b"same"), ("ws/assets/new.txt", b"uploaded to the cloud")):
        remote.objects[key] = (data, "text/plain", None)
    target = MemoryBackupTarget()
    report = eng.Report(target="t")
    eng.backup_assets([local, remote], target, report, dry_run=False, work=tmp_path)
    assert (report.assets_uploaded, report.failures) == (3, [])
    assert set(target.list("assets/")) == {"assets/ws/assets/a.txt", "assets/ws/assets/both.txt", "assets/ws/assets/new.txt"}
    again = eng.Report(target="t")
    eng.backup_assets([local, remote], target, again, dry_run=False, work=tmp_path)
    assert (again.assets_uploaded, again.assets_unchanged) == (0, 3)


def test_backup_asset_providers_from_env(tmp_path, entry_points):  # noqa: F811
    from marvin.services.backup_engine import engine as eng

    entry_points.append(_EP("fake", FAKE_PLUGIN))
    (tmp_path / "assets").mkdir()
    settings = eng.BackupSettings.from_env({"BACKUP_DATA_DIR": str(tmp_path), "BACKUP_ASSET_PROVIDERS": " fakes3, nowhere ,"})
    assert eng.asset_provider_slugs(settings) == ["local", "fakes3", "nowhere"]
    sources, problems = eng.open_asset_sources(settings, env={})
    assert [type(s).__name__ for s in sources] == ["LocalStorageProvider", "FakeRemote"]
    assert len(problems) == 1 and "nowhere" in problems[0]
    assert eng.asset_provider_slugs(eng.BackupSettings.from_env({})) == ["local"]
