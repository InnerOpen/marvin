"""Migration ``a225a6254088``: ``groups.is_platform`` and its partial unique index go; the workspace that carried the
marker is recorded as ``{id, name}`` in ``platform_settings.retired_platform_workspace``; the downgrade puts the
column and index back and re-marks the recorded workspace.

Run on PostgreSQL (the test database; DDL is transactional, so each case rolls back) and on a scratch in-memory SQLite.
"""

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from marvin.db.migration_types import GUID
from marvin.db.models import SqlAlchemyBase

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_a225a6254088_*.py"))
_spec = importlib.util.spec_from_file_location("drop_groups_is_platform", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

GROUPS = sa.table(
    "groups", sa.column("id", GUID()), sa.column("name", sa.String()), sa.column("slug", sa.String()), sa.column("is_platform", sa.Boolean())
)
SETTINGS = sa.table("platform_settings", sa.column("id", GUID()), sa.column("key", sa.String()), sa.column("value_json", sa.JSON()))


@pytest.fixture(scope="module")
def sqlite_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(params=["postgres", "sqlite"])
def conn(request):
    """The database as it was before the migration (marker column and index present), in a transaction rolled back after."""
    if request.param == "postgres":
        from marvin.db.db_setup import engine

        if engine.dialect.name != "postgresql":
            pytest.skip("the suite's own database is SQLite here (no transactional DDL); the scratch SQLite case covers it")
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    if "is_platform" not in {c["name"] for c in sa.inspect(connection).get_columns("groups")}:
        connection.execute(sa.text("ALTER TABLE groups ADD COLUMN is_platform BOOLEAN NOT NULL DEFAULT false"))
        connection.execute(sa.text("CREATE UNIQUE INDEX uq_groups_is_platform ON groups (is_platform) WHERE is_platform"))
    connection.execute(sa.delete(SETTINGS).where(SETTINGS.c.key == mig.KEY))
    connection.execute(sa.update(GROUPS).values(is_platform=False))
    yield connection
    outer.rollback()
    connection.close()
    if request.param == "sqlite":  # DDL isn't rolled back there: leave the scratch database as the next case expects
        with engine.begin() as c:
            if "is_platform" not in {col["name"] for col in sa.inspect(c).get_columns("groups")}:
                c.execute(sa.text("ALTER TABLE groups ADD COLUMN is_platform BOOLEAN NOT NULL DEFAULT false"))
                c.execute(sa.text("CREATE UNIQUE INDEX uq_groups_is_platform ON groups (is_platform) WHERE is_platform"))


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _group(conn, name: str, *, marked: bool = False):
    gid = uuid.uuid4()
    conn.execute(GROUPS.insert().values(id=gid, name=f"{name}-{gid.hex[:6]}", slug=f"{name.lower()}-{gid.hex[:6]}", is_platform=marked))
    return gid, conn.execute(sa.select(GROUPS.c.name).where(GROUPS.c.id == gid)).scalar()


def _columns(conn) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns("groups")}


def _indexes(conn) -> set[str]:
    return {i["name"] for i in sa.inspect(conn).get_indexes("groups")}


def _recorded(conn):
    value = conn.execute(sa.select(SETTINGS.c.value_json).where(SETTINGS.c.key == mig.KEY)).scalar()
    return json.loads(value) if isinstance(value, str) else value


def test_upgrade_records_the_marked_workspace_and_drops_the_marker(conn):
    gid, name = _group(conn, "Marvin Admin", marked=True)
    _group(conn, "Other")
    _run(conn, "upgrade")
    assert _recorded(conn) == {"id": str(gid), "name": name}
    assert "is_platform" not in _columns(conn) and "uq_groups_is_platform" not in _indexes(conn)
    assert conn.execute(sa.select(sa.func.count()).select_from(GROUPS.c.id.table)).scalar() >= 2  # no group was touched


def test_upgrade_with_no_marked_workspace_records_nothing(conn):
    _group(conn, "Unmarked")
    _run(conn, "upgrade")
    assert _recorded(conn) is None and "is_platform" not in _columns(conn)


def test_upgrade_replaces_an_earlier_record(conn):
    conn.execute(SETTINGS.insert().values(id=uuid.uuid4(), key=mig.KEY, value_json={"id": str(uuid.uuid4()), "name": "stale"}))
    gid, name = _group(conn, "Fresh", marked=True)
    _run(conn, "upgrade")
    assert _recorded(conn) == {"id": str(gid), "name": name}


def test_downgrade_restores_the_column_the_index_and_the_marker(conn):
    gid, _ = _group(conn, "Marvin Admin", marked=True)
    other, _ = _group(conn, "Other")
    _run(conn, "upgrade")
    _run(conn, "downgrade")
    assert "is_platform" in _columns(conn) and "uq_groups_is_platform" in _indexes(conn)
    marked = conn.execute(sa.select(GROUPS.c.id).where(GROUPS.c.is_platform.is_(True))).scalars().all()
    assert [str(m) if not isinstance(m, uuid.UUID) else m for m in marked] == [gid] or [uuid.UUID(str(m)) for m in marked] == [gid]
    assert other not in [uuid.UUID(str(m)) for m in marked]
    assert _recorded(conn) is None  # the record goes with the column's return
    with pytest.raises(sa.exc.IntegrityError):  # the unique index is enforced again: one marker at most
        with conn.begin_nested():
            conn.execute(sa.update(GROUPS).where(GROUPS.c.id == other).values(is_platform=True))


def test_downgrade_after_the_workspace_was_deleted_marks_nothing(conn):
    gid, _ = _group(conn, "Marvin Admin", marked=True)
    _run(conn, "upgrade")
    conn.execute(sa.delete(GROUPS).where(GROUPS.c.id == gid))
    _run(conn, "downgrade")  # the deleted workspace can't be brought back; the schema still is
    assert conn.execute(sa.select(sa.func.count()).select_from(GROUPS).where(GROUPS.c.is_platform.is_(True))).scalar() == 0
