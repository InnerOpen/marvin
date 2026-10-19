"""
This module provides custom datetime utilities for SQLAlchemy models in Marvin.

It includes:
- Functions to get the current UTC time (`get_utc_now`) and date (`get_utc_today`).
- A SQLAlchemy `TypeDecorator` called `NaiveDateTime` to ensure that all datetimes
  are stored in the database as naive (timezone-unaware) UTC and are converted
  back to timezone-aware UTC when retrieved. This standardizes datetime handling
  across different database backends.
- `AwareDateTime`, for the columns that are timezone-aware on Postgres (`timestamptz`): SQLite stores no zone, so
  it hands back naive values that fail against an aware `now`; this stores UTC and hands back aware UTC on both.
"""

from datetime import UTC, datetime

from sqlalchemy.types import DateTime, TypeDecorator


def get_utc_now():
    """
    Returns the current time in UTC.
    """
    return datetime.now(UTC)


class NaiveDateTime(TypeDecorator):
    """
    Mealie uses naive date times since the app handles timezones explicitly.
    All timezones are generated, stored, and retrieved as UTC.

    This class strips the timezone from a datetime object when storing it so the database (i.e. postgres)
    doesn't do any timezone conversion when storing the datetime, then re-inserts UTC when retrieving it.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return value

        try:
            if value.tzinfo is not None:
                value = value.astimezone(UTC)
            return value.replace(tzinfo=None)
        except Exception:
            return value

    def process_result_value(self, value: datetime | None, dialect):
        try:
            if value is not None:
                value = value.replace(tzinfo=UTC)
        except Exception:
            pass

        return value


class AwareDateTime(TypeDecorator):
    """A `timestamptz` column on Postgres (the same DDL as `DateTime(timezone=True)`, so no migration), aware UTC on SQLite.

    SQLite keeps the wall-clock text it is given and returns a naive datetime, which raises `TypeError` the first time
    it is compared with an aware `datetime.now(UTC)`. Values are converted to UTC on the way in (a naive one is taken to
    be UTC already, the convention everywhere in Marvin) and tagged UTC on the way out. Postgres already does both, so
    its values pass through untouched.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("timezone", True)
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value: datetime | None, dialect):
        if value is not None and dialect.name == "sqlite" and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
