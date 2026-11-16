"""Migration ``b7596d29dc7c`` (``group_preferences.paid_approvals_per_day``, nullable integer; ``workflow_approvals.paid``,
boolean, false) — down, up, down, up on a scratch SQLite, an approval kept as not paid."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_b7596d29dc7c_*.py"))
_spec = importlib.util.spec_from_file_location("paid_approvals_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)  # the tables at head: the columns already there
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn, table: str) -> dict:
    return {c["name"]: c["nullable"] for c in sa.inspect(conn).get_columns(table)}


def test_down_drops_both_and_up_brings_them_back_with_an_old_approval_not_paid(conn):
    _run(conn, "downgrade")
    assert "paid" not in _columns(conn, "workflow_approvals") and "paid_approvals_per_day" not in _columns(conn, "group_preferences")
    conn.execute(
        sa.text(
            "INSERT INTO workflow_approvals (id, group_id, automation_id, step_index, target_index, message, min_role, status, expires_at)"
            " VALUES ('a1', 'g1', 'w1', 0, 0, 'Make it?', 30, 'approved', '2026-11-20 00:00:00')"
        )
    )

    _run(conn, "upgrade")

    assert _columns(conn, "workflow_approvals")["paid"] is False and _columns(conn, "group_preferences")["paid_approvals_per_day"] is True
    assert conn.execute(sa.text("SELECT paid FROM workflow_approvals")).scalar() in (0, False)
    _run(conn, "downgrade")
    _run(conn, "upgrade")
    assert "paid" in _columns(conn, "workflow_approvals")
