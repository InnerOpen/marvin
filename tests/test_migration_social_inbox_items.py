"""Migration ``7c3f9a1e5b82``: ``social_inbox_items`` — up, down, up on both engines, and the table it makes is the model's.

Run on PostgreSQL (the test database; DDL is transactional, so each case rolls back) and on a scratch in-memory SQLite.
"""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.social_inbox import SocialInboxItemModel

TABLE = "social_inbox_items"
LATER_COLUMNS = {"reply_rule", "reply_text", "reply_note", "attachments"}  # added by ef911a9c1779, e2c7f4a9b815
_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_7c3f9a1e5b82_*.py"))
_spec = importlib.util.spec_from_file_location("social_inbox_items_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture(scope="module")
def sqlite_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(params=["postgres", "sqlite"])
def conn(request):
    """The database as it is at head (the table present), in a transaction rolled back after."""
    if request.param == "postgres":
        from marvin.db.db_setup import engine

        if engine.dialect.name != "postgresql":
            pytest.skip("the suite's own database is SQLite here (no transactional DDL); the scratch SQLite case covers it")
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    yield connection
    outer.rollback()
    connection.close()
    if request.param == "sqlite":  # DDL isn't rolled back there: leave the scratch database as the next case expects
        with engine.begin() as c:
            if TABLE not in sa.inspect(c).get_table_names():
                SocialInboxItemModel.__table__.create(c)


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _exists(conn) -> bool:
    return TABLE in sa.inspect(conn).get_table_names()


def _shape(conn) -> dict:
    insp = sa.inspect(conn)
    return {
        "columns": {c["name"]: c["nullable"] for c in insp.get_columns(TABLE)},
        "unique": {u["name"]: tuple(u["column_names"]) for u in insp.get_unique_constraints(TABLE)},
        "indexes": {i["name"]: tuple(i["column_names"]) for i in insp.get_indexes(TABLE) if not i.get("duplicates_constraint")},
        "foreign_keys": {
            (f["constrained_columns"][0], f["referred_table"], (f.get("options") or {}).get("ondelete")) for f in insp.get_foreign_keys(TABLE)
        },
    }


def _model_shape() -> dict:
    """What the model declares, in the same terms."""
    table = SocialInboxItemModel.__table__
    return {
        "columns": {c.name: c.nullable for c in table.columns if c.name not in LATER_COLUMNS},
        "unique": {c.name: tuple(col.name for col in c.columns) for c in table.constraints if isinstance(c, sa.UniqueConstraint)},
        "indexes": {i.name: tuple(c.name for c in i.columns) for i in table.indexes},
        "foreign_keys": {(fk.parent.name, fk.column.table.name, fk.ondelete) for fk in table.foreign_keys},
    }


def test_up_down_up_leaves_the_table_the_model_declares(conn):
    assert _exists(conn)
    _run(conn, "downgrade")
    assert not _exists(conn)
    _run(conn, "upgrade")
    assert _exists(conn)
    assert _shape(conn) == _model_shape()
    _run(conn, "downgrade")
    assert not _exists(conn)
    _run(conn, "upgrade")
    assert _exists(conn) and _shape(conn) == _model_shape()


def test_the_upgraded_table_defaults_the_status_and_enforces_one_row_per_integration_and_item(sqlite_engine):
    """Rows, on the scratch SQLite (it has no group or integration to point at, so its foreign keys (off by default there) aren't in play; Postgres's
    keys are checked by the shape test above)."""
    table = SocialInboxItemModel.__table__
    now = datetime.now(UTC)
    row = {
        "id": uuid.uuid4(), "group_id": uuid.uuid4(), "integration_id": uuid.uuid4(), "integration_slug": "i", "network": "x",
        "item_id": "c1", "kind": "comment", "text": "hi", "posted_at": now, "first_seen_at": now,
    }  # fmt: skip
    with sqlite_engine.connect() as conn:
        outer = conn.begin()
        _run(conn, "downgrade")
        _run(conn, "upgrade")
        conn.execute(sa.insert(table).values(**row))
        assert tuple(conn.execute(sa.select(table.c.status, table.c.reply_rehearsal)).one()) == ("new", False)
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.insert(table).values(**{**row, "id": uuid.uuid4()}))
        outer.rollback()
