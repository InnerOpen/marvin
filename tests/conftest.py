import contextlib
import os
from collections.abc import Generator

from pytest import MonkeyPatch, fixture

mp = MonkeyPatch()
mp.setenv("PRODUCTION", "False")  # Set to False for testing (enables debug handlers)
mp.setenv("TESTING", "True")
mp.setenv("MEDIA_EMBEDS_FETCH_ENABLED", "False")  # no test may reach a media provider (oEmbed) over the network

# The suite defaults to SQLite, matching the app's own default, so a checkout whose .env points at a
# real Postgres dev database doesn't become the target of a schema-dropping test run. This must run
# before marvin.core.config is imported, since that calls dotenv.load_dotenv() to fold .env into the
# environment. Only an already-exported DB_ENGINE wins, keeping `DB_ENGINE=postgres` available as an
# opt-in (CI uses it against POSTGRES_DB=marvin_test) — see the guard in _create_test_schema, which
# requires the target to be a test database. This covers a direct `pytest`; the Taskfile applies the
# same default to `task py:test`, which needs its own because its `dotenv:` exports .env for us.
if "DB_ENGINE" not in os.environ:
    mp.setenv("DB_ENGINE", "sqlite")
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from marvin.app import app
from marvin.db.db_setup import engine, generate_session
from marvin.db.models import SqlAlchemyBase


@fixture(scope="session", autouse=True)
def _create_test_schema() -> Generator[None, None, None]:
    """Build the schema on the empty test database once per session, via migrations.

    The test config points at a separate, unmigrated test data dir. We can't use
    create_all — the models declare JSONB (postgres) which SQLite can't compile — so
    we run the Alembic migrations, which use sqlite-compatible sa.JSON(). Any partial
    tables from an earlier run are dropped first for a clean slate.
    """
    from alembic import command
    from alembic.config import Config

    # Safety: this fixture DROPS the entire schema. On SQLite that's an isolated per-run test file,
    # but the Postgres provider uses POSTGRES_DB from the environment verbatim — a misconfigured .env
    # (e.g. DB_ENGINE=postgres pointing at a real dev/prod DB) would wipe it. Refuse unless the target
    # is clearly a test database.
    if engine.dialect.name == "postgresql" and "test" not in (engine.url.database or "").lower():
        raise RuntimeError(
            f"Refusing to run the test suite against Postgres database '{engine.url.database}': it does "
            "not look like a test database, and the suite drops the entire schema on setup. Point tests "
            "at a dedicated DB (e.g. POSTGRES_DB=marvin_test)."
        )

    with contextlib.suppress(Exception):
        SqlAlchemyBase.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        # Alembic's batch_alter_table temp tables (_alembic_tmp_*) aren't model-known, so drop_all
        # misses them; a partial migration can leave one and wedge the next run's batch op with
        # "table _alembic_tmp_X already exists". Sweep them for a truly clean slate.
        if conn.dialect.name == "sqlite":
            leftovers = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_alembic_tmp_%'").all()
            for (name,) in leftovers:
                conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{name}"')
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    cfg = Config(str(Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


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
