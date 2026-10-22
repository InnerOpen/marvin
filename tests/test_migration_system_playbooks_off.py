"""Migration ``b5e9c3a72d18``: nullable ``system_playbooks_off`` on ``workspace_ai_settings``.

Checked on both engines (PostgreSQL, the test database, rolled back after; and a scratch in-memory SQLite). The suite's database is
already at head, so each case first downgrades, then runs the migration.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.groups import Groups

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_b5e9c3a72d18_*.py"))
_spec = importlib.util.spec_from_file_location("system_playbooks_off_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

COLUMN = "system_playbooks_off"


def _columns(conn) -> dict:
    return {c["name"]: c for c in sa.inspect(conn).get_columns("workspace_ai_settings")}


def _run(conn, step: str):
    with Operations.context(MigrationContext.configure(conn)):
        return getattr(mig, step)()


@pytest.fixture
def sqlite_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(params=["postgres", "sqlite"])
def conn(request):
    """The database as it was before the migration (the column absent), in a transaction rolled back after."""
    if request.param == "postgres":
        from marvin.db.db_setup import engine

        if engine.dialect.name != "postgresql":
            pytest.skip("the suite's own database is SQLite here; the scratch SQLite case covers it")
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    if COLUMN in _columns(connection):
        _run(connection, "downgrade")
    yield connection
    outer.rollback()
    connection.close()


def _settings_row(conn) -> uuid.UUID:
    session = Session(bind=conn)
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    session.close()
    sid, sqlite = uuid.uuid4(), conn.dialect.name == "sqlite"
    conn.execute(
        sa.text(
            "insert into workspace_ai_settings (id, group_id, enabled, credential_mode, approval_mode) "
            "values (:i, :g, :e, 'platform', 'suggest-only')"
        ),
        {"i": sid.hex if sqlite else sid, "g": gid.hex if sqlite else gid, "e": True},
    )
    return sid


def test_the_column_goes_up_down_and_up_again(conn):
    sid = _settings_row(conn)
    assert COLUMN not in _columns(conn)

    _run(conn, "upgrade")
    assert _columns(conn)[COLUMN]["nullable"] is True
    key = sid.hex if conn.dialect.name == "sqlite" else sid
    assert conn.execute(sa.text("select system_playbooks_off from workspace_ai_settings where id = :i"), {"i": key}).scalar() is None

    _run(conn, "downgrade")
    assert COLUMN not in _columns(conn)
    assert conn.execute(sa.text("select count(*) from workspace_ai_settings where id = :i"), {"i": key}).scalar() == 1

    _run(conn, "upgrade")
    assert COLUMN in _columns(conn)
