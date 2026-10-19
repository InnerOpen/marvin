"""Runs inside the subprocess `tests/test_fresh_install_journey.py` starts: a Marvin process of its own, on the DATA_DIR
its environment names, so the journey never touches the test suite's database.

    python -m tests.fresh_install_driver journey <bundle.zip> <backup key>   # first start, then the admin's steps
    python -m tests.fresh_install_driver inspect                             # start on an existing DATA_DIR, report
    python -m tests.fresh_install_driver first_boot                          # first start only: what a bare install holds

Both print one JSON object (the facts) as the last line of stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

EMAIL = os.environ.get("DEFAULT_EMAIL", "changeme@example.com")
PASSWORD = os.environ["DEFAULT_PASSWORD"]


def _start():
    """What a container's entrypoint does first: wait for the database, migrate it, create the first admin."""
    from marvin.db import init_db

    init_db.main()


def _login(client) -> dict[str, str]:
    res = client.post("/api/auth/token", data={"username": EMAIL, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _facts(workspace_name: str) -> dict:
    """What an operator could check afterwards, read the way the running app reads it."""
    from sqlalchemy import func, select

    from marvin.core.config import get_app_settings
    from marvin.db.db_setup import engine, session_context
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.secrets import WorkspaceSecret
    from marvin.db.models.groups.variables import WorkspaceVariable
    from marvin.db.models.platform import Assets, Collections, Entries, Resources, Tags
    from marvin.db.models.users import Users
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.secrets import get_secret_backend
    from marvin.services.storage import provider_factory

    settings = get_app_settings()
    with session_context() as session:
        group = session.execute(select(Groups).where(Groups.name == workspace_name)).scalars().first()
        facts: dict = {
            "engine": engine.dialect.name,
            "db_file": str(settings.DB_PROVIDER.db_path) if hasattr(settings.DB_PROVIDER, "db_path") else None,
            "users": session.scalar(select(func.count()).select_from(Users)),
            "admin_logged_in": True,
            "workspace": bool(group),
        }
        if not group:
            return facts
        gid = group.id

        def count(model, **where):
            return session.scalar(select(func.count()).select_from(model).filter_by(group_id=gid, **where))

        facts.update(
            entries=count(Entries),
            published_entries=count(Entries, status="published"),
            collections=count(Collections),
            tags=count(Tags),
            resources=count(Resources),
            assets=count(Assets),
            variables={v.slug: v.value for v in session.query(WorkspaceVariable).filter_by(group_id=gid)},
            secret_rows=sorted(s.slug for s in session.query(WorkspaceSecret).filter_by(group_id=gid)),
        )
        facts["secrets"] = {slug: get_secret_backend().get(slug, gid) for slug in facts["secret_rows"]}
        repos = get_repositories(session, group_id=gid)
        files = {}
        for asset in repos.assets.get_all(limit=None):
            raw = provider_factory.provider_for(asset).get(asset.storage_key).read()
            files[asset.original_filename] = hashlib.sha256(raw).hexdigest()
        facts["files"] = files
        return facts


def journey(bundle: Path, backup_key: str) -> dict:
    from fastapi.testclient import TestClient

    from marvin.app import app

    _start()
    client = TestClient(app)
    headers = _login(client)  # the bootstrapped admin can sign in
    created = client.post("/api/admin/groups", json={"name": "Journey Co"}, headers=headers)
    assert created.status_code == 201, created.text
    gid = created.json()["id"]
    imported = client.post(
        f"/api/admin/backups/workspaces/{gid}/import",
        files={"file": (bundle.name, bundle.read_bytes(), "application/zip")},
        data={"backup_key": backup_key},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    return {**_facts("Journey Co"), "imported": imported.json()["imported"]}


def inspect() -> dict:
    from fastapi.testclient import TestClient

    from marvin.app import app

    _start()
    _login(TestClient(app))
    return _facts("Journey Co")


def first_boot() -> dict:
    """Start on an empty database and report what exists: no workspace, an admin who can sign in and use Admin."""
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from marvin.app import app
    from marvin.db.db_setup import engine, session_context
    from marvin.db.models.groups import Groups
    from marvin.db.models.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    _start()
    client = TestClient(app)
    headers = _login(client)
    current = client.get("/api/self/workspaces/current", headers=headers)
    admin_groups = client.get("/api/admin/groups", headers=headers)
    with session_context() as session:
        admin = session.execute(select(Users).where(Users.email == EMAIL)).scalar_one()
        facts = {
            "engine": engine.dialect.name,
            "groups": session.scalar(select(func.count()).select_from(Groups)),
            "users": session.scalar(select(func.count()).select_from(Users)),
            "memberships": session.scalar(select(func.count()).select_from(WorkspaceMembers)),
            "admin_home": admin.group_id,
            "admin_role": str(admin.platform_role),
            "homes": [u.group_id for u in session.execute(select(Users)).scalars()],
        }
    _start()  # a second start changes nothing
    with session_context() as session:
        facts["groups_after_restart"] = session.scalar(select(func.count()).select_from(Groups))
        facts["users_after_restart"] = session.scalar(select(func.count()).select_from(Users))
    facts.update(
        current_status=current.status_code,
        current=current.json(),
        admin_groups_status=admin_groups.status_code,
        admin_groups_total=admin_groups.json().get("total"),
        about_status=client.get("/api/admin/about", headers=headers).status_code,
        workspace_page_status=client.get("/api/platform/entries", headers=headers).status_code,
    )
    return facts


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "first_boot":
        result = first_boot()
    else:
        result = journey(Path(sys.argv[2]), sys.argv[3]) if command == "journey" else inspect()
    sys.stdout.write("\n" + json.dumps(result, default=str) + "\n")
