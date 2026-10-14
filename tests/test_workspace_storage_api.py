"""Workspace → Storage API (BYO storage slice 2): OWNERs add, check and switch to a bucket; ADMINs only look; a
check proves the bucket and its public URL; keys changed after a check stop uploads; the platform policy is a
super admin's. Uses the stand-in plugin of tests/test_workspace_storage.py."""

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
