"""Backup key naming and retention — the layout the old ``scripts/offsite_backup.py`` wrote, so a target carries on
the history it left.

    postgres/marvin-<UTC YYYYmmddTHHMMSSZ>.dump         pg_dump --format=custom
    config/marvin-config-<UTC YYYYmmddTHHMMSSZ>.tar.gz  .secret, scheduler_state.json, templates/
    assets/<storage key>                                incremental mirror, never deleted
    sqlite/marvin-<UTC YYYYmmddTHHMMSSZ>.db.gz          LEGACY: consistent SQLite snapshot (gzip)

The ``sqlite/`` family is legacy (SQLite was retired): the engine never writes it and cannot restore it, but
backups that still sit on NAS and R2 targets must keep listing, parsing a timestamp and aging out under the
retention, so the key shape stays known here (``DB_PREFIX``, ``db_key``, ``key_timestamp``). To bring one over,
see ``marvin.scripts.sqlite_to_postgres`` and docs/manual/postgres.md.

Keeping the layout means a target can read and prune the history the old script left behind.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DB_PREFIX = "sqlite/"  # legacy family: listed and pruned, never written
PG_PREFIX = "postgres/"
CONFIG_PREFIX = "config/"
ASSETS_PREFIX = "assets/"
BUNDLES_PREFIX = "bundles/"
TS_FORMAT = "%Y%m%dT%H%M%SZ"

# The keys the engine names (and so may prune): each family with its own extension.
_KEY_EXT = {"sqlite/marvin-": ".db.gz", "postgres/marvin-": ".dump", "config/marvin-config-": ".tar.gz"}
_STAMPED_KEY = re.compile(
    r"^(?P<family>sqlite/marvin-|postgres/marvin-|config/marvin-config-)(?P<ts>\d{8}T\d{6}Z)(?P<ext>\.db\.gz|\.dump|\.tar\.gz)$"
)


# A workspace backup bundle as Marvin names it (repos/seed/workspace_exporter.py): `<slug>-backup-<date>-<token>.zip`,
# or `-scheduled-<token>` from the create_workspace_bundles task. Only these are copied to `bundles/` and pruned.
_BUNDLE_NAME = re.compile(r"^(?P<slug>[^/]+?)-backup-(?P<date>\d{4}-\d{2}-\d{2})-(?:[a-z]+-)?[0-9a-f]{16}\.zip$")


class BackupError(Exception):
    """A step failed; the message is safe to log (it never carries credentials)."""


def stamp(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime(TS_FORMAT)


def db_key(ts: datetime) -> str:
    """A legacy `sqlite/` key. The engine no longer writes these; kept to name the family (tests, tooling)."""
    return f"{DB_PREFIX}marvin-{stamp(ts)}.db.gz"


def pg_key(ts: datetime) -> str:
    return f"{PG_PREFIX}marvin-{stamp(ts)}.dump"


def config_key(ts: datetime) -> str:
    return f"{CONFIG_PREFIX}marvin-config-{stamp(ts)}.tar.gz"


def asset_key(storage_key: str) -> str:
    return ASSETS_PREFIX + storage_key


def bundle_key(filename: str) -> str | None:
    """`bundles/<workspace>/<filename>` for a bundle Marvin named, else None (not ours to copy)."""
    m = _BUNDLE_NAME.match(filename)
    return f"{BUNDLES_PREFIX}{m['slug']}/{filename}" if m else None


def expired_bundles(keys: Iterable[str], keep: int) -> list[str]:
    """Bundle keys beyond the newest `keep` of each workspace, by the date in the name. Keys the engine did not
    name are never expired."""
    by_workspace: dict[str, list[tuple[str, str]]] = {}
    for key in keys:
        if not key.startswith(BUNDLES_PREFIX):
            continue
        folder, _, filename = key[len(BUNDLES_PREFIX) :].partition("/")
        m = _BUNDLE_NAME.match(filename)
        if m and m["slug"] == folder:
            by_workspace.setdefault(folder, []).append((m["date"], key))
    expired = []
    for bundles in by_workspace.values():
        expired += [key for _, key in sorted(bundles, reverse=True)[keep:]]
    return sorted(expired)


def key_timestamp(key: str) -> datetime | None:
    """The UTC timestamp a `sqlite/`, `postgres/` or `config/` key was named with, or None for any other key."""
    m = _STAMPED_KEY.match(key)
    if not m or _KEY_EXT[m["family"]] != m["ext"]:
        return None
    return datetime.strptime(m["ts"], TS_FORMAT).replace(tzinfo=UTC)


@dataclass(frozen=True)
class Retention:
    """How many periods a target keeps (per target, admin-configurable): the newest backup of each of the
    last ``hourly`` hours, ``daily`` days and ``weekly`` ISO weeks that have one. The default is "30 days,
    hourly for the last two". ``hourly`` applies to database backups (``postgres/``, ``sqlite/``), not
    the config archive; 0 turns the hourly or weekly rule off, and ``daily`` stays >= 1 so a run never
    prunes the backup it just made. Same knobs as ``offsite_backup`` (BACKUP_KEEP_*), other defaults."""

    hourly: int = 48
    daily: int = 30
    weekly: int = 0
    bundles: int = 14
    """Workspace backup bundles kept per workspace under `bundles/`; 0 = don't copy bundles to this target."""

    def __post_init__(self) -> None:
        if self.daily < 1 or self.hourly < 0 or self.weekly < 0 or self.bundles < 0:
            raise BackupError(f"retention needs daily >= 1 and hourly, weekly, bundles >= 0, not {self}")

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> Retention:
        counts = {}
        for name in ("hourly", "daily", "weekly", "bundles"):
            var = f"BACKUP_KEEP_{name.upper()}"
            raw = str(env.get(var) or "").strip()
            if not raw:
                continue
            if not raw.isdecimal():
                raise BackupError(f"{var} must be a whole number >= 0, not {raw!r}")
            counts[name] = int(raw)
        return cls(**counts)

    def for_prefix(self, prefix: str) -> tuple[int, int, int]:
        """(hourly, daily, weekly) for one key family."""
        return (self.hourly if prefix in (PG_PREFIX, DB_PREFIX) else 0), self.daily, self.weekly


def select_retained(keys: Iterable[str], keep_daily: int, keep_weekly: int, keep_hourly: int = 0) -> set[str]:
    """Keys to keep: the newest per UTC hour for the newest `keep_hourly` hours that have a backup, the
    newest per UTC day for the newest `keep_daily` days that have one, plus the newest per ISO week for
    the newest `keep_weekly` weeks. Counting periods that *have* a backup (not calendar periods back
    from now) means a gap in backups never empties the target."""
    stamped = sorted(((ts, k) for k in keys if (ts := key_timestamp(k)) is not None), reverse=True)
    newest: dict[str, dict[Any, str]] = {"hour": {}, "day": {}, "week": {}}
    for ts, key in stamped:  # newest first, so the first key seen per period is the newest
        newest["hour"].setdefault((ts.date(), ts.hour), key)
        newest["day"].setdefault(ts.date(), key)
        newest["week"].setdefault(ts.isocalendar()[:2], key)
    keep = set(list(newest["hour"].values())[:keep_hourly])
    keep |= set(list(newest["day"].values())[:keep_daily])
    return keep | set(list(newest["week"].values())[:keep_weekly])


def select_expired(keys: Iterable[str], retention: Retention, prefix: str) -> list[str]:
    """Stamped keys of ``prefix`` outside the retention set. Keys the engine did not name are never expired."""
    keys = [k for k in keys if k.startswith(prefix)]
    hourly, daily, weekly = retention.for_prefix(prefix)
    keep = select_retained(keys, daily, weekly, hourly)
    return sorted(k for k in keys if key_timestamp(k) is not None and k not in keep)
