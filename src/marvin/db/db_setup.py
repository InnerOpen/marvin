"""
This module handles the global setup for the SQLAlchemy database connection.

It initializes the database engine and session maker, and provides
functions for generating and managing database sessions.
"""

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from marvin.core.config import get_app_settings
from marvin.db.locking import SQLITE_BEGIN_OPTION

logger = logging.getLogger(__name__)

settings = get_app_settings()

SQLITE_MIN_VERSION = (3, 35, 0)
"""Oldest SQLite the schema and queries are written for (``ALTER TABLE ... DROP COLUMN``, ``RETURNING``)."""

_DML = ("INSERT", "UPDATE", "DELETE", "REPLACE", "SAVEPOINT")
"""Statements that must run inside a transaction we began: a write, or a SAVEPOINT (outside one, SQLite makes the
SAVEPOINT the transaction and RELEASE commits it)."""


def check_sqlite_version(version: tuple[int, ...] | None = None) -> str:
    """Return the SQLite library version string, raising when it is older than ``SQLITE_MIN_VERSION``."""
    found = version or sqlite3.sqlite_version_info
    text = ".".join(str(part) for part in found)
    if tuple(found) < SQLITE_MIN_VERSION:
        needed = ".".join(str(part) for part in SQLITE_MIN_VERSION)
        raise RuntimeError(f"SQLite {text} is too old: Marvin needs {needed} or newer (the library Python was built with).")
    return text


def _configure_sqlite(engine: sa.engine.Engine) -> None:
    """Pragmas and the transaction recipe for a SQLite engine.

    pysqlite's own transaction handling is wrong for SQLAlchemy in one way that matters: it begins its transaction
    lazily before the first INSERT/UPDATE/DELETE, so a SAVEPOINT taken before that is released into autocommit and a
    later rollback cannot undo the work (a claim inside ``begin_nested()`` stayed claimed). SQLAlchemy's documented fix
    is ``isolation_level = None`` plus a ``BEGIN`` of our own. We keep pysqlite's lazy timing for the begin itself:
    ``BEGIN`` goes out just before the first write or SAVEPOINT, and reads stay outside any transaction. A ``BEGIN``
    in the ``begin`` event instead would hold every session's first read as a snapshot until it ends, and a session
    that then writes after someone else committed fails at once with SQLITE_BUSY_SNAPSHOT: Postgres's READ COMMITTED
    behaviour, which the code was written against, has no such failure. A unit of work that needs the write lock
    before it reads asks for it with the ``sqlite_begin="IMMEDIATE"`` execution option (``db.locking.begin_write``).
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, connection_record):
        dbapi_conn.isolation_level = None  # pysqlite stops emitting BEGIN; see docstring
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={int(settings.DB_SQLITE_BUSY_TIMEOUT_MS)}")
            if settings.DB_SQLITE_WAL_MODE:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")  # safe under WAL: a power cut can lose the last commits, not corrupt
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        mode = str(conn.get_execution_options().get(SQLITE_BEGIN_OPTION, "DEFERRED")).upper()
        if mode not in ("DEFERRED", "IMMEDIATE"):
            raise ValueError(f"{SQLITE_BEGIN_OPTION}={mode!r}: DEFERRED or IMMEDIATE")
        if mode == "IMMEDIATE":
            conn.exec_driver_sql("BEGIN IMMEDIATE")  # the write lock now; DEFERRED waits for the first write

    @event.listens_for(engine, "before_cursor_execute")
    def _lazy_begin(conn, cursor, statement, parameters, context, executemany):
        raw = conn.connection.dbapi_connection
        if not raw.in_transaction and statement.lstrip()[:9].upper().startswith(_DML):
            raw.execute("BEGIN")


def sql_global_init(db_url: str) -> tuple[sessionmaker[Session], sa.engine.Engine]:
    """
    Initializes the SQLAlchemy engine and session maker.

    Args:
        db_url (str): The database connection URL.

    Returns:
        tuple[sessionmaker[Session], sa.engine.Engine]: A tuple containing the
            session maker (SessionLocal) and the database engine.
    """
    if db_url.startswith("sqlite"):
        logger.info("SQLite %s", check_sqlite_version())
        # Connections are shared across the request threadpool (FastAPI runs sync routes in worker threads);
        # SQLAlchemy's pool hands each to one thread at a time. A file database gets a QueuePool.
        engine = sa.create_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
            future=True,
            connect_args={"check_same_thread": False},
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
        _configure_sqlite(engine)
        if engine.url.database:
            # Create the file now (a fresh install has none): the startup guard reads "no marvin.db" as a lost database.
            Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
            engine.connect().close()
    else:
        engine = sa.create_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
            future=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

    return SessionLocal, engine


SessionLocal, engine = sql_global_init(settings.DB_URL)  # type: ignore


@contextmanager
def session_context() -> Session:
    """
    session_context() provides a managed session to the database that is automatically
    closed when the context is exited. This is the preferred method of accessing the
    database.

    Note: use `generate_session` when using the `Depends` function from FastAPI
    """
    global SessionLocal
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()


def generate_session() -> Generator[Session, None, None]:
    """
    WARNING: This function should _only_ be called when used with
    using the `Depends` function from FastAPI. This function will leak
    sessions if used outside of the context of a request.

    Use `with_session` instead. That function will allow you to use the
    session within a context manager
    """
    global SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
