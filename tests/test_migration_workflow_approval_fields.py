"""Migration ``fb2528af50a6`` (``workflow_approvals.fields``, ``field_values`` and ``carry``, nullable JSON: an approval's
editable boxes, what was approved, a Redo's carried text) — down, up, down, up on a scratch SQLite, a row kept."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

TABLE = "workflow_approvals"
_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_fb2528af50a6_*.py"))
_spec = importlib.util.spec_from_file_location("workflow_approval_fields_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)  # the table at head: the columns already there
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn) -> dict:
    return {c["name"]: c["nullable"] for c in sa.inspect(conn).get_columns(TABLE)}


NEW = ("fields", "field_values", "carry")


def test_down_drops_the_columns_and_up_brings_them_back_nullable_keeping_a_row(conn):
    conn.execute(
        sa.text(
            f"INSERT INTO {TABLE} (id, group_id, automation_id, step_index, target_index, message, min_role, status, expires_at)"
            " VALUES ('a1', 'g1', 'w1', 0, 0, 'Make it?', 30, 'pending', '2026-11-20 00:00:00')"
        )
    )
    _run(conn, "downgrade")
    assert not set(NEW) & set(_columns(conn))

    _run(conn, "upgrade")

    assert all(_columns(conn)[name] is True for name in NEW)
    _run(conn, "downgrade")
    _run(conn, "upgrade")
    assert all(_columns(conn)[name] is True for name in NEW) and _columns(conn)["message"] is False
    assert conn.execute(sa.text(f"SELECT message, fields FROM {TABLE}")).all() == [("Make it?", None)]
