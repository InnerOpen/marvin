"""Names shared by the SQLite transaction recipe in ``db_setup`` and the code that asks for the write lock."""

SQLITE_BEGIN_OPTION = "sqlite_begin"
"""Execution option naming the statement that starts a SQLite transaction: ``DEFERRED`` (default) or ``IMMEDIATE``."""
