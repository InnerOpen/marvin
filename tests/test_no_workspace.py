"""Users with no workspace: no home (``users.group_id`` NULL) and no memberships.

An Admin-created, OIDC or LDAP sign-up starts that way, and so does the first super admin of a fresh install. Admin
must work for them (it holds no workspace's content); workspace-scoped APIs answer 409 ``no_workspace``; the
current workspace is ``null``; and deleting a workspace clears the homes pointing at it.
"""

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import select

from marvin.app import app
from marvin.core.security import create_access_token
from marvin.db.models.groups import Groups
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.users.users import Users
from marvin.db.models.users.workspace_members import WorkspaceMembers
from marvin.services.workspace.current import current_workspace_id
from tests._routes import api_routes

# ── fixtures ────────────────────────────────────────────────────────────────


def _group(db_session, name: str) -> Groups:
    group = Groups(session=db_session, name=name, slug=name.lower())
    db_session.add(group)
    db_session.flush()
    return group


def _user(db_session, marker: str, *, super_admin: bool = False, home=None, active=None) -> Users:
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=home,
            active_group_id=active,
            username=f"nw-{marker}",
            email=f"nw-{marker}@t.test",
            full_name=f"NW {marker}",
            password="x",
            is_superuser=super_admin,
            platform_role="SUPER_ADMIN" if super_admin else "NONE",
            auth_method="MARVIN",
        )
    )
    db_session.flush()
    return db_session.get(Users, uid)


def _join(db_session, user: Users, group: Groups, role: str = "EDITOR") -> None:
    db_session.add(WorkspaceMembers(session=db_session, user_id=user.id, group_id=group.id, workspace_role=role))
    db_session.flush()
    db_session.refresh(user)


def _client(user: Users) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"})


@pytest.fixture
def world(db_session):
    """Two workspaces, and a super admin who has no home and is in neither."""
    marker = uuid.uuid4().hex[:8]
    beta = _group(db_session, f"Beta-{marker}")
    alpha = _group(db_session, f"Alpha-{marker}")
    admin = _user(db_session, f"{marker}-admin", super_admin=True)
    db_session.commit()
    yield SimpleNamespace(marker=marker, alpha=alpha, beta=beta, admin=admin, client=_client(admin))
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    ids = db_session.execute(select(Users.id).where(Users.username.like(f"nw-{marker}%"))).scalars().all()
    db_session.execute(sa.delete(EventLogModel).where(EventLogModel.user_id.in_(ids)))
    db_session.execute(sa.delete(WorkspaceMembers).where(WorkspaceMembers.user_id.in_(ids)))
    db_session.execute(sa.delete(Users).where(Users.id.in_(ids)))
    for group in (alpha, beta):
        purge_group_dependents(db_session, group.id)
        db_session.delete(db_session.get(Groups, group.id))
    db_session.commit()


# ── Admin works with no workspace ────────────────────────────────────────────


def test_a_super_admin_with_no_workspace_gets_200_on_every_admin_get(world, db_session):
    from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, platform_workspace

    made = None
    try:  # GET /admin/groups/platform answers 404 on a database init_db hasn't run against
        platform_workspace(db_session)
    except PlatformWorkspaceMissing:
        made = _group(db_session, f"Platform-{world.marker}")
        made.is_platform = True
        db_session.commit()
    try:
        _every_admin_get_answers_200(world)
    finally:
        if made is not None:
            db_session.delete(db_session.get(Groups, made.id))
            db_session.commit()


def _every_admin_get_answers_200(world):
    gets = [r for r in api_routes(app) if r.path.startswith("/api/admin") and "GET" in r.methods and "{" not in r.path]
    assert len(gets) > 20  # the router really was walked
    failed = {}
    for route in gets:
        res = world.client.get(route.path)
        if res.status_code != 200:
            failed[route.path] = (res.status_code, res.text[:200])
    assert not failed, failed


def test_the_workspace_apis_answer_409_no_workspace(world):
    for path in ["/api/platform/entries", "/api/platform/collections", "/api/groups/ai-settings", "/api/groups/invitations", "/api/self/api-tokens"]:
        res = world.client.get(path)
        assert res.status_code == 409, (path, res.status_code, res.text[:200])
        assert res.json()["detail"]["code"] == "no_workspace", path


def test_current_workspace_is_null_and_the_list_still_works(world):
    assert world.client.get("/api/self/workspaces/current").json() is None
    listed = world.client.get("/api/self/workspaces").json()
    assert {w["workspace"]["id"] for w in listed} >= {str(world.alpha.id), str(world.beta.id)}
    assert not any(w["isActive"] for w in listed)


def test_a_character_pack_line_needs_a_workspace_to_bill(world, db_session):
    from marvin.db.models.platform.character_packs import CharacterPackModel

    pack = CharacterPackModel(
        session=db_session, name=f"nw-{world.marker}", slug=f"nw-{world.marker}", pack={"states": {}, "files": []}, persona={"persona_prompt": "x"}
    )
    db_session.add(pack)
    db_session.commit()
    try:
        res = world.client.post(f"/api/admin/character-packs/{pack.slug}/bubble-lines/generate", json={})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "no_workspace"
        res = world.client.post(f"/api/admin/character-packs/{pack.slug}/bubble-lines/generate", json={"workspaceId": str(uuid.uuid4())})
        assert res.status_code == 404
    finally:
        db_session.delete(pack)
        db_session.commit()


# ── the resolver ─────────────────────────────────────────────────────────────


def test_fallback_order(world, db_session):
    alpha, beta = world.alpha, world.beta
    gamma = _group(db_session, f"Gamma-{world.marker}")
    db_session.commit()
    try:
        # active, when they can reach it
        user = _user(db_session, f"{world.marker}-a", home=beta.id, active=gamma.id)
        _join(db_session, user, alpha)
        _join(db_session, user, beta)
        _join(db_session, user, gamma)
        assert current_workspace_id(user, db_session) == gamma.id
        # active no longer reachable (membership gone): the home they are a member of
        db_session.query(WorkspaceMembers).filter_by(user_id=user.id, group_id=gamma.id).delete()
        db_session.refresh(user)
        assert current_workspace_id(user, db_session) == beta.id
        # a home they are not a member of is skipped: the first membership by name
        db_session.query(WorkspaceMembers).filter_by(user_id=user.id, group_id=beta.id).delete()
        db_session.refresh(user)
        assert current_workspace_id(user, db_session) == alpha.id
        # nothing left
        db_session.query(WorkspaceMembers).filter_by(user_id=user.id).delete()
        db_session.refresh(user)
        assert current_workspace_id(user, db_session) is None
    finally:
        db_session.rollback()
        db_session.query(WorkspaceMembers).filter_by(group_id=gamma.id).delete()
        db_session.query(Users).filter(Users.active_group_id == gamma.id).update({"active_group_id": None})
        db_session.delete(db_session.get(Groups, gamma.id))
        db_session.commit()


def test_a_super_admin_reaches_their_home_and_active_without_membership(world, db_session):
    home_only = _user(db_session, f"{world.marker}-h", super_admin=True, home=world.beta.id)
    assert current_workspace_id(home_only, db_session) == world.beta.id
    active = _user(db_session, f"{world.marker}-s", super_admin=True, home=world.beta.id, active=world.alpha.id)
    assert current_workspace_id(active, db_session) == world.alpha.id
    assert current_workspace_id(world.admin, db_session) is None
    db_session.commit()


# ── creating and deleting ────────────────────────────────────────────────────


def test_a_user_made_with_no_group_has_no_home(world, db_session):
    user = Users(session=db_session, full_name="No Home", password="x", email=f"nohome-{world.marker}@t.test", username=f"nw-{world.marker}-nohome")
    db_session.add(user)
    db_session.commit()
    assert user.group_id is None and user.group is None and user.group_slug is None


def test_admin_creates_a_user_with_no_home_and_reads_it_back(world):
    created = world.client.post(
        "/api/admin/users",
        json={"email": f"nw-{world.marker}-new@t.test", "username": f"nw-{world.marker}-new", "fullName": "New", "password": "A-long-passw0rd!"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["groupId"] is None and body["group"] is None and body["groupSlug"] is None
    assert world.client.get(f"/api/admin/users/{body['id']}").status_code == 200
    page = world.client.get("/api/admin/users").json()
    assert any(u["id"] == body["id"] for u in page["items"])


def test_deleting_a_workspace_clears_the_homes_pointing_at_it(world, db_session):
    doomed = _group(db_session, f"Doomed-{world.marker}")
    resident = _user(db_session, f"{world.marker}-res", home=doomed.id, active=doomed.id)
    _join(db_session, resident, doomed)
    db_session.commit()
    res = world.client.delete(f"/api/admin/groups/{doomed.id}?force=true")
    assert res.status_code == 200, res.text
    db_session.expire_all()
    resident = db_session.get(Users, resident.id)
    assert resident is not None and resident.group_id is None and resident.active_group_id is None
    assert current_workspace_id(resident, db_session) is None


def test_the_first_workspace_an_admin_creates_becomes_their_current_one(world, db_session):
    res = world.client.post("/api/admin/groups", json={"name": f"First-{world.marker}"})
    assert res.status_code == 201, res.text
    gid = res.json()["id"]
    try:
        current = world.client.get("/api/self/workspaces/current").json()
        assert current["id"] == gid
        db_session.expire_all()
        assert str(db_session.get(Users, world.admin.id).active_group_id) == gid
        assert world.client.get("/api/platform/entries").status_code == 200  # a workspace now: its APIs answer
    finally:
        group = db_session.get(Groups, uuid.UUID(gid))
        from marvin.services.group.group_purge import purge_group_dependents

        db_session.query(Users).filter(Users.active_group_id == group.id).update({"active_group_id": None})
        purge_group_dependents(db_session, group.id)
        db_session.delete(group)
        db_session.commit()


# ── platform events carry no workspace ───────────────────────────────────────


def test_platform_events_have_no_workspace(world, db_session):
    before = db_session.execute(select(sa.func.count()).select_from(EventLogModel)).scalar()
    policy = world.client.get("/api/admin/storage/workspace-policy").json()
    res = world.client.put(
        "/api/admin/storage/workspace-policy",
        json={"allowed": not policy["allowed"], "endpointPolicy": policy["endpointPolicy"]},
    )
    assert res.status_code == 200, res.text
    world.client.put("/api/admin/storage/workspace-policy", json={"allowed": policy["allowed"], "endpointPolicy": policy["endpointPolicy"]})
    db_session.expire_all()
    rows = (
        db_session.execute(select(EventLogModel).where(EventLogModel.user_id == world.admin.id, EventLogModel.integration_id == "storage_settings"))
        .scalars()
        .all()
    )
    assert rows, "the storage policy change wasn't audited"
    assert all(r.workspace_id is None for r in rows)
    assert db_session.execute(select(sa.func.count()).select_from(EventLogModel)).scalar() > before


def test_an_api_token_event_has_no_workspace_even_with_one(world, db_session):
    member = _user(db_session, f"{world.marker}-tok", home=world.alpha.id)
    _join(db_session, member, world.alpha)
    db_session.commit()
    res = _client(member).post("/api/self/api-tokens", json={"name": f"nw-{world.marker}"})
    assert res.status_code in (200, 201), res.text
    db_session.expire_all()
    rows = (
        db_session.execute(select(EventLogModel).where(EventLogModel.user_id == member.id, EventLogModel.integration_id == "api_token_management"))
        .scalars()
        .all()
    )
    assert rows and all(r.workspace_id is None for r in rows)


# ── migration 9d7cd212484e ───────────────────────────────────────────────────

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_9d7cd212484e_*.py"))
_spec = importlib.util.spec_from_file_location("users_without_a_home", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

PLAT, OTHER, HOMELESS, HOUSED = (uuid.uuid4().hex for _ in range(4))


@pytest.fixture
def old_schema(tmp_path):
    """SQLite as it was: ``users.group_id`` NOT NULL with an unnamed foreign key to groups."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE groups (id CHAR(32) PRIMARY KEY, name VARCHAR NOT NULL, is_platform BOOLEAN NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE users (id CHAR(32) PRIMARY KEY, group_id CHAR(32) NOT NULL, FOREIGN KEY(group_id) REFERENCES groups (id))")
        conn.exec_driver_sql("INSERT INTO groups VALUES (?, 'Zed', 1), (?, 'Alpha', 0)", (PLAT, OTHER))
        conn.exec_driver_sql("INSERT INTO users VALUES (?, ?)", (HOUSED, OTHER))
    yield engine
    engine.dispose()


def _run(engine, step: str) -> None:
    with engine.begin() as conn:
        original = mig.op
        mig.op = Operations(MigrationContext.configure(conn))
        try:
            getattr(mig, step)()
        finally:
            mig.op = original


def test_migration_makes_the_home_nullable_and_set_null(old_schema):
    _run(old_schema, "upgrade")
    with old_schema.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("INSERT INTO users VALUES (?, NULL)", (HOMELESS,))
        conn.exec_driver_sql("DELETE FROM groups WHERE id = ?", (OTHER,))
        homes = dict(conn.exec_driver_sql("SELECT id, group_id FROM users").all())
    assert homes == {HOUSED: None, HOMELESS: None}


def test_migration_downgrade_gives_a_homeless_user_the_platform_workspace(old_schema):
    _run(old_schema, "upgrade")
    with old_schema.begin() as conn:
        conn.exec_driver_sql("INSERT INTO users VALUES (?, NULL)", (HOMELESS,))
    _run(old_schema, "downgrade")
    with old_schema.connect() as conn:
        homes = dict(conn.exec_driver_sql("SELECT id, group_id FROM users").all())
        assert homes == {HOUSED: OTHER, HOMELESS: PLAT}
        with pytest.raises(sa.exc.IntegrityError):
            conn.exec_driver_sql("INSERT INTO users VALUES (?, NULL)", (uuid.uuid4().hex,))
