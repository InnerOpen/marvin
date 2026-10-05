"""`POST/GET /api/platform/site/rebuild`: ask for a site rebuild and see where it stands.

The POST goes through the same coalescing queue as the `request_site_rebuild` workflow step, so repeat
calls join one pending rebuild (one build), and it is refused with a 409 when nothing would build the
site. EDITOR and above, like publishing. The GET reads the queue, the last `webhook_triggered` sent and
the newest build/deploy event a host reported.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import delete, select

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.event_bus_service.event_types import EventTypes

URL = "/api/platform/site/rebuild"


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    slug = f"rebuild-ep-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield SimpleNamespace(gid=gid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.execute(delete(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == gid))
    db_session.execute(delete(IntegrationEventSubscriptionModel).where(IntegrationEventSubscriptionModel.group_id == gid))
    db_session.execute(delete(IntegrationModel).where(IntegrationModel.group_id == gid))
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@fixture(autouse=True)
def dispatched(monkeypatch):
    """Every event dispatched (as its keyword arguments) instead of publishing it."""
    calls = []

    class _Bus:
        def __init__(self, *a, **k):
            pass

        def dispatch(self, **kw):
            calls.append(kw)

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _Bus)
    return calls


def _sign_in(workspace, role: WorkspaceRole | None, platform_role: PlatformRole = PlatformRole.NONE) -> TestClient:
    members = [SimpleNamespace(group_id=workspace.gid, workspace_role=role)] if role else []
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(),
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="Edna Editor",
        email=f"{workspace.slug}@t.test",
        platform_role=platform_role,
        workspace_memberships=members,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _deploy_hook(db_session, workspace, events=("webhook_triggered",), enabled=True, name="Pages deploy hook"):
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.services.event_bus_service.event_types import WebhookMode

    hook = GroupWebhooksModel(
        session=db_session,
        group_id=workspace.gid,
        name=name,
        enabled=enabled,
        url="https://deploy.example.test/hook",
        webhook_type=WebhookMode.event_driven,
        subscribed_events=list(events),
    )
    db_session.add(hook)
    db_session.commit()
    return hook.id


def _deploy_integration(db_session, workspace, enabled=True):
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.groups.integrations import IntegrationModel

    integration = IntegrationModel(
        session=db_session, group_id=workspace.gid, provider="cloudflare_pages", name="Cloudflare Pages", slug="pages", enabled=enabled
    )
    db_session.add(integration)
    db_session.flush()
    db_session.add(
        IntegrationEventSubscriptionModel(
            session=db_session, group_id=workspace.gid, integration_id=integration.id, event_type="webhook_triggered", action="deploy"
        )
    )
    db_session.commit()
    return integration.id


def _rows(db_session, workspace):
    db_session.expire_all()
    return db_session.execute(select(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == workspace.gid)).scalars().all()


# ── Roles ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, None], ids=["viewer", "author", "non-member"])
@pytest.mark.parametrize("method", ["POST", "GET"])
def test_below_editor_gets_403(db_session, workspace, role, method):
    _deploy_hook(db_session, workspace)

    response = _sign_in(workspace, role).request(method, URL)

    assert response.status_code == 403
    assert _rows(db_session, workspace) == []


@pytest.mark.parametrize(
    "role, platform_role",
    [(WorkspaceRole.EDITOR, PlatformRole.NONE), (WorkspaceRole.ADMIN, PlatformRole.NONE), (None, PlatformRole.SUPER_ADMIN)],
    ids=["editor", "admin", "super-admin"],
)
def test_editor_and_above_request_a_rebuild(db_session, workspace, role, platform_role):
    _deploy_hook(db_session, workspace)
    client = _sign_in(workspace, role, platform_role)

    assert client.post(URL).status_code == 202
    assert client.get(URL).status_code == 200
    assert len(_rows(db_session, workspace)) == 1


# ── Nothing builds the site ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "setup",
    [
        lambda s, w: None,
        lambda s, w: _deploy_hook(s, w, events=("entry_published",)),
        lambda s, w: _deploy_hook(s, w, enabled=False),
        lambda s, w: _deploy_integration(s, w, enabled=False),
    ],
    ids=["nothing", "hook-on-other-events", "disabled-hook", "disabled-integration"],
)
def test_409_when_nothing_builds_the_site(db_session, workspace, setup, dispatched):
    setup(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.EDITOR)

    response = client.post(URL, json={"reason": "please"})

    assert response.status_code == 409
    assert "Nothing is set up to build" in response.json()["detail"]
    assert _rows(db_session, workspace) == []
    assert dispatched == []
    assert client.get(URL).json()["configured"] is False


# ── Payload ───────────────────────────────────────────────────────────────────────────────────────
def test_the_response_says_what_was_queued_and_what_builds_it(db_session, workspace):
    hook_id = _deploy_hook(db_session, workspace)
    before = datetime.now(UTC)

    body = _sign_in(workspace, WorkspaceRole.EDITOR).post(URL, json={"reason": "  New menu is up  "}).json()

    assert set(body) == {"requested", "queuedAt", "lastRequestedAt", "expectedSendAt", "requestCount", "reason", "target", "targets"}
    assert body["requested"] is True
    assert body["reason"] == "New menu is up"
    assert body["requestCount"] == 1
    assert body["target"] == {"kind": "webhook", "id": str(hook_id), "name": "Pages deploy hook", "provider": None, "action": None}
    assert body["targets"] == [body["target"]]
    queued = datetime.fromisoformat(body["queuedAt"])
    queued = queued if queued.tzinfo else queued.replace(tzinfo=UTC)
    assert before - timedelta(seconds=1) <= queued <= datetime.now(UTC) + timedelta(seconds=1)
    assert datetime.fromisoformat(body["expectedSendAt"]) > datetime.fromisoformat(body["queuedAt"])


def test_the_body_is_optional_and_the_reason_defaults_to_who_asked(db_session, workspace):
    _deploy_hook(db_session, workspace)

    body = _sign_in(workspace, WorkspaceRole.EDITOR).post(URL).json()

    assert body["reason"] == "Rebuild requested by Edna Editor"
    (row,) = _rows(db_session, workspace)
    assert row.reason == "Rebuild requested by Edna Editor"
    assert row.changes == [{"label": "Rebuild requested by Edna Editor", "event": None, "entity_type": "workspace", "entity_id": str(workspace.gid)}]


def test_an_overlong_reason_is_a_422(db_session, workspace):
    _deploy_hook(db_session, workspace)

    assert _sign_in(workspace, WorkspaceRole.EDITOR).post(URL, json={"reason": "x" * 201}).status_code == 422


def test_an_integration_action_is_a_target(db_session, workspace):
    integration_id = _deploy_integration(db_session, workspace)

    body = _sign_in(workspace, WorkspaceRole.EDITOR).post(URL).json()

    assert body["target"] == {
        "kind": "integration",
        "id": str(integration_id),
        "name": "Cloudflare Pages",
        "provider": "cloudflare_pages",
        "action": "deploy",
    }


def test_with_several_targets_all_are_listed_and_none_is_named(db_session, workspace):
    _deploy_hook(db_session, workspace, name="A")
    _deploy_hook(db_session, workspace, name="B")
    _deploy_integration(db_session, workspace)

    body = _sign_in(workspace, WorkspaceRole.EDITOR).post(URL).json()

    assert body["target"] is None
    assert [(t["kind"], t["name"]) for t in body["targets"]] == [("integration", "Cloudflare Pages"), ("webhook", "A"), ("webhook", "B")]


# ── Debounce ──────────────────────────────────────────────────────────────────────────────────────
def test_repeat_requests_join_one_pending_rebuild(db_session, workspace, dispatched):
    _deploy_hook(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.EDITOR)

    first = client.post(URL, json={"reason": "one"}).json()
    second = client.post(URL, json={"reason": "two"}).json()
    third = client.post(URL).json()

    assert [r["requestCount"] for r in (first, second, third)] == [1, 2, 3]
    assert first["queuedAt"] == second["queuedAt"] == third["queuedAt"]
    (row,) = _rows(db_session, workspace)
    assert row.request_count == 3
    assert len(row.changes) == 1  # repeat requests for the workspace collapse to its newest line
    assert row.changes[0]["label"] == "Rebuild requested by Edna Editor"
    # Only the request that opened the batch announces it.
    assert [c["event_type"] for c in dispatched] == [EventTypes.site_rebuild_queued]


def test_the_scheduler_tick_sends_it_once(db_session, workspace):
    from marvin.services.site_rebuild import dispatch_due_rebuilds

    _deploy_hook(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.EDITOR)
    client.post(URL, json={"reason": "one"})
    client.post(URL, json={"reason": "two"})
    sent = []

    later = datetime.now(UTC) + timedelta(hours=1)
    dispatch_due_rebuilds(db_session, lambda gid, summary, changes, count: sent.append((gid, summary, count)), now=later)
    dispatch_due_rebuilds(db_session, lambda gid, summary, changes, count: sent.append((gid, summary, count)), now=later)

    assert [s for s in sent if s[0] == workspace.gid] == [(workspace.gid, "2 requests, latest: two", 2)]
    assert client.get(URL).json()["pending"] is None


# ── Status ────────────────────────────────────────────────────────────────────────────────────────
def _log_event(db_session, workspace, event_type, at, document_data, title):
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.add(
        EventLogModel(
            event_id=uuid.uuid4(),
            event_type=event_type,
            occurred_at=at,
            workspace_id=workspace.gid,
            integration_id="test",
            event_data={"documentData": document_data},
            message_title=title,
        )
    )
    db_session.commit()


def test_status_shows_the_pending_rebuild(db_session, workspace):
    hook_id = _deploy_hook(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.EDITOR)
    queued = client.post(URL, json={"reason": "one"}).json()

    status = client.get(URL).json()

    assert status["configured"] is True
    assert status["target"]["id"] == str(hook_id)
    assert status["pending"]["queuedAt"] == queued["queuedAt"]
    assert status["pending"]["requestCount"] == 1
    assert status["pending"]["reason"] == "one"
    assert [c["label"] for c in status["pending"]["changes"]] == ["one"]
    assert isinstance(status["quietSeconds"], int) and isinstance(status["maxWaitSeconds"], int)
    assert status["lastSent"] is None and status["lastBuild"] is None


def test_status_shows_the_last_rebuild_sent_and_the_newest_build_event(db_session, workspace):
    _deploy_hook(db_session, workspace)
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    _log_event(db_session, workspace, "webhook_triggered", t0, {"requestCount": 4, "changes": []}, "Site rebuild requested: 4 requests")
    _log_event(db_session, workspace, "site_deployment_started", t0 + timedelta(seconds=30), {"deploymentId": "dep-1"}, "Deploy started")
    _log_event(
        db_session,
        workspace,
        "site_deployment_failed",
        t0 + timedelta(minutes=2),
        {"deploymentId": "dep-1", "errorMessage": "npm ERR! build failed", "siteUrl": "https://x.pages.dev"},
        "Deploy failed",
    )
    _log_event(db_session, workspace, "entry_published", t0 + timedelta(minutes=3), {}, "Entry published")

    status = _sign_in(workspace, WorkspaceRole.EDITOR).get(URL).json()

    assert status["pending"] is None
    assert status["lastSent"]["requestCount"] == 4
    assert status["lastSent"]["message"] == "Site rebuild requested: 4 requests"
    build = status["lastBuild"]
    assert (build["eventType"], build["stage"], build["status"]) == ("site_deployment_failed", "deployment", "failed")
    assert (build["detail"], build["deploymentId"], build["siteUrl"]) == ("npm ERR! build failed", "dep-1", "https://x.pages.dev")
