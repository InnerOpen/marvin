"""Which installed plugins have a newer release: each `marvin-*` package installed from a GitHub tag (its
direct_url.json) against the newest version tag of that repository.

The answer is cached in `platform_settings` for REFRESH_HOURS. A stale cache is refreshed in a background thread, so
Admin → Overview never waits on GitHub; the first look after a restart shows the previous answer. Picking up an
update is a Marvin release (bump the pin in pyproject's `plugins` group), so this only says one exists.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_KEY = "plugin_updates"
REFRESH_HOURS = 12
_GITHUB = re.compile(r"^https://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$")
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$")
_refreshing = threading.Lock()


@dataclass
class PluginUpdate:
    package: str
    installed: str
    latest: str
    repo: str


def _version(tag: str) -> tuple[int, ...] | None:
    m = _VERSION.match(tag or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def installed_from_github() -> dict[str, tuple[str, str]]:
    """{package: (installed version, "owner/repo")} for marvin-* packages installed from a GitHub URL."""
    import importlib.metadata as md

    found: dict[str, tuple[str, str]] = {}
    for dist in md.distributions():
        name = (dist.metadata.get("Name") or "").lower()
        if not name.startswith("marvin-") or name == "marvin":
            continue
        raw = dist.read_text("direct_url.json")
        m = _GITHUB.match((json.loads(raw).get("url") or "") if raw else "")
        if m:
            found[name] = (dist.version, f"{m.group(1)}/{m.group(2)}")
    return found


def latest_tag(repo: str, http=None) -> str | None:
    """The highest version-shaped tag of a public GitHub repository, or None."""
    import httpx

    client = http or httpx
    resp = client.get(f"https://api.github.com/repos/{repo}/tags?per_page=50", timeout=5.0, headers={"Accept": "application/vnd.github+json"})
    if resp.status_code != 200:
        return None
    tags = [t.get("name", "") for t in resp.json() if isinstance(t, dict)]
    versioned = [(v, t) for t in tags if (v := _version(t)) is not None]
    return max(versioned)[1] if versioned else None


def refresh(session, http=None) -> dict:
    """Ask GitHub for every plugin's newest tag and store the answer."""
    from marvin.services.platform_settings import PlatformSettingsService

    latest: dict[str, str] = {}
    for package, (_version_now, repo) in installed_from_github().items():
        try:
            tag = latest_tag(repo, http)
        except Exception:  # noqa: BLE001 — one unreachable repository doesn't stop the rest
            logger.debug("plugin update check failed for %s", repo, exc_info=True)
            continue
        if tag:
            latest[package] = tag
    value = {"checked_at": datetime.now(UTC).isoformat(), "latest": latest}
    PlatformSettingsService(session).set(CACHE_KEY, value)
    return value


def _refresh_in_background() -> None:
    if not _refreshing.acquire(blocking=False):
        return  # one already running

    def work():
        try:
            from marvin.db.db_setup import session_context

            with session_context() as session:
                refresh(session)
        except Exception:  # noqa: BLE001
            logger.debug("background plugin update check failed", exc_info=True)
        finally:
            _refreshing.release()

    threading.Thread(target=work, name="plugin-update-check", daemon=True).start()


def available_updates(session, *, refresh_if_stale: bool = True) -> list[PluginUpdate]:
    """Installed plugins whose repository has a higher version tag, from the cache (refreshed in the background when
    older than REFRESH_HOURS)."""
    from marvin.services.platform_settings import PlatformSettingsService

    cached = PlatformSettingsService(session).get(CACHE_KEY) or {}
    checked = cached.get("checked_at")
    stale = not checked or datetime.now(UTC) - datetime.fromisoformat(checked) > timedelta(hours=REFRESH_HOURS)
    if stale and refresh_if_stale:
        _refresh_in_background()
    updates = []
    for package, (version_now, repo) in sorted(installed_from_github().items()):
        tag = (cached.get("latest") or {}).get(package)
        newest, current = _version(tag or ""), _version(version_now)
        if newest and current and newest > current:
            updates.append(PluginUpdate(package=package, installed=version_now, latest=tag.lstrip("v"), repo=repo))
    return updates
