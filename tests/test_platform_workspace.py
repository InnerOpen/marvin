"""The platform (admin's) workspace: found by its ``is_platform`` marker, never by name.

Covers the migration that sets the marker, the resolver, the lookups that used to go by
``settings.DEFAULT_GROUP``, and the super-admin rename (name + slug) — including that a changed slug
keeps resolving, so the current-workspace selection, Publishing API URLs and backups survive it.
"""

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.db_setup import generate_session
from marvin.db.models.groups import Groups, GroupSlugAlias
from marvin.db.models.users.roles import PlatformRole
from marvin.db.models.users.users import Users
from marvin.repos.all_repositories import get_repositories
from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, is_platform_workspace, platform_workspace
from marvin.services.group.workspace_rename import WorkspaceRenameError, find_group_by_slug, rename_workspace

MIGRATION = next((Path(__file__).resolve().parents[1] / "src/marvin/alembic/versions").glob("*_efee4271020c_*.py"))


# ── migration ────────────────────────────────────────────────────────────────


def _load_migration():
    spec = importlib.util.spec_from_file_location("platform_marker_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pre_migration_db(tmp_path):
    """A SQLite database with a ``groups`` table as it was before the marker."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE groups (id CHAR(32) PRIMARY KEY, name VARCHAR NOT NULL UNIQUE, slug VARCHAR UNIQUE, created_at DATETIME)")
    yield engine
    engine.dispose()


def _run(engine, step: str) -> None:
    migration = _load_migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration, step)()


def _marked(engine) -> list[str]:
    with engine.connect() as conn:
        return [r[0] for r in conn.exec_driver_sql("SELECT name FROM groups WHERE is_platform ORDER BY name")]


def _insert(engine, *rows) -> None:
    with engine.begin() as conn:
        for name, created in rows:
            conn.exec_driver_sql(
                "INSERT INTO groups (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
                (uuid.uuid4().hex, name, name.lower().replace(" ", "-"), created),
            )


def test_migration_marks_the_group_named_default_group(pre_migration_db):
    _insert(pre_migration_db, ("Client A", "2025-01-01 00:00:00"), ("Default", "2025-06-01 00:00:00"))
    _run(pre_migration_db, "upgrade")
    assert _marked(pre_migration_db) == ["Default"]


def test_migration_falls_back_to_the_oldest_group(pre_migration_db):
    _insert(pre_migration_db, ("Newer", "2025-06-01 00:00:00"), ("Oldest", "2024-01-01 00:00:00"))
    _run(pre_migration_db, "upgrade")
    assert _marked(pre_migration_db) == ["Oldest"]


def test_migration_on_an_empty_database_marks_nothing(pre_migration_db):
    _run(pre_migration_db, "upgrade")
    assert _marked(pre_migration_db) == []


def test_migration_up_down_up_and_one_marker_only(pre_migration_db):
    _insert(pre_migration_db, ("Client A", "2025-01-01 00:00:00"), ("Default", "2025-06-01 00:00:00"))
    _run(pre_migration_db, "upgrade")
    _run(pre_migration_db, "downgrade")
    with pre_migration_db.connect() as conn:
        assert "is_platform" not in {c["name"] for c in sa.inspect(conn).get_columns("groups")}
        assert "group_slug_aliases" not in sa.inspect(conn).get_table_names()
    _run(pre_migration_db, "upgrade")
    assert _marked(pre_migration_db) == ["Default"]
    with pytest.raises(sa.exc.IntegrityError), pre_migration_db.begin() as conn:
        conn.exec_driver_sql("UPDATE groups SET is_platform = 1 WHERE name = 'Client A'")


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def platform(db_session):
    """The test database's platform workspace (made if missing), its name/slug restored afterwards."""
    try:
        group = platform_workspace(db_session)
    except PlatformWorkspaceMissing:  # kept afterwards: the marker is unique, later tests reuse it
        name = f"Default-{uuid.uuid4().hex[:6]}"
        group = Groups(session=db_session, name=name, slug=name.lower(), is_platform=True)
        db_session.add(group)
        db_session.commit()
    original = (group.name, group.slug)
    yield group
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(GroupSlugAlias).filter(GroupSlugAlias.group_id == group.id).delete(synchronize_session=False)
    group = db_session.get(Groups, group.id)
    group.name, group.slug = original
    db_session.commit()


@pytest.fixture
def others(db_session):
    """Two ordinary workspaces, removed afterwards."""
    tag = uuid.uuid4().hex[:8]
    made = []
    for key in ("a", "b"):
        group = Groups(session=db_session, name=f"pw-{tag}-{key}", slug=f"pw-{tag}-{key}")
        db_session.add(group)
        made.append(group)
    db_session.commit()
    yield SimpleNamespace(a=made[0], b=made[1], tag=tag)
    db_session.rollback()
    ids = [g.id for g in made]
    db_session.query(GroupSlugAlias).filter(GroupSlugAlias.group_id.in_(ids)).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id.in_(ids)).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.name.like(f"pw-{tag}%")).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def super_admin(db_session, platform):
    """A real SUPER_ADMIN row signed in (loaded fresh per request, so active_group_id is live)."""
    uid = uuid.uuid4()
    tag = uid.hex[:8]
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=platform.id,
            username=f"pw-admin-{tag}",
            email=f"pw-admin-{tag}@t.test",
            full_name="Platform Admin",
            password="x",
            is_superuser=True,
            admin=True,
            platform_role=PlatformRole.SUPER_ADMIN.value,
            auth_method="MARVIN",
        )
    )
    db_session.commit()

    def current(session: Session = Depends(generate_session)):
        return get_repositories(session, group_id=None).users.get_one(uid, "id", any_case=False)

    app.dependency_overrides[get_current_user] = current
    yield SimpleNamespace(id=uid, client=TestClient(app))
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.query(EventLogModel).filter(EventLogModel.user_id == uid).delete(synchronize_session=False)
    db_session.query(Users).filter(Users.id == uid).delete(synchronize_session=False)
    db_session.commit()


# ── resolver: by marker, not by name ─────────────────────────────────────────


def test_resolver_follows_the_marker_through_a_rename(db_session, platform):
    rename_workspace(db_session, platform, name=f"Renamed {uuid.uuid4().hex[:6]}", slug="renamed-platform-x")
    db_session.commit()
    assert platform_workspace(db_session).id == platform.id
    assert is_platform_workspace(db_session, platform.id)


def test_new_user_without_a_group_lands_in_the_renamed_platform_workspace(db_session, platform):
    rename_workspace(db_session, platform, name=f"Not Default {uuid.uuid4().hex[:6]}")
    db_session.commit()
    user = Users(
        session=db_session, full_name="Lands Here", password="x", username=f"pw-{uuid.uuid4().hex[:8]}", email=f"pw-{uuid.uuid4().hex[:8]}@t.test"
    )
    assert user.group.id == platform.id
    db_session.rollback()  # never saved


def test_init_reuses_the_platform_workspace_whatever_its_name(db_session, platform):
    from marvin.db.init_db import platform_workspace_init

    rename_workspace(db_session, platform, name=f"Mine {uuid.uuid4().hex[:6]}")
    db_session.commit()
    before = db_session.query(Groups).count()
    group = platform_workspace_init(get_repositories(db_session, group_id=None), "Default")
    assert group.id == platform.id
    assert db_session.query(Groups).count() == before


def test_about_reports_the_platform_workspaces_current_name(super_admin, db_session, platform):
    name = f"Ops {uuid.uuid4().hex[:6]}"
    rename_workspace(db_session, platform, name=name)
    db_session.commit()
    res = super_admin.client.get("/api/admin/about")
    assert res.status_code == 200, res.text
    assert res.json()["defaultGroup"] == name


def test_default_group_is_never_used_to_look_the_workspace_up():
    """``DEFAULT_GROUP`` only names a fresh install's platform workspace (and reports/hints about it)."""
    src = Path(__file__).resolve().parents[1] / "src/marvin"
    uses = {
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if "alembic" not in path.parts and "settings.DEFAULT_GROUP" in path.read_text(encoding="utf-8").replace("``settings.DEFAULT_GROUP``", "")
    }
    assert uses == {"db/init_db.py", "routes/admin/about_controller.py"}


# ── admin API ────────────────────────────────────────────────────────────────


def test_get_platform_and_is_platform_in_reads(super_admin, platform, others):
    res = super_admin.client.get("/api/admin/groups/platform")
    assert res.status_code == 200, res.text
    assert res.json()["id"] == str(platform.id) and res.json()["isPlatform"] is True
    assert super_admin.client.get(f"/api/admin/groups/{others.a.id}").json()["isPlatform"] is False
    listed = {w["workspace"]["id"]: w["workspace"]["isPlatform"] for w in super_admin.client.get("/api/self/workspaces").json()}
    assert listed[str(platform.id)] is True and listed[str(others.a.id)] is False


def test_rename_name_and_slug_keeps_the_current_workspace_and_old_slug(super_admin, db_session, platform):
    old_slug = platform.slug
    client = super_admin.client
    assert client.put("/api/self/workspaces/current", json={"workspace": old_slug}).status_code == 200

    new_slug = f"platform-{uuid.uuid4().hex[:6]}"
    res = client.put(f"/api/admin/groups/{platform.id}", json={"id": str(platform.id), "name": "Platform Renamed", "slug": new_slug})
    assert res.status_code == 200, res.text
    assert (res.json()["name"], res.json()["slug"], res.json()["isPlatform"]) == ("Platform Renamed", new_slug, True)

    # The selection is by id: still the same workspace, now under its new name and slug.
    current = client.get("/api/self/workspaces/current").json()
    assert (current["id"], current["slug"]) == (str(platform.id), new_slug)
    # The old slug still resolves — switching by it (CLI --workspace), publishing URLs, backups.
    assert client.put("/api/self/workspaces/current", json={"workspace": old_slug}).json()["id"] == str(platform.id)
    assert find_group_by_slug(db_session, old_slug).id == platform.id
    assert platform_workspace(db_session).id == platform.id


def test_name_only_rename_derives_the_slug(super_admin, platform):
    name = f"Platform {uuid.uuid4().hex[:6]}"
    res = super_admin.client.put(f"/api/admin/groups/{platform.id}", json={"id": str(platform.id), "name": name})
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == name.lower().replace(" ", "-")


def test_renaming_back_to_a_former_slug_drops_the_alias(db_session, platform):
    first = platform.slug
    rename_workspace(db_session, platform, name=platform.name, slug=f"tmp-{uuid.uuid4().hex[:6]}")
    rename_workspace(db_session, platform, name=platform.name, slug=first)
    db_session.commit()
    assert platform.slug == first
    assert db_session.query(GroupSlugAlias).filter(GroupSlugAlias.slug == first).count() == 0


def test_cannot_take_a_slug_or_name_in_use_or_another_workspaces_former_slug(super_admin, db_session, platform, others):
    put = lambda body: super_admin.client.put(f"/api/admin/groups/{platform.id}", json={"id": str(platform.id), **body})  # noqa: E731
    assert put({"name": platform.name, "slug": others.a.slug}).status_code == 409
    assert put({"name": others.a.name}).status_code == 409

    old_b = others.b.slug
    rename_workspace(db_session, others.b, name=others.b.name, slug=f"{old_b}-new")
    db_session.commit()
    res = put({"name": platform.name, "slug": old_b})
    assert res.status_code == 409 and "used to belong" in res.text
    assert find_group_by_slug(db_session, old_b).id == others.b.id
    with pytest.raises(WorkspaceRenameError):
        rename_workspace(db_session, platform, name="   ")


def test_a_new_workspace_never_takes_a_former_slug(db_session, others):
    old_a = others.a.slug
    rename_workspace(db_session, others.a, name=others.a.name, slug=f"{old_a}-moved")
    db_session.commit()
    from marvin.schemas.group import GroupCreate

    made = get_repositories(db_session, group_id=None).groups.create(GroupCreate(name=old_a))
    assert made.slug != old_a and made.name == f"{old_a} (1)"
    assert find_group_by_slug(db_session, old_a).id == others.a.id


def test_platform_workspace_cannot_be_deleted_or_unmarked(super_admin, db_session, platform):
    client = super_admin.client
    for force in ("false", "true"):
        res = client.delete(f"/api/admin/groups/{platform.id}?force={force}")
        assert res.status_code == 409, res.text
    res = client.put(f"/api/admin/groups/{platform.id}", json={"id": str(platform.id), "name": platform.name, "isPlatform": False})
    assert res.status_code == 200
    db_session.expire_all()
    assert platform_workspace(db_session).id == platform.id


def test_publishing_api_resolves_a_former_slug(db_session, others, monkeypatch):
    import asyncio

    from fastapi import HTTPException

    import marvin.core.dependencies.dependencies as deps
    from marvin.core.config import get_app_settings

    old = others.a.slug
    rename_workspace(db_session, others.a, name=others.a.name, slug=f"{old}-v2")
    db_session.commit()

    # A valid client token for workspace A: the old slug in the URL still reaches A.
    client_for = lambda group: SimpleNamespace(validate_token=lambda plaintext_token: SimpleNamespace(group_id=group.id, permissions=[]))  # noqa: E731
    creds = SimpleNamespace(credentials=f"{get_app_settings().SECURITY_TOKEN_PREFIX_CLIENT}x")
    monkeypatch.setattr(deps, "get_repositories", lambda session, group_id=None: SimpleNamespace(api_clients=client_for(others.a)))
    _client, group, _checker = asyncio.run(deps.get_publishing_context(old, creds, db_session))[:3]
    assert group.id == others.a.id

    # A token for another workspace is still refused, and an unknown slug is still a 404.
    monkeypatch.setattr(deps, "get_repositories", lambda session, group_id=None: SimpleNamespace(api_clients=client_for(others.b)))
    for slug, code in ((old, 403), (f"nope-{uuid.uuid4().hex[:6]}", 404)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(deps.get_publishing_context(slug, creds, db_session))
        assert exc.value.status_code == code


def test_workspace_backups_keep_their_old_slug_files(super_admin, db_session, platform):
    from marvin.core.config import get_app_dirs

    backup_dir = get_app_dirs().BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    old = platform.slug
    kept = backup_dir / f"{old}-backup-2026-01-01-abc.zip"
    stranger = backup_dir / f"{old}x-backup-2026-01-01-abc.zip"
    for p in (kept, stranger):
        p.write_bytes(b"PK")
    try:
        client = super_admin.client
        assert client.put("/api/self/workspaces/current", json={"workspace": str(platform.id)}).status_code == 200
        rename_workspace(db_session, platform, name=platform.name, slug=f"moved-{uuid.uuid4().hex[:6]}")
        db_session.commit()
        names = {b["filename"] for b in client.get("/api/platform/workspace/backups").json()}
        assert kept.name in names and stranger.name not in names
        assert client.get(f"/api/platform/workspace/backups/{kept.name}").status_code == 200
    finally:
        for p in (kept, stranger):
            p.unlink(missing_ok=True)
