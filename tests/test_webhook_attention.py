"""Outgoing webhooks that need a look: enabled, with a destination the server must not post to (localhost, loopback, link-local,
private ranges). The rule is the one WebhookCreate already enforces in production; outside production private destinations are
allowed, so nothing is flagged. The count is registered in the Automation summary and each row carries the reason."""

# ruff: noqa: F811 — `workspace` is a fixture
import pytest

from marvin.core.config import get_app_settings
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.webhook import WebhookRead, private_destination
from marvin.services.automation import attention
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import workspace  # noqa: F401 — fixture


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(get_app_settings(), "PRODUCTION", True)


def _hook(session, gid, name, url, *, enabled=True):
    row = GroupWebhooksModel(session=session, group_id=gid, name=name, enabled=enabled, url=url)
    session.add(row)
    session.commit()
    return row


def _reasons(workspace) -> dict:
    res = gates._sign_in(workspace, WorkspaceRole.ADMIN).get("/api/groups/webhooks")
    assert res.status_code == 200
    return {r["name"]: r["attention"] for r in res.json()["items"]}


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8083/hook",
        "http://LOCALHOST/hook",
        "http://127.0.0.1/hook",
        "http://[::1]/hook",
        "http://0.0.0.0/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.10.10/x",
        "http://10.1.2.3/x",
        "http://172.16.0.9/x",
        "http://192.168.1.20:5678/x",
    ],
)
def test_private_destinations_are_named(url):
    assert private_destination(url)


@pytest.mark.parametrize(
    "url", ["https://example.com/hook", "https://hooks.example.test/x?token=abc", "http://8.8.8.8/x", "http://n8n.internal-name.example/x"]
)
def test_public_destinations_are_not(url):
    assert private_destination(url) is None


def test_create_still_refuses_the_same_urls_in_production(production):
    from pydantic import ValidationError

    from marvin.schemas.group.webhook import WebhookCreate

    with pytest.raises(ValidationError):
        WebhookCreate(name="x", url="http://10.0.0.5/x")


def test_an_enabled_webhook_to_localhost_is_flagged_in_production(db_session, workspace, production):
    _hook(db_session, workspace.gid, "Webhook", "http://localhost:8083/hook")
    _hook(db_session, workspace.gid, "Lan", "http://192.168.1.20/hook")
    _hook(db_session, workspace.gid, "Fine", "https://example.com/hook")

    assert _reasons(workspace) == {"Webhook": "unreachable_address", "Lan": "unreachable_address", "Fine": None}
    assert attention.outgoing_webhooks_needing_a_look(db_session, workspace.gid) == 2


def test_a_disabled_webhook_is_not_flagged(db_session, workspace, production):
    _hook(db_session, workspace.gid, "Off", "http://localhost/hook", enabled=False)

    assert _reasons(workspace) == {"Off": None}
    assert attention.outgoing_webhooks_needing_a_look(db_session, workspace.gid) == 0


def test_private_destinations_are_fine_where_the_deployment_allows_them(db_session, workspace, monkeypatch):
    monkeypatch.setattr(get_app_settings(), "PRODUCTION", False)
    _hook(db_session, workspace.gid, "Dev", "http://localhost:8083/hook")

    assert _reasons(workspace) == {"Dev": None}
    assert attention.outgoing_webhooks_needing_a_look(db_session, workspace.gid) == 0


def test_the_summary_counts_them_under_outgoing_webhooks(db_session, workspace, production):
    _hook(db_session, workspace.gid, "Webhook", "http://localhost/hook")

    found = gates._sign_in(workspace, WorkspaceRole.ADMIN).get("/api/automations/attention").json()

    assert found == {
        "total": 1,
        "kinds": {"workflows": 0, "incoming_webhooks": 0, "outgoing_webhooks": 1, "scheduled_tasks": 0},
        "firstPage": "/automation/webhooks?status=attention",
    }


def test_another_workspaces_webhooks_never_count(db_session, workspace, production):
    import uuid

    from marvin.db.models.groups import Groups
    from marvin.services.group.group_purge import purge_group_dependents

    other = Groups(session=db_session, name=f"wa-{uuid.uuid4().hex[:6]}", slug=f"wa-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    db_session.flush()
    try:
        _hook(db_session, other.id, "Theirs", "http://localhost/hook")
        assert attention.outgoing_webhooks_needing_a_look(db_session, workspace.gid) == 0
        assert attention.outgoing_webhooks_needing_a_look(db_session, other.id) == 1
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, other.id)
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()


def test_a_stored_unreachable_url_still_reads_in_production(production):
    import uuid

    read = WebhookRead(id=uuid.uuid4(), group_id=uuid.uuid4(), name="w", url="http://localhost/h", enabled=True)
    assert read.attention == "unreachable_address"
