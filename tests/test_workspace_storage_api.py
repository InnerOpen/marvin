"""Workspace → Storage API (BYO storage slice 2): OWNERs add, check and switch to a bucket; ADMINs only look; a
check proves the bucket and its public URL; keys changed after a check stop uploads; the platform policy is a
super admin's. Uses the stand-in plugin of tests/test_workspace_storage.py."""

import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.storage import workspace as ws_storage
from marvin.services.storage import workspace_admin
from tests.test_opaque_storage_keys import platform  # noqa: F401  (fixture)
from tests.test_storage_providers import entry_points  # noqa: F401  (fixture)
from tests.test_workspace_storage import R2, BucketProvider, _upload, byo  # noqa: F401  (fixture)

BASE = "/api/groups/storage-settings"
FIELDS = {"B_BUCKET": "theirs", "B_ENDPOINT": R2, "B_PUBLIC": "https://files.example.com"}
KEYS = {"B_KEY": "their-key", "B_KEY_ID": "their-key-id"}


class _Resp:
    def __init__(self, status_code, content=b""):
        self.status_code, self.content = status_code, content


@pytest.fixture
def api(byo, monkeypatch):  # noqa: F811
    """The workspace's secrets are listed, and the public URL serves the bucket (unless a test breaks it)."""
    from marvin.services.integrations import http_client

    monkeypatch.setattr(workspace_admin, "_secret_slugs", lambda group_id: set(byo.secrets))
    served = {"on": True}

    def get(url, **_kw):
        bucket = BucketProvider.buckets.get("theirs")
        key = urlsplit(url).path.lstrip("/")
        if not served["on"] or bucket is None or not bucket.exists(key):
            return _Resp(404)
        with bucket.get(key) as fh:
            return _Resp(200, fh.read())

    monkeypatch.setattr(http_client, "build_http", lambda: SimpleNamespace(get=get))
    yield SimpleNamespace(workspace=byo.workspace, secrets=byo.secrets, served=served)
    app.dependency_overrides.pop(get_current_user, None)


def _as(workspace, role: WorkspaceRole | None, platform_role=PlatformRole.NONE) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="Owner",
        username="owner",
        platform_role=platform_role,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _add(client, **overrides) -> dict:
    res = client.post(f"{BASE}/connections", json={"pluginSlug": "bucket", "label": "Their R2", "settings": FIELDS, "secretRefs": KEYS, **overrides})
    assert res.status_code == 201, res.text
    return res.json()


def test_admins_see_the_page_but_only_owners_change_it(api):
    admin = _as(api.workspace, WorkspaceRole.ADMIN)
    page = admin.get(BASE)
    assert page.status_code == 200 and page.json()["canEdit"] is False
    assert page.json()["providers"][0]["slug"] == "bucket"
    assert admin.post(f"{BASE}/connections", json={"pluginSlug": "bucket", "settings": FIELDS, "secretRefs": KEYS}).status_code == 403
    assert _as(api.workspace, WorkspaceRole.EDITOR).get(BASE).status_code == 403
    assert _as(api.workspace, WorkspaceRole.OWNER).get(BASE).json()["canEdit"] is True


def test_an_owner_adds_checks_and_switches_to_a_bucket(api, db_session):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    conn = _add(owner)
    assert (conn["status"], conn["secretRefs"], conn["location"]) == ("unverified", KEYS, f"ws:{conn['id']}")

    early = owner.put(f"{BASE}/mode", json={"mode": "workspace", "connectionId": conn["id"]})
    assert early.status_code == 422 and "Check the connection first" in early.json()["detail"]

    check = owner.post(f"{BASE}/connections/{conn['id']}/check").json()
    assert check["ok"] is True, check
    assert [s["name"] for s in check["steps"]] == ["list", "put", "get", "delete", "public url"]

    page = owner.put(f"{BASE}/mode", json={"mode": "workspace", "connectionId": conn["id"]}).json()
    assert (page["mode"], page["activeConnectionId"]) == ("workspace", conn["id"])
    asset = _upload(db_session, api.workspace.gid, api.workspace.uid)
    assert asset.storage_provider == f"ws:{conn['id']}"
    assert owner.get(BASE).json()["connections"][0]["files"] == 1


def test_a_public_url_that_doesnt_serve_the_bucket_fails_the_check(api):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    conn = _add(owner)
    api.served["on"] = False
    check = owner.post(f"{BASE}/connections/{conn['id']}/check").json()
    assert check["ok"] is False and check["steps"][-1]["name"] == "public url"
    assert "answered 404" in check["steps"][-1]["error"]
    stored = owner.get(BASE).json()["connections"][0]
    assert stored["status"] == "failing" and stored["lastError"].startswith("public url:")


def test_keys_changed_after_the_check_stop_uploads_until_checked_again(api, db_session):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    conn = _add(owner)
    owner.post(f"{BASE}/connections/{conn['id']}/check")
    owner.put(f"{BASE}/mode", json={"mode": "workspace", "connectionId": conn["id"]})

    api.secrets["their-key"] = "rotated-in-secrets-page"
    with pytest.raises(ws_storage.WorkspaceStorageUnavailable, match="keys changed"):
        _upload(db_session, api.workspace.gid, api.workspace.uid)

    assert owner.post(f"{BASE}/connections/{conn['id']}/check").json()["ok"] is True
    assert _upload(db_session, api.workspace.gid, api.workspace.uid).storage_provider == f"ws:{conn['id']}"


def test_the_bucket_never_changes_on_a_connection_but_its_keys_can(api):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    conn = _add(owner)
    owner.post(f"{BASE}/connections/{conn['id']}/check")

    moved = owner.patch(f"{BASE}/connections/{conn['id']}", json={"settings": {"B_BUCKET": "another"}})
    assert moved.status_code == 422 and "can't change" in moved.json()["detail"]

    api.secrets["new-key"] = "k-456"
    rekeyed = owner.patch(f"{BASE}/connections/{conn['id']}", json={"secretRefs": {"B_KEY": "new-key"}})
    assert rekeyed.status_code == 200 and rekeyed.json()["status"] == "unverified"


@pytest.mark.parametrize(
    "body, message",
    [
        ({"secretRefs": {**KEYS, "B_KEY": "no-such-secret"}}, "No workspace secret"),
        ({"settings": {**FIELDS, "B_KEY": "pasted-key"}}, "must come from a workspace secret"),
        ({"settings": {**FIELDS, "B_ENDPOINT": "https://minio.lan"}}, "Endpoint refused"),
        ({"settings": {"B_BUCKET": "theirs"}}, "Missing:"),
    ],
)
def test_a_connection_that_cant_work_is_refused_with_why(api, body, message):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    res = owner.post(f"{BASE}/connections", json={"pluginSlug": "bucket", "settings": FIELDS, "secretRefs": KEYS, **body})
    assert res.status_code == 422 and message in res.json()["detail"]


def test_the_active_connection_is_retired_only_after_switching_away(api, db_session):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    conn = _add(owner)
    owner.post(f"{BASE}/connections/{conn['id']}/check")
    owner.put(f"{BASE}/mode", json={"mode": "workspace", "connectionId": conn["id"]})
    old = _upload(db_session, api.workspace.gid, api.workspace.uid, b"kept")

    assert owner.post(f"{BASE}/connections/{conn['id']}/retire").status_code == 422
    owner.put(f"{BASE}/mode", json={"mode": "platform"})
    assert owner.post(f"{BASE}/connections/{conn['id']}/retire").json()["status"] == "retired"

    from marvin.services.storage.provider_factory import provider_for

    with provider_for(old.storage_provider).get(old.storage_key) as fh:
        assert fh.read() == b"kept"  # a retired connection still serves its files


def test_the_policy_is_a_super_admins_and_off_blocks_switching(api, db_session):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    assert owner.put("/api/admin/storage/workspace-policy", json={"allowed": False}).status_code == 403

    root = _as(api.workspace, WorkspaceRole.OWNER, PlatformRole.SUPER_ADMIN)
    res = root.put("/api/admin/storage/workspace-policy", json={"allowed": False, "endpointPolicy": "known"})
    assert res.status_code == 200 and res.json() == {"allowed": False, "endpointPolicy": "known"}

    owner = _as(api.workspace, WorkspaceRole.OWNER)
    blocked = owner.put(f"{BASE}/mode", json={"mode": "workspace", "connectionId": "00000000-0000-0000-0000-000000000000"})
    assert blocked.status_code == 422 and "doesn't allow" in blocked.json()["detail"]


# ── copying existing files into the bucket (slice 3) ─────────────────────────


def _verified(owner) -> dict:
    conn = _add(owner)
    assert owner.post(f"{BASE}/connections/{conn['id']}/check").json()["ok"] is True
    return conn


def test_a_run_into_a_workspace_bucket_only_takes_that_workspaces_files(api, db_session):
    from marvin.services.storage.migration import MigrationError, migrate

    conn = _verified(_as(api.workspace, WorkspaceRole.OWNER))
    with pytest.raises(MigrationError, match="give --workspace"):
        migrate(f"ws:{conn['id']}", dry_run=True)
    from tests.test_opaque_storage_keys import _drop_workspace, _make_workspace

    other = _make_workspace(db_session, "Other")
    try:
        with pytest.raises(MigrationError, match="belongs to another workspace"):
            migrate(f"ws:{conn['id']}", workspace=other.slug, dry_run=True)
    finally:
        _drop_workspace(db_session, other)


def test_the_plan_counts_files_and_entries_that_link_to_them(api, db_session, platform):  # noqa: F811
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.services.storage.keys import workspace_code

    owner = _as(api.workspace, WorkspaceRole.OWNER)
    first, second = (_upload(db_session, api.workspace.gid, api.workspace.uid, data) for data in (b"one", b"three"))
    et = EntryTypes(session=db_session, group_id=api.workspace.gid, name="Note", slug="note", schema_json={})
    db_session.add(et)
    db_session.flush()
    code = workspace_code(db_session, api.workspace.gid)
    db_session.add_all(
        [
            Entries(
                session=db_session,
                group_id=api.workspace.gid,
                entry_type_id=et.id,
                title="Linked",
                slug="linked",
                data_json={"body": f"<img src='https://cdn.example/{code}/x.png'>"},
            ),
            Entries(session=db_session, group_id=api.workspace.gid, entry_type_id=et.id, title="Plain", slug="plain", data_json={"body": "no files"}),
        ]
    )
    db_session.commit()
    conn = _verified(owner)
    try:
        plan = owner.get(f"{BASE}/connections/{conn['id']}/copy").json()
        assert (plan["files"], plan["bytes"], plan["entriesWithLinks"], plan["ready"]) == (2, len(b"one") + len(b"three"), 1, True)
        assert plan["byLocation"] == [{"location": "local", "files": 2, "bytes": 8}]
        assert first.storage_provider == second.storage_provider == "local"
    finally:
        db_session.query(Entries).filter(Entries.group_id == api.workspace.gid).delete()
        db_session.query(EntryTypes).filter(EntryTypes.group_id == api.workspace.gid).delete()
        db_session.commit()


def test_copying_moves_every_file_into_the_bucket_and_keeps_the_originals(api, db_session, platform, monkeypatch):  # noqa: F811
    from marvin.db.models.platform import Assets
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventTypes
    from marvin.services.scheduled_tasks import TaskHandlerRegistry

    sent = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw["event_type"]))

    owner = _as(api.workspace, WorkspaceRole.OWNER)
    old = [_upload(db_session, api.workspace.gid, api.workspace.uid, data) for data in (b"alpha", b"beta")]
    conn = _verified(owner)

    started = owner.post(f"{BASE}/connections/{conn['id']}/copy")
    assert started.status_code == 202, started.text
    task = db_session.get(ScheduledTaskModel, uuid.UUID(started.json()["taskId"]))
    assert (task.task_type, task.enabled, task.task_config["connection_id"]) == ("copy_to_workspace_storage", False, conn["id"])

    assert EventTypes.scheduled_task_triggered in sent  # Run Now's trigger; run it here instead of the listener
    summary = TaskHandlerRegistry.get_handler(task.task_type).execute(task, None)
    assert "2 asset rows moved" in summary and "0 failed" in summary
    db_session.expire_all()
    bucket = BucketProvider.buckets["theirs"]
    for asset in old:
        row = db_session.get(Assets, asset.id)
        assert row.storage_provider == f"ws:{conn['id']}" and bucket.exists(row.storage_key)
        assert platform.local.exists(row.storage_key)  # the original stays: published links keep working
    assert owner.get(f"{BASE}/connections/{conn['id']}/copy").json()["files"] == 0
    db_session.query(ScheduledTaskModel).filter_by(id=task.id).delete()
    db_session.commit()


def test_only_a_verified_bucket_takes_a_copy(api):
    owner = _as(api.workspace, WorkspaceRole.OWNER)
    conn = _add(owner)
    res = owner.post(f"{BASE}/connections/{conn['id']}/copy")
    assert res.status_code == 422 and "Check the connection first" in res.json()["detail"]
    assert _as(api.workspace, WorkspaceRole.ADMIN).post(f"{BASE}/connections/{conn['id']}/copy").status_code == 403
