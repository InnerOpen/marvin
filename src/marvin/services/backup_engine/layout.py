"""Backup key naming and retention, the same layout ``scripts/offsite_backup.py`` writes.

    sqlite/marvin-<UTC YYYYmmddTHHMMSSZ>.db.gz          consistent SQLite snapshot (gzip)
    postgres/marvin-<UTC YYYYmmddTHHMMSSZ>.dump         pg_dump --format=custom
    config/marvin-config-<UTC YYYYmmddTHHMMSSZ>.tar.gz  .secret, scheduler_state.json, templates/
    assets/<storage key>                                incremental mirror, never deleted

Keeping the layout means a target can read and prune the history the old script left behind.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DB_PREFIX = "sqlite/"
PG_PREFIX = "postgres/"
CONFIG_PREFIX = "config/"
ASSETS_PREFIX = "assets/"
TS_FORMAT = "%Y%m%dT%H%M%SZ"

# The keys the engine names (and so may prune): each family with its own extension.
_KEY_EXT = {"sqlite/marvin-": ".db.gz", "postgres/marvin-": ".dump", "config/marvin-config-": ".tar.gz"}
_STAMPED_KEY = re.compile(
    r"^(?P<family>sqlite/marvin-|postgres/marvin-|config/marvin-config-)(?P<ts>\d{8}T\d{6}Z)(?P<ext>\.db\.gz|\.dump|\.tar\.gz)$"
)


class BackupError(Exception):
    """A step failed; the message is safe to log (it never carries credentials)."""


def stamp(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime(TS_FORMAT)


def db_key(ts: datetime) -> str:
    return f"{DB_PREFIX}marvin-{stamp(ts)}.db.gz"


def pg_key(ts: datetime) -> str:
    return f"{PG_PREFIX}marvin-{stamp(ts)}.dump"


def config_key(ts: datetime) -> str:
    return f"{CONFIG_PREFIX}marvin-config-{stamp(ts)}.tar.gz"


def asset_key(storage_key: str) -> str:
    return ASSETS_PREFIX + storage_key


def db_prefix(engine: str) -> str:
    return PG_PREFIX if engine == "postgres" else DB_PREFIX


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

    def __post_init__(self) -> None:
        if self.daily < 1 or self.hourly < 0 or self.weekly < 0:
            raise BackupError(f"retention needs daily >= 1 and hourly, weekly >= 0, not {self}")

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> Retention:
        counts = {}
        for name in ("hourly", "daily", "weekly"):
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
