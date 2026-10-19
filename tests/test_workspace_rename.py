"""Renaming a workspace (name + slug) as a super admin, including that a changed slug keeps resolving, so the
current-workspace selection, Publishing API URLs and backups survive it. (Any workspace can be renamed: none is special.)
"""

import uuid
from types import SimpleNamespace

import pytest
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
from marvin.services.group.group_purge import purge_group_dependents
from marvin.services.group.workspace_rename import WorkspaceRenameError, find_group_by_slug, rename_workspace

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def ws(db_session):
    """An ordinary workspace to rename, removed afterwards."""
    name = f"rn-{uuid.uuid4().hex[:6]}"
    group = Groups(session=db_session, name=name, slug=name)
    db_session.add(group)
    db_session.commit()
    yield group
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(GroupSlugAlias).filter(GroupSlugAlias.group_id == group.id).delete(synchronize_session=False)
    purge_group_dependents(db_session, group.id)  # its audit events (workspace_updated ...) reference it
    db_session.query(Groups).filter(Groups.id == group.id).delete(synchronize_session=False)
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
def super_admin(db_session, ws):
    """A real SUPER_ADMIN row signed in (loaded fresh per request, so active_group_id is live)."""
    uid = uuid.uuid4()
    tag = uid.hex[:8]
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=ws.id,
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


def test_rename_name_and_slug_keeps_the_current_workspace_and_old_slug(super_admin, db_session, ws):
    old_slug = ws.slug
    client = super_admin.client
    assert client.put("/api/self/workspaces/current", json={"workspace": old_slug}).status_code == 200

    new_slug = f"platform-{uuid.uuid4().hex[:6]}"
    res = client.put(f"/api/admin/groups/{ws.id}", json={"id": str(ws.id), "name": "Platform Renamed", "slug": new_slug})
    assert res.status_code == 200, res.text
    assert (res.json()["name"], res.json()["slug"]) == ("Platform Renamed", new_slug)

    # The selection is by id: still the same workspace, now under its new name and slug.
    current = client.get("/api/self/workspaces/current").json()
    assert (current["id"], current["slug"]) == (str(ws.id), new_slug)
    # The old slug still resolves — switching by it (CLI --workspace), publishing URLs, backups.
    assert client.put("/api/self/workspaces/current", json={"workspace": old_slug}).json()["id"] == str(ws.id)
    assert find_group_by_slug(db_session, old_slug).id == ws.id


def test_name_only_rename_derives_the_slug(super_admin, ws):
    name = f"Platform {uuid.uuid4().hex[:6]}"
    res = super_admin.client.put(f"/api/admin/groups/{ws.id}", json={"id": str(ws.id), "name": name})
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == name.lower().replace(" ", "-")


def test_renaming_back_to_a_former_slug_drops_the_alias(db_session, ws):
    first = ws.slug
    rename_workspace(db_session, ws, name=ws.name, slug=f"tmp-{uuid.uuid4().hex[:6]}")
    rename_workspace(db_session, ws, name=ws.name, slug=first)
    db_session.commit()
    assert ws.slug == first
    assert db_session.query(GroupSlugAlias).filter(GroupSlugAlias.slug == first).count() == 0


def test_cannot_take_a_slug_or_name_in_use_or_another_workspaces_former_slug(super_admin, db_session, ws, others):
    put = lambda body: super_admin.client.put(f"/api/admin/groups/{ws.id}", json={"id": str(ws.id), **body})  # noqa: E731
    assert put({"name": ws.name, "slug": others.a.slug}).status_code == 409
    assert put({"name": others.a.name}).status_code == 409

    old_b = others.b.slug
    rename_workspace(db_session, others.b, name=others.b.name, slug=f"{old_b}-new")
    db_session.commit()
    res = put({"name": ws.name, "slug": old_b})
    assert res.status_code == 409 and "used to belong" in res.text
    assert find_group_by_slug(db_session, old_b).id == others.b.id
    with pytest.raises(WorkspaceRenameError):
        rename_workspace(db_session, ws, name="   ")


def test_a_new_workspace_never_takes_a_former_slug(db_session, others):
    old_a = others.a.slug
    rename_workspace(db_session, others.a, name=others.a.name, slug=f"{old_a}-moved")
    db_session.commit()
    from marvin.schemas.group import GroupCreate

    made = get_repositories(db_session, group_id=None).groups.create(GroupCreate(name=old_a))
    assert made.slug != old_a and made.name == f"{old_a} (1)"
    assert find_group_by_slug(db_session, old_a).id == others.a.id


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


def test_workspace_backups_keep_their_old_slug_files(super_admin, db_session, ws):
    from marvin.core.config import get_app_dirs

    backup_dir = get_app_dirs().BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    old = ws.slug
    kept = backup_dir / f"{old}-backup-2026-01-01-abc.zip"
    stranger = backup_dir / f"{old}x-backup-2026-01-01-abc.zip"
    for p in (kept, stranger):
        p.write_bytes(b"PK")
    try:
        client = super_admin.client
        assert client.put("/api/self/workspaces/current", json={"workspace": str(ws.id)}).status_code == 200
        rename_workspace(db_session, ws, name=ws.name, slug=f"moved-{uuid.uuid4().hex[:6]}")
        db_session.commit()
        names = {b["filename"] for b in client.get("/api/platform/workspace/backups").json()}
        assert kept.name in names and stranger.name not in names
        assert client.get(f"/api/platform/workspace/backups/{kept.name}").status_code == 200
    finally:
        for p in (kept, stranger):
            p.unlink(missing_ok=True)
