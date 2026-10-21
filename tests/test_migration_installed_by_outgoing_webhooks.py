"""Migration ``f2a6c8d41b95``: ``source_integration_id`` / ``source_blueprint`` on outgoing webhooks (``webhook_urls``), and a
backfill that labels only a row that exactly matches a known plugin blueprint (name and URL host, in a workspace with one
integration of that provider). No plugin declares an outgoing webhook yet, so the shipped snapshot is empty and the backfill is
exercised with a made-up one.

Checked on both engines (PostgreSQL, the test database, rolled back after; and a scratch in-memory SQLite). The suite's database is
already at head, so each case first downgrades, then runs the migration.
"""

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.groups import Groups

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_f2a6c8d41b95_*.py"))
_spec = importlib.util.spec_from_file_location("installed_by_outgoing_webhooks_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

KNOWN = [{"provider": "acme", "slug": "acme-notify", "name": "Acme: notify", "host": "hooks.acme.test"}]


def _columns(conn) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns("webhook_urls")}


def _run(conn, step: str, *args):
    with Operations.context(MigrationContext.configure(conn)):
        return getattr(mig, step)(*args)


@pytest.fixture
def sqlite_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    # create_all gave the table the mixin's unnamed foreign key, which a downgrade cannot name; rebuild it as it was before the migration.
    with engine.begin() as c:
        ddl = c.execute(sa.text("select sql from sqlite_master where type = 'table' and name = 'webhook_urls'")).scalar()
        ddl = re.sub(r"\n\s*(source_integration_id|source_blueprint) [^\n]*,", "", ddl)
        ddl = re.sub(r",\s*FOREIGN KEY\(source_integration_id\)[^\n]*", "", ddl)
        c.execute(sa.text("drop table webhook_urls"))
        c.execute(sa.text(ddl))
    yield engine
    engine.dispose()


@pytest.fixture(params=["postgres", "sqlite"])
def conn(request):
    """The database as it was before the migration (the two columns absent), in a transaction rolled back after."""
    if request.param == "postgres":
        from marvin.db.db_setup import engine

        if engine.dialect.name != "postgresql":
            pytest.skip("the suite's own database is SQLite here; the scratch SQLite case covers it")
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    if "source_blueprint" in _columns(connection):
        _run(connection, "downgrade")
    yield connection
    outer.rollback()
    connection.close()


def _group(conn):
    session = Session(bind=conn)
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    session.close()
    return gid


def _integration(conn, gid, provider="acme", slug=None):
    iid = uuid.uuid4()
    conn.execute(
        sa.text("insert into integrations (id, group_id, provider, name, slug, enabled, config) values (:i, :g, :p, :n, :s, :e, '{}')"),
        {
            "i": iid.hex if conn.dialect.name == "sqlite" else iid,
            "g": gid.hex if conn.dialect.name == "sqlite" else gid,
            "p": provider,
            "n": provider,
            "s": slug or f"{provider}-{iid.hex[:6]}",
            "e": True,
        },
    )
    return iid


def _hook(conn, gid, name, url):
    hid = uuid.uuid4()
    sqlite = conn.dialect.name == "sqlite"
    conn.execute(
        sa.text("insert into webhook_urls (id, group_id, name, url, enabled, method, webhook_type) values (:i, :g, :n, :u, :e, 'POST', 'generic')"),
        {"i": hid.hex if sqlite else hid, "g": gid.hex if sqlite else gid, "n": name, "u": url, "e": False},
    )
    return hid


def _label(conn, hid):
    row = conn.execute(
        sa.text("select source_integration_id, source_blueprint from webhook_urls where id = :i"),
        {"i": hid.hex if conn.dialect.name == "sqlite" else hid},
    ).one()
    return row[0], row[1]


def _uuid(value):
    return value if value is None or isinstance(value, uuid.UUID) else uuid.UUID(value)


def test_the_columns_go_up_down_and_up_again(conn):
    gid = _group(conn)
    hid = _hook(conn, gid, "Mine", "https://example.test/x")
    assert not {"source_integration_id", "source_blueprint"} & _columns(conn)

    _run(conn, "upgrade")
    assert {"source_integration_id", "source_blueprint"} <= _columns(conn)
    assert _label(conn, hid) == (None, None)  # the shipped snapshot is empty: nothing is labelled
    index_columns = [i["column_names"] for i in sa.inspect(conn).get_indexes("webhook_urls")]
    assert ["source_integration_id"] in index_columns

    _run(conn, "downgrade")
    assert not {"source_integration_id", "source_blueprint"} & _columns(conn)
    assert (
        conn.execute(sa.text("select count(*) from webhook_urls where id = :i"), {"i": hid.hex if conn.dialect.name == "sqlite" else hid}).scalar()
        == 1
    )

    _run(conn, "upgrade")
    assert {"source_integration_id", "source_blueprint"} <= _columns(conn)


def test_an_exact_match_is_labelled(conn):
    gid = _group(conn)
    iid = _integration(conn, gid)
    other_group = _group(conn)  # a workspace with no acme integration
    mine = _hook(conn, gid, "Acme: notify", "https://hooks.acme.test/in/abc")
    _run(conn, "upgrade")
    _run(conn, "_backfill", conn, KNOWN)
    integration, blueprint = _label(conn, mine)
    assert _uuid(integration) == iid and blueprint == "acme-notify"
    assert other_group is not None


LOOKALIKES = {
    "another name": ("Acme notify", "https://hooks.acme.test/in/abc"),
    "another host": ("Acme: notify", "https://hooks.elsewhere.test/in/abc"),
    "a lookalike host": ("Acme: notify", "https://hooks.acme.test.evil.test/in/abc"),
    "the host as a path": ("Acme: notify", "https://elsewhere.test/hooks.acme.test"),
}


@pytest.mark.parametrize("what", sorted(LOOKALIKES))
def test_a_lookalike_stays_yours(conn, what):
    gid = _group(conn)
    _integration(conn, gid)
    name, url = LOOKALIKES[what]
    hid = _hook(conn, gid, name, url)
    _run(conn, "upgrade")
    _run(conn, "_backfill", conn, KNOWN)
    assert _label(conn, hid) == (None, None)


@pytest.mark.parametrize("integrations", [0, 2])
def test_a_match_is_left_alone_unless_the_workspace_has_exactly_one_integration_of_that_provider(conn, integrations):
    gid = _group(conn)
    for _ in range(integrations):
        _integration(conn, gid)
    hid = _hook(conn, gid, "Acme: notify", "https://hooks.acme.test/in/abc")
    _run(conn, "upgrade")
    _run(conn, "_backfill", conn, KNOWN)
    assert _label(conn, hid) == (None, None)


def test_the_shipped_snapshot_labels_nothing(conn):
    assert mig._KNOWN == []  # no plugin blueprint creates an outgoing webhook today
    gid = _group(conn)
    _integration(conn, gid)
    hid = _hook(conn, gid, "Acme: notify", "https://hooks.acme.test/in/abc")
    _run(conn, "upgrade")
    assert _label(conn, hid) == (None, None)
