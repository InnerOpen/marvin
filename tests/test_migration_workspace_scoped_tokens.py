"""Migration ``84b33c929065``: ``long_live_tokens.group_id`` (nullable, indexed, FK to groups ON DELETE CASCADE).

Both directions are run on a scratch in-memory SQLite (the suite's other schema tests build tables from the models, which
would never run the migration). Existing tokens keep a NULL ``group_id``: they stay global.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_84b33c929065_*.py"))
_spec = importlib.util.spec_from_file_location("workspace_scoped_tokens_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    connection = engine.connect()
    yield connection
    connection.close()
    engine.dispose()


def _run(connection, step) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        step()
    connection.commit()


def _columns(connection) -> set[str]:
    return {c["name"] for c in sa.inspect(connection).get_columns("long_live_tokens")}


def test_downgrade_drops_the_column_and_upgrade_puts_it_back_with_its_index_and_cascade(conn):
    assert "group_id" in _columns(conn)  # the models already have it

    _run(conn, mig.downgrade)
    inspector = sa.inspect(conn)
    assert "group_id" not in _columns(conn)
    assert not [i for i in inspector.get_indexes("long_live_tokens") if "group_id" in i["column_names"]]

    _run(conn, mig.upgrade)
    inspector = sa.inspect(conn)
    column = next(c for c in inspector.get_columns("long_live_tokens") if c["name"] == "group_id")
    assert column["nullable"] is True
    assert any(i["column_names"] == ["group_id"] for i in inspector.get_indexes("long_live_tokens"))
    fk = next(f for f in inspector.get_foreign_keys("long_live_tokens") if f["constrained_columns"] == ["group_id"])
    assert fk["referred_table"] == "groups" and fk["options"].get("ondelete") == "CASCADE"


def test_a_token_that_existed_before_the_migration_is_still_global_after_it(conn):
    _run(conn, mig.downgrade)
    conn.execute(
        sa.text(
            "INSERT INTO users (id, username, email, full_name, password, is_superuser, platform_role, auth_method) "
            "VALUES ('u1','u','u@t.test','U','x',0,'NONE','MARVIN')"
        )
    )
    conn.execute(sa.text("INSERT INTO long_live_tokens (id, name, token_hash, enabled, user_id, created_by) VALUES ('t1','old','h',1,'u1','u1')"))
    conn.commit()

    _run(conn, mig.upgrade)

    assert conn.execute(sa.text("SELECT group_id FROM long_live_tokens WHERE id='t1'")).scalar() is None
