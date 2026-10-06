"""Copy a Marvin SQLite database into PostgreSQL, every table, and prove the copy is complete.

    python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db --dry-run
    python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db [--truncate]

The target comes from the app's own settings (DB_ENGINE=postgres + POSTGRES_* or POSTGRES_URL_OVERRIDE),
the same connection the backend would use. Steps:

1. Read the source read-only, in one read transaction (a consistent view even if something writes).
2. `alembic upgrade head` on the target, so the schema is exactly what the app creates. The source's
   alembic revision must equal the target's: copy with the same image version that last ran on the
   SQLite file.
3. Refuse a target that holds data unless --truncate (a re-run with --truncate is idempotent).
4. Check every source value against the target column type before writing anything: SQLite keeps
   booleans as 0/1, datetimes/JSON/GUIDs as text and enforces neither types nor lengths. Values are
   converted by the *target* (reflected Postgres) column type; anything that does not convert cleanly
   (bad JSON, a time-less datetime, a too-long string, a NUL byte, a NULL in a NOT NULL column) is
   reported and nothing is written.
5. In ONE transaction: truncate the target tables, drop the foreign keys, copy each table in FK
   dependency order in batches, re-create the foreign keys (Postgres re-validates every row: an orphan
   left behind by SQLite's unenforced FKs fails here, named), reset serial/identity sequences, then
   verify — per-table row counts equal and a content checksum over every column of every row equal on
   both sides. Any failure rolls the whole transaction back, leaving the target as it was.

--dry-run touches nothing: it reports source and target row counts and runs the step-4 check.
`alembic_version` (and plugins' `*_alembic_version`) are never copied; SQLite's own `sqlite_*` tables
are ignored. See docs/manual/postgres.md for the runbook and the production cutover checklist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("marvin.sqlite_to_postgres")

BATCH_SIZE = 1000
MAX_REPORTED_PROBLEMS = 50
_INT_BOUNDS = {"smallint": 2**15, "int": 2**31, "bigint": 2**63}
_TRUE = {"1", "t", "true", "y", "yes"}
_FALSE = {"0", "f", "false", "n", "no"}
_INT_TEXT = re.compile(r"^[+-]?\d+$")
NULL_MARK = "\x00null"  # canonical form of SQL NULL in checksums (never a real canonical value)


class CopyError(Exception):
    """The copy cannot proceed or did not verify; the message says why."""


class CoercionError(ValueError):
    """A source value does not convert cleanly to its target column type."""


def is_copied_table(name: str) -> bool:
    """Every table except Alembic's bookkeeping and SQLite's internals."""
    return not (name == "alembic_version" or name.endswith("_alembic_version") or name.startswith("sqlite_"))


# --------------------------------------------------------------------------------------------------
# Column types and value coercion
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    """What the copy needs to know about one target column."""

    name: str
    kind: str
    nullable: bool = True
    length: int | None = None
    enums: tuple[str, ...] = ()

    @classmethod
    def from_column(cls, column: sa.Column) -> ColumnSpec:
        t = column.type
        return cls(
            name=column.name,
            kind=column_kind(t),
            nullable=bool(column.nullable),
            length=getattr(t, "length", None) if isinstance(t, sa.String) and not isinstance(t, sa.Enum) else None,
            enums=tuple(t.enums) if isinstance(t, sa.Enum) else (),
        )


def column_kind(coltype: sa.types.TypeEngine) -> str:
    """Map a (reflected) SQLAlchemy type to the coercion kind. Order matters: Enum is a String,
    Float a Numeric, BigInteger an Integer."""
    checks: tuple[tuple[type | tuple[type, ...], str | Callable[[Any], str]], ...] = (
        (sa.JSON, "json"),
        (sa.Uuid, "uuid"),
        (sa.Enum, "enum"),
        (sa.Boolean, "bool"),
        (sa.DateTime, lambda t: "timestamptz" if t.timezone else "timestamp"),
        (sa.Date, "date"),
        (sa.Time, "time"),
        (sa.BigInteger, "bigint"),
        (sa.SmallInteger, "smallint"),
        (sa.Integer, "int"),
        (sa.Float, "float"),
        (sa.Numeric, "numeric"),
        (sa.LargeBinary, "bytes"),
        (sa.String, "string"),
    )
    for types, kind in checks:
        if isinstance(coltype, types):
            return kind(coltype) if callable(kind) else kind
    return "other"


def _as_text(value: Any) -> str:
    if isinstance(value, bytes | memoryview):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CoercionError("bytes that are not UTF-8 text") from exc
    if isinstance(value, str):
        return value
    raise CoercionError(f"expected text, got {type(value).__name__}")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = _as_text(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CoercionError(f"not an ISO datetime: {text[:40]!r}") from exc
    if len(text) <= 10:  # a bare date in a datetime column: refuse rather than invent midnight
        raise CoercionError(f"date without a time in a datetime column: {text!r}")
    return parsed


Notes = Counter | None


def _to_json(value: Any, spec: ColumnSpec, notes: Notes) -> Any:
    if not isinstance(value, bytes | memoryview | str):
        return value
    try:
        parsed = json.loads(_as_text(value))
    except ValueError as exc:
        raise CoercionError(f"invalid JSON: {exc}") from exc
    return sa.JSON.NULL if parsed is None else parsed  # JSON null stays JSON null, not SQL NULL


def _to_uuid(value: Any, spec: ColumnSpec, notes: Notes) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, bytes) and len(value) == 16:
        return uuid.UUID(bytes=value)
    try:
        return uuid.UUID(_as_text(value).strip())  # 32 hex digits (Marvin's SQLite GUID) or dashed
    except ValueError as exc:
        raise CoercionError(f"not a UUID: {str(value)[:40]!r}") from exc


def _to_bool(value: Any, spec: ColumnSpec, notes: Notes) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
        return value.strip().lower() in _TRUE
    raise CoercionError(f"not a boolean: {value!r}")


def _to_timestamp(value: Any, spec: ColumnSpec, notes: Notes) -> datetime:
    parsed = _parse_datetime(value)
    if parsed.tzinfo is not None:
        if notes is not None:
            notes[(spec.name, "UTC offset in a naive timestamp column; stored as naive UTC")] += 1
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _to_timestamptz(value: Any, spec: ColumnSpec, notes: Notes) -> datetime:
    parsed = _parse_datetime(value)
    # Marvin writes UTC everywhere and SQLite drops the zone, so a naive value is UTC.
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _to_date(value: Any, spec: ColumnSpec, notes: Notes) -> date:
    if isinstance(value, datetime):
        raise CoercionError("datetime in a date column")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_as_text(value).strip())
    except ValueError as exc:
        raise CoercionError(f"not an ISO date: {str(value)[:40]!r}") from exc


def _to_time(value: Any, spec: ColumnSpec, notes: Notes) -> time:
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(_as_text(value).strip())
    except ValueError as exc:
        raise CoercionError(f"not an ISO time: {str(value)[:40]!r}") from exc


def _to_int(value: Any, spec: ColumnSpec, notes: Notes) -> int:
    if isinstance(value, int):  # bool included
        result = int(value)
    elif isinstance(value, float) and value.is_integer():
        result = int(value)
    elif isinstance(value, str) and _INT_TEXT.match(value.strip()):
        result = int(value.strip())
    else:
        raise CoercionError(f"not an integer: {value!r}")
    bound = _INT_BOUNDS[spec.kind]
    if not -bound <= result < bound:
        raise CoercionError(f"{result} out of range for {spec.kind}")
    return result


def _to_float(value: Any, spec: ColumnSpec, notes: Notes) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise CoercionError(f"not a number: {value!r}")
    try:
        return float(value)
    except ValueError as exc:
        raise CoercionError(f"not a number: {value!r}") from exc


def _to_numeric(value: Any, spec: ColumnSpec, notes: Notes) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise CoercionError(f"not a number: {value!r}") from exc


def _to_bytes(value: Any, spec: ColumnSpec, notes: Notes) -> bytes:
    if isinstance(value, bytes | memoryview):
        return bytes(value)
    raise CoercionError(f"expected bytes, got {type(value).__name__}")


def _to_text(value: Any, spec: ColumnSpec, notes: Notes) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        text = str(value)  # SQLite type affinity: a number stored in a text column
        if notes is not None:
            notes[(spec.name, "number stored in a text column; copied as its text")] += 1
    else:
        text = _as_text(value)
    if "\x00" in text:
        raise CoercionError("contains a NUL character (Postgres text cannot hold it)")
    if spec.length is not None and len(text) > spec.length:
        raise CoercionError(f"{len(text)} characters, column allows {spec.length}")
    if spec.enums and text not in spec.enums:
        raise CoercionError(f"{text!r} is not one of {list(spec.enums)}")
    return text


_COERCERS: dict[str, Callable[[Any, ColumnSpec, Notes], Any]] = {
    "json": _to_json,
    "uuid": _to_uuid,
    "bool": _to_bool,
    "timestamp": _to_timestamp,
    "timestamptz": _to_timestamptz,
    "date": _to_date,
    "time": _to_time,
    "smallint": _to_int,
    "int": _to_int,
    "bigint": _to_int,
    "float": _to_float,
    "numeric": _to_numeric,
    "bytes": _to_bytes,
    "string": _to_text,
    "enum": _to_text,
}


def coerce(value: Any, spec: ColumnSpec, notes: Notes = None) -> Any:
    """Convert one raw SQLite value to the Python value the Postgres column takes. Idempotent: a value
    already of the target type (e.g. one read back from Postgres) comes back unchanged in meaning.
    `notes` counts lossless normalisations worth reporting (e.g. a UTC offset in a naive column).
    Unknown kinds pass through for Postgres to judge."""
    if value is None:
        if not spec.nullable:
            raise CoercionError("NULL in a NOT NULL column")
        return None
    convert = _COERCERS.get(spec.kind)
    return convert(value, spec, notes) if convert else value


def canonical_json(text: Any) -> str:
    """Formatting-independent form of a JSON value stored as text (SQL NULL distinct from JSON null)."""
    if text is None:
        return NULL_MARK
    if not isinstance(text, str | bytes):
        return json.dumps(text, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical(value: Any, kind: str) -> str:
    """Stable text for a coerced value, used by the checksum on both sides."""
    if value is None:
        return NULL_MARK
    if kind == "timestamptz":
        return value.astimezone(UTC).isoformat()
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


class RowChecksum:
    """Order-independent checksum of a table's rows: the sum (mod 2**256) of each row's sha256. Equal
    for the same multiset of rows whatever order they are read in."""

    def __init__(self) -> None:
        self.total = 0
        self.rows = 0

    def add(self, parts: Iterable[str]) -> None:
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8", "surrogatepass")).digest()
        self.total = (self.total + int.from_bytes(digest, "big")) % 2**256
        self.rows += 1

    @property
    def hexdigest(self) -> str:
        return f"{self.total:064x}"


# --------------------------------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------------------------------


def copy_order(metadata: sa.MetaData) -> list[sa.Table]:
    """Copied tables, parents before children. Self-references and cycles cannot be ordered away;
    the copy drops and re-creates the foreign keys, so this order is for readability, not safety."""
    return [t for t in metadata.sorted_tables if is_copied_table(t.name)]


@dataclass
class TablePlan:
    table: sa.Table
    specs: list[ColumnSpec]

    @property
    def name(self) -> str:
        return self.table.name

    @property
    def columns(self) -> list[str]:
        return [s.name for s in self.specs]


@dataclass
class TableResult:
    name: str
    source_rows: int
    target_rows: int | None = None
    source_checksum: str | None = None
    target_checksum: str | None = None

    @property
    def ok(self) -> bool:
        return self.source_rows == self.target_rows and self.source_checksum == self.target_checksum


@dataclass
class Report:
    revision: str | None = None
    tables: list[TableResult] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    problem_count: int = 0
    notes: Counter = field(default_factory=Counter)
    sequences_reset: int = 0
    foreign_keys: int = 0

    def problem(self, message: str) -> None:
        self.problem_count += 1
        if len(self.problems) < MAX_REPORTED_PROBLEMS:
            self.problems.append(message)

    def lines(self) -> list[str]:
        out = [f"{'table':40} {'source':>8} {'target':>8}  checksum"]
        for t in self.tables:
            target = "-" if t.target_rows is None else str(t.target_rows)
            check = "-" if t.target_checksum is None else ("ok" if t.ok else "MISMATCH")
            out.append(f"{t.name:40} {t.source_rows:>8} {target:>8}  {check}")
        total_source = sum(t.source_rows for t in self.tables)
        total_target = sum(t.target_rows or 0 for t in self.tables)
        out.append(f"{'TOTAL (' + str(len(self.tables)) + ' tables)':40} {total_source:>8} {total_target:>8}")
        for (column, note), count in sorted(self.notes.items()):
            out.append(f"note: {column}: {count} value(s): {note}")
        return out


def open_source(path: Path) -> sqlite3.Connection:
    """Read-only, autocommit-off connection held in one read transaction for a consistent view."""
    if not path.is_file():
        raise CopyError(f"source database not found: {path}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None)
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        conn.close()
        raise CopyError(f"source {path.name} fails PRAGMA quick_check")
    conn.execute("BEGIN")
    return conn


def source_tables(src: sqlite3.Connection) -> dict[str, list[str]]:
    names = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {n: [r[1] for r in src.execute(f'PRAGMA table_info("{n}")')] for n in names if is_copied_table(n)}


def source_revision(src: sqlite3.Connection) -> str | None:
    try:
        rows = src.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.OperationalError:
        return None
    return ",".join(sorted(r[0] for r in rows)) or None


def target_revision(conn: Connection) -> str | None:
    if not sa.inspect(conn).has_table("alembic_version"):
        return None
    return ",".join(sorted(r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version"))) or None


def reflect_target(conn: Connection) -> sa.MetaData:
    metadata = sa.MetaData()
    metadata.reflect(conn)
    for table in metadata.tables.values():
        for column in table.c:
            if isinstance(column.type, sa.JSON):
                # SQL NULL stays SQL NULL; JSON null is passed explicitly as sa.JSON.NULL by coerce().
                column.type = type(column.type)(none_as_null=True)
    return metadata


def plan_tables(src: sqlite3.Connection, metadata: sa.MetaData) -> list[TablePlan]:
    """Match source and target tables/columns exactly; any difference means a schema mismatch."""
    source = source_tables(src)
    target = {t.name: t for t in copy_order(metadata)}
    errors = []
    if missing := sorted(set(source) - set(target)):
        errors.append(f"tables in the source but not the target: {missing}")
    if extra := sorted(set(target) - set(source)):
        errors.append(f"tables in the target but not the source: {extra}")
    for name in sorted(set(source) & set(target)):
        s_cols, t_cols = set(source[name]), set(target[name].c.keys())
        if s_cols != t_cols:
            errors.append(f"{name}: columns differ (source only {sorted(s_cols - t_cols)}, target only {sorted(t_cols - s_cols)})")
    if errors:
        raise CopyError("schema mismatch — run the same Marvin version on both sides:\n  " + "\n  ".join(errors))
    return [TablePlan(t, [ColumnSpec.from_column(c) for c in t.c]) for t in copy_order(metadata)]


def iter_source_rows(src: sqlite3.Connection, plan: TablePlan, batch_size: int) -> Iterator[list[tuple]]:
    cols = ", ".join(f'"{c}"' for c in plan.columns)
    cursor = src.execute(f'SELECT {cols} FROM "{plan.name}"')
    while batch := cursor.fetchmany(batch_size):
        yield batch


def _row_label(plan: TablePlan, row: tuple) -> str:
    pk = [c.name for c in plan.table.primary_key.columns]
    if not pk:
        return ""
    values = dict(zip(plan.columns, row, strict=True))
    return " " + ",".join(f"{k}={values[k]!r}" for k in pk)


def check_and_checksum(src: sqlite3.Connection, plan: TablePlan, report: Report, batch_size: int) -> TableResult:
    """Coerce every source row (recording problems) and checksum the coerced rows."""
    checksum = RowChecksum()
    notes: Counter = Counter()
    for batch in iter_source_rows(src, plan, batch_size):
        for row in batch:
            parts = []
            for spec, raw in zip(plan.specs, row, strict=True):
                try:
                    value = coerce(raw, spec, notes)
                    parts.append(canonical_json(raw) if spec.kind == "json" else canonical(value, spec.kind))
                except (CoercionError, ValueError) as exc:
                    report.problem(f"{plan.name}.{spec.name}{_row_label(plan, row)}: {exc}")
                    parts.append("")
            checksum.add(parts)
    for (column, note), count in notes.items():
        report.notes[(f"{plan.name}.{column}", note)] += count
    return TableResult(plan.name, checksum.rows, source_checksum=checksum.hexdigest)


def target_counts(conn: Connection, plans: list[TablePlan]) -> dict[str, int]:
    return {p.name: conn.execute(sa.select(sa.func.count()).select_from(p.table)).scalar_one() for p in plans}


# --------------------------------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------------------------------


def _quote(conn: Connection, name: str) -> str:
    return conn.dialect.identifier_preparer.quote(name)


def foreign_keys(conn: Connection) -> list[tuple[str, str, str]]:
    """(table, constraint name, definition) for every FK in the current schema."""
    rows = conn.exec_driver_sql(
        "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid = c.connamespace WHERE c.contype = 'f' AND n.nspname = current_schema() "
        "ORDER BY 1, 2"
    )
    return [(r[0], r[1], r[2]) for r in rows]


def reset_sequences(conn: Connection, plans: list[TablePlan]) -> int:
    """Point every serial/identity sequence past the copied rows. Marvin's keys are UUIDs today, so
    this is usually a no-op; it keeps the tool right for any integer key a table gains later."""
    reset = 0
    for plan in plans:
        table = _quote(conn, plan.name)
        for spec in plan.specs:
            if spec.kind not in _INT_BOUNDS:
                continue
            seq = conn.execute(sa.text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table, "c": spec.name}).scalar()
            if seq:
                col = _quote(conn, spec.name)
                conn.execute(
                    sa.text(f"SELECT setval(:seq, COALESCE((SELECT MAX({col}) FROM {table}), 1), (SELECT MAX({col}) FROM {table}) IS NOT NULL)"),
                    {"seq": seq},
                )
                reset += 1
    return reset


def target_checksum(conn: Connection, plan: TablePlan, batch_size: int) -> tuple[int, str]:
    """Checksum the target rows the same way as the source: JSON read as text, the rest through coerce()."""
    selected = [sa.cast(plan.table.c[s.name], sa.Text) if s.kind == "json" else plan.table.c[s.name] for s in plan.specs]
    checksum = RowChecksum()
    result = conn.execution_options(yield_per=batch_size).execute(sa.select(*selected))
    for row in result:
        checksum.add(
            canonical_json(v) if s.kind == "json" else canonical(coerce(v, ColumnSpec(s.name, s.kind)), s.kind)
            for s, v in zip(plan.specs, row, strict=True)
        )
    return checksum.rows, checksum.hexdigest


def copy_table(conn: Connection, src: sqlite3.Connection, plan: TablePlan, batch_size: int) -> int:
    insert = plan.table.insert()
    copied = 0
    for batch in iter_source_rows(src, plan, batch_size):
        rows = [{s.name: coerce(v, s) for s, v in zip(plan.specs, row, strict=True)} for row in batch]
        conn.execute(insert, rows)
        copied += len(rows)
    return copied


def survey(src: sqlite3.Connection, engine: Engine, batch_size: int = BATCH_SIZE) -> Report:
    """Dry run: counts on both sides plus the full coercion check. Writes nothing."""
    report = Report(revision=source_revision(src))
    with engine.connect() as conn:
        target_rev = target_revision(conn)
        metadata = reflect_target(conn)
        if target_rev is None:
            log.info("target has no schema yet (a real copy runs alembic upgrade head first); source counts only")
            for name in source_tables(src):
                report.tables.append(TableResult(name, src.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]))
            return report
        if target_rev != report.revision:
            report.problem(f"source is at alembic revision {report.revision}, target at {target_rev}")
        plans = plan_tables(src, metadata)
        counts = target_counts(conn, plans)
    for plan in plans:
        result = check_and_checksum(src, plan, report, batch_size)
        result.target_rows = counts[plan.name]
        report.tables.append(result)
    return report


def copy_database(src: sqlite3.Connection, engine: Engine, *, truncate: bool = False, batch_size: int = BATCH_SIZE) -> Report:
    """Copy every table from `src` into the (already migrated) target behind `engine`, in one
    transaction, and verify it. Raises CopyError — with the target rolled back — on any failure."""
    report = Report(revision=source_revision(src))
    with engine.connect() as conn:
        target_rev = target_revision(conn)
        metadata = reflect_target(conn)
        conn.rollback()
    if target_rev is None:
        raise CopyError("target has no alembic_version: run `alembic upgrade head` on it first")
    if target_rev != report.revision:
        raise CopyError(
            f"source is at alembic revision {report.revision}, target at {target_rev}: run the same Marvin version "
            "against the SQLite file first (its startup migrates it), then copy"
        )
    plans = plan_tables(src, metadata)

    with engine.connect() as conn:
        occupied = {k: v for k, v in target_counts(conn, plans).items() if v}
        conn.rollback()
    if occupied and not truncate:
        sample = ", ".join(f"{k}={v}" for k, v in sorted(occupied.items())[:8])
        raise CopyError(f"target already holds data ({sample}); pass --truncate to replace it")

    # Check everything before writing anything.
    for plan in plans:
        report.tables.append(check_and_checksum(src, plan, report, batch_size))
    if report.problem_count:
        raise CopyError(f"{report.problem_count} source value(s) do not convert; nothing written")

    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE " + ", ".join(_quote(conn, p.name) for p in plans))
        fks = foreign_keys(conn)
        report.foreign_keys = len(fks)
        for table, name, _ in fks:
            conn.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {_quote(conn, name)}")
        for plan in plans:
            copied = copy_table(conn, src, plan, batch_size)
            log.info("copied %-40s %8d", plan.name, copied)
        failed = []
        for table, name, definition in fks:
            try:
                with conn.begin_nested():
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD CONSTRAINT {_quote(conn, name)} {definition}")
            except sa.exc.DBAPIError as exc:
                detail = str(getattr(exc.orig, "pgerror", None) or exc.orig).strip().replace("\n", " ")
                failed.append(f"{table}.{name}: {detail}")
        if failed:
            raise CopyError("foreign keys do not hold on the copied data (orphan rows in the source):\n  " + "\n  ".join(failed))
        report.sequences_reset = reset_sequences(conn, plans)
        for plan, result in zip(plans, report.tables, strict=True):
            result.target_rows, result.target_checksum = target_checksum(conn, plan, batch_size)
        if bad := [t.name for t in report.tables if not t.ok]:
            raise CopyError(f"verification failed for {bad}; rolled back")
    return report


# --------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------


def migrate_target() -> None:
    """`alembic upgrade head` through the app's own Alembic config (its env.py reads the app settings)."""
    from alembic import command
    from alembic.config import Config

    import marvin

    ini = os.getenv("ALEMBIC_CONFIG_FILE") or str(Path(marvin.__file__).parent / "alembic.ini")
    command.upgrade(Config(ini), "head")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m marvin.scripts.sqlite_to_postgres", description=__doc__.split("\n\n")[0])
    p.add_argument("--source", type=Path, required=True, help="the SQLite file (a copy, or with the backend stopped)")
    p.add_argument("--truncate", action="store_true", help="replace whatever the target tables hold")
    p.add_argument("--dry-run", action="store_true", help="report counts and check every value; write nothing")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    args = _parser().parse_args(argv)
    from marvin.core.config import get_app_settings

    settings = get_app_settings()
    if settings.DB_ENGINE != "postgres" or not settings.DB_URL:
        log.error("DB_ENGINE must be postgres (with POSTGRES_* set): the target is the app's own database")
        return 2
    engine = sa.create_engine(settings.DB_URL, pool_pre_ping=True)
    log.info("source %s -> target %s", args.source, settings.DB_URL_PUBLIC)
    try:
        src = open_source(args.source)
        if args.dry_run:
            report = survey(src, engine, args.batch_size)
        else:
            migrate_target()
            logging.getLogger().setLevel(logging.INFO)  # alembic's fileConfig resets logging
            report = copy_database(src, engine, truncate=args.truncate, batch_size=args.batch_size)
    except CopyError as exc:
        log.error("%s", exc)
        return 1
    for line in report.lines():
        sys.stdout.write(line + "\n")
    for problem in report.problems:
        sys.stdout.write(f"problem: {problem}\n")
    if report.problem_count > len(report.problems):
        sys.stdout.write(f"... and {report.problem_count - len(report.problems)} more problem(s)\n")
    status = "DRY RUN" if args.dry_run else "COPIED"
    sys.stdout.write(
        f"{status}: revision {report.revision}, {len(report.tables)} tables, {sum(t.source_rows for t in report.tables)} rows, "
        f"{report.foreign_keys} foreign keys re-validated, {report.sequences_reset} sequences reset, {report.problem_count} problem(s)\n"
    )
    return 1 if report.problem_count else 0


if __name__ == "__main__":
    sys.exit(main())
