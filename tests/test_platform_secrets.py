"""Platform secrets: `workspace_secrets` rows with a NULL group, written through services/secrets/platform.py.

They are unique per slug, and no workspace API can list, read, change or resolve one.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy.exc import IntegrityError

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups import Groups
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.secrets.platform import (
    PlatformSecretReadOnly,
    delete_platform_secret,
    get_platform_secret,
    platform_secret_set,
    set_platform_secret,
)
from marvin.services.secrets.resolver import resolve, resolve_secret

BASE = "/api/groups/secrets"


@fixture
def slug(db_session):
    value = f"PLATFORM_TEST_{uuid.uuid4().hex[:8].upper()}"
    yield value
    db_session.rollback()
    db_session.query(WorkspaceSecret).filter(WorkspaceSecret.slug == value).delete()
    db_session.commit()


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"ps-{gid.hex[:8]}", slug=f"ps-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield gid
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _owner(gid) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(),
        group_id=gid,
        active_group_id=gid,
        admin=False,
        is_superuser=False,
        full_name="Owner",
        platform_role=PlatformRole.NONE,
        get_workspace_role=lambda group_id: WorkspaceRole.OWNER if str(group_id) == str(gid) else None,
    )
    return TestClient(app)


def _rows(db_session, slug):
    db_session.expire_all()
    return db_session.query(WorkspaceSecret).filter(WorkspaceSecret.slug == slug).all()


def test_a_platform_secret_round_trips_and_is_stored_without_a_workspace(db_session, slug):
    assert get_platform_secret(slug) is None and not platform_secret_set(slug)

    set_platform_secret(slug, "hunter2")
    assert get_platform_secret(slug) == "hunter2" and platform_secret_set(slug)
    [row] = _rows(db_session, slug)
    assert row.group_id is None and "hunter2" not in row.encrypted_value  # encrypted at rest

    set_platform_secret(slug, "hunter3")  # overwrite, not a second row
    assert get_platform_secret(slug) == "hunter3" and len(_rows(db_session, slug)) == 1

    delete_platform_secret(slug)
    assert get_platform_secret(slug) is None and not _rows(db_session, slug)
    delete_platform_secret(slug)  # deleting what isn't there is fine


def test_the_platform_scope_is_unique_per_slug(db_session, slug):
    set_platform_secret(slug, "one")
    db_session.add(WorkspaceSecret(session=db_session, group_id=None, name="dup", slug=slug, encrypted_value="x"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_platform_secret_with_a_workspaces_slug_does_not_collide(db_session, workspace, slug):
    set_platform_secret(slug, "platform-value")
    db_session.add(WorkspaceSecret(session=db_session, group_id=workspace, name="mine", slug=slug, encrypted_value="x"))
    db_session.commit()  # same slug in a workspace is a different secret
    assert len(_rows(db_session, slug)) == 2


def test_workspace_secret_apis_never_list_or_touch_platform_rows(db_session, workspace, slug):
    set_platform_secret(slug, "platform-value")
    [platform_row] = _rows(db_session, slug)
    client = _owner(workspace)

    assert client.get(BASE).json() == []  # list
    assert slug not in client.get(f"{BASE}/slugs").json()

    for call in (
        lambda: client.post(f"{BASE}/{platform_row.id}/reveal"),
        lambda: client.patch(f"{BASE}/{platform_row.id}", json={"value": "stolen"}),
        lambda: client.delete(f"{BASE}/{platform_row.id}"),
    ):
        assert call().status_code == 404
    assert get_platform_secret(slug) == "platform-value"

    # The workspace can create a secret under the same slug: it is its own.
    res = client.post(BASE, json={"name": "Mine", "slug": slug, "value": "workspace-value"})
    assert res.status_code == 201, res.text
    assert [s["slug"] for s in client.get(BASE).json()] == [slug]
    assert get_platform_secret(slug) == "platform-value"


def test_a_workspace_cannot_resolve_a_platform_secret(db_session, workspace, slug):
    set_platform_secret(slug, "platform-value")

    assert resolve_secret(slug, workspace) is None
    assert "platform-value" not in resolve("x {{" + slug + "}}", workspace)
    assert resolve_secret(slug, None) == "platform-value"  # only the platform scope reads it


def test_the_env_backend_cannot_store_a_platform_secret(monkeypatch, slug):
    from marvin.services.secrets import platform
    from marvin.services.secrets.backends.env import EnvSecretBackend

    monkeypatch.setattr(platform, "get_secret_backend", lambda: EnvSecretBackend())
    with pytest.raises(PlatformSecretReadOnly):
        set_platform_secret(slug, "x")
    delete_platform_secret(slug)  # nothing of ours to remove, no error
    monkeypatch.setenv(slug, "from-env")
    assert get_platform_secret(slug) == "from-env"
