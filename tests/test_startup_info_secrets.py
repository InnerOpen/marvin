"""The startup-info endpoints dump the app settings; neither may carry a credential.

`GET /api/app/about/startup-info` is open to any signed-in user (and any API token), and its admin
twin to super admins. Both returned `DEFAULT_PASSWORD` — the initial admin's password — in plain text,
and the user route also returned the `DB_PROVIDER` object, whose `POSTGRES_URL_OVERRIDE` is a plain
connection string that can embed the database password.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole

ROUTES = {
    "any user": ("/api/app/about/startup-info", PlatformRole.NONE),
    "admin": ("/api/admin/about/startup-info", PlatformRole.SUPER_ADMIN),
}


@pytest.fixture
def sign_in():
    def _sign_in(platform_role):
        caller = SimpleNamespace(
            id=None, group_id=None, active_group_id=None, is_superuser=False, platform_role=platform_role, workspace_memberships=[]
        )
        app.dependency_overrides[get_current_user] = lambda: caller
        return TestClient(app)

    yield _sign_in
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize(("path", "platform_role"), ROUTES.values(), ids=ROUTES.keys())
def test_startup_info_carries_no_default_password_or_db_provider(sign_in, path, platform_role):
    password = get_app_settings().DEFAULT_PASSWORD
    assert password  # always set: generated at startup when the env doesn't provide one

    res = sign_in(platform_role).get(path)

    assert res.status_code == 200, res.text
    leaked = password in res.text  # not asserted directly, so a failure doesn't print the password
    assert not leaked
    assert res.json().get("defaultPassword") in (None, "*****")
    assert "dbProvider" not in res.json()
