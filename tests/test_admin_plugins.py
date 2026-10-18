"""The platform admin's installed-plugins list (services/plugins.py, GET /api/admin/plugins).

Plugin discovery is the integrations SDK's job (entry points, at startup), and the SDK is optional, so
these tests stand in for the discovered sources at the one seam the service reads them through, and
exercise the real gate, query and response shape around it.
"""

import uuid
from types import SimpleNamespace

import pytest

from marvin.db.models.users.roles import PlatformRole

PLUGINS_URL = "/api/admin/plugins"


def _report(name, *, ok=True, slugs=(), distribution=None, version=None, error=None):
    return SimpleNamespace(name=name, ok=ok, slugs=list(slugs), distribution=distribution, version=version, error=error)


def _provider(slug, name, *, actions=0, content=0):
    return SimpleNamespace(slug=slug, name=name, actions=tuple(range(actions)), content=tuple(range(content)))


@pytest.fixture
def as_user(client):
    """Call the API as a stand-in user with the given platform role."""
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    def _as(platform_role):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(platform_role=platform_role, is_superuser=False, admin=True)
        return client

    yield _as
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def no_installed_storage_plugins(monkeypatch):
    """No storage or AI provider plugins unless a test stands some in: a plugin installed in the
    environment (e.g. marvin-storage-s3 or marvin-ai-openai in a dev venv) would otherwise show up in
    every listing."""
    import marvin.services.plugins as plugins

    monkeypatch.setattr(plugins, "_storage_sources", lambda: [])
    monkeypatch.setattr(plugins, "_ai_sources", lambda: [])


@pytest.fixture
def workspaces(db_session):
    """Two throwaway workspaces; they and their integrations are removed afterwards."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.integrations import IntegrationModel

    ids = []
    for _ in range(2):
        marker = uuid.uuid4().hex[:8]
        g = Groups(session=db_session, name=f"Plug {marker}", slug=f"plug-{marker}")
        db_session.add(g)
        db_session.flush()
        ids.append(g.id)
    db_session.commit()
    yield ids
    db_session.rollback()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id.in_(ids)).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id.in_(ids)).delete(synchronize_session=False)
    db_session.commit()


def _connect(db_session, group_id, provider, slug):
    from marvin.db.models.groups.integrations import IntegrationModel

    db_session.add(IntegrationModel(session=db_session, group_id=group_id, provider=provider, name=slug, slug=slug))
    db_session.commit()


def test_list_plugins_refuses_unauthenticated_request(client):
    assert client.get(PLUGINS_URL).status_code in (401, 403)


def test_list_plugins_refuses_workspace_admin(as_user):
    assert as_user(PlatformRole.NONE).get(PLUGINS_URL).status_code == 403


def test_list_plugins_reports_providers_and_workspace_usage(as_user, workspaces, db_session, monkeypatch):
    import marvin.services.plugins as plugins

    # Provider slugs unique to this test, so rows other tests leave behind can't skew the counts.
    tag = uuid.uuid4().hex[:6]
    rss, hook = f"rss_{tag}", f"hook_{tag}"
    sources = [
        (
            _report("rss", slugs=[rss, hook], distribution="marvin-integration-rss", version="1.2.0"),
            [_provider(rss, "RSS Feed", actions=2, content=1), _provider(hook, "Webhook Out", actions=1)],
        )
    ]
    monkeypatch.setattr(plugins, "_integration_sources", lambda: sources)
    first, second = workspaces
    _connect(db_session, first, rss, "news")
    _connect(db_session, first, rss, "blog")  # a second connection in the same workspace counts once
    _connect(db_session, second, rss, "feed")

    body = as_user(PlatformRole.SUPER_ADMIN).get(PLUGINS_URL).json()

    assert body == [
        {
            "name": "rss",
            "package": "marvin-integration-rss",
            "version": "1.2.0",
            "latestVersion": None,
            "kind": "integration",
            "ok": True,
            "error": None,
            "providers": [
                {
                    "slug": rss,
                    "name": "RSS Feed",
                    "icon": "",
                    "hasLogo": False,
                    "actions": 2,
                    "blueprints": 1,
                    "workspaces": 2,
                    "provides": [],
                    "inUse": [],
                },
                {
                    "slug": hook,
                    "name": "Webhook Out",
                    "icon": "",
                    "hasLogo": False,
                    "actions": 1,
                    "blueprints": 0,
                    "workspaces": 0,
                    "provides": [],
                    "inUse": [],
                },
            ],
        }
    ]


def test_list_plugins_keeps_a_plugin_that_failed_to_load(as_user, monkeypatch):
    import marvin.services.plugins as plugins

    sources = [
        (_report("zeta", distribution="marvin-integration-zeta"), []),
        (_report("broken", ok=False, distribution="marvin-integration-broken", error="ImportError: boom"), []),
    ]
    monkeypatch.setattr(plugins, "_integration_sources", lambda: sources)

    body = as_user(PlatformRole.SUPER_ADMIN).get(PLUGINS_URL).json()

    assert [(p["package"], p["ok"], p["error"]) for p in body] == [
        ("marvin-integration-broken", False, "ImportError: boom"),
        ("marvin-integration-zeta", True, None),
    ]


def test_integration_sources_without_the_sdk_is_empty(monkeypatch):
    import marvin.services.integrations as integrations
    from marvin.services.plugins import _integration_sources

    monkeypatch.setattr(integrations, "INTEGRATIONS_AVAILABLE", False)

    assert _integration_sources() == []


def test_list_plugins_reports_storage_plugins_and_what_they_are_used_for(as_user, monkeypatch):
    import marvin.services.plugins as plugins

    provider_cls, target_cls = object(), object()
    sources = [
        (
            _report("s3", slugs=["s3"], distribution="marvin-storage-s3", version="0.1.0"),
            [SimpleNamespace(slug="s3", name="S3-compatible", provider=provider_cls, target=target_cls)],
        ),
        (
            _report("nas", slugs=["nas"], distribution="marvin-storage-nas"),
            [SimpleNamespace(slug="nas", name="NAS", provider=None, target=target_cls)],
        ),
    ]
    monkeypatch.setattr(plugins, "_integration_sources", lambda: [])
    monkeypatch.setattr(plugins, "_storage_sources", lambda: sources)
    monkeypatch.setattr(plugins, "_active_storage_provider", lambda: "s3")

    body = {p["package"]: p for p in as_user(PlatformRole.SUPER_ADMIN).get(PLUGINS_URL).json()}

    s3 = body["marvin-storage-s3"]
    assert s3["kind"] == "storage" and s3["version"] == "0.1.0"
    assert [(p["slug"], p["provides"], p["inUse"]) for p in s3["providers"]] == [("s3", ["assets", "backups"], ["assets"])]
    assert [(p["slug"], p["provides"], p["inUse"]) for p in body["marvin-storage-nas"]["providers"]] == [("nas", ["backups"], [])]


def test_list_plugins_shows_a_newer_release_from_the_cached_check_only(as_user, db_session, monkeypatch):
    """`latestVersion` comes from the cached update check: set for a plugin behind its newest tag, None for one on it,
    and no request goes to GitHub while listing."""
    import marvin.services.plugin_updates as pu
    import marvin.services.plugins as plugins
    from marvin.services.platform_settings import PlatformSettingsService

    sources = [
        (_report("behind", distribution="marvin-integration-behind", version="0.1.0"), []),
        (_report("current", distribution="Marvin_Integration_Current", version="0.2.0"), []),  # name case/underscores differ
        (_report("untracked", distribution="marvin-integration-untracked", version="1.0.0"), []),
    ]
    monkeypatch.setattr(plugins, "_integration_sources", lambda: sources)
    monkeypatch.setattr(
        pu,
        "installed_from_github",
        lambda: {
            "marvin-integration-behind": ("0.1.0", "o/behind"),
            "marvin-integration-current": ("0.2.0", "o/current"),
        },
    )
    monkeypatch.setattr(pu, "latest_tag", lambda *a, **k: pytest.fail("listing plugins must not ask GitHub"))
    svc = PlatformSettingsService(db_session)
    svc.set(
        pu.CACHE_KEY,
        {"checked_at": "2999-01-01T00:00:00+00:00", "latest": {"marvin-integration-behind": "v0.3.0", "marvin-integration-current": "v0.2.0"}},
    )
    try:
        rows = {r["name"]: r for r in as_user(PlatformRole.SUPER_ADMIN).get(PLUGINS_URL).json()}
    finally:
        svc.set(pu.CACHE_KEY, {})

    assert {name: row["latestVersion"] for name, row in rows.items()} == {"behind": "0.3.0", "current": None, "untracked": None}


def test_list_plugins_survives_a_failing_update_lookup(as_user, monkeypatch):
    import marvin.services.plugin_updates as pu
    import marvin.services.plugins as plugins

    monkeypatch.setattr(plugins, "_integration_sources", lambda: [(_report("one", distribution="marvin-integration-one", version="1.0.0"), [])])

    def boom(*_a, **_k):
        raise RuntimeError("settings table unreadable")

    monkeypatch.setattr(pu, "available_updates", boom)
    body = as_user(PlatformRole.SUPER_ADMIN).get(PLUGINS_URL).json()
    assert [(r["name"], r["latestVersion"]) for r in body] == [("one", None)]
