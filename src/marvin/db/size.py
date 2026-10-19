"""How big the database is, and which tables make it up, on either engine.

Postgres answers from its catalogs. SQLite is a file: its size is that file plus its write-ahead log, and the per-table
split comes from the ``dbstat`` virtual table when this SQLite was built with it (most are), else from row counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class TableSize:
    name: str
    size_bytes: int  # table plus its indexes; 0 when the engine cannot say
    rows: int


def _sqlite_file(session: Session) -> Path | None:
    database = session.get_bind().url.database  # type: ignore[union-attr]
    return Path(database) if database and database != ":memory:" else None


def sqlite_file_bytes(path: Path | str) -> int:
    """A SQLite database's size on disk: the file and its write-ahead log."""
    path = Path(path)
    return sum(p.stat().st_size for p in (path, path.with_name(path.name + "-wal")) if p.exists())


def database_size_bytes(session: Session) -> int:
    """The database's size in bytes (SQLite: the file and its ``-wal``). Raises if the engine can't say."""
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        return int(session.execute(sa.text("SELECT pg_database_size(current_database())")).scalar() or 0)
    path = _sqlite_file(session)
    if path is None:
        return int(
            session.execute(sa.text("SELECT (SELECT page_count FROM pragma_page_count) * (SELECT page_size FROM pragma_page_size)")).scalar() or 0
        )
    return sqlite_file_bytes(path)


def _sqlite_tables(session: Session) -> list[str]:
    rows = session.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"))
    return [r[0] for r in rows]


def largest_tables(session: Session, limit: int) -> list[TableSize]:
    """The ``limit`` biggest tables, largest first (SQLite without ``dbstat``: the ones with the most rows)."""
    if session.get_bind().dialect.name != "sqlite":
        rows = session.execute(
            sa.text(
                "SELECT relname, pg_total_relation_size(relid) AS bytes, n_live_tup FROM pg_stat_user_tables "
                "ORDER BY pg_total_relation_size(relid) DESC LIMIT :n"
            ),
            {"n": limit},
        ).all()
        return [TableSize(name, int(nbytes or 0), max(int(live or 0), 0)) for name, nbytes, live in rows]

    sizes: dict[str, int] = {}
    try:
        for name, nbytes in session.execute(
            sa.text("SELECT m.tbl_name, SUM(d.pgsize) FROM dbstat d JOIN sqlite_master m ON m.name = d.name GROUP BY m.tbl_name")
        ):
            sizes[name] = int(nbytes or 0)
    except sa.exc.OperationalError:  # SQLite built without SQLITE_ENABLE_DBSTAT_VTAB
        session.rollback()
    tables = _sqlite_tables(session)
    # Row counts are exact here (SQLite keeps no estimate), so count only what will be shown: the biggest by size,
    # or every table when there are no sizes to rank by.
    ranked = sorted(tables, key=lambda t: sizes.get(t, 0), reverse=True)[:limit] if sizes else tables
    counted = [TableSize(t, sizes.get(t, 0), int(session.execute(sa.text(f'SELECT count(*) FROM "{t}"')).scalar() or 0)) for t in ranked]
    counted.sort(key=lambda t: (t.size_bytes, t.rows), reverse=True)
    return counted[:limit]
