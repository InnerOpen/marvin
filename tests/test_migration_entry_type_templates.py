"""Migration ``4b537ff0c66a`` (``entry_types.templates_json``, nullable JSON: the type's entry templates) — down, up, down,
up on a scratch SQLite, with a type's row kept throughout."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

TABLE = "entry_types"
_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_4b537ff0c66a_*.py"))
_spec = importlib.util.spec_from_file_location("entry_type_templates_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)  # the table at head: templates_json already there
    with engine.connect() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO entry_types (id, name, slug, sort_order, is_system, is_rendered, schema_json) "
                "VALUES ('a', 'Artwork', 'artwork', 0, 0, 0, '{}')"
            )
        )
        yield connection
    engine.dispose()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn) -> dict:
    return {c["name"]: c["nullable"] for c in sa.inspect(conn).get_columns(TABLE)}


def test_down_drops_templates_and_up_brings_them_back_nullable(conn):
    _run(conn, "downgrade")
    assert "templates_json" not in _columns(conn)
    _run(conn, "upgrade")
    assert _columns(conn)["templates_json"] is True
    _run(conn, "downgrade")
    _run(conn, "upgrade")
    assert _columns(conn)["templates_json"] is True
    assert conn.execute(sa.text("SELECT slug, templates_json FROM entry_types")).all() == [("artwork", None)]  # the type kept, no templates
