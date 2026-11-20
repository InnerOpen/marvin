"""Migration ``405a40177415`` (``workspace_packages.sidebar``, string, not null, default ``collections``) — down, up, down, up on a
scratch SQLite, a package installed before it kept and placed under Collections."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_405a40177415_*.py"))
_spec = importlib.util.spec_from_file_location("package_sidebar_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)  # the tables at head: the column already there
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn) -> dict:
    return {c["name"]: c for c in sa.inspect(conn).get_columns("workspace_packages")}


def test_down_drops_it_and_up_places_an_installed_package_under_collections(conn):
    _run(conn, "downgrade")
    assert "sidebar" not in _columns(conn)
    conn.execute(
        sa.text(
            "INSERT INTO workspace_packages (id, group_id, slug, name, description, version, manifest)"
            " VALUES ('p1', 'g1', 'screenplay-studio', 'Screenplay Studio', '', '239', '{}')"
        )
    )

    _run(conn, "upgrade")

    column = _columns(conn)["sidebar"]
    assert column["nullable"] is False and "collections" in str(column["default"])
    assert conn.execute(sa.text("SELECT slug, version, sidebar FROM workspace_packages")).one() == ("screenplay-studio", "239", "collections")
    _run(conn, "downgrade")
    assert conn.execute(sa.text("SELECT slug FROM workspace_packages")).scalar() == "screenplay-studio"
    _run(conn, "upgrade")
    assert "sidebar" in _columns(conn)
