"""The SQLite engine: which engine an environment means, the startup guard, the pragmas and the transaction recipe.

These build their own engines on files in tmp_path and run Alembic in a subprocess, so they behave the same whichever
engine the suite itself runs on.
"""

import logging
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from marvin.core.settings.db_providers import SQLiteProvider, db_provider_factory, resolve_engine
from marvin.core.settings.settings import app_settings_constructor, guard_existing_install
from marvin.db import db_setup

ALEMBIC_INI = Path(db_setup.__file__).resolve().parents[1] / "alembic.ini"


# ── resolve_engine ──────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "sqlite"),  # a fresh install
        ({"DB_ENGINE": ""}, "sqlite"),  # empty means unset
        ({"POSTGRES_SERVER": "db"}, "postgres"),  # an install that already points at Postgres keeps it
        ({"POSTGRES_URL_OVERRIDE": "postgresql://u:p@h/db"}, "postgres"),
        ({"POSTGRES_SERVER": "   "}, "sqlite"),
        ({"POSTGRES_USER": "u", "POSTGRES_DB": "d"}, "sqlite"),  # a server is what counts
        ({"DB_ENGINE": "sqlite", "POSTGRES_SERVER": "db"}, "sqlite"),  # explicit wins
        ({"DB_ENGINE": "postgres"}, "postgres"),
        ({"DB_ENGINE": " SQLite "}, "sqlite"),
    ],
)
def test_resolve_engine(env, expected):
    assert resolve_engine(env) == expected


def test_resolve_engine_refuses_an_unknown_engine():
    with pytest.raises(ValueError, match="mysql"):
        resolve_engine({"DB_ENGINE": "mysql"})


# ── settings: the engine, the file, the guard ───────────────────────────────────────────────────────────────────


def _settings(tmp_path, monkeypatch, production=True, **env):
    for key in ("DB_ENGINE", "POSTGRES_SERVER", "POSTGRES_URL_OVERRIDE", "DB_SQLITE_PATH"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return app_settings_constructor(
        data_dir=tmp_path, production=production, env_file=tmp_path / "no.env", env_secrets=tmp_path / "no.secrets", secrets_dir=None
    )


def test_a_fresh_data_dir_defaults_to_a_sqlite_file_in_it(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    assert settings.DB_ENGINE == "sqlite"
    assert settings.DB_URL == f"sqlite:///{tmp_path / 'marvin.db'}"
    assert (tmp_path / ".secret").exists()  # the first start made it, as before


def test_db_sqlite_path_moves_the_file(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere" / "m.db"
    settings = _settings(tmp_path, monkeypatch, DB_SQLITE_PATH=str(elsewhere))
    assert settings.DB_URL == f"sqlite:///{elsewhere}"


def test_postgres_settings_win_over_the_default(tmp_path, monkeypatch):
    settings = _settings(
        tmp_path, monkeypatch, POSTGRES_SERVER="db.example", POSTGRES_PORT="5432", POSTGRES_USER="u", POSTGRES_PASSWORD="p", POSTGRES_DB="m"
    )
    assert settings.DB_ENGINE == "postgres"
    assert settings.DB_URL.startswith("postgresql+psycopg2://u:p@db.example:5432/m")


def test_a_dotenv_that_names_a_postgres_server_picks_postgres(tmp_path, monkeypatch):
    """Local dev: `.env` carries POSTGRES_* (and often DB_ENGINE=postgres); the auto rule alone is enough."""
    for key in (
        "DB_ENGINE",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_URL_OVERRIDE",
        "DB_SQLITE_PATH",
    ):
        monkeypatch.delenv(key, raising=False)  # the Postgres run exports its own: the file is what is under test
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_SERVER=127.0.0.1\nPOSTGRES_PORT=5434\nPOSTGRES_USER=default\nPOSTGRES_PASSWORD=default\nPOSTGRES_DB=marvin\n")
    settings = app_settings_constructor(data_dir=tmp_path, production=False, env_file=env_file, env_secrets=tmp_path / "no.secrets", secrets_dir=None)
    assert settings.DB_ENGINE == "postgres" and settings.DB_URL.endswith("127.0.0.1:5434/marvin")


def test_an_existing_install_with_no_database_is_refused(tmp_path, monkeypatch):
    (tmp_path / ".secret").write_text("an-earlier-run")
    with pytest.raises(RuntimeError, match=r"\.secret from an earlier run but no database"):
        _settings(tmp_path, monkeypatch)
    assert (tmp_path / ".secret").read_text() == "an-earlier-run"  # nothing was touched


def test_the_guard_passes_when_the_database_is_there_or_the_engine_was_chosen(tmp_path, monkeypatch):
    (tmp_path / ".secret").write_text("an-earlier-run")
    _settings(tmp_path, monkeypatch, DB_ENGINE="sqlite")  # explicit: the operator meant it
    (tmp_path / "marvin.db").touch()
    assert _settings(tmp_path, monkeypatch).DB_ENGINE == "sqlite"  # the file exists
    guard_existing_install(tmp_path, tmp_path / "marvin.db")


def test_the_guard_looks_where_db_sqlite_path_says(tmp_path, monkeypatch):
    (tmp_path / ".secret").write_text("an-earlier-run")
    (tmp_path / "marvin.db").touch()  # not the configured file
    with pytest.raises(RuntimeError, match="no database"):
        _settings(tmp_path, monkeypatch, DB_SQLITE_PATH=str(tmp_path / "other.db"))


def test_the_factory_builds_both_providers_and_refuses_anything_else(tmp_path, monkeypatch):
    for key, value in {"POSTGRES_SERVER": "h", "POSTGRES_PORT": "5432", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_DB": "d"}.items():
        monkeypatch.setenv(key, value)
    assert isinstance(db_provider_factory("sqlite", tmp_path, tmp_path / ".env"), SQLiteProvider)
    assert db_provider_factory("postgres", tmp_path, tmp_path / ".env").db_url.startswith("postgresql+psycopg2://")
    with pytest.raises(ValueError):
        db_provider_factory("oracle", tmp_path, tmp_path / ".env")


# ── db_setup: the version check, pragmas and the transaction recipe ─────────────────────────────────────────────


def test_the_sqlite_version_check():
    assert db_setup.check_sqlite_version((3, 35, 0)) == "3.35.0"
    assert db_setup.check_sqlite_version()  # the library running this suite is new enough
    with pytest.raises(RuntimeError, match=r"3\.34\.1 is too old.*3\.35\.0"):
        db_setup.check_sqlite_version((3, 34, 1))


@pytest.fixture
def lite(tmp_path):
    _factory, engine = db_setup.sql_global_init(f"sqlite:///{tmp_path / 'lite.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE claims (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
    yield engine
    engine.dispose()


def test_the_file_exists_as_soon_as_the_engine_does(tmp_path):
    _factory, engine = db_setup.sql_global_init(f"sqlite:///{tmp_path / 'sub' / 'fresh.db'}")
    try:
        assert (tmp_path / "sub" / "fresh.db").exists()  # the startup guard reads a missing file as a lost database
    finally:
        engine.dispose()


def test_connections_get_the_pragmas(lite):
    with lite.connect() as conn:
        pragma = lambda name: conn.exec_driver_sql(f"PRAGMA {name}").scalar()  # noqa: E731
        assert pragma("foreign_keys") == 1
        assert pragma("journal_mode") == "wal"
        assert pragma("synchronous") == 1  # NORMAL
        assert pragma("busy_timeout") == 30000


def test_a_released_savepoint_is_still_undone_by_the_outer_rollback(lite):
    """pysqlite's default begins its transaction lazily at the first write, so the SAVEPOINT taken before it was released
    into autocommit and a later rollback could not take the claim back (finding 9)."""
    with Session(lite) as session:
        nested = session.begin_nested()
        session.execute(sa.text("INSERT INTO claims (name) VALUES ('once')"))
        nested.commit()  # RELEASE
        session.rollback()
    with lite.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM claims").scalar() == 0


def test_a_failed_nested_block_rolls_back_only_itself(lite):
    with Session(lite) as session:
        session.execute(sa.text("INSERT INTO claims (name) VALUES ('kept')"))
        with pytest.raises(sa.exc.IntegrityError), session.begin_nested():
            session.execute(sa.text("INSERT INTO claims (name) VALUES ('kept')"))
        session.commit()
    with lite.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM claims").scalar() == 1


def test_begin_immediate_takes_the_write_lock_up_front(lite):
    holder = lite.connect().execution_options(**{db_setup.SQLITE_BEGIN_OPTION: "IMMEDIATE"})
    try:
        holder.exec_driver_sql("SELECT 1")  # the transaction begins here, as BEGIN IMMEDIATE
        with lite.connect() as reader:  # WAL: readers never wait for the writer
            assert reader.exec_driver_sql("SELECT count(*) FROM claims").scalar() == 0
        with lite.connect() as writer:
            writer.connection.dbapi_connection.execute("PRAGMA busy_timeout=50")  # raw: SQLAlchemy has not begun yet
            with pytest.raises(OperationalError, match="locked"):
                writer.execution_options(**{db_setup.SQLITE_BEGIN_OPTION: "IMMEDIATE"}).exec_driver_sql("SELECT 1")
    finally:
        holder.rollback()
        holder.close()


def test_an_unknown_begin_mode_is_refused(lite):
    with (
        pytest.raises(ValueError, match="DEFERRED or IMMEDIATE"),
        lite.connect().execution_options(**{db_setup.SQLITE_BEGIN_OPTION: "EXCLUSIVE"}) as conn,
    ):
        conn.exec_driver_sql("SELECT 1")


# ── Alembic runs on its own engine, without the foreign-key pragma ──────────────────────────────────────────────


def test_alembic_migrates_with_foreign_keys_off(tmp_path):
    """alembic/env.py builds its own engine on purpose: a batch_alter_table rebuild drops and recreates a table, and
    with foreign keys enforced that cascade-deletes every child row. The app's engine turns them on, so env.py must
    never reuse it."""
    script = textwrap.dedent(
        """
        import sys
        import sqlalchemy as sa

        seen = []
        orig = sa.engine_from_config

        def wrapped(*args, **kwargs):
            engine = orig(*args, **kwargs)

            @sa.event.listens_for(engine, "connect")
            def _seen(dbapi_conn, record):
                seen.append(dbapi_conn.execute("PRAGMA foreign_keys").fetchone()[0])

            return engine

        sa.engine_from_config = wrapped
        from alembic.config import main

        main(argv=["-c", sys.argv[1], "upgrade", "head"])
        print("FOREIGN_KEYS", seen)
        """
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "DB_ENGINE": "sqlite",
        "DB_SQLITE_PATH": str(tmp_path / "migrated.db"),
        "DATA_DIR": str(tmp_path),
        "PRODUCTION": "False",
        "TESTING": "False",
    }
    done = subprocess.run([sys.executable, "-c", script, str(ALEMBIC_INI)], env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "FOREIGN_KEYS [0]" in done.stdout, done.stdout[-500:]


# ── Stage 3: the write lock and the watchdog ────────────────────────────────────────────────────────────────────


def test_begin_write_holds_the_write_lock_until_the_session_ends_its_transaction(lite):
    from marvin.db.locking import begin_write

    with Session(lite) as session:
        begin_write(session)
        rival = lite.raw_connection()
        try:
            rival.driver_connection.execute("PRAGMA busy_timeout=50")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                rival.driver_connection.execute("BEGIN IMMEDIATE")  # the lock is taken from the first statement on
            session.rollback()
            rival.driver_connection.execute("BEGIN IMMEDIATE")  # released
            rival.driver_connection.execute("ROLLBACK")
        finally:
            rival.close()


def test_begin_write_commits_what_the_session_holds_and_then_takes_the_lock(lite):
    from marvin.db.locking import begin_write

    with Session(lite) as session:
        session.execute(sa.text("INSERT INTO claims (name) VALUES ('before')"))
        begin_write(session)
        with lite.connect() as other:  # committed: another connection sees it
            assert other.exec_driver_sql("SELECT count(*) FROM claims").scalar() == 1
        session.execute(sa.text("INSERT INTO claims (name) VALUES ('after')"))
        session.commit()


def test_a_competing_writer_waits_for_begin_write_instead_of_failing(lite):
    from marvin.db.locking import begin_write

    finished = []

    def rival():
        with Session(lite) as other:
            begin_write(other)  # waits on busy_timeout for the holder, not SQLITE_BUSY
            other.execute(sa.text("INSERT INTO claims (name) VALUES ('rival')"))
            other.commit()
            finished.append(time.monotonic())

    with Session(lite) as holder:
        begin_write(holder)
        thread = threading.Thread(target=rival)
        thread.start()
        time.sleep(0.3)
        assert not finished  # still waiting on the holder's lock
        holder.execute(sa.text("INSERT INTO claims (name) VALUES ('holder')"))
        holder.commit()
        released = time.monotonic()
    thread.join(timeout=10)
    assert finished and finished[0] >= released
    with lite.connect() as conn:
        assert conn.exec_driver_sql("SELECT name FROM claims ORDER BY id").scalars().all() == ["holder", "rival"]


def test_begin_write_does_nothing_on_postgres():
    from marvin.db.locking import begin_write

    class Session_:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def __getattr__(self, name):  # any other call would be a bug
            raise AssertionError(f"begin_write touched the session: {name}")

    begin_write(Session_())  # type: ignore[arg-type]


def test_a_write_transaction_held_open_too_long_is_reported_with_where_it_is_stuck(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(db_setup.settings, "DB_SQLITE_WRITE_WARN_SECONDS", 0.2)
    _factory, engine = db_setup.sql_global_init(f"sqlite:///{tmp_path / 'slow.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        caplog.set_level(logging.WARNING, logger="marvin.db.locking")

        with engine.begin() as conn:  # quick: nothing to say
            conn.exec_driver_sql("INSERT INTO t DEFAULT VALUES")
        time.sleep(0.5)
        assert "write transaction open" not in caplog.text

        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO t DEFAULT VALUES")
            slow_call = time.sleep  # stands in for the LLM / HTTP call a session must not be held across
            slow_call(0.8)
        assert caplog.text.count("write transaction open") == 1  # once per transaction
        assert "INSERT INTO t DEFAULT VALUES" in caplog.text and "slow_call" in caplog.text
        assert "test_a_write_transaction_held_open_too_long" in caplog.text  # where the thread was
    finally:
        engine.dispose()


def test_a_read_only_transaction_is_never_reported(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(db_setup.settings, "DB_SQLITE_WRITE_WARN_SECONDS", 0.1)
    _factory, engine = db_setup.sql_global_init(f"sqlite:///{tmp_path / 'read.db'}")
    try:
        caplog.set_level(logging.WARNING, logger="marvin.db.locking")
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
            time.sleep(0.4)
        assert "write transaction open" not in caplog.text
    finally:
        engine.dispose()
