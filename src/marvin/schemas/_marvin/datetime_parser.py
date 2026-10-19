"""
This module provides datetime parsing utilities, originally sourced from Pydantic V1.
(Source: https://github.com/pydantic/pydantic/blob/abcf81ec104d2da70894ac0402ae11a7186c5e47/pydantic/datetime_parse.py)

It includes functions to parse strings, numbers, or existing datetime objects into
standard Python `date`, `time`, `datetime`, and `timedelta` objects.
The parsing logic supports various common formats, including ISO 8601 and Unix timestamps.
Custom error classes are defined for parsing failures.

This utility is likely used within Marvin for consistent datetime handling when
processing input data for Pydantic models or other components requiring datetime objects.
"""

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# Regular expression for YYYY-MM-DD date format.
date_expr = r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
# Regular expression for HH:MM[:SS[.ffffff]][Z or +/-HH[:MM]] time format.
time_expr = (
    r"(?P<hour>\d{1,2}):(?P<minute>\d{1,2})"
    r"(?::(?P<second>\d{1,2})(?:\.(?P<microsecond>\d{1,6})\d{0,6})?)?"  # Optional seconds and microseconds
    r"(?P<tzinfo>Z|[+-]\d{2}(?::?\d{2})?)?$"  # Optional timezone information (Z, +HH:MM, or +HHMM)
)

datetime_re = re.compile(f"^{date_expr}[T ]{time_expr}$")  # Matches datetime string with 'T' or space separator.


# Epoch reference for Unix timestamp conversions (UTC).
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Watershed value to differentiate between timestamps in seconds vs. milliseconds.
# If a numeric timestamp is greater than this, it's assumed to be in milliseconds.
# (2e10 seconds is approx. 11th Oct 2603; 2e10 milliseconds is approx. 20th Aug 1970)
MS_WATERSHED = int(2e10)

# Maximum numeric value for timestamp conversion to avoid overflow with datetime.max.
# Corresponds to a value slightly larger than `(datetime.max - EPOCH).total_seconds() * 1e9` (nanoseconds).
MAX_NUMBER = int(3e20)


class DateTimeError(ValueError):
    """Raised when datetime parsing fails due to invalid format or value."""

    def __init__(self, *args: object) -> None:
        super().__init__("invalid datetime format")


def get_numeric(value: str | bytes | int | float, native_expected_type: str) -> float | None:  # Return float | None for consistency
    """
    Attempts to convert a value to a float if it's a string or bytes.
    Returns integers and floats directly. Returns None if conversion from string/bytes fails.

    Args:
        value (str | bytes | int | float): The input value to convert.
        native_expected_type (str): A string describing the expected Python type (e.g., "date", "time")
                                    used in error messages if a TypeError occurs for an unexpected input type.

    Returns:
        float | None: The numeric representation of the value, or None if conversion is not possible.

    Raises:
        TypeError: If the input `value` is of an unexpected type (not str, bytes, int, or float).
    """
    if isinstance(value, int | float):
        return float(value)  # Ensure float for consistency with downstream parsing
    if isinstance(value, str | bytes):  # Ensure value is str or bytes before trying float()
        try:
            return float(value)
        except ValueError:  # If string/bytes cannot be converted to float
            return None
    # If not int, float, str, or bytes, it's an unexpected type for numeric conversion in this context.
    raise TypeError(f"invalid type; expected {native_expected_type}, string, bytes, int or float, got {type(value).__name__}")


def from_unix_seconds(seconds: int | float) -> datetime:
    """
    Converts a Unix timestamp (seconds or milliseconds since epoch) to a UTC datetime object.

    Handles very large or small timestamp values by clamping to `datetime.max` or `datetime.min`.
    Automatically detects if the timestamp is in milliseconds based on `MS_WATERSHED`.

    Args:
        seconds (int | float): The Unix timestamp.

    Returns:
        datetime: The corresponding datetime object in UTC.
    """
    # Clamp to datetime.max/min for extreme values to prevent OverflowError
    if seconds > MAX_NUMBER:  # MAX_NUMBER is a very large number, effectively for nanoseconds scale
        return datetime.max.replace(tzinfo=UTC)
    elif seconds < -MAX_NUMBER:  # Similar for negative (before epoch)
        return datetime.min.replace(tzinfo=UTC)

    # If timestamp appears to be in milliseconds, convert to seconds
    current_seconds = seconds
    while abs(current_seconds) > MS_WATERSHED:
        current_seconds /= 1000

    # Create datetime object from epoch and timedelta, then set timezone to UTC
    dt = EPOCH + timedelta(seconds=current_seconds)
    return dt  # EPOCH is already UTC, timedelta preserves that. No need for .replace(tzinfo=timezone.utc) again.


def _parse_timezone(value: str | None, error_type: type[Exception]) -> timezone | None:  # Corrected return type
    """
    Parses a timezone string (e.g., "Z", "+05:00", "-0800") into a `datetime.timezone` object.

    Args:
        value (str | None): The timezone string to parse.
        error_type (type[Exception]): The type of exception to raise if parsing fails (e.g., TimeError, DateTimeError).

    Returns:
        timezone | None: A `datetime.timezone` object representing the offset,
                         or `timezone.utc` for "Z", or None if no timezone string is provided.

    Raises:
        Exception (of type `error_type`): If the timezone string is malformed or represents an invalid offset.
    """
    if value == "Z":  # UTC Zulu time
        return UTC
    elif value is not None:
        # Parse +/-HH:MM or +/-HHMM format
        offset_sign = -1 if value[0] == "-" else 1
        # Extract numerical parts of the offset string
        offset_hours_str = value[1:3]
        offset_minutes_str = value[4:6] if len(value) > 3 and value[3] == ":" else value[3:5] if len(value) > 3 else "00"

        try:
            offset_hours = int(offset_hours_str)
            offset_minutes = int(offset_minutes_str)
        except ValueError as e:  # Handle cases where parts are not integers
            raise error_type(f"Invalid timezone offset format: {value}") from e

        # Calculate total offset in minutes
        total_offset_minutes = offset_sign * (offset_hours * 60 + offset_minutes)

        try:
            return timezone(timedelta(minutes=total_offset_minutes))
        except ValueError as e:  # If timedelta results in an out-of-range offset
            raise error_type(f"Invalid timezone offset value: {value}") from e
    else:  # No timezone information provided
        return None


def parse_datetime(value: datetime | str | bytes | int | float) -> datetime:
    """
    Parse a datetime from various input types (datetime, int, float, str, bytes)
    and return a `datetime.datetime` object.

    Supports Unix timestamps (seconds or milliseconds) and string formats like
    "YYYY-MM-DD[T ]HH:MM[:SS[.ffffff]][offset]". If an offset is present in the
    string or implied by Unix timestamp (which is UTC), the resulting `datetime`
    object will be timezone-aware.

    Args:
        value: The input value to parse.

    Returns:
        datetime.datetime: The parsed datetime object.

    Raises:
        DateTimeError: If the input is well-formatted but not a valid datetime,
                       or if the input string format is incorrect.
        TypeError: If the input type is invalid for datetime parsing.
    """
    if isinstance(value, datetime):  # If already a datetime object, return it
        return value

    # Try parsing as a numeric Unix timestamp
    numeric_value = get_numeric(value, "datetime")  # Raises TypeError for invalid types
    if numeric_value is not None:
        return from_unix_seconds(numeric_value)  # Returns UTC datetime

    # If not numeric, assume string or bytes
    if isinstance(value, bytes):
        value_str = value.decode()
    elif isinstance(value, str):
        value_str = value
    else:
        raise DateTimeError()

    match = datetime_re.match(value_str)  # Match against "YYYY-MM-DD[T ]HH:MM..." format
    if match is None:
        raise DateTimeError()

    kw = match.groupdict()
    # Ensure microseconds are 6 digits long
    if kw["microsecond"]:
        kw["microsecond"] = kw["microsecond"].ljust(6, "0")

    # Parse timezone information if present
    parsed_tzinfo = _parse_timezone(kw.pop("tzinfo"), DateTimeError)

    # Convert matched string parts to integers
    datetime_params: dict[str, Any] = {k: int(v) for k, v in kw.items() if v is not None}
    datetime_params["tzinfo"] = parsed_tzinfo  # Add parsed timezone

    try:
        return datetime(**datetime_params)  # noqa: DTZ001 Create datetime object
    except ValueError as e:  # Catch errors from invalid datetime values
        raise DateTimeError() from e
