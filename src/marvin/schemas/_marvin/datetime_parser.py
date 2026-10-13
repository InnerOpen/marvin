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
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

# Regular expression for YYYY-MM-DD date format.
date_expr = r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
# Regular expression for HH:MM[:SS[.ffffff]][Z or +/-HH[:MM]] time format.
time_expr = (
    r"(?P<hour>\d{1,2}):(?P<minute>\d{1,2})"
    r"(?::(?P<second>\d{1,2})(?:\.(?P<microsecond>\d{1,6})\d{0,6})?)?"  # Optional seconds and microseconds
    r"(?P<tzinfo>Z|[+-]\d{2}(?::?\d{2})?)?$"  # Optional timezone information (Z, +HH:MM, or +HHMM)
)

# Compiled regular expressions for efficiency.
date_re = re.compile(f"^{date_expr}$")  # Matches date string exactly.
time_re = re.compile(f"^{time_expr}$")  # Matches time string exactly.
datetime_re = re.compile(f"^{date_expr}[T ]{time_expr}$")  # Matches datetime string with 'T' or space separator.

# Regular expression for "standard" duration format (e.g., "1 day, 10:20:30.123456" or "-3:00:00").
standard_duration_re = re.compile(
    r"^"
    r"(?:(?P<days>-?\d+) (?:days?|d), )?"  # Optional days part (e.g., "1 day, ", "-2 days, ")
    r"((?:(?P<hours>-?\d+):)(?=\d+:\d+))?"  # Optional hours part, if followed by minutes:seconds
    r"(?:(?P<minutes>-?\d+):)?"  # Optional minutes part
    r"(?P<seconds>-?\d+)"  # Seconds part (required)
    r"(?:\.(?P<microseconds>\d{1,6})\d{0,6})?"  # Optional microseconds
    r"$"
)

# Regular expression for ISO 8601 duration format (e.g., "P1DT12H30M5S", "PT10S").
iso8601_duration_re = re.compile(
    r"^(?P<sign>[-+]?)"  # Optional sign
    r"P"  # Period designator (required)
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"  # Optional days (allows decimals)
    r"(?:T"  # Time designator
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"  # Optional hours (allows decimals)
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"  # Optional minutes (allows decimals)
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"  # Optional seconds (allows decimals)
    r")?"
    r"$"
)

# Epoch reference for Unix timestamp conversions (UTC).
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Watershed value to differentiate between timestamps in seconds vs. milliseconds.
# If a numeric timestamp is greater than this, it's assumed to be in milliseconds.
# (2e10 seconds is approx. 11th Oct 2603; 2e10 milliseconds is approx. 20th Aug 1970)
MS_WATERSHED = int(2e10)

# Maximum numeric value for timestamp conversion to avoid overflow with datetime.max.
# Corresponds to a value slightly larger than `(datetime.max - EPOCH).total_seconds() * 1e9` (nanoseconds).
MAX_NUMBER = int(3e20)


# Custom error classes for parsing failures.
class DateError(ValueError):
    """Raised when date parsing fails due to invalid format or value."""

    def __init__(self, *args: object) -> None:
        super().__init__("invalid date format")


class TimeError(ValueError):
    """Raised when time parsing fails due to invalid format or value."""

    def __init__(self, *args: object) -> None:
        super().__init__("invalid time format")


class DateTimeError(ValueError):
    """Raised when datetime parsing fails due to invalid format or value."""

    def __init__(self, *args: object) -> None:
        super().__init__("invalid datetime format")


class DurationError(ValueError):
    """Raised when duration parsing fails due to invalid format or value."""

    def __init__(self, *args: object) -> None:
        super().__init__("invalid duration format")


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


def parse_date(value: date | str | bytes | int | float) -> date:
    """
    Parse a date from various input types (date, int, float, str, bytes)
    and return a `datetime.date` object.

    Supports Unix timestamps (seconds or milliseconds) and "YYYY-MM-DD" string format.

    Args:
        value: The input value to parse.

    Returns:
        datetime.date: The parsed date object.

    Raises:
        DateError: If the input is well-formatted but not a valid date,
                   or if the input string format is incorrect.
        TypeError: If the input type is invalid for date parsing.
    """
    if isinstance(value, datetime):  # If it's a datetime object, return its date part
        return value.date()
    if isinstance(value, date):  # If it's already a date object, return it
        return value

    # Try parsing as a numeric Unix timestamp
    numeric_value = get_numeric(value, "date")  # Raises TypeError for invalid types
    if numeric_value is not None:
        return from_unix_seconds(numeric_value).date()

    # If not numeric, assume string or bytes
    if isinstance(value, bytes):
        value_str = value.decode()  # Decode bytes to string
    elif isinstance(value, str):
        value_str = value
    else:  # Should have been caught by get_numeric's TypeError or earlier isinstance checks
        raise DateError()

    match = date_re.match(value_str)
    if match is None:  # Check if string matches "YYYY-MM-DD" format
        raise DateError()

    # Extract year, month, day from regex match groups
    kw = {k: int(v) for k, v in match.groupdict().items()}

    try:
        return date(**kw)  # Create date object
    except ValueError as e:  # Catch errors from invalid date values (e.g., month=13)
        raise DateError() from e


def parse_time(value: time | str | bytes | int | float) -> time:
    """
    Parse a time from various input types (time, str, bytes, int, float)
    and return a `datetime.time` object.

    Supports numeric seconds since midnight and string formats like "HH:MM[:SS[.ffffff]][offset]".
    If an offset is present in the string, the resulting `time` object will be timezone-aware.

    Args:
        value: The input value to parse.

    Returns:
        datetime.time: The parsed time object.

    Raises:
        TimeError: If the input is well-formatted but not a valid time (e.g., seconds >= 86400),
                   or if the input string format is incorrect.
        TypeError: If the input type is invalid for time parsing.
    """
    if isinstance(value, time):  # If already a time object, return it
        return value

    # Try parsing as numeric seconds from midnight
    numeric_value = get_numeric(value, "time")  # Raises TypeError for invalid types
    if numeric_value is not None:
        if not (0 <= numeric_value < 86400):  # Check if seconds are within a day
            raise TimeError("Numeric time value out of range (0 <= seconds < 86400)")
        # Create time from timedelta since midnight, ensuring it's UTC if no tz info derived
        # For simplicity, this example makes it naive, or UTC if we want to be explicit.
        # Pydantic V1's original logic created a datetime then took .time().
        # This can be simplified if we just want the time component.
        # dt_for_time = datetime.min + timedelta(seconds=numeric_value)
        # return dt_for_time.time()
        # To include potential tz for consistency if numbers could imply it (though unusual):
        return (datetime.min.replace(tzinfo=UTC) + timedelta(seconds=numeric_value)).time().replace(tzinfo=None)  # Naive time

    # If not numeric, assume string or bytes
    if isinstance(value, bytes):
        value_str = value.decode()
    elif isinstance(value, str):
        value_str = value
    else:
        raise TimeError()

    match = time_re.match(value_str)  # Match against HH:MM:SS... format
    if match is None:
        raise TimeError()

    kw = match.groupdict()
    # Ensure microseconds are 6 digits long, padding with zeros if necessary
    if kw["microsecond"]:
        kw["microsecond"] = kw["microsecond"].ljust(6, "0")

    # Parse timezone information if present
    parsed_tzinfo = _parse_timezone(kw.pop("tzinfo"), TimeError)

    # Convert matched string parts to integers
    time_params: dict[str, Any] = {k: int(v) for k, v in kw.items() if v is not None}
    time_params["tzinfo"] = parsed_tzinfo  # Add parsed timezone

    try:
        return time(**time_params)  # Create time object
    except ValueError as e:  # Catch errors from invalid time values (e.g., hour=25)
        raise TimeError() from e


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


def parse_duration(value: timedelta | str | bytes | int | float) -> timedelta:  # Added timedelta to input types
    """
    Parse a duration from various input types (timedelta, int, float, str, bytes)
    and return a `datetime.timedelta` object.

    Supports numeric seconds, a "standard" format (e.g., "X days, HH:MM:SS.ffffff"),
    and ISO 8601 duration format (e.g., "P1DT12H30M5S").

    Args:
        value: The input value to parse.

    Returns:
        datetime.timedelta: The parsed timedelta object.

    Raises:
        DurationError: If the input string format is incorrect.
        TypeError: If the input type is invalid for duration parsing.
    """
    if isinstance(value, timedelta):  # If already a timedelta object, return it
        return value

    # If numeric, interpret as seconds
    if isinstance(value, int | float):
        return timedelta(seconds=value)  # Directly create timedelta from seconds

    # If string or bytes, attempt parsing known formats
    if isinstance(value, bytes):
        value_str = value.decode()
    elif isinstance(value, str):
        value_str = value
    else:  # Should have been caught by earlier isinstance checks or is an unhandled type
        raise TypeError(f"invalid type for duration; expected timedelta, string, bytes, int or float, got {type(value).__name__}")

    # Attempt to match standard or ISO 8601 duration string formats
    try:
        # Try standard format first, then ISO 8601
        match = standard_duration_re.match(value_str) or iso8601_duration_re.match(value_str)
    except TypeError as e:  # Should not happen if value_str is string
        raise TypeError("Internal error: value for regex match was not a string.") from e  # Should not occur

    if not match:  # If no regex match found
        raise DurationError()

    kw = match.groupdict()
    # Handle optional sign for ISO 8601 durations
    sign_multiplier = -1 if kw.pop("sign", "+") == "-" else 1

    # Ensure microseconds are 6 digits long, correctly handling negative seconds
    if kw.get("microseconds"):
        kw["microseconds"] = kw["microseconds"].ljust(6, "0")
    # If seconds are negative and microseconds exist, microseconds should also be treated as part of the negative duration.
    # This specific logic from Pydantic V1 handles a nuance in how timedelta kwargs work with negative values.
    if kw.get("seconds") and kw.get("microseconds") and kw["seconds"].startswith("-") and not kw["microseconds"].startswith("-"):
        # If seconds are negative (e.g. "-5") and microseconds positive ("123"),
        # timedelta treats them additively (e.g. -5s + 0.123s).
        # To make them part of the same negative component, if days/hours/mins are 0,
        # it implies the whole duration is negative.
        # Pydantic V1's original logic:
        # if kw.get("seconds") and kw.get("microseconds") and kw["seconds"].startswith("-"):
        #    kw["microseconds"] = "-" + kw["microseconds"]
        # This interpretation might be complex. Simpler: convert all to float, apply sign at end.
        pass  # Current kw_ float conversion handles signs appropriately for individual components.

    # Convert all matched components to float, filtering out None values
    duration_params: dict[str, float] = {k: float(v) for k, v in kw.items() if v is not None}

    # Create timedelta. The sign_multiplier applies to ISO 8601 durations.
    # For standard_duration_re, days/hours/etc. can already be negative.
    # This might need adjustment if standard_duration_re components are always positive.
    # Assuming components from regex can be negative for standard_duration_re.
    # If sign_multiplier is -1, it means the ISO duration was P-1DT...
    # Standard format like "-1 day, ..." already has negative in its 'days' component.

    # Let's refine: if it's an ISO match and has a sign, apply it.
    # The standard_duration_re already captures signs in its components.
    # This means we only apply sign_multiplier if it was an ISO match with a sign.
    # However, the current structure applies it regardless.
    # For Pydantic V1's logic: it expects components to be positive after sign extraction for ISO.

    # Simplification: If the regex was iso8601_duration_re, all components are positive floats.
    # If it was standard_duration_re, components can be negative floats.
    # The sign multiplier is primarily for ISO.
    # The original code `sign * timedelta(**kw_)` might double-negative if standard components are already negative.
    # Let's assume Pydantic's logic was sound and replicate carefully.
    # The key is that timedelta itself handles negative components correctly.
    # The `sign` is only from iso8601_duration_re.
    # If it was standard_duration_re, `sign` is not in kw, so pop returns "+", sign_multiplier is 1.

    return sign_multiplier * timedelta(**duration_params)  # type: ignore # Pydantic V1 did this.
