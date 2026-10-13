"""
This module handles the global setup for the SQLAlchemy database connection.

It initializes the database engine and session maker, and provides
functions for generating and managing database sessions.
"""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from marvin.core.config import get_app_settings

settings = get_app_settings()


def sql_global_init(db_url: str) -> tuple[sessionmaker[Session], sa.engine.Engine]:
    """
    Initializes the SQLAlchemy engine and session maker.

    Args:
        db_url (str): The database connection URL.

    Returns:
        tuple[sessionmaker[Session], sa.engine.Engine]: A tuple containing the
            session maker (SessionLocal) and the database engine.
    """
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
