"""Write locking for SQLite, and the watchdog that reports a writer holding it too long.

SQLite has one writer at a time. A transaction that starts as a reader and then writes (SQLAlchemy's default: BEGIN is
deferred) must upgrade its read snapshot to the write lock, and if another connection wrote in between it fails at
once with SQLITE_BUSY_SNAPSHOT: ``busy_timeout`` cannot help, because waiting would not make the snapshot any fresher.
A unit of work that is about to write, and must not lose a race (claiming an idempotency key, a one-use link, a
once-per email), calls ``begin_write`` first: its transaction then starts with ``BEGIN IMMEDIATE``, taking the write
lock up front, and a competing writer waits on ``busy_timeout`` instead of failing. On Postgres it does nothing:
unique indexes and row locks already serialize those races.

The cost of the lock is that every other writer waits while it is held, so a write transaction must stay short. A
session held across an LLM or HTTP call stalls the whole app; ``watch_writes`` warns (with where that thread is stuck)
when one stays open past ``DB_SQLITE_WRITE_WARN_SECONDS``.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SQLITE_BEGIN_OPTION = "sqlite_begin"
"""Execution option naming the statement that starts a SQLite transaction: ``DEFERRED`` (default) or ``IMMEDIATE``."""


def begin_write(session: Session) -> None:
    """Make the session's next transaction a writer from its first statement (SQLite); no-op elsewhere.

    Ends the transaction the session has open (committing what it holds: the call sites do so anyway right after
    their claim), then begins the next one as ``BEGIN IMMEDIATE`` and returns with the write lock held. Call it
    before reading the state a write depends on, at the top of the unit of work, not in the middle of one.
    """
    bind = session.get_bind()
    if isinstance(bind, Connection) or bind.dialect.name != "sqlite":
        return
    if session.in_transaction():
        session.commit()
    session.connection(execution_options={SQLITE_BEGIN_OPTION: "IMMEDIATE"})


# ── the long-write-transaction watchdog ─────────────────────────────────────────────────────────────────────────

_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


@dataclass
class _OpenWrite:
    since: float
    thread_id: int
    statement: str
    warned: bool = False


class _Watchdog:
    """One daemon thread scanning the SQLite write transactions that are open, warning once for each that is slow."""

    def __init__(self, threshold: float):
        self.threshold = threshold
        self.interval = max(0.05, min(1.0, threshold / 4))
        self.open: dict[int, _OpenWrite] = {}
        self._lock = threading.Lock()
        self._tick = threading.Event()  # never set: waiting on it is a sleep that a test patching time.sleep cannot hijack
        self._thread: threading.Thread | None = None

    def started(self, dbapi_conn, statement: str) -> None:
        key = id(dbapi_conn)
        with self._lock:
            if key in self.open:
                return
            self.open[key] = _OpenWrite(time.monotonic(), threading.get_ident(), " ".join(statement.split())[:200])
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="sqlite-write-watchdog", daemon=True)
                self._thread.start()

    def ended(self, dbapi_conn) -> None:
        with self._lock:
            self.open.pop(id(dbapi_conn), None)

    def _run(self) -> None:
        while True:
            self._tick.wait(self.interval)
            now = time.monotonic()
            with self._lock:
                slow = [w for w in self.open.values() if not w.warned and now - w.since >= self.threshold]
                for w in slow:
                    w.warned = True
            for w in slow:
                frame = sys._current_frames().get(w.thread_id)
                where = "".join(traceback.format_stack(frame, limit=12)) if frame is not None else "(thread has gone)"
                logger.warning(
                    "SQLite write transaction open for %.1fs (first write: %s). Every other writer is waiting on it: "
                    "a session must not be held across an AI, HTTP or other slow call. The thread is at:\n%s",
                    now - w.since,
                    w.statement,
                    where,
                )


def watch_writes(engine: sa.engine.Engine, threshold_seconds: float) -> _Watchdog | None:
    """Warn when a write transaction on this SQLite engine stays open past ``threshold_seconds`` (0 turns it off)."""
    if threshold_seconds <= 0:
        return None
    dog = _Watchdog(threshold_seconds)

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        head = statement.lstrip()[:16].upper()
        if head.startswith(_WRITES) or head.startswith("BEGIN IMMEDIATE"):
            dog.started(conn.connection.dbapi_connection, statement)

    @event.listens_for(engine, "commit")
    def _commit(conn):
        dog.ended(conn.connection.dbapi_connection)

    @event.listens_for(engine, "rollback")
    def _rollback(conn):
        dog.ended(conn.connection.dbapi_connection)

    @event.listens_for(engine, "checkin")
    def _checkin(dbapi_conn, record):  # back in the pool by any road: nothing is open on it
        dog.ended(dbapi_conn)

    return dog
