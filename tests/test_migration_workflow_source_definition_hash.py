"""Migration ``a4d8e1c27b63``: nullable ``source_definition_hash`` on ``workspace_automations``.

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

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_a4d8e1c27b63_*.py"))
_spec = importlib.util.spec_from_file_location("workflow_source_definition_hash_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

COLUMN = "source_definition_hash"


def _columns(conn) -> dict:
    return {c["name"]: c for c in sa.inspect(conn).get_columns("workspace_automations")}


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


def _workflow(conn) -> uuid.UUID:
    session = Session(bind=conn)
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    session.close()
    wid, sqlite = uuid.uuid4(), conn.dialect.name == "sqlite"
    conn.execute(
        sa.text("insert into workspace_automations (id, group_id, name, slug, enabled, definition) values (:i, :g, 'W', :s, :e, '{}')"),
        {"i": wid.hex if sqlite else wid, "g": gid.hex if sqlite else gid, "s": f"w-{wid.hex[:6]}", "e": False},
    )
    return wid


def test_the_column_goes_up_down_and_up_again(conn):
    wid = _workflow(conn)
    assert COLUMN not in _columns(conn)

    _run(conn, "upgrade")
    assert _columns(conn)[COLUMN]["nullable"] is True
    key = wid.hex if conn.dialect.name == "sqlite" else wid
    assert conn.execute(sa.text("select source_definition_hash from workspace_automations where id = :i"), {"i": key}).scalar() is None

    _run(conn, "downgrade")
    assert COLUMN not in _columns(conn)
    assert conn.execute(sa.text("select count(*) from workspace_automations where id = :i"), {"i": key}).scalar() == 1

    _run(conn, "upgrade")
    assert COLUMN in _columns(conn)
