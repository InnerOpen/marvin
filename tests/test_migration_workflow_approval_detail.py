"""Migration ``a4d9e2c7b318`` (``workflow_approvals.detail``, nullable text: the whole of a long question, folded away under
its short message) — down, up, down, up on a scratch SQLite."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

TABLE = "workflow_approvals"
_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_a4d9e2c7b318_*.py"))
_spec = importlib.util.spec_from_file_location("workflow_approval_detail_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)  # the table at head: detail already there
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn) -> dict:
    return {c["name"]: c["nullable"] for c in sa.inspect(conn).get_columns(TABLE)}


def test_down_drops_detail_and_up_brings_it_back_nullable(conn):
    _run(conn, "downgrade")
    assert "detail" not in _columns(conn)

    _run(conn, "upgrade")

    assert _columns(conn)["detail"] is True
    _run(conn, "downgrade")
    _run(conn, "upgrade")
    assert _columns(conn)["detail"] is True and _columns(conn)["message"] is False  # the rest of the table is as it was
