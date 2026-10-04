"""The f7c3a9e5b2d8 data migration: the single Ask (`agent`) invocation source → `bubble` + `ask_page`.

The mapping is checked as pure functions, then the upgrade/downgrade are run against a scratch SQLite
table so the row rewrite itself is exercised (the session's test DB has no pre-split policies in it).
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import marvin.db.migration_types as mt

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_f7c3a9e5b2d8_*.py"))
_spec = importlib.util.spec_from_file_location("split_ask_sources", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_split_agent_false_switches_both_surfaces_off_and_drops_agent():
    assert mig.split_agent({"agent": False, "mcp": True}) == {"mcp": True, "bubble": False, "ask_page": False}


def test_split_agent_true_is_just_dropped():
    assert mig.split_agent({"agent": True, "editor": False}) == {"editor": False}


def test_split_leaves_a_policy_without_agent_alone():
    assert mig.split_agent({"editor": False}) is None


def test_join_folds_either_surface_off_back_into_agent_false():
    assert mig.join_surfaces({"bubble": False, "ask_page": True, "mcp": True}) == {"mcp": True, "agent": False}


def test_join_with_both_surfaces_on_drops_them():
    assert mig.join_surfaces({"bubble": True, "ask_page": True}) == {}


def test_join_leaves_a_policy_without_surfaces_alone():
    assert mig.join_surfaces({"editor": False}) is None


@pytest.fixture
def scratch():
    """An in-memory DB with just the columns the migration touches, and an alembic op bound to it."""
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    table = sa.Table(
        "workspace_ai_settings",
        meta,
        sa.Column("id", mt.GUID(), primary_key=True),
        sa.Column("invocation_sources", sa.JSON(), nullable=True),
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        original = mig.op
        mig.op = ops
        try:
            yield conn, table
        finally:
            mig.op = original


def _seed(conn, table, policies):
    ids = [uuid.uuid4() for _ in policies]
    conn.execute(table.insert(), [{"id": i, "invocation_sources": p} for i, p in zip(ids, policies, strict=True)])
    return ids


def _policies(conn, table, ids):
    rows = dict(conn.execute(sa.select(table.c.id, table.c.invocation_sources)).all())
    return [rows[i] for i in ids]


def test_upgrade_rewrites_stored_policies(scratch):
    conn, table = scratch
    ids = _seed(conn, table, [{"agent": False, "mcp": False}, {"agent": True}, {"editor": False}, None])
    mig.upgrade()
    assert _policies(conn, table, ids) == [
        {"mcp": False, "bubble": False, "ask_page": False},
        {},
        {"editor": False},
        None,
    ]


def test_downgrade_restores_agent_false(scratch):
    conn, table = scratch
    ids = _seed(conn, table, [{"bubble": False, "ask_page": False}, {"ask_page": False}, {"bubble": True}])
    mig.downgrade()
    assert _policies(conn, table, ids) == [{"agent": False}, {"agent": False}, {}]
