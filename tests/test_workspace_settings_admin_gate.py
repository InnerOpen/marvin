"""Workspace-settings routes are workspace-admin only.

Integrations (CRUD, checks, Run action, option pickers, event connections), outgoing webhooks, SMTP
profiles, variables, email event subscriptions, scheduled tasks, workspace export/backups, invite
tokens and the platform email test/edit routes used to let any member through — a VIEWER could point
a webhook at their own server or fire an integration action with the workspace's credentials. Each
route must refuse VIEWER/AUTHOR/EDITOR with a 403 before it looks anything up, and let OWNER/ADMIN
past the gate (a 404 for a made-up id proves that).
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.integrations import INTEGRATIONS_AVAILABLE

NOPE = "00000000-0000-4000-8000-000000000000"

INTEGRATIONS = "/api/groups/integrations"
WEBHOOKS = "/api/groups/webhooks"
SMTP = "/api/groups/smtp-profiles"
VARIABLES = "/api/groups/variables"
EMAIL_SUBS = "/api/groups/email-event-subscriptions"
TASKS = "/api/platform/scheduled-tasks"
WORKSPACE = "/api/platform/workspace"
EMAIL = "/api/platform/email"

_WEBHOOK = {"name": "Hook", "url": "https://example.com/hook"}

# (method, path, json body). Bodies are valid so FastAPI's validation (which runs before the handler)
# can't answer first; `{slug}` is the workspace slug.
GATED = [
    # integrations
    ("GET", INTEGRATIONS, None),
    ("POST", INTEGRATIONS, {"provider": "no_such_provider", "name": "X"}),
    ("PATCH", f"{INTEGRATIONS}/{NOPE}", {}),
    ("DELETE", f"{INTEGRATIONS}/{NOPE}", None),
    ("POST", f"{INTEGRATIONS}/{NOPE}/check", None),
    ("POST", f"{INTEGRATIONS}/{NOPE}/actions/anything", {}),
    ("POST", f"{INTEGRATIONS}/{NOPE}/options", {"action_key": "a", "input": "b"}),
    ("GET", f"{INTEGRATIONS}/plugins", None),
    ("GET", f"{INTEGRATIONS}/subscriptions", None),
    ("POST", f"{INTEGRATIONS}/subscriptions", {"integration_id": NOPE, "event_type": "entry_created", "action": "a"}),
    ("PATCH", f"{INTEGRATIONS}/subscriptions/{NOPE}", {}),
    ("DELETE", f"{INTEGRATIONS}/subscriptions/{NOPE}", None),
    # integrations: the Alerts & health page
    ("GET", f"{INTEGRATIONS}/health", None),
    ("GET", f"{INTEGRATIONS}/alerts", None),
    ("GET", f"{INTEGRATIONS}/retries", None),
    ("POST", f"{INTEGRATIONS}/retries/{NOPE}/retry-now", None),
    ("POST", f"{INTEGRATIONS}/retries/{NOPE}/give-up", None),
    ("GET", f"{INTEGRATIONS}/handled-failures", None),
    # outgoing webhooks
    ("GET", WEBHOOKS, None),
    ("POST", WEBHOOKS, _WEBHOOK),
    ("GET", f"{WEBHOOKS}/rerun", None),
    ("GET", f"{WEBHOOKS}/log", None),
    ("GET", f"{WEBHOOKS}/{NOPE}", None),
    ("GET", f"{WEBHOOKS}/{NOPE}/test", None),
    ("GET", f"{WEBHOOKS}/{NOPE}/logs", None),
    ("PUT", f"{WEBHOOKS}/{NOPE}", _WEBHOOK),
    ("DELETE", f"{WEBHOOKS}/{NOPE}", None),
    # SMTP profiles
    ("GET", SMTP, None),
    ("POST", SMTP, {"name": "Mail", "host": "smtp.example.com"}),
    ("GET", f"{SMTP}/{NOPE}", None),
    ("PATCH", f"{SMTP}/{NOPE}", {}),
    ("DELETE", f"{SMTP}/{NOPE}", None),
    ("POST", f"{SMTP}/{NOPE}/test", {"recipient_email": "a@example.com"}),
    # variables
    ("GET", VARIABLES, None),
    ("POST", VARIABLES, {"name": "Site", "slug": "SITE_NAME", "value": "v"}),
    ("PATCH", f"{VARIABLES}/{NOPE}", {}),
    ("DELETE", f"{VARIABLES}/{NOPE}", None),
    # email event subscriptions
    ("GET", EMAIL_SUBS, None),
    ("POST", EMAIL_SUBS, {"template_id": NOPE, "event_type": "entry_created"}),
    ("GET", f"{EMAIL_SUBS}/{NOPE}", None),
    ("DELETE", f"{EMAIL_SUBS}/{NOPE}", None),
    # invite tokens (live: whoever holds one joins with its role)
    ("GET", "/api/groups/invitations", None),
    # scheduled tasks
    ("GET", TASKS, None),
    ("POST", TASKS, {"name": "T", "schedule_type": "cron", "schedule_config": {"cron": "0 0 * * *"}, "task_type": "no_such_type"}),
    ("GET", f"{TASKS}/log", None),
    ("GET", f"{TASKS}/no-such-task", None),
    ("PATCH", f"{TASKS}/no-such-task", {}),
    ("DELETE", f"{TASKS}/no-such-task", None),
    ("POST", f"{TASKS}/no-such-task/execute", None),
    ("GET", f"{TASKS}/no-such-task/history", None),
    # workspace export and backups
    ("GET", f"{WORKSPACE}/export", None),
    ("GET", f"{WORKSPACE}/export/pretty", None),
    ("POST", f"{WORKSPACE}/backups", None),
    ("GET", f"{WORKSPACE}/backups", None),
    ("GET", WORKSPACE + "/backups/{slug}-missing.zip", None),
    # platform email: test sends and template edits
    ("POST", f"{EMAIL}/test", {"email": "a@example.com"}),
    ("PATCH", f"{EMAIL}/templates/{NOPE}", {}),
    ("POST", f"{EMAIL}/templates/{NOPE}/test", {"recipient_email": "a@example.com"}),
]

# Reads with no workspace configuration in them, which member pages use.
OPEN = [
    f"{INTEGRATIONS}/providers",
    f"{WEBHOOKS}/types",
    f"{TASKS}/task-types",
]

BELOW_ADMIN = [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER]


@fixture
def workspace(db_session):
    """A workspace with one user in it; tests sign that user in with whatever role they need."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    slug = f"gate-{marker}"
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
            full_name="GATE",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.core.config import get_app_dirs
    from marvin.services.group.group_purge import purge_group_dependents

    for backup in get_app_dirs().BACKUP_DIR.glob(f"{slug}-*.zip"):
        backup.unlink()
    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole | None, platform_role: PlatformRole = PlatformRole.NONE) -> TestClient:
    """Make the workspace's user the caller, holding `role` in it (None = not a member)."""
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="GATE",
        email=f"{workspace.slug}@t.test",
        platform_role=platform_role,
        workspace_memberships=[],
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _call(client: TestClient, workspace, method: str, path: str, body):
    kwargs = {"json": body} if body is not None else {}
    return client.request(method, path.format(slug=workspace.slug), **kwargs)


def _ids(route):
    return f"{route[0]} {route[1]}"


# The integrations controller is only mounted when marvin_integration_sdk is installed (CI runs without it).
_NEEDS_SDK = pytest.mark.skipif(not INTEGRATIONS_AVAILABLE, reason="integration routes need marvin_integration_sdk")


def _gated(routes):
    return [pytest.param(r, id=_ids(r), marks=_NEEDS_SDK if r[1].startswith(INTEGRATIONS) else ()) for r in routes]


def _open(paths):
    return [pytest.param(p, id=p, marks=_NEEDS_SDK if p.startswith(INTEGRATIONS) else ()) for p in paths]


@pytest.mark.parametrize("role", BELOW_ADMIN)
@pytest.mark.parametrize("route", _gated(GATED))
def test_members_below_admin_get_403(workspace, role, route):
    res = _call(_sign_in(workspace, role), workspace, *route)
    assert res.status_code == 403, res.text


@pytest.mark.parametrize("route", _gated(GATED))
def test_non_member_gets_403(workspace, route):
    res = _call(_sign_in(workspace, None), workspace, *route)
    assert res.status_code == 403, res.text


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
@pytest.mark.parametrize("route", _gated(GATED))
def test_owner_or_admin_gets_past_the_gate(workspace, role, route):
    res = _call(_sign_in(workspace, role), workspace, *route)
    assert res.status_code != 403, res.text
    assert res.status_code < 500, res.text


@pytest.mark.parametrize("route", _gated(GATED))
def test_platform_super_admin_gets_past_the_gate(workspace, route):
    res = _call(_sign_in(workspace, None, PlatformRole.SUPER_ADMIN), workspace, *route)
    assert res.status_code != 403, res.text
    assert res.status_code < 500, res.text


@pytest.mark.parametrize("path", _open(OPEN))
def test_catalog_reads_stay_open_to_viewers(workspace, path):
    assert _sign_in(workspace, WorkspaceRole.VIEWER).get(path).status_code == 200


def test_webhook_logs_are_scoped_to_the_workspace(workspace, db_session):
    """A webhook id from another workspace returned that workspace's request payloads and responses."""
    from datetime import UTC, datetime

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.services.group.group_purge import purge_group_dependents

    other = uuid.uuid4()
    group = Groups(session=db_session, name=f"other-{other.hex[:8]}", slug=f"other-{other.hex[:8]}")
    group.id = other
    db_session.add(group)
    db_session.flush()
    hook = GroupWebhooksModel(session=db_session, group_id=other, name="theirs", url="https://example.com/theirs")
    db_session.add(hook)
    db_session.flush()
    db_session.add(
        WebhookExecutionLogModel(
            session=db_session,
            webhook_id=hook.id,
            group_id=other,
            executed_at=datetime.now(UTC),
            status="success",
            request_payload={"secret": "theirs"},
        )
    )
    db_session.commit()
    try:
        res = _sign_in(workspace, WorkspaceRole.ADMIN).get(f"{WEBHOOKS}/{hook.id}/logs")
        assert res.status_code == 200, res.text
        assert res.json() == []
    finally:
        purge_group_dependents(db_session, other)
        db_session.query(Groups).filter(Groups.id == other).delete()
        db_session.commit()
