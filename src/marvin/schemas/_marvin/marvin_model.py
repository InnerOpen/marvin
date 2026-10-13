"""
This module defines base Pydantic models and related utilities for use throughout
the Marvin application's schemas.

It includes:
- `_MarvinModel`: A custom base Pydantic model providing common configurations
  (like camelCase aliasing), datetime normalization, and utility methods for
  model transformation and search query modification.
- `SearchType`: An enumeration for different search strategies.
- `HasUUID`: A protocol for models that have a UUID `id` field.
- `extract_uuids`: A helper function to extract UUIDs from a sequence of models
  that conform to the `HasUUID` protocol.

The datetime parsing logic within `_MarvinModel` specifically addresses issues
with timezone formats from databases like PostgreSQL.
"""

from __future__ import annotations  # Enables using Self for return type hints

import re  # For regular expression operations in datetime parsing
from collections.abc import Sequence  # For typing sequences
from datetime import UTC, datetime  # Standard datetime objects
from enum import Enum  # For creating enumerations like SearchType
from typing import Any, ClassVar, Protocol, TypeVar  # Typing utilities

from humps import camelize  # For converting snake_case to camelCase for API responses
from pydantic import UUID4, BaseModel, ConfigDict, model_validator  # Core Pydantic components

# Placeholder for SQLAlchemy specific types, assuming they would be imported if used directly
# For example, if filter_search_query was fully implemented here:
# from sqlalchemy import Select, or_, func, desc, text
# from sqlalchemy.orm import InstrumentedAttribute, Session
# from marvin.db.models import SqlAlchemyBase

# Define a TypeVar for generic methods like cast
T = TypeVar("T", bound=BaseModel)

# Regex pattern to find timezones specified only with an hour part (e.g., "+05" instead of "+05:00")
# This is used in `fix_hour_only_tz` to correct such formats.
HOUR_ONLY_TZ_PATTERN = re.compile(r"([+-]\d{2})$")


class SearchType(Enum):
    """
    Enumeration defining different types of search strategies that can be applied.
    """

    fuzzy = "fuzzy"  # Fuzzy search, typically using trigram similarity (e.g., pg_trgm).
    tokenized = "tokenized"  # Token-based search, often using LIKE or full-text search capabilities.


class _MarvinModel(BaseModel):
    """
    A base Pydantic model for all Marvin application schemas.

    Provides common configurations and utility methods:
    - `model_config`: Configures Pydantic behavior, such as generating camelCase
      aliases for API interaction and allowing population by alias.
    - Search-related class variables (`_fuzzy_similarity_threshold`, `_normalize_search`,
      `_searchable_properties`) for defining how search queries are built for models
      inheriting from this base.
    - Model validators (`fix_hour_only_tz`, `set_tz_info`) to normalize datetime
      fields, ensuring consistent timezone handling (UTC).
    - Utility methods (`cast`, `map_to`, `map_from`, `merge`) for transforming and
      manipulating model instances.
    - Placeholder methods (`loader_options`, `filter_search_query`) intended for
      integration with data loading (e.g., SQLAlchemy eager loading) and search
      query construction, to be implemented or overridden by subclasses.
    """

    # --- Search Configuration Class Variables ---
    _fuzzy_similarity_threshold: ClassVar[float] = 0.5
    """
    Similarity threshold for fuzzy searches (e.g., using pg_trgm).
    A value between 0 and 1. Higher means more similar. Defaults to 0.5.
    """
    _normalize_search: ClassVar[bool] = False
    """
    Whether to normalize search strings (e.g., lowercasing, removing diacritics)
    before applying search logic. Defaults to False.
    Subclasses or the search utility itself should implement the normalization if True.
    """
    _searchable_properties: ClassVar[list[str]] = []
    """
    A list of attribute names (strings) on the model that should be considered
    when performing a text-based search. The order can be significant, as the
    first property is sometimes used for primary sorting in search results.
    Example: `["name", "description"]`
    """

    # Pydantic model configuration
    model_config = ConfigDict(
        alias_generator=camelize,  # Automatically generate camelCase aliases for fields
        populate_by_name=True,  # Allow populating model fields by their original Python names (snake_case)
        # as well as by their aliases (camelCase).
        from_attributes=True,  # Allow creating Pydantic models from ORM objects (SQLAlchemy models).
    )

    @model_validator(mode="before")  # Runs before Pydantic's own validation
    @classmethod
    def fix_hour_only_tz(cls, data: Any) -> Any:  # data can be dict or model instance
        """
        Corrects datetime string timezones that only specify the hour part (e.g., "+05").

        PostgreSQL sometimes returns timezone offsets like "+HH" instead of the
        standard "+HH:MM". This validator appends ":00" to such timezones in string
        representations of datetime fields before Pydantic attempts to parse them.
        This addresses a known Pydantic issue: https://github.com/pydantic/pydantic/issues/8609

        Args:
            data (Any): The input data to the model (can be a dictionary or an object).

        Returns:
            Any: The (potentially modified) input data.
        """
        if not isinstance(data, dict) and not hasattr(data, "__dict__"):  # Process dicts or objects with __dict__
            return data

        for field_name, field_info in cls.model_fields.items():
            # Check if the field is annotated as datetime
            if field_info.annotation == datetime:
                # Get the value of the field from the input data
                # Handles both dict input and object input (e.g., from ORM)
                field_value = data.get(field_name) if isinstance(data, dict) else getattr(data, field_name, None)

                if isinstance(field_value, str):
                    # If the string value matches the hour-only timezone pattern, append ":00"
                    if HOUR_ONLY_TZ_PATTERN.search(field_value):
                        corrected_value = field_value + ":00"
                        if isinstance(data, dict):
                            data[field_name] = corrected_value
                        else:
                            setattr(data, field_name, corrected_value)
        return data

    @model_validator(mode="after")  # Runs after Pydantic's own validation and model creation
    def set_tz_info(self) -> _MarvinModel:
        """
        Ensures all naive datetime attributes on the model instance are set to UTC.

        This validator iterates through the model's fields after initialization.
        If a field is a `datetime` object and is timezone-naive (tzinfo is None),
        it replaces it with a new `datetime` object that has its timezone set to UTC.
        This standardizes datetime objects to be timezone-aware and UTC-based,
        aligning with the common practice of storing datetimes in UTC in the database.

        Returns:
            Self: The modified model instance with datetime fields set to UTC.
        """
        for field_name in self.model_fields:  # Iterate through defined fields of the model
            field_value = getattr(self, field_name)
            if isinstance(field_value, datetime):
                if field_value.tzinfo is None:  # Check if the datetime is naive
                    # If naive, assume it's UTC and make it timezone-aware
                    setattr(self, field_name, field_value.replace(tzinfo=UTC))
        return self

    def cast(self, target_cls: type[T], **kwargs: Any) -> T:
        """
        Casts the current model instance to an instance of another Pydantic model type.

        Attributes with matching names are copied from the current model to the new
        target model instance. Additional keyword arguments can be provided to
        override or add attributes to the target instance.

        This is useful for transforming Data Transfer Objects (DTOs) or API request
        schemas into different Pydantic models, such as those used for database
        operations or internal service layers.

        Args:
            target_cls (type[T]): The Pydantic model class to cast to.
            **kwargs (Any): Additional keyword arguments to initialize the target class,
                            potentially overriding values from the source model.

        Returns:
            T: An instance of `target_cls`.
        """
        # Collect fields from the current model that also exist in the target class
        shared_fields_data = {
            field_name: getattr(self, field_name)
            for field_name in self.model_fields  # Fields of the current model
            if field_name in target_cls.model_fields  # Check if field exists in target
        }
        # Update with any explicitly provided kwargs, allowing overrides
        shared_fields_data.update(kwargs)
        return target_cls(**shared_fields_data)  # Create instance of target class

    def map_to(self, destination_model_instance: T) -> T:
        """
        Maps attribute values from this model instance to a `destination_model_instance`.

        Iterates through fields of this model. If a field with the same name exists
        in the `destination_model_instance`, its value is updated from this model.
        The `destination_model_instance` is modified in-place and also returned.

        Args:
            destination_model_instance (T): The target Pydantic model instance to map values to.

        Returns:
            T: The modified `destination_model_instance`.
        """
        for field_name in self.model_fields:  # Iterate fields of the source model (self)
            if hasattr(destination_model_instance, field_name):  # Check if destination has the same field
                setattr(destination_model_instance, field_name, getattr(self, field_name))
        return destination_model_instance

    def map_from(self, source_model_instance: BaseModel) -> None:
        """
        Maps attribute values from a `source_model_instance` to this model instance.

        Iterates through fields of the `source_model_instance`. If a field with the
        same name exists in this model, its value is updated from the source.
        This model instance is modified in-place.

        Args:
            source_model_instance (BaseModel): The source Pydantic model instance to map values from.
        """
        for field_name in source_model_instance.model_fields:  # Iterate fields of the source model
            if field_name in self.model_fields:  # Check if current model (self) has the same field
                setattr(self, field_name, getattr(source_model_instance, field_name))

    def merge(self, source_model_instance: _MarvinModel, replace_null: bool = False) -> None:
        """
        Merges attribute values from a `source_model_instance` into this model instance.

        Iterates through fields of the `source_model_instance`. If a field with the
        same name exists in this model:
        - If `replace_null` is True, the value is copied regardless.
        - If `replace_null` is False (default), the value is copied only if it's not None
          in the `source_model_instance`.
        This model instance is modified in-place.

        Args:
            source_model_instance (Self): Another instance of the same model type (or a compatible one)
                                          from which to merge values.
            replace_null (bool, optional): If True, null (None) values from the source
                                           will overwrite existing values in this model.
                                           If False, null values from the source are ignored.
                                           Defaults to False.
        """
        for field_name in source_model_instance.model_fields:
            source_value = getattr(source_model_instance, field_name)
            if field_name in self.model_fields:  # Check if current model has the field
                if source_value is not None or replace_null:  # Condition for copying value
                    setattr(self, field_name, source_value)

    @classmethod
    def loader_options(cls) -> list[Any]:  # Return type should be list[LoaderOption] from SQLAlchemy if used
        """
        Placeholder for defining SQLAlchemy loader options for this model.

        This method is intended to be overridden by subclasses that correspond to
        SQLAlchemy models. It should return a list of SQLAlchemy loader options
        (e.g., `joinedload`, `selectinload`) to optimize database queries by
        specifying how related data should be fetched.

        Returns:
            list[Any]: An empty list by default. Subclasses should return a list
                       of SQLAlchemy loader option instances.
        """
        # Example for a subclass:
        # from sqlalchemy.orm import joinedload
        # from .related_model_schema import RelatedModelSchema # Assuming this maps to a related DB model
        # return [joinedload(cls.orm_model.relationship_name.of_type(RelatedModelSchema.orm_model))]
        return []  # Default implementation returns no options

    @classmethod
    def filter_search_query(
        cls,
        db_model: Any,  # Should be type[SqlAlchemyBase] from marvin.db.models
        query: Any,  # Should be type[Select] from sqlalchemy
        session: Any,  # Should be type[Session] from sqlalchemy.orm
        search_type: SearchType,
        search: str,
        search_list: list[str],
    ) -> Any:  # Should return type[Select]
        """
        Applies search filtering to a SQLAlchemy query based on this model's configuration.

        This method constructs search conditions based on `_searchable_properties`,
        `search_type` (fuzzy or tokenized), and the provided search terms.
        It's a placeholder for actual SQLAlchemy query construction logic.

        NOTE: This method currently raises `AttributeError("Not Implemented")` if
        `_searchable_properties` is empty. The SQLAlchemy-specific parts
        (pg_trgm functions, ORM operations) are commented out as they depend on
        SQLAlchemy imports not present in this Pydantic-focused base module.
        A full implementation would require these imports and a valid `db_model`.

        Args:
            db_model (Any): The SQLAlchemy model class corresponding to this schema.
            query (Any): The SQLAlchemy Select query object to filter.
            session (Any): The SQLAlchemy session (used for dialect-specific settings like pg_trgm).
            search_type (SearchType): The type of search to perform (fuzzy or tokenized).
            search (str): The primary search string.
            search_list (list[str]): A list of tokenized search terms (used for tokenized search).

        Returns:
            Any: The modified SQLAlchemy Select query with search filters applied.

        Raises:
            AttributeError: If `_searchable_properties` is not defined on the class.
        """
        if not cls._searchable_properties:
            # If no properties are defined as searchable, this method cannot proceed.
            raise AttributeError(f"Model {cls.__name__} has no '_searchable_properties' defined for search functionality.")

        # The following is a conceptual SQLAlchemy implementation based on the original code.
        # It requires SQLAlchemy imports (Select, or_, func, desc, text, InstrumentedAttribute, Session)
        # and `db_model` to be a valid SQLAlchemy model class.

        # from sqlalchemy import or_, func, desc, text # Example imports
        # from sqlalchemy.orm import InstrumentedAttribute

        # model_properties: list[InstrumentedAttribute] = [
        #     getattr(db_model, prop_name) for prop_name in cls._searchable_properties
        # ]

        # if search_type is SearchType.fuzzy:
        #     # Set PostgreSQL's trigram similarity threshold for fuzzy search
        #     session.execute(text(f"SET pg_trgm.word_similarity_threshold = {cls._fuzzy_similarity_threshold};"))
        #     # Create OR conditions for each searchable property using word similarity operator '%>'
        #     filters = [prop.op("%>")(search) for prop in model_properties]
        #     # Order results by similarity to the first searchable property using distance operator '<->>'
        #     # func.least might be used if comparing distances across multiple properties,
        #     # but typically order by the most relevant one.
        #     if model_properties:
        #         query = query.filter(or_(*filters)).order_by(model_properties[0].op("<->>")(search))
        #     else: # Should not happen if _searchable_properties check passed
        #         query = query.filter(or_(*filters))
        #     return query
        # elif search_type is SearchType.tokenized:
        #     filters = []
        #     for prop in model_properties:
        #         # Create LIKE conditions for each token in search_list against each property
        #         filters.extend([prop.ilike(f"%{term}%") for term in search_list]) # Use ilike for case-insensitivity

        #     if model_properties:
        #         query = query.filter(or_(*filters)).order_by(
        #             desc(model_properties[0].ilike(f"%{search}%")) # Order by relevance to the full search string
        #         )
        #     else: # Should not happen
        #         query = query.filter(or_(*filters))
        #     return query
        # else:
        #     return query # No known search type, return original query

        # Placeholder until SQLAlchemy parts are actively used/integrated here:
        cls.logger.warning(f"Search for model {cls.__name__} was called but SQLAlchemy logic is placeholder.")
        return query  # Return unmodified query


class HasUUID(Protocol):
    """
    A protocol defining an object that has a UUID `id` attribute.

    This is useful for type hinting functions or collections that operate on
    objects identifiable by a UUID, without requiring them to inherit from a
    specific base class.
    """

    id: UUID4  # The required attribute: an ID of type UUID4


def extract_uuids(models: Sequence[HasUUID]) -> list[UUID4]:
    """
    Extracts UUID `id` attributes from a sequence of model instances.

    Args:
        models (Sequence[HasUUID]): A sequence of objects, where each object
                                    is expected to have an `id` attribute of type UUID4
                                    (conforming to the `HasUUID` protocol).

    Returns:
        list[UUID4]: A list containing the UUID `id` from each model instance.
    """
    return [model.id for model in models]
