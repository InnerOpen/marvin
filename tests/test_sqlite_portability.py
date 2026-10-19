"""What makes the schema and the models behave the same on SQLite as on Postgres.

AwareDateTime (aware UTC out of both), the SQLite-only `String(N)` check, VACUUM leaving no write-ahead log, and the
whole migration chain going up, down and up on a SQLite file. Each runs on whichever engine the suite is on, except
where it says it only means one.
"""

import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import DataError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from marvin.db import db_setup, length_check
from marvin.db.models._model_utils.datetime import AwareDateTime
from marvin.db.models.platform.scheduler_lock import SchedulerLockModel

on_sqlite = pytest.mark.skipif(db_setup.engine.dialect.name != "sqlite", reason="only SQLite needs this: Postgres has no such behaviour")
ALEMBIC_INI = Path(db_setup.__file__).resolve().parents[1] / "alembic.ini"


# ── AwareDateTime ───────────────────────────────────────────────────────────────────────────────────────────────


def test_an_aware_datetime_column_returns_aware_utc(db_session):
    """The scheduler lease is compared with an aware `now`; SQLite used to hand back a naive datetime and the
    comparison raised TypeError."""
    expires = datetime(2026, 10, 18, 12, 0, tzinfo=timezone(timedelta(hours=-4)))  # 16:00 UTC
    lock_id = f"test-{uuid.uuid4().hex[:8]}"
    db_session.add(SchedulerLockModel(id=lock_id, holder_id="a", expires_at=expires, acquired_at=expires))
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(SchedulerLockModel, lock_id)
    try:
        assert row.expires_at.tzinfo is not None
        assert row.expires_at == expires  # the same instant
        assert row.expires_at - datetime.now(UTC)  # comparable with an aware now
        assert row.expires_at.astimezone(UTC).hour == 16
    finally:
        db_session.delete(row)
        db_session.commit()


def test_a_naive_value_is_taken_as_utc_and_none_stays_none():
    kind = AwareDateTime()
    sqlite = sa.dialects.sqlite.dialect()
    assert kind.process_bind_param(None, sqlite) is None and kind.process_result_value(None, sqlite) is None
    naive = datetime(2026, 10, 18, 12, 0)  # noqa: DTZ001 — naive on purpose
    assert kind.process_bind_param(naive, sqlite) == naive
    assert kind.process_result_value(naive, sqlite) == naive.replace(tzinfo=UTC)
    aware = datetime(2026, 10, 18, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert kind.process_bind_param(aware, sqlite) == datetime(2026, 10, 18, 12, 0)  # noqa: DTZ001
    assert kind.process_bind_param(aware, sa.dialects.postgresql.dialect()) == aware  # Postgres converts for itself


def test_it_is_still_timestamptz_on_postgres():
    """No migration: the DDL for a Postgres database is the one `DateTime(timezone=True)` always gave."""
    ddl = str(sa.schema.CreateTable(SchedulerLockModel.__table__).compile(dialect=sa.dialects.postgresql.dialect()))
    assert "expires_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl


# ── String(N) on SQLite ─────────────────────────────────────────────────────────────────────────────────────────


class _Base(DeclarativeBase):
    pass


class _Short(_Base):
    __tablename__ = "short"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(5))
    note: Mapped[str | None] = mapped_column(sa.Text)
    kind: Mapped[str | None] = mapped_column(sa.Enum("a", "bb", name="short_kind", native_enum=False))


@pytest.fixture
def scratch():
    engine = sa.create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    session = Session(engine)
    event.listen(session, "before_flush", length_check.check_lengths)
    yield session
    session.close()
    engine.dispose()


def test_a_value_too_long_for_its_column_is_refused_like_postgres_refuses_it(scratch):
    scratch.add(_Short(code="toolong"))
    with pytest.raises(DataError, match=r"value too long for type character varying\(5\): short.code \(7 characters\)"):
        scratch.flush()


def test_an_update_to_a_too_long_value_is_refused_too(scratch):
    row = _Short(code="ok")
    scratch.add(row)
    scratch.flush()
    row.code = "123456"
    with pytest.raises(DataError, match="short.code"):
        scratch.flush()


def test_values_that_fit_text_columns_and_unset_ones_pass(scratch):
    scratch.add_all([_Short(code="12345", note="n" * 10_000), _Short(code="")])  # exactly N; Text has no limit
    scratch.flush()


@on_sqlite
def test_the_real_sqlite_engine_has_the_check_installed():
    assert length_check._installed  # Postgres enforces the length itself, so only a SQLite engine installs it


# ── VACUUM ──────────────────────────────────────────────────────────────────────────────────────────────────────


@on_sqlite
def test_optimize_database_folds_the_write_ahead_log_back_in(db_session):
    from marvin.services.scheduled_tasks.handlers.maintenance import OptimizeDatabaseHandler

    db_file = Path(db_setup.engine.url.database)
    summary = OptimizeDatabaseHandler().execute(SimpleNamespace(group_id=None, task_config={}), None)
    assert "→" in summary  # sizes before and after, as on Postgres
    wal = db_file.with_name(db_file.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


# ── migrations on a SQLite file ─────────────────────────────────────────────────────────────────────────────────


def _alembic(tmp_path, *args):
    env = {
        "PATH": "/usr/bin:/bin",
        "DB_ENGINE": "sqlite",
        "DB_SQLITE_PATH": str(tmp_path / "cycle.db"),
        "DATA_DIR": str(tmp_path),
        "PRODUCTION": "False",
        "TESTING": "False",
    }
    done = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args], env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, f"alembic {' '.join(args)}:\n{done.stderr[-3000:]}"


def _tables(tmp_path) -> set[str]:
    with sa.create_engine(f"sqlite:///{tmp_path / 'cycle.db'}").connect() as conn:
        return {name for (name,) in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_the_migrations_go_up_down_and_up_again_on_a_sqlite_file(tmp_path):
    _alembic(tmp_path, "upgrade", "head")
    built = _tables(tmp_path)
    assert {"users", "groups", "entries", "scheduler_lock"} <= built
    _alembic(tmp_path, "downgrade", "base")
    assert _tables(tmp_path) <= {"alembic_version"}  # nothing the migrations made is left
    _alembic(tmp_path, "upgrade", "head")
    assert _tables(tmp_path) == built
