"""GET /api/admin/about/statistics: the platform-wide counts the admin Overview shows, including the automation, agent and
connection counts that replaced the separate Platform System page."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marvin.db.models.users.roles import PlatformRole

STATS_URL = "/api/admin/about/statistics"
NEW_COUNTS = [
    "totalWorkflows",
    "enabledWorkflows",
    "pendingApprovals",
    "totalAgents",
    "totalPlaybooks",
    "totalIntegrations",
    "totalScheduledTasks",
    "totalIncomingWebhooks",
    "totalFormSubmissions",
    "connectedApps",
]


@pytest.fixture
def admin_client():
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    user = SimpleNamespace(platform_role=PlatformRole.SUPER_ADMIN, is_superuser=False, admin=True, username="root", email="root@t.test")
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_statistics_carry_the_automation_agent_and_connection_counts(admin_client):
    response = admin_client.get(STATS_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    for key in NEW_COUNTS:
        assert isinstance(body.get(key), int) and body[key] >= 0, key
    assert body["enabledWorkflows"] <= body["totalWorkflows"]
