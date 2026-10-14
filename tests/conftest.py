import contextlib
import os
from collections.abc import Generator

from pytest import MonkeyPatch, fixture

mp = MonkeyPatch()
mp.setenv("PRODUCTION", "False")  # Set to False for testing (enables debug handlers)
mp.setenv("TESTING", "True")
mp.setenv("MEDIA_EMBEDS_FETCH_ENABLED", "False")  # no test may reach a media provider (oEmbed) over the network

# The suite runs on Postgres (SQLite was retired 2026-10-13): by default the dev container
# (docker/docker-compose.dev.yml, 127.0.0.1:5434) and its own `marvin_test` database, made below if missing — so a
# checkout whose .env points at the real dev database never becomes the target of a schema-dropping test run. This
# must run before marvin.core.config is imported, since that folds .env into the environment; only already-exported
# POSTGRES_* win (CI exports its service container's). The guard in _create_test_schema still requires a database
# whose name says "test".
mp.setenv("DB_ENGINE", "postgres")
for _key, _default in (("POSTGRES_SERVER", "127.0.0.1"), ("POSTGRES_PORT", "5434"), ("POSTGRES_USER", "default"), ("POSTGRES_PASSWORD", "default")):
    if _key not in os.environ:
        mp.setenv(_key, _default)
if "test" not in os.environ.get("POSTGRES_DB", "").lower():
    mp.setenv("POSTGRES_DB", "marvin_test")


def _ensure_test_database() -> None:
    """Create the test database on the server if it isn't there yet (a fresh dev container has only `marvin`)."""
    import psycopg2
    from psycopg2 import sql

    name = os.environ["POSTGRES_DB"]
    conn = psycopg2.connect(
        host=os.environ["POSTGRES_SERVER"], port=os.environ["POSTGRES_PORT"], user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], dbname="postgres",
    )  # fmt: skip
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        conn.close()


_ensure_test_database()
from pathlib import Path

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

    with contextlib.suppress(Exception):
        SqlAlchemyBase.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    cfg = Config(str(Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@fixture(autouse=True)
def _no_plugin_update_check(monkeypatch) -> None:
    """Admin → Overview starts a background GitHub tag check when its cache is stale; no test should reach GitHub."""
    from marvin.services import plugin_updates

    monkeypatch.setattr(plugin_updates, "_refresh_in_background", lambda: None)


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
