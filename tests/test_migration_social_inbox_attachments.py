"""Migration ``e2c7f4a9b815``: ``social_inbox_items.attachments`` (nullable JSON) — down, up, down, up on a scratch SQLite."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

TABLE = "social_inbox_items"
_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_e2c7f4a9b815_*.py"))
_spec = importlib.util.spec_from_file_location("social_inbox_attachments_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)  # the table at head: attachments already there
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn) -> dict:
    return {c["name"]: c["nullable"] for c in sa.inspect(conn).get_columns(TABLE)}


def test_down_drops_attachments_and_up_brings_it_back_nullable(conn):
    _run(conn, "downgrade")
    assert "attachments" not in _columns(conn)

    _run(conn, "upgrade")

    assert _columns(conn)["attachments"] is True
    _run(conn, "downgrade")
    _run(conn, "upgrade")
    assert _columns(conn)["attachments"] is True
