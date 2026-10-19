import contextlib
import os
import secrets
from collections.abc import Generator
from pathlib import Path

from pytest import MonkeyPatch, fixture

mp = MonkeyPatch()
mp.setenv("PRODUCTION", "False")  # Set to False for testing (enables debug handlers)
mp.setenv("TESTING", "True")
mp.setenv("MEDIA_EMBEDS_FETCH_ENABLED", "False")  # no test may reach a media provider (oEmbed) over the network
# Marvin's built-in embedding model is a 65 MB download on first use: off, so no test fetches it; the tests that use it
# put a fake in its place (tests/test_builtin_embeddings.py).
mp.setenv("EMBEDDINGS_BUILTIN_ENABLED", "False")

# The suite runs on SQLite by default (decision 8 of tasks/sqlite-engine-plan.md): a file of its own per run under
# tests/.temp, so nothing needs to be running and parallel runs never share a database. Export DB_ENGINE=postgres to run
# it on Postgres instead: by default the dev container (docker/docker-compose.dev.yml, 127.0.0.1:5434) and its own
# `marvin_test` database, made afresh below — so a checkout whose .env points at the real dev database never becomes
# the target of a schema-dropping run (`task py:test` pins DB_ENGINE=sqlite for the same reason: it exports .env). This
# must run before marvin.core.config is imported, since that folds .env into the environment; only already-exported
# POSTGRES_* win (CI exports its service container's). The guard in _create_test_schema still requires a Postgres
# database whose name says "test".
_ENGINE = os.environ.get("DB_ENGINE", "").strip().lower() or "sqlite"
if _ENGINE not in ("sqlite", "postgres"):
    raise RuntimeError(f"DB_ENGINE={_ENGINE!r}: the suite runs on sqlite or postgres")
mp.setenv("DB_ENGINE", _ENGINE)
# Under pytest-xdist (`pytest -n auto`, `task ci`) each worker is a process with its own database: "gw0", "gw1", …
_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")

_SQLITE_TEST_FILE: Path | None = None
if _ENGINE == "sqlite":
    # A fresh file per run. An exported DB_SQLITE_PATH is honoured only when its name says "test" (the suite drops
    # the schema it finds there, so a real database must never be the target — the Postgres guard's twin).
    _exported = os.environ.get("DB_SQLITE_PATH", "")
    _SQLITE_TEST_FILE = (
        Path(_exported)
        if "test" in Path(_exported).name.lower()
        else Path(__file__).resolve().parent / ".temp" / f"marvin-test-{os.getpid()}-{secrets.token_hex(4)}.db"
    )
    if _XDIST_WORKER:  # the controller's path reaches every worker through the environment: a file each
        _SQLITE_TEST_FILE = _SQLITE_TEST_FILE.with_name(f"{_SQLITE_TEST_FILE.stem}-{_XDIST_WORKER}{_SQLITE_TEST_FILE.suffix}")
    _SQLITE_TEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    mp.setenv("DB_SQLITE_PATH", str(_SQLITE_TEST_FILE))
else:
    for _key, _default in (
        ("POSTGRES_SERVER", "127.0.0.1"),
        ("POSTGRES_PORT", "5434"),
        ("POSTGRES_USER", "default"),
        ("POSTGRES_PASSWORD", "default"),
    ):
        if _key not in os.environ:
            mp.setenv(_key, _default)
    if "test" not in os.environ.get("POSTGRES_DB", "").lower():
        mp.setenv("POSTGRES_DB", "marvin_test")
    if _XDIST_WORKER:  # a database each (made afresh below), or the workers drop each other's schema
        mp.setenv("POSTGRES_DB", f"{os.environ['POSTGRES_DB']}_{_XDIST_WORKER}")


def _fresh_test_database() -> None:
    """Start the run on an empty test database: drop it (whatever an earlier run left) and create it again.

    Dropping the database takes no per-table locks. The schema fixture's drop_all takes one per table in one transaction,
    and Postgres's lock table is shared by the whole server: twelve xdist workers each dropping ~200 tables at once ran
    it out ("out of shared memory", increase max_locks_per_transaction), and the error, suppressed there, surfaced as
    DuplicateTable when the migrations then ran on the tables still standing."""
    import psycopg2
    from psycopg2 import sql

    name = os.environ["POSTGRES_DB"]
    if "test" not in name.lower():  # the guard in _create_test_schema, before anything is dropped
        raise RuntimeError(f"refusing to recreate {name!r}: the suite only drops a database whose name says test")
    conn = psycopg2.connect(
        host=os.environ["POSTGRES_SERVER"], port=os.environ["POSTGRES_PORT"], user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], dbname="postgres",
    )  # fmt: skip
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        conn.close()


if _ENGINE == "postgres":
    _fresh_test_database()

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from marvin.app import app
from marvin.db.db_setup import engine, generate_session
from marvin.db.models import SqlAlchemyBase


@fixture(scope="session", autouse=True)
def _create_test_schema() -> Generator[None, None, None]:
    """Build the schema on the empty test database once per session, via the Alembic migrations (what a deployment
    runs), after dropping whatever an earlier run left."""
    from alembic import command
    from alembic.config import Config

    # Safety: this fixture DROPS the entire schema, and the provider uses POSTGRES_DB verbatim — a misconfigured
    # environment pointing at a real dev/prod DB would wipe it. Refuse unless the target is clearly a test database.
    if engine.dialect.name == "postgresql" and "test" not in (engine.url.database or "").lower():
        raise RuntimeError(
            f"Refusing to run the test suite against Postgres database '{engine.url.database}': it does "
            "not look like a test database, and the suite drops the entire schema on setup. Point tests "
            "at a dedicated DB (e.g. POSTGRES_DB=marvin_test)."
        )

    # A no-op on the fresh database (or SQLite file) a run normally starts on; it clears an exported DB_SQLITE_PATH. Not
    # suppressed: an error here is the real cause of whatever setup step would fail next.
    SqlAlchemyBase.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    cfg = Config(str(Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield
    _remove_sqlite_test_file()


def _remove_sqlite_test_file() -> None:
    """This run's own SQLite file (and its WAL side files) goes with it."""
    if _SQLITE_TEST_FILE is not None:
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                Path(f"{_SQLITE_TEST_FILE}{suffix}").unlink()


def pytest_unconfigure(config) -> None:
    # Under xdist the controller imports the app (which opens its file) but runs no tests, so the session fixture
    # above never removes it; a plain run has removed it already.
    _remove_sqlite_test_file()


@fixture(autouse=True)
def _no_plugin_update_check(monkeypatch) -> None:
    """Admin → Overview starts a background GitHub tag check when its cache is stale; no test should reach GitHub."""
    from marvin.services import plugin_updates

    monkeypatch.setattr(plugin_updates, "_refresh_in_background", lambda: None)


@fixture(autouse=True)
def _no_ambient_smtp(monkeypatch) -> None:
    """A developer's .env often points SMTP_* at a local Mailpit. With nothing listening on it (or a port that drops
    packets, as WSL's forwarding does) every test that sends mail waits out the 10 s SMTP timeout: a 56-minute suite.
    Tests that need SMTP set the settings they want (and fake the send); none should reach a socket by accident."""
    from marvin.core.config import get_app_settings

    settings = get_app_settings()
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
        monkeypatch.setattr(settings, name, None)


@fixture
def client() -> TestClient:
    """FastAPI test client for making API requests."""
    return TestClient(app)


@fixture
def db_session() -> Generator[Session, None, None]:
    """
    Database session fixture for tests.

    Yields a SQLAlchemy session for database operations in tests.
    Session is automatically closed after the test completes.
    """
    session = next(generate_session())
    try:
        yield session
    finally:
        session.close()
