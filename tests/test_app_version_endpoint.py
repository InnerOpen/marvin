"""The unauthenticated version endpoint the admin's update banner relies on."""

from fastapi.testclient import TestClient

from marvin.core.settings.static import APP_VERSION


def test_version_endpoint_is_public_and_reports_app_version(client: TestClient):
    res = client.get("/api/app/about/version")
    assert res.status_code == 200
    assert res.json() == {"version": APP_VERSION}


def test_about_itself_still_requires_auth(client: TestClient):
    assert client.get("/api/app/about").status_code == 401
