"""Enforce ``String(N)`` on SQLite, as Postgres does.

SQLite ignores the length in ``VARCHAR(N)``: a 60-character value goes into a ``String(32)`` column without complaint,
and the code then fails the first time it runs on Postgres (``value too long for type character varying(32)``). On
SQLite this checks each new or changed row at flush and raises the same ``DataError`` Postgres would, so the suite
(and a SQLite install) finds the column-length bug where it is written. It is installed only for a SQLite engine;
Postgres enforces the length itself.

Bulk statements (``Query.update``, Core ``insert``) never flush an object and are not checked.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import event, inspect
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Mapper, Session

_limits: dict[Mapper, tuple[tuple[str, str, int], ...]] = {}
_installed = False


def _limited_columns(mapper: Mapper) -> tuple[tuple[str, str, int], ...]:
    """(attribute key, column name, N) for each plain ``String(N)`` column the mapper maps. Enums and type decorators
    validate or convert their own values, so they are left alone."""
    if mapper not in _limits:
        found = []
        for prop in mapper.column_attrs:
            column = prop.columns[0]
            kind = column.type
            if isinstance(kind, sa.String) and not isinstance(kind, sa.Enum) and kind.length:
                found.append((prop.key, column.name, kind.length))
        _limits[mapper] = tuple(found)
    return _limits[mapper]


def check_lengths(session: Session, flush_context, instances) -> None:
    """``before_flush``: raise ``DataError`` for a value longer than its ``String(N)`` column."""
    for obj in (*session.new, *session.dirty):
        state = inspect(obj)
        for key, column, length in _limited_columns(state.mapper):
            value = state.dict.get(key)  # what is loaded or set: never triggers a load
            if isinstance(value, str) and len(value) > length:
                raise DataError(
                    None,
                    None,
                    ValueError(
                        f"value too long for type character varying({length}): {state.mapper.local_table.name}.{column} ({len(value)} characters)"
                    ),
                )


def install() -> None:
    """Check every session's flushes (once per process)."""
    global _installed
    if not _installed:
        event.listen(Session, "before_flush", check_lengths)
        _installed = True
