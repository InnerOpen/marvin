"""Write a backup run into Marvin's database (``backup_runs``), from the backup job itself.

The job runs beside the live backend and must not build Marvin's settings or open the database through
SQLAlchemy (see ``engine``), so this is one plain DB-API ``INSERT`` into the job's own database: Postgres
through ``psycopg2`` with the POSTGRES_* connection the job already has for ``pg_dump``, or SQLite at
``BACKUP_DATA_DIR/marvin.db`` (the data volume the job mounts; WAL lets it write while the backend runs).
The backend reads the rows for Admin → Backup health, sends ``backup_completed`` / ``backup_failed`` from
them, and notices a target that stops writing them (``services/backup_health``).

Recording never decides the job's outcome: when the database can't be reached (or isn't migrated yet) the
run is logged as unrecorded and the job exits as it would have, so the backend sees the target as overdue
instead. Nothing recorded is a credential: the target's non-secret settings, its ``describe()``, counts,
and an error summary scrubbed of every credential-like value in the environment.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("marvin.backup")

TABLE = "backup_runs"
DB_NAME = "marvin.db"
CONNECT_TIMEOUT = 10  # seconds
SQLITE_BUSY_TIMEOUT = 30  # seconds: the backend may hold the write lock for a moment

# Columns this module writes, in order. tests/test_backup_health.py checks they match the model.
COLUMNS = (
    "id",
    "target_name",
    "target_type",
    "status",
    "started_at",
    "finished_at",
    "duration_seconds",
    "schedule",
    "time_zone",
    "keep_hourly",
    "keep_daily",
    "keep_weekly",
    "location",
    "settings_json",
    "db_engine",
    "db_key",
    "db_bytes",
    "db_gz_bytes",
    "config_items",
    "assets_uploaded",
    "assets_uploaded_bytes",
    "assets_unchanged",
    "pruned",
    "failures",
    "error_summary",
    "host",
    "created_at",
    "update_at",
)


@dataclass
class RunRecord:
    """One run, as the job knows it. ``status``: ok, partial (the database was backed up, another step
    failed) or failed (it wasn't, or the target couldn't be opened)."""

    target_name: str
    target_type: str
    status: str
    started_at: datetime
    finished_at: datetime
    schedule: str | None = None
    time_zone: str | None = None
    retention: tuple[int, int, int] | None = None
    location: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    db_engine: str | None = None
    db_key: str | None = None
    db_bytes: int | None = None
    db_gz_bytes: int | None = None
    config_items: int | None = None
    assets_uploaded: int | None = None
    assets_uploaded_bytes: int | None = None
    assets_unchanged: int | None = None
    pruned: int | None = None
    failures: int = 0
    error_summary: str | None = None
    host: str | None = None

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())


def status_of(db_backed_up: bool, failures: int) -> str:
    if not db_backed_up:
        return "failed"
    return "partial" if failures else "ok"


def schedule_from_env(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    """(BACKUP_SCHEDULE, BACKUP_TIME_ZONE): what the chart says the CronJob runs on."""
    return (env.get("BACKUP_SCHEDULE") or "").strip() or None, (env.get("BACKUP_TIME_ZONE") or "").strip() or None


def target_settings(slug: str, env: Mapping[str, Any]) -> dict[str, Any]:
    """The target's declared settings as this job reads them, minus every secret and credential (an
    access key id included): what Admin → Storage shows for a target the backend has no settings for."""
    from marvin_integration_sdk.storage import read_config

    from marvin.services.storage import registry
    from marvin.services.storage.healthcheck import is_credential_name

    try:
        target_cls = registry.get_plugin(slug, needs="target").target
        declared = tuple(target_cls.settings)
        values = read_config(declared, env)
    except Exception:  # unknown slug, missing settings: the run record says why elsewhere
        return {}
    shown = {s.env for s in declared if not s.secret and not is_credential_name(s.env)}
    out = {k: v for k, v in values.items() if k in shown and v not in (None, "")}
    if env.get("BACKUP_PREFIX"):
        out["BACKUP_PREFIX"] = env["BACKUP_PREFIX"]
    return out


# --------------------------------------------------------------------------------------------------
# Writing the row
# --------------------------------------------------------------------------------------------------


def _naive(dt: datetime) -> datetime:
    return (dt.astimezone(UTC) if dt.tzinfo else dt).replace(tzinfo=None)


def _sqlite_time(dt: datetime) -> str:
    # SQLAlchemy's SQLite DateTime storage format, so the backend reads the value back as a datetime.
    return _naive(dt).strftime("%Y-%m-%d %H:%M:%S.%f")


def _values(record: RunRecord, dialect: str, now: datetime) -> tuple[Any, ...]:
    run_id = uuid.uuid4()
    when = _sqlite_time if dialect == "sqlite" else _naive
    hourly, daily, weekly = record.retention or (None, None, None)
    row = {
        "id": f"{run_id.int:032x}" if dialect == "sqlite" else str(run_id),  # GUID: CHAR(32) hex / native UUID
        "target_name": record.target_name[:63],
        "target_type": record.target_type[:40],
        "status": record.status,
        "started_at": when(record.started_at),
        "finished_at": when(record.finished_at),
        "duration_seconds": round(record.duration_seconds, 3),
        "schedule": (record.schedule or None) and record.schedule[:64],
        "time_zone": (record.time_zone or None) and record.time_zone[:64],
        "keep_hourly": hourly,
        "keep_daily": daily,
        "keep_weekly": weekly,
        "location": (record.location or None) and record.location[:255],
        "settings_json": json.dumps(record.settings) if record.settings else None,
        "db_engine": record.db_engine,
        "db_key": (record.db_key or None) and record.db_key[:255],
        "db_bytes": record.db_bytes,
        "db_gz_bytes": record.db_gz_bytes,
        "config_items": record.config_items,
        "assets_uploaded": record.assets_uploaded,
        "assets_uploaded_bytes": record.assets_uploaded_bytes,
        "assets_unchanged": record.assets_unchanged,
        "pruned": record.pruned,
        "failures": record.failures,
        "error_summary": record.error_summary,
        "host": (record.host or None) and record.host[:63],
        "created_at": when(now),
        "update_at": when(now),
    }
    return tuple(row[c] for c in COLUMNS)


def _insert_sql(placeholder: str) -> str:
    return f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join([placeholder] * len(COLUMNS))})"


def _write_sqlite(path: Path, values: tuple[Any, ...]) -> None:
    if not path.is_file():
        # Never create a database: a missing file means the wrong directory (or a backend that never ran).
        raise FileNotFoundError(f"{path} not found")
    conn = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT)
    try:
        with conn:
            conn.execute(_insert_sql("?"), values)
    finally:
        conn.close()


def _write_postgres(pg_env: Mapping[str, str], values: tuple[Any, ...]) -> None:
    import psycopg2  # the backend image's postgres group; imported only on Postgres installs

    conn = psycopg2.connect(
        host=pg_env.get("PGHOST"),
        port=pg_env.get("PGPORT") or None,
        user=pg_env.get("PGUSER"),
        password=pg_env.get("PGPASSWORD"),
        dbname=pg_env.get("PGDATABASE"),
        connect_timeout=CONNECT_TIMEOUT,
        application_name="marvin-backup",
    )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(_insert_sql("%s"), values)
    finally:
        conn.close()


def record_run(record: RunRecord, env: Mapping[str, str] | None = None, now: datetime | None = None) -> bool:
    """Insert ``record`` into ``backup_runs``. True when written; False (logged, never raised) otherwise."""
    from .engine import pg_env_from

    env = dict(os.environ if env is None else env)
    engine = (env.get("BACKUP_DB_ENGINE") or env.get("DB_ENGINE") or "sqlite").lower()
    record.host = record.host or env.get("HOSTNAME") or socket.gethostname()
    now = now or datetime.now(UTC)
    try:
        if engine == "postgres":
            pg_env = pg_env_from(env)
            if not all(pg_env.get(k) for k in ("PGHOST", "PGUSER", "PGDATABASE")):
                raise RuntimeError("POSTGRES_SERVER/POSTGRES_USER/POSTGRES_DB not set")
            _write_postgres(pg_env, _values(record, "postgres", now))
        elif engine == "sqlite":
            data_dir = Path(env.get("BACKUP_DATA_DIR") or "/app/data")
            _write_sqlite(data_dir / DB_NAME, _values(record, "sqlite", now))
        else:
            raise RuntimeError(f"unknown DB engine {engine!r}")
    except Exception as exc:
        # The message names the table or the connection problem; libpq never echoes the password.
        log.error(
            "backup[%s]: run NOT recorded in the database (%s: %s); Marvin will see this target as overdue",
            record.target_name,
            type(exc).__name__,
            exc,
        )
        return False
    log.info("backup[%s]: run recorded (%s)", record.target_name, record.status)
    return True
