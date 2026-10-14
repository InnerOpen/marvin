"""Plugin update notices (services/plugin_updates.py): installed GitHub plugins against their newest version tag."""

from datetime import UTC, datetime, timedelta

import pytest

from marvin.services import plugin_updates as pu
from marvin.services.platform_settings import PlatformSettingsService


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _GitHub:
    """Stands in for httpx: tags per repository, or a status code for a repository that fails."""

    def __init__(self, tags):
        self.tags = tags

    def get(self, url, **_kw):
        repo = url.split("/repos/")[1].split("/tags")[0]
        found = self.tags.get(repo)
        return _Resp(found, []) if isinstance(found, int) else _Resp(200, [{"name": t} for t in found])


@pytest.fixture
def installed(monkeypatch, db_session):
    plugins = {"marvin-storage-s3": ("0.1.0", "InnerOpen/marvin-storage-s3"), "marvin-ai-openai": ("0.2.0", "InnerOpen/marvin-ai-openai")}
    monkeypatch.setattr(pu, "installed_from_github", lambda: plugins)
    yield plugins
    PlatformSettingsService(db_session).set(pu.CACHE_KEY, {})


def test_the_highest_version_tag_wins_and_other_tags_are_ignored():
    http = _GitHub({"o/r": ["v0.9.0", "v0.10.0", "nightly", "v0.2.1"]})
    assert pu.latest_tag("o/r", http) == "v0.10.0"
    assert pu.latest_tag("o/missing", _GitHub({"o/missing": 404})) is None


def test_a_plugin_behind_its_newest_tag_is_listed_and_one_on_it_is_not(db_session, installed):
    http = _GitHub({"InnerOpen/marvin-storage-s3": ["v0.1.0", "v0.2.0"], "InnerOpen/marvin-ai-openai": ["v0.2.0"]})
    pu.refresh(db_session, http)
    updates = pu.available_updates(db_session, refresh_if_stale=False)
    assert [(u.package, u.installed, u.latest) for u in updates] == [("marvin-storage-s3", "0.1.0", "0.2.0")]


def test_an_unreachable_repository_leaves_the_others_checked(db_session, installed):
    http = _GitHub({"InnerOpen/marvin-storage-s3": ["v0.3.0"], "InnerOpen/marvin-ai-openai": 403})
    assert pu.refresh(db_session, http)["latest"] == {"marvin-storage-s3": "v0.3.0"}


def test_a_fresh_cache_is_not_refreshed_and_a_stale_one_is(db_session, installed, monkeypatch):
    started = []
    monkeypatch.setattr(pu, "_refresh_in_background", lambda: started.append(1))
    svc = PlatformSettingsService(db_session)
    svc.set(pu.CACHE_KEY, {"checked_at": datetime.now(UTC).isoformat(), "latest": {}})
    pu.available_updates(db_session)
    assert started == []
    old = datetime.now(UTC) - timedelta(hours=pu.REFRESH_HOURS + 1)
    svc.set(pu.CACHE_KEY, {"checked_at": old.isoformat(), "latest": {}})
    pu.available_updates(db_session)
    assert started == [1]
