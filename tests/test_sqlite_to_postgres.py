"""SQLite -> Postgres copy tool (marvin.scripts.sqlite_to_postgres): type coercion, checksums, table
order and schema matching as unit tests; the whole copy (FK drop/re-validate, truncate, rollback on
orphans) against a real Postgres when one is available — the Postgres CI job, or S2P_TEST_PG_URL."""

import json
import os
import sqlite3
import uuid
from collections import Counter
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from marvin.scripts import sqlite_to_postgres as s2p


def naive(*parts: int) -> datetime:
    """A naive UTC datetime, the form Marvin keeps in `timestamp` columns."""
    return datetime(*parts, tzinfo=UTC).replace(tzinfo=None)


def spec(kind: str, **kw) -> s2p.ColumnSpec:
    return s2p.ColumnSpec("col", kind, **kw)


# --------------------------------------------------------------------------------------------------
# Type mapping
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("coltype", "kind"),
    [
        (postgresql.JSON(), "json"),
        (postgresql.JSONB(), "json"),
        (postgresql.UUID(), "uuid"),
        (sa.Uuid(), "uuid"),
        (postgresql.ENUM("A", "B", name="e"), "enum"),  # an Enum is a String: must win
        (sa.Boolean(), "bool"),
        (sa.DateTime(), "timestamp"),
        (postgresql.TIMESTAMP(timezone=True), "timestamptz"),
        (sa.Date(), "date"),
        (sa.Time(), "time"),
        (sa.BigInteger(), "bigint"),  # a BigInteger is an Integer: must win
        (sa.SmallInteger(), "smallint"),
        (sa.Integer(), "int"),
        (postgresql.DOUBLE_PRECISION(), "float"),  # a Float is a Numeric: must win
        (sa.Numeric(10, 2), "numeric"),
        (postgresql.BYTEA(), "bytes"),
        (sa.String(20), "string"),
        (sa.Text(), "string"),
        (postgresql.INTERVAL(), "other"),
    ],
)
def test_column_kind(coltype, kind):
    assert s2p.column_kind(coltype) == kind


def test_column_spec_from_reflected_column():
    col = sa.Column("name", sa.String(12), nullable=False)
    assert s2p.ColumnSpec.from_column(col) == s2p.ColumnSpec("name", "string", nullable=False, length=12)
    role = sa.Column("role", postgresql.ENUM("OWNER", "EDITOR", name="role"))
    assert s2p.ColumnSpec.from_column(role).enums == ("OWNER", "EDITOR")
    assert s2p.ColumnSpec.from_column(role).length is None


# --------------------------------------------------------------------------------------------------
# Coercion: what SQLite actually stores -> what Postgres takes
# --------------------------------------------------------------------------------------------------


def test_booleans_stored_as_integers():
    assert s2p.coerce(0, spec("bool")) is False
    assert s2p.coerce(1, spec("bool")) is True
    assert s2p.coerce("true", spec("bool")) is True
    assert s2p.coerce("0", spec("bool")) is False
    with pytest.raises(s2p.CoercionError):
        s2p.coerce(2, spec("bool"))


def test_naive_timestamps_parse_from_sqlalchemy_sqlite_text():
    assert s2p.coerce("2026-07-16 20:20:00.000000", spec("timestamp")) == naive(2026, 7, 16, 20, 20)
    assert s2p.coerce("2026-07-16 20:20:00", spec("timestamp")) == naive(2026, 7, 16, 20, 20)
    assert s2p.coerce("2026-07-16T20:20:00.5", spec("timestamp")) == naive(2026, 7, 16, 20, 20, 0, 500000)


def test_offset_in_naive_column_becomes_naive_utc_and_is_noted():
    notes = Counter()
    value = s2p.coerce("2026-07-16 22:20:00.000001+02:00", spec("timestamp"), notes)
    assert value == naive(2026, 7, 16, 20, 20, 0, 1)
    assert value.tzinfo is None
    assert sum(notes.values()) == 1


def test_timestamptz_treats_naive_text_as_utc():
    assert s2p.coerce("2026-07-16 20:20:00", spec("timestamptz")) == datetime(2026, 7, 16, 20, 20, tzinfo=UTC)
    assert s2p.coerce("2026-07-16T20:20:00Z", spec("timestamptz")).tzinfo is not None


@pytest.mark.parametrize("bad", ["2026-07-16", "yesterday", "", 1700000000])
def test_timestamps_refuse_what_they_cannot_read_exactly(bad):
    # SQLAlchemy's own SQLite DATETIME parser would silently drop the time from a 'T'-less date or
    # anything it half-matches; the copy refuses instead.
    with pytest.raises(s2p.CoercionError):
        s2p.coerce(bad, spec("timestamp"))


def test_date_and_time():
    assert s2p.coerce("2026-07-16", spec("date")) == date(2026, 7, 16)
    assert s2p.coerce("20:20:01", spec("time")) == time(20, 20, 1)
    with pytest.raises(s2p.CoercionError):
        s2p.coerce("2026-07-16 10:00", spec("date"))


def test_guids_stored_as_32_hex_digits():
    u = uuid.uuid4()
    assert s2p.coerce(u.hex, spec("uuid")) == u
    assert s2p.coerce(str(u), spec("uuid")) == u
    assert s2p.coerce(u.bytes, spec("uuid")) == u
    with pytest.raises(s2p.CoercionError):
        s2p.coerce("not-a-uuid", spec("uuid"))


def test_json_text_parses_and_keeps_json_null_distinct_from_sql_null():
    assert s2p.coerce('{"a": [1, 2]}', spec("json")) == {"a": [1, 2]}
    assert s2p.coerce('"text"', spec("json")) == "text"
    assert s2p.coerce("null", spec("json")) is sa.JSON.NULL
    assert s2p.coerce(None, spec("json")) is None
    assert s2p.coerce(5, spec("json")) == 5
    with pytest.raises(s2p.CoercionError):
        s2p.coerce("{bad json", spec("json"))


def test_integers_and_ranges():
    assert s2p.coerce(5, spec("int")) == 5
    assert s2p.coerce("12", spec("int")) == 12
    assert s2p.coerce(3.0, spec("int")) == 3
    assert s2p.coerce(2**40, spec("bigint")) == 2**40
    for bad, kind in ((2**31, "int"), (2**15, "smallint"), (1.5, "int"), ("x", "int")):
        with pytest.raises(s2p.CoercionError):
            s2p.coerce(bad, spec(kind))


def test_numbers():
    assert s2p.coerce(1, spec("float")) == 1.0
    assert s2p.coerce("2.5", spec("float")) == 2.5
    assert s2p.coerce(1.10, spec("numeric")) == Decimal("1.1")
    with pytest.raises(s2p.CoercionError):
        s2p.coerce("abc", spec("float"))


def test_strings_lengths_nul_and_affinity():
    notes = Counter()
    assert s2p.coerce(42, spec("string"), notes) == "42"
    assert sum(notes.values()) == 1
    assert s2p.coerce(b"caf\xc3\xa9", spec("string")) == "café"
    with pytest.raises(s2p.CoercionError, match="allows 3"):
        s2p.coerce("abcd", spec("string", length=3))
    with pytest.raises(s2p.CoercionError, match="NUL"):
        s2p.coerce("a\x00b", spec("string"))
    with pytest.raises(s2p.CoercionError):
        s2p.coerce(b"\xff", spec("string"))


def test_enums_must_be_a_label():
    assert s2p.coerce("OWNER", spec("enum", enums=("OWNER", "EDITOR"))) == "OWNER"
    with pytest.raises(s2p.CoercionError):
        s2p.coerce("owner", spec("enum", enums=("OWNER", "EDITOR")))


def test_null_in_not_null_column_is_refused():
    assert s2p.coerce(None, spec("string")) is None
    with pytest.raises(s2p.CoercionError, match="NOT NULL"):
        s2p.coerce(None, spec("string", nullable=False))


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (1, "bool"),
        ("2026-07-16 20:20:00.000000", "timestamp"),
        ("2026-07-16 20:20:00", "timestamptz"),
        (uuid.uuid4().hex, "uuid"),
        ("17", "int"),
        ("2.5", "float"),
        ("1.10", "numeric"),
        ("x", "string"),
        ("2026-07-16", "date"),
    ],
)
def test_coerce_is_idempotent_so_read_back_values_checksum_the_same(raw, kind):
    once = s2p.coerce(raw, spec(kind))
    assert s2p.canonical(s2p.coerce(once, spec(kind)), kind) == s2p.canonical(once, kind)


def test_canonical_forms():
    assert s2p.canonical(None, "string") == s2p.NULL_MARK
    assert s2p.canonical(datetime(2026, 1, 1, 5, tzinfo=UTC), "timestamptz") == "2026-01-01T05:00:00+00:00"
    assert s2p.canonical_json('{"b": 1, "a": 2}') == s2p.canonical_json('{"a":2,"b":1}')
    assert s2p.canonical_json("null") != s2p.canonical_json(None)


def test_row_checksum_ignores_order_but_not_content():
    a, b, c = s2p.RowChecksum(), s2p.RowChecksum(), s2p.RowChecksum()
    for rows, chk in ((["1", "x"], ["2", "y"]), a), ((["2", "y"], ["1", "x"]), b), ((["1", "x"], ["2", "z"]), c):
        for row in rows:
            chk.add(row)
    assert a.hexdigest == b.hexdigest != c.hexdigest
    assert a.rows == 2


# --------------------------------------------------------------------------------------------------
# Planning: order and schema matching
# --------------------------------------------------------------------------------------------------


def _schema() -> sa.MetaData:
    md = sa.MetaData()
    sa.Table("parents", md, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "children",
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_id", sa.ForeignKey("parents.id")),
        sa.Column("prev_id", sa.ForeignKey("children.id")),  # self-reference
    )
    sa.Table("grandchildren", md, sa.Column("id", sa.Integer, primary_key=True), sa.Column("child_id", sa.ForeignKey("children.id")))
    sa.Table("alembic_version", md, sa.Column("version_num", sa.String(32), primary_key=True))
    sa.Table("plugin_alembic_version", md, sa.Column("version_num", sa.String(32), primary_key=True))
    return md


def test_copy_order_puts_parents_first_and_skips_alembic_tables():
    names = [t.name for t in s2p.copy_order(_schema())]
    assert names == ["parents", "children", "grandchildren"]


def test_is_copied_table():
    assert s2p.is_copied_table("entries")
    for name in ("alembic_version", "x_alembic_version", "sqlite_stat1", "sqlite_sequence"):
        assert not s2p.is_copied_table(name)


def _sqlite(tmp_path: Path, ddl: str) -> sqlite3.Connection:
    path = tmp_path / "src.db"
    conn = sqlite3.connect(path)
    conn.executescript(ddl)
    conn.commit()
    conn.close()
    return s2p.open_source(path)


def test_plan_tables_matches_exactly(tmp_path):
    src = _sqlite(
        tmp_path,
        "CREATE TABLE parents (id INTEGER PRIMARY KEY); CREATE TABLE children (id INTEGER, parent_id INTEGER, prev_id INTEGER);"
        "CREATE TABLE grandchildren (id INTEGER, child_id INTEGER); CREATE TABLE alembic_version (version_num TEXT);",
    )
    plans = s2p.plan_tables(src, _schema())
    assert [p.name for p in plans] == ["parents", "children", "grandchildren"]
    assert plans[1].columns == ["id", "parent_id", "prev_id"]


def test_plan_tables_refuses_schema_drift(tmp_path):
    src = _sqlite(tmp_path, "CREATE TABLE parents (id INTEGER, extra TEXT); CREATE TABLE children (id INTEGER); CREATE TABLE stray (id INTEGER);")
    with pytest.raises(s2p.CopyError) as exc:
        s2p.plan_tables(src, _schema())
    message = str(exc.value)
    assert "stray" in message and "grandchildren" in message and "extra" in message


def test_open_source_is_read_only(tmp_path):
    src = _sqlite(tmp_path, "CREATE TABLE t (id INTEGER);")
    with pytest.raises(sqlite3.OperationalError):
        src.execute("INSERT INTO t VALUES (1)")


# --------------------------------------------------------------------------------------------------
# The whole copy, against a real Postgres
# --------------------------------------------------------------------------------------------------


def _postgres_url() -> str | None:
    if url := os.getenv("S2P_TEST_PG_URL"):
        return url
    from marvin.db.db_setup import engine

    return engine.url.render_as_string(hide_password=False) if engine.dialect.name == "postgresql" else None


SCHEMA = "s2p_test"
REV = "abc123"
P1, P2 = uuid.uuid4(), uuid.uuid4()
C1, C2 = uuid.uuid4(), uuid.uuid4()

SOURCE_DDL = f"""
CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
INSERT INTO alembic_version VALUES ('{REV}');
CREATE TABLE parents (id CHAR(32) PRIMARY KEY, name VARCHAR(20) NOT NULL, active BOOLEAN, role VARCHAR(6),
                      created_at DATETIME, seen_at DATETIME, settings JSON, score FLOAT);
CREATE TABLE children (id CHAR(32) PRIMARY KEY, parent_id CHAR(32) REFERENCES parents(id), prev_id CHAR(32) REFERENCES children(id),
                       n INTEGER);
CREATE TABLE counters (id INTEGER PRIMARY KEY, label TEXT);
INSERT INTO parents VALUES ('{P1.hex}', 'one', 1, 'OWNER', '2026-07-16 20:20:00.000000', '2026-07-16 20:20:00.000000',
                            '{{"b": 1, "a": [true, null]}}', 1.5);
INSERT INTO parents VALUES ('{P2.hex}', 'two', 0, 'EDITOR', '2026-07-16 21:00:00.000000+00:00', NULL, 'null', NULL);
-- C1 points at C2, which comes later: only works because the copy drops and re-creates the FKs.
INSERT INTO children VALUES ('{C1.hex}', '{P1.hex}', '{C2.hex}', 1);
INSERT INTO children VALUES ('{C2.hex}', '{P2.hex}', NULL, 2);
INSERT INTO counters VALUES (1, 'a'), (7, 'b');
"""


def _target_metadata() -> sa.MetaData:
    md = sa.MetaData()
    sa.Table("alembic_version", md, sa.Column("version_num", sa.String(32), primary_key=True))
    sa.Table(
        "parents",
        md,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean),
        sa.Column("role", postgresql.ENUM("OWNER", "EDITOR", name="s2p_role")),
        sa.Column("created_at", sa.DateTime),
        sa.Column("seen_at", sa.DateTime(timezone=True)),
        sa.Column("settings", sa.JSON),
        sa.Column("score", postgresql.DOUBLE_PRECISION),
    )
    sa.Table(
        "children",
        md,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_id", sa.ForeignKey("parents.id", ondelete="CASCADE")),
        sa.Column("prev_id", sa.ForeignKey("children.id", ondelete="SET NULL")),
        sa.Column("n", sa.Integer),
    )
    sa.Table("counters", md, sa.Column("id", sa.Integer, primary_key=True, autoincrement=True), sa.Column("label", sa.Text))
    return md


@pytest.fixture
def pg_engine():
    url = _postgres_url()
    if not url:
        pytest.skip("needs Postgres: the Postgres CI job, or S2P_TEST_PG_URL")
    admin = sa.create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.exec_driver_sql(f"CREATE SCHEMA {SCHEMA}")
    engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    md = _target_metadata()
    md.create_all(engine)
    with engine.begin() as conn:
        conn.execute(md.tables["alembic_version"].insert(), {"version_num": REV})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        admin.dispose()


def _counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t: conn.exec_driver_sql(f"SELECT COUNT(*) FROM {t}").scalar_one() for t in ("parents", "children", "counters")}


def test_copy_round_trip_truncate_and_rollback(tmp_path, pg_engine):
    src = _sqlite(tmp_path, SOURCE_DDL)

    report = s2p.copy_database(src, pg_engine)
    assert {t.name: (t.source_rows, t.target_rows, t.ok) for t in report.tables} == {
        "parents": (2, 2, True),
        "children": (2, 2, True),
        "counters": (2, 2, True),
    }
    assert report.foreign_keys == 2
    assert report.sequences_reset == 1
    assert sum(report.notes.values()) == 1  # the +00:00 in a naive column

    with pg_engine.connect() as conn:
        one = conn.exec_driver_sql("SELECT active, role::text, created_at, seen_at, settings::text, score FROM parents WHERE name = 'one'").one()
        assert one.active is True and one.role == "OWNER"
        assert one.created_at == naive(2026, 7, 16, 20, 20)
        assert one.seen_at == datetime(2026, 7, 16, 20, 20, tzinfo=UTC)
        assert json.loads(one.settings) == {"b": 1, "a": [True, None]}
        two = conn.exec_driver_sql("SELECT active, settings IS NULL AS sql_null, settings::text AS js, seen_at FROM parents WHERE name = 'two'").one()
        assert two.active is False and two.sql_null is False and two.js == "null" and two.seen_at is None
        # the sequence continues past the copied keys
        assert conn.exec_driver_sql("INSERT INTO counters (label) VALUES ('c') RETURNING id").scalar_one() == 8
        conn.rollback()

    src.close()
    src = s2p.open_source(tmp_path / "src.db")
    with pytest.raises(s2p.CopyError, match="--truncate"):
        s2p.copy_database(src, pg_engine)

    again = s2p.copy_database(src, pg_engine, truncate=True)
    assert all(t.ok for t in again.tables)
    src.close()  # releases its read transaction, so the orphan can be written below
    assert _counts(pg_engine) == {"parents": 2, "children": 2, "counters": 2}

    # An orphan (SQLite never enforced the FK) fails the re-created constraint; everything rolls back.
    raw = sqlite3.connect(tmp_path / "src.db")
    raw.execute(f"INSERT INTO children VALUES ('{uuid.uuid4().hex}', '{uuid.uuid4().hex}', NULL, 3)")
    raw.commit()
    raw.close()
    with pytest.raises(s2p.CopyError, match="foreign keys"):
        s2p.copy_database(s2p.open_source(tmp_path / "src.db"), pg_engine, truncate=True)
    assert _counts(pg_engine) == {"parents": 2, "children": 2, "counters": 2}


def test_copy_refuses_bad_values_before_writing(tmp_path, pg_engine):
    src = _sqlite(tmp_path, SOURCE_DDL + f"UPDATE parents SET settings = '{{oops' WHERE id = '{P2.hex}';")
    with pytest.raises(s2p.CopyError, match="do not convert"):
        s2p.copy_database(src, pg_engine)
    assert _counts(pg_engine) == {"parents": 0, "children": 0, "counters": 0}
    report = s2p.survey(s2p.open_source(tmp_path / "src.db"), pg_engine)
    assert report.problem_count == 1 and "invalid JSON" in report.problems[0]


def test_copy_refuses_a_revision_mismatch(tmp_path, pg_engine):
    src = _sqlite(tmp_path, SOURCE_DDL + "UPDATE alembic_version SET version_num = 'older';")
    with pytest.raises(s2p.CopyError, match="alembic revision"):
        s2p.copy_database(src, pg_engine)
