"""
This module provides convenient aliases for custom database types used in migrations.

It re-exports `datetime`, `NaiveDateTime`, `HttpUrlType`, and `GUID` types from their respective model utility
modules. This allows Alembic migration scripts to refer to these custom types
in a simpler way, without needing to import them from deeper module paths.
"""

from marvin.db.models._model_utils.datetime import NaiveDateTime as _naive_datetime
from marvin.db.models._model_utils.datetime import datetime as _custom_datetime  # Alias to avoid naming conflict
from marvin.db.models._model_utils.guid import GUID as _custom_guid  # Alias for clarity
from marvin.db.models._model_utils.httpurl import HttpUrlType as _http_url_type

# Re-export for use in Alembic migrations and potentially other database-related operations.
# These aliases provide a stable import path for custom types used in table definitions
# within migration scripts.
DateTime = _custom_datetime
"""Alias for the custom UTC-aware datetime type used in Marvin models."""

NaiveDateTime = _naive_datetime
"""Alias for the naive datetime type used in Marvin models (stored as UTC without timezone info)."""

HttpUrlType = _http_url_type
"""Alias for the HTTP URL type used in Marvin models (Pydantic HttpUrl stored as string)."""

GUID = _custom_guid
"""Alias for the custom GUID type used for primary keys in Marvin models."""
