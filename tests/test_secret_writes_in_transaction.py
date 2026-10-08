"""A secret written while saving something lands in the caller's transaction.

Saving an SMTP profile with a password used to 500 with "database is locked" on SQLite: the profile was flushed
(the request now holds the write lock) and the database secret backend then opened a second connection to store
the password, which waited on that lock. Written through the request's session, the secret also commits — or
rolls back — with the row that points at it, instead of surviving a save that failed.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.integrations import INTEGRATIONS_AVAILABLE
from marvin.services.secrets.backends.database import DatabaseSecretBackend

SMTP = "/api/groups/smtp-profiles"
INTEGRATIONS = "/api/groups/integrations"


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    slug = f"sec-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=slug,
            email=f"{slug}@t.test",
            full_name="SEC",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == gid).delete()
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@fixture
def admin(workspace) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="SEC",
        email=f"{workspace.slug}@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[],
        get_workspace_role=lambda group_id: WorkspaceRole.ADMIN if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _secret_slugs(db_session, gid) -> list[str]:
    db_session.expire_all()
    return [s for (s,) in db_session.query(WorkspaceSecret.slug).filter(WorkspaceSecret.group_id == gid).all()]


def test_smtp_profile_with_a_password_saves(admin, workspace):
    backend = DatabaseSecretBackend()
    created = admin.post(SMTP, json={"name": "Mail", "host": "smtp.example.com", "password": "hunter2!"})
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["hasPassword"]
    ref = f"SMTP_{uuid.UUID(profile['id']).hex.upper()}"
    assert backend.get(ref, workspace.gid) == "hunter2!"

    updated = admin.patch(f"{SMTP}/{profile['id']}", json={"password": "correct horse"})
    assert updated.status_code == 200, updated.text
    assert backend.get(ref, workspace.gid) == "correct horse"

    cleared = admin.patch(f"{SMTP}/{profile['id']}", json={"password": ""})
    assert cleared.status_code == 200, cleared.text
    assert backend.get(ref, workspace.gid) is None


def test_a_failed_save_leaves_no_secret(admin, workspace, db_session, monkeypatch):
    from marvin.routes.groups.smtp_controller import SMTPProfilesController

    def boom(self, keep_id):
        raise RuntimeError("save failed after the password was stored")

    monkeypatch.setattr(SMTPProfilesController, "_deactivate_others", boom)
    with pytest.raises(RuntimeError):
        admin.post(SMTP, json={"name": "Mail", "host": "smtp.example.com", "password": "hunter2!", "isActive": True})

    assert _secret_slugs(db_session, workspace.gid) == []


def test_backend_writes_through_a_session_without_committing(workspace, db_session):
    backend = DatabaseSecretBackend()
    backend.set("PENDING", "v", workspace.gid, session=db_session)
    db_session.rollback()
    assert backend.get("PENDING", workspace.gid) is None

    backend.set("KEPT", "v1", workspace.gid, session=db_session)
    db_session.commit()
    assert backend.get("KEPT", workspace.gid) == "v1"

    backend.delete("KEPT", workspace.gid, session=db_session)
    assert backend.get("KEPT", workspace.gid) == "v1"  # not until the caller commits
    db_session.commit()
    assert backend.get("KEPT", workspace.gid) is None


def test_backend_without_a_session_commits_on_its_own(workspace):
    backend = DatabaseSecretBackend()
    backend.set("SOLO", "v", workspace.gid)
    assert backend.get("SOLO", workspace.gid) == "v"
    backend.delete("SOLO", workspace.gid)
    assert backend.get("SOLO", workspace.gid) is None


@pytest.mark.skipif(not INTEGRATIONS_AVAILABLE, reason="integration routes need marvin_integration_sdk")
def test_integration_with_a_credential_saves(admin, workspace, monkeypatch):
    from marvin.routes.groups import integrations_controller as ic

    # Any provider will do: the credential path is what's under test, not the provider's config or health check.
    monkeypatch.setattr(ic, "get_provider", lambda slug: SimpleNamespace(slug=slug))
    monkeypatch.setattr(ic.IntegrationsController, "_validate_config", lambda self, provider, config: None)
    monkeypatch.setattr(ic.IntegrationsController, "_run_check", lambda self, row: None)

    created = admin.post(INTEGRATIONS, json={"provider": "stub", "name": "Stub", "credential": "tok-1"})
    assert created.status_code == 201, created.text
    backend = DatabaseSecretBackend()
    assert backend.get("INTEGRATION_STUB", workspace.gid) == "tok-1"

    updated = admin.patch(f"{INTEGRATIONS}/{created.json()['id']}", json={"credential": "tok-2"})
    assert updated.status_code == 200, updated.text
    assert backend.get("INTEGRATION_STUB", workspace.gid) == "tok-2"
