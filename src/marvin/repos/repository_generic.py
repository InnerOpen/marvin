"""
This module provides generic repository classes for common database operations.

It defines:
- `RepositoryGeneric`: A base class offering CRUD (Create, Read, Update, Delete)
  functionalities, along with pagination, filtering, and searching capabilities
  for SQLAlchemy models. It is designed to work with Pydantic schemas for data
  validation and serialization.
- `GroupRepositoryGeneric`: A subclass of `RepositoryGeneric` that is specifically
  designed for resources that are scoped to a group. It requires a `group_id`
  upon initialization and automatically applies group-based filtering.
"""

from __future__ import annotations  # For TypeVar T bound to RepositoryGeneric

import random
from collections.abc import Iterable
from datetime import UTC, datetime
from math import ceil
from typing import Any, Generic, TypeVar

from fastapi import HTTPException, status  # For raising HTTP exceptions on bad input
from pydantic import UUID4, BaseModel  # For UUID type hinting and base Pydantic model
from sqlalchemy import (
    ColumnElement,  # For type hinting column elements
    Select,  # For type hinting Select statements
    case,
    delete,
    func,
    nulls_first,
    nulls_last,
    select,
)
from sqlalchemy.orm import InstrumentedAttribute  # For attribute type in ordering
from sqlalchemy.orm.session import Session  # For SQLAlchemy session type hinting
from sqlalchemy.sql import sqltypes  # For checking SQL type (e.g., String)

from marvin.core.root_logger import get_logger  # Application logger
from marvin.db.models import SqlAlchemyBase  # Base for SQLAlchemy models
from marvin.schemas._marvin import _MarvinModel  # Base for Pydantic schemas
from marvin.schemas.response.pagination import (
    OrderByNullPosition,
    OrderDirection,
    PaginationBase,
    PaginationQuery,
    RequestQuery,
)
from marvin.schemas.response.query_filter import QueryFilterBuilder  # For advanced query filtering
from marvin.schemas.response.query_search import SearchFilter  # For text search capabilities

from ._utils import NOT_SET, NotSet  # Sentinel for unset parameters

# Type variables for generic repository
Schema = TypeVar("Schema", bound=_MarvinModel)  # Pydantic schema type
Model = TypeVar("Model", bound=SqlAlchemyBase)  # SQLAlchemy model type
CreateSchema = TypeVar("CreateSchema", bound=BaseModel)  # Pydantic schema for creation
UpdateSchema = TypeVar("UpdateSchema", bound=BaseModel)  # Pydantic schema for updates

T = TypeVar("T", bound="RepositoryGeneric")  # For self-referential types, not strictly used here but good practice


class RepositoryGeneric(Generic[Schema, Model]):
    """
    A generic base repository providing common database operations.

    This class is designed to be inherited by specific entity repositories.
    It handles CRUD operations, pagination, filtering, and searching.

    Type Parameters:
        Schema: The Pydantic schema used for reading/serializing data.
        Model: The SQLAlchemy model representing the database table.
    """

    session: Session
    """The SQLAlchemy session used for database interactions."""

    primary_key: str
    """The name of the primary key attribute on the SQLAlchemy model."""

    model: type[Model]
    """The SQLAlchemy model class this repository manages."""

    schema: type[Schema]
    """The Pydantic schema class used for validating and serializing model instances."""

    _group_id: UUID4 | None = None  # Internal storage for group_id if repository is group-scoped
    """
    Internal storage for the group ID. Used by `GroupRepositoryGeneric` or if
    a generic repository instance is manually scoped to a group.
    """

    def __init__(
        self,
        session: Session,
        primary_key: str,
        sql_model: type[Model],
        schema: type[Schema],
    ) -> None:
        """
        Initializes the RepositoryGeneric instance.

        Args:
            session (Session): The SQLAlchemy session for database operations.
            primary_key (str): The name of the primary key attribute of the `sql_model`.
            sql_model (type[Model]): The SQLAlchemy model class.
            schema (type[Schema]): The Pydantic schema class for serialization.
        """
        self.session = session
        self.primary_key = primary_key
        self.model = sql_model
        self.schema = schema
        self.logger = get_logger()  # Initialize logger for repository actions

    @property
    def group_id(self) -> UUID4 | None:
        """
        The group ID this repository is scoped to, if any.

        Returns:
            UUID4 | None: The group ID, or None if not group-scoped.
        """
        return self._group_id

    @property
    def column_aliases(self) -> dict[str, ColumnElement]:
        """
        A dictionary of column aliases for use in query filtering and ordering.

        This allows mapping user-friendly filter/sort names to actual SQLAlchemy
        column expressions, potentially involving joins or calculated fields.
        Should be overridden by subclasses if aliases are needed.

        Example:
            `{"user_name": UserModel.name, "profile_bio": ProfileModel.bio}`

        Returns:
            dict[str, ColumnElement]: A dictionary mapping alias strings to
                                      SQLAlchemy ColumnElement objects.
        """
        return {}

    def _random_seed(self) -> str:
        """
        Generates a seed string based on the current UTC time.

        Used for reproducible "random" ordering in pagination if requested.

        Returns:
            str: A string representation of the current UTC datetime.
        """
        return str(datetime.now(tz=UTC))

    def _log_exception(self, e: Exception) -> None:
        """
        Logs an exception that occurred during query processing.

        Args:
            e (Exception): The exception to log.
        """
        self.logger.error(f"Error processing query for Repo model={self.model.__name__} schema={self.schema.__name__}")
        self.logger.error(e)

    def _query(self, override_schema: type[_MarvinModel] | None = None, with_options: bool = True) -> Select:
        """
        Constructs a basic SQLAlchemy select query for the repository's model.

        Optionally applies loader options from the schema for optimizing
        related data loading (e.g., joinedload, selectinload).

        Args:
            override_schema (type[_MarvinModel] | None, optional): A Pydantic schema
                to use for loader options instead of the default `self.schema`.
                Defaults to None.
            with_options (bool, optional): Whether to apply loader options from the
                schema. Defaults to True.

        Returns:
            Select: A SQLAlchemy Select statement.
        """
        q = select(self.model)
        if with_options:
            # Determine which schema's loader options to use
            schema_for_options = override_schema or self.schema
            # Apply loader options if the schema defines them
            if hasattr(schema_for_options, "loader_options") and callable(schema_for_options.loader_options):
                q = q.options(*schema_for_options.loader_options())
        return q

    def _filter_builder(self, **kwargs) -> dict[str, Any]:
        """
        Builds a dictionary of filters to be applied to queries.

        Automatically adds a `group_id` filter if `self.group_id` is set.
        Merges any additional keyword arguments into the filter dictionary.

        Args:
            **kwargs: Additional key-value pairs to include in the filter.

        Returns:
            dict[str, Any]: A dictionary of filter criteria.
        """
        dct = {}
        if self.group_id:  # Apply group scoping if group_id is available
            dct["group_id"] = self.group_id
        return {**dct, **kwargs}

    def get_all(
        self,
        limit: int | None = None,
        order_by: str | None = None,
        order_descending: bool = True,
        override_schema: type[Schema] | None = None,  # Corrected override to override_schema
    ) -> list[Schema]:
        """
        Retrieves all records, with optional limit and ordering.

        This is a convenience method that uses `page_all` to fetch the first page
        with the specified limit.

        Args:
            limit (int | None, optional): Maximum number of records to return.
                If None, returns all records (equivalent to per_page=-1). Defaults to None.
            order_by (str | None, optional): Attribute name to order by. Defaults to None.
            order_descending (bool, optional): If True, order in descending order.
                Defaults to True.
            override_schema (type[Schema] | None, optional): A Pydantic schema to use for
                serialization instead of `self.schema`. Defaults to None.

        Returns:
            list[Schema]: A list of Pydantic schema instances.
        """
        pq = PaginationQuery(
            per_page=limit if limit is not None else -1,  # -1 signifies all items for page_all
            order_by=order_by,
            order_direction=OrderDirection.desc if order_descending else OrderDirection.asc,
            page=1,  # Get the first page
        )
        results = self.page_all(pq, override_schema=override_schema)  # Pass override_schema
        return results.items

    def multi_query(
        self,
        query_by: dict[str, str | bool | int | UUID4],  # Value can be str, bool, int, UUID4 etc.
        start: int = 0,
        limit: int | None = None,
        override_schema: type[Schema] | None = None,
        order_by: str | None = None,  # Simple ordering, field name string
        order_descending: bool = True,  # Added for consistency
    ) -> list[Schema]:
        """
        Retrieves multiple records based on a dictionary of query parameters.

        Args:
            query_by (dict[str, Any]): A dictionary of attribute-value pairs to filter by.
            start (int, optional): Offset for query results (for manual pagination). Defaults to 0.
            limit (int | None, optional): Maximum number of records to return. Defaults to None.
            override_schema (type[Schema] | None, optional): Pydantic schema for serialization.
                                                           Defaults to `self.schema`.
            order_by (str | None, optional): Attribute name for simple ordering. Defaults to None.
            order_descending (bool, optional): Direction for simple ordering. Defaults to True.


        Returns:
            list[Schema]: A list of Pydantic schema instances.
        """
        eff_schema = override_schema or self.schema
        fltr = self._filter_builder(**query_by)  # Apply group_id filter if applicable
        q = self._query(override_schema=eff_schema).filter_by(**fltr)

        if order_by:
            order_attribute = getattr(self.model, str(order_by))
            if order_attribute:
                order_expression = order_attribute.desc() if order_descending else order_attribute.asc()
                q = q.order_by(order_expression)

        if start > 0:
            q = q.offset(start)
        if limit is not None:
            q = q.limit(limit)

        result = self.session.execute(q).unique().scalars().all()
        return [eff_schema.model_validate(db_obj) for db_obj in result]

    def _query_one(self, match_value: Any, match_key: str | None = None) -> Model | None:
        """
        Queries the database for a single item and returns the SQLAlchemy model instance.

        If no `match_key` is provided, the `self.primary_key` is used.
        Applies group_id filtering if applicable.

        Args:
            match_value (Any): The value to match for the given `match_key`.
            match_key (str | None, optional): The attribute name to filter by.
                                             Defaults to `self.primary_key`.

        Returns:
            Model | None: The SQLAlchemy model instance if found, otherwise None.
        """
        # Determine the key to use for matching (default to primary_key)
        key_to_match = match_key or self.primary_key

        # Build filter conditions, including group_id if set
        filter_conditions = self._filter_builder(**{key_to_match: match_value})

        # Construct and execute the query
        query = self._query().filter_by(**filter_conditions)
        return self.session.execute(query).unique().scalars().one_or_none()

    def get_one(self, value: Any, key: str | None = None, any_case: bool = False, override_schema: type[Schema] | None = None) -> Schema | None:
        """
        Retrieves a single record by a specific key-value pair.

        Args:
            value (Any): The value to match.
            key (str | None, optional): The attribute name to filter by.
                                        Defaults to `self.primary_key`.
            any_case (bool, optional): If True and `key` refers to a string column,
                                       perform a case-insensitive search. Defaults to False.
            override_schema (type[Schema] | None, optional): Pydantic schema for serialization.
                                                           Defaults to `self.schema`.

        Returns:
            Schema | None: The Pydantic schema instance if found, otherwise None.
        """
        key_to_use = key or self.primary_key
        eff_schema = override_schema or self.schema
        query = self._query(override_schema=eff_schema)
        base_filters = self._filter_builder()  # Get base filters (e.g., group_id)

        if any_case:
            # Ensure the attribute exists on the model
            model_attribute = getattr(self.model, key_to_use)
            if model_attribute is None:
                # Handle error: key does not exist on model
                return None
            # Apply case-insensitive search for string types
            query = query.where(func.lower(model_attribute) == str(value).lower())
            if base_filters:  # Apply base filters if they exist
                query = query.filter_by(**base_filters)
        else:
            # Apply case-sensitive search, merging key-value with base filters
            all_filters = {**base_filters, key_to_use: value}
            query = query.filter_by(**all_filters)

        result = self.session.execute(query).unique().scalars().one_or_none()

        if not result:
            return None
        return eff_schema.model_validate(result)

    def create(self, data: CreateSchema | dict) -> Schema:
        """
        Creates a new record in the database.

        Args:
            data (CreateSchema | dict): The data for the new record, either as a
                                        Pydantic schema instance or a dictionary.

        Returns:
            Schema: The Pydantic schema instance of the created record.

        Raises:
            Exception: Propagates database exceptions on commit failure after rollback.
        """
        try:
            # Convert Pydantic model to dict if necessary
            data_dict = data if isinstance(data, dict) else data.model_dump()
            # Create SQLAlchemy model instance, passing session for auto_init if used
            new_document = self.model(session=self.session, **data_dict)
            self.session.add(new_document)
            self.session.commit()
        except Exception:
            self.session.rollback()  # Ensure rollback on any error
            raise  # Re-raise the exception

        self.session.refresh(new_document)  # Refresh to get DB-generated values
        return self.schema.model_validate(new_document)  # Validate and return as output schema

    def create_many(self, data: Iterable[CreateSchema | dict]) -> list[Schema]:
        """
        Creates multiple records in the database in a single transaction.

        Args:
            data (Iterable[CreateSchema | dict]): An iterable of data for the new records.

        Returns:
            list[Schema]: A list of Pydantic schema instances of the created records.
        """
        new_documents = []
        for document_data in data:
            # Convert each item to dict if it's a Pydantic model
            item_dict = document_data if isinstance(document_data, dict) else document_data.model_dump()
            # Create SQLAlchemy model instance
            new_document = self.model(session=self.session, **item_dict)
            new_documents.append(new_document)

        self.session.add_all(new_documents)  # Add all new instances to the session
        try:
            self.session.commit()  # Commit the transaction
        except Exception:
            self.session.rollback()
            raise

        for created_document in new_documents:  # Refresh each new document
            self.session.refresh(created_document)

        return [self.schema.model_validate(db_obj) for db_obj in new_documents]

    def update(self, match_value: Any, new_data: UpdateSchema | dict, match_key: str | None = None) -> Schema:
        """
        Updates an existing record in the database.

        Args:
            match_value (Any): The value to match for identifying the record to update.
            new_data (UpdateSchema | dict): The new data for the record.
            match_key (str | None, optional): The attribute name to match against `match_value`.
                                             Defaults to `self.primary_key`.

        Returns:
            Schema: The Pydantic schema instance of the updated record.

        Raises:
            HTTPException(404): If the record to update is not found.
        """
        # Convert Pydantic model to dict if necessary, excluding unset fields for partial updates
        update_data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Query for the existing entry
        entry = self._query_one(match_value=match_value, match_key=match_key)
        if not entry:
            # Consider raising an exception if the entry is not found
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{self.model.__name__} not found for update.")

        # Update attributes of the fetched entry
        # The `update` method on SqlAlchemyBase models (if using auto_init) can handle this.
        # Otherwise, iterate and setattr.
        if hasattr(entry, "update") and callable(entry.update):
            entry.update(session=self.session, **update_data_dict)  # Assuming entry.update handles partial updates
        else:  # Manual attribute setting as a fallback
            for key, value in update_data_dict.items():
                setattr(entry, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(entry)
        return self.schema.model_validate(entry)

    def update_many(self, data: Iterable[UpdateSchema | dict]) -> list[Schema]:
        """
        Updates multiple records in the database.

        Each item in `data` should ideally contain an 'id' (or the primary key)
        to identify the record to update, along with the fields to be updated.

        Args:
            data (Iterable[UpdateSchema | dict]): An iterable of update data.

        Returns:
            list[Schema]: A list of Pydantic schema instances of the updated records.
        """
        document_data_by_id: dict[Any, dict] = {}
        for document_update_data in data:
            item_dict = document_update_data if isinstance(document_update_data, dict) else document_update_data.model_dump(exclude_unset=True)
            # Assume 'id' is the primary key for matching, or use self.primary_key
            pk_value = item_dict.get(self.primary_key)
            if pk_value is None:
                # Handle items without a PK, e.g., skip or raise error
                continue
            document_data_by_id[pk_value] = item_dict

        # Fetch all documents to be updated in one query
        ids_to_update = list(document_data_by_id.keys())
        if not ids_to_update:
            return []

        documents_to_update_query = self._query().filter(getattr(self.model, self.primary_key).in_(ids_to_update))
        db_documents_to_update = self.session.execute(documents_to_update_query).unique().scalars().all()

        updated_db_documents = []
        for db_document in db_documents_to_update:
            pk_value = getattr(db_document, self.primary_key)
            if pk_value in document_data_by_id:
                update_data = document_data_by_id[pk_value]
                # Use the model's update method or setattr loop
                if hasattr(db_document, "update") and callable(db_document.update):
                    db_document.update(session=self.session, **update_data)
                else:
                    for key, value in update_data.items():
                        setattr(db_document, key, value)
                updated_db_documents.append(db_document)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return [self.schema.model_validate(db_obj) for db_obj in updated_db_documents]

    def patch(self, match_value: Any, new_data: UpdateSchema | dict, match_key: str | None = None) -> Schema:
        """
        Partially updates an existing record by applying only the fields present in `new_data`.

        This method first fetches the existing record, converts it to a Pydantic model
        (which applies default values for missing fields if any), then updates this
        model with `new_data`, and finally uses the result to perform a full update
        on the database object. This ensures that default values from the Pydantic
        schema are respected during the patch.

        Args:
            match_value (Any): Value to identify the record to patch.
            new_data (UpdateSchema | dict): Data containing fields to update.
            match_key (str | None, optional): Attribute to match `match_value` against.
                                             Defaults to `self.primary_key`.

        Returns:
            Schema: The Pydantic schema of the patched record.
        """
        update_data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        db_entry = self._query_one(match_value=match_value, match_key=match_key)
        if not db_entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{self.model.__name__} not found for patch.")

        # Convert DB entry to Pydantic schema to get a full dict with defaults
        pydantic_entry = self.schema.model_validate(db_entry)
        entry_as_dict = pydantic_entry.model_dump()

        # Apply the partial updates from new_data
        entry_as_dict.update(update_data_dict)

        # Perform a full update with the merged data
        # This re-uses the main update logic which might include model's .update() method
        return self.update(match_value, entry_as_dict, match_key=match_key)

    def delete(self, value: Any, match_key: str | None = None) -> Schema:
        """
        Deletes a single record from the database.

        Args:
            value (Any): The value to match for identifying the record to delete.
            match_key (str | None, optional): The attribute name to match `value` against.
                                             Defaults to `self.primary_key`.

        Returns:
            Schema: The Pydantic schema instance of the deleted record.

        Raises:
            HTTPException(404): If the record to delete is not found.
            Exception: Propagates database exceptions on commit failure after rollback.
        """
        key_to_match = match_key or self.primary_key

        # Fetch the record to be deleted
        db_record_to_delete = self._query_one(match_value=value, match_key=key_to_match)

        if not db_record_to_delete:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"{self.model.__name__} with {key_to_match}='{value}' not found for deletion."
            )

        # Convert to Pydantic schema before deletion for the return value
        deleted_schema_instance = self.schema.model_validate(db_record_to_delete)

        try:
            self.session.delete(db_record_to_delete)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            self.logger.error(f"Error deleting {self.model.__name__}: {e}")
            raise  # Re-raise the original exception

        return deleted_schema_instance

    def delete_many(self, ids_to_delete: Iterable[Any]) -> list[Schema]:  # Assuming IDs are passed
        """
        Deletes multiple records from the database based on a list of their primary key values.

        Args:
            ids_to_delete (Iterable[Any]): An iterable of primary key values of the records to delete.

        Returns:
            list[Schema]: A list of Pydantic schema instances of the deleted records.
        """
        if not ids_to_delete:
            return []

        # Fetch records to be deleted to return them and ensure they exist
        query = self._query().filter(getattr(self.model, self.primary_key).in_(ids_to_delete))
        db_records_to_delete = self.session.execute(query).unique().scalars().all()

        if not db_records_to_delete:  # No records found matching the IDs
            return []

        deleted_schema_instances = [self.schema.model_validate(db_obj) for db_obj in db_records_to_delete]

        try:
            # Delete each record individually to ensure ORM cascades are triggered correctly
            # for each instance if defined. Bulk delete via query might bypass some ORM event hooks.
            for db_record in db_records_to_delete:
                self.session.delete(db_record)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            self.logger.error(f"Error deleting multiple {self.model.__name__} instances: {e}")
            raise

        return deleted_schema_instances

    def delete_all(self) -> int:
        """
        Deletes all records from the table associated with this repository.
        Applies group_id filtering if this repository is group-scoped.

        Returns:
            int: The number of records deleted.
        """
        filter_conditions = self._filter_builder()
        delete_stmt = delete(self.model)
        if filter_conditions:  # Apply group_id filter if present
            delete_stmt = delete_stmt.filter_by(**filter_conditions)

        result = self.session.execute(delete_stmt)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return result.rowcount

    def count_all(self, match_key: str | None = None, match_value: Any | None = None) -> int:
        """
        Counts all records, optionally matching a specific key-value pair.
        Applies group_id filtering if applicable.

        Args:
            match_key (str | None, optional): Attribute name to filter by. Defaults to None.
            match_value (Any | None, optional): Value to match for `match_key`. Defaults to None.

        Returns:
            int: The total count of matching records.
        """
        # Base query for counting
        count_query = select(func.count(getattr(self.model, self.primary_key)))  # Count primary keys for efficiency

        # Build filter conditions, including group_id
        filter_conditions = self._filter_builder()
        if match_key is not None and match_value is not None:
            filter_conditions[match_key] = match_value

        if filter_conditions:
            count_query = count_query.filter_by(**filter_conditions)

        return self.session.scalar(count_query) or 0

    def _count_attribute(  # This method seems unused, consider removal or refinement
        self,
        attribute_name: str,  # Should be an attribute of self.model
        attr_match: Any | None = None,  # Value to match
        count: bool = True,  # If False, returns matching objects instead of count
        override_schema: type[Schema] | None = None,
    ) -> int | list[Schema]:
        """
        Counts records where `attribute_name` matches `attr_match`, or retrieves them.
        Applies group_id filtering. (Consider if this method is still needed or if
        `count_all` and `multi_query` cover its use cases.)

        Args:
            attribute_name (str): The name of the attribute on the model to filter by.
            attr_match (Any | None, optional): The value the attribute should match.
                                              If None, behavior might be to count all or based on other criteria.
            count (bool, optional): If True, returns the count. If False, returns the list
                                    of matching Pydantic schema instances. Defaults to True.
            override_schema (type[Schema] | None, optional): Pydantic schema for serialization
                                                           if `count` is False. Defaults to `self.schema`.

        Returns:
            int | list[Schema]: The count or list of matching Pydantic schemas.
        """
        eff_schema = override_schema or self.schema
        model_attr = getattr(self.model, attribute_name, None)
        if model_attr is None:
            raise ValueError(f"Attribute '{attribute_name}' not found on model '{self.model.__name__}'.")

        # Base query construction
        if count:
            query = select(func.count(getattr(self.model, self.primary_key)))
        else:
            query = self._query(override_schema=eff_schema)

        # Apply attribute match filter
        if attr_match is not None:
            query = query.where(model_attr == attr_match)

        # Apply group_id filter from _filter_builder
        group_filter = self._filter_builder()
        if group_filter:  # Ensure group_filter is not empty before applying
            # If query is already a select() from _query, it has self.model as target.
            # If it's func.count(), we need to specify where clause on self.model.
            # This part needs care depending on whether it's a count or select entities.
            # For now, assuming filter_by works if the main entity is self.model
            if "group_id" in group_filter and hasattr(self.model, "group_id"):
                query = query.filter_by(group_id=group_filter["group_id"])

        if count:
            return self.session.scalar(query) or 0
        else:
            result = self.session.execute(query).unique().scalars().all()
            return [eff_schema.model_validate(db_obj) for db_obj in result]

    def page_all(
        self,
        pagination: PaginationQuery,
        override_schema: type[Schema] | None = None,  # Corrected 'override' to 'override_schema'
        search: str | None = None,
    ) -> PaginationBase[Schema]:
        """
        Retrieves a paginated list of records, with optional searching and filtering.

        Applies group_id filtering, query filters from `pagination.query_filter`,
        text search if `search` is provided, and ordering/pagination parameters.

        Args:
            pagination (PaginationQuery): Pydantic model containing pagination,
                                          ordering, and filtering parameters.
            override_schema (type[Schema] | None, optional): Pydantic schema for serialization.
                                                           Defaults to `self.schema`.
            search (str | None, optional): A search string to filter records by.
                                           Uses `SearchFilter` logic. Defaults to None.

        Returns:
            PaginationBase[Schema]: A Pydantic model containing pagination metadata
                                    and the list of items for the current page.

        Raises:
            HTTPException: If query filter parsing fails or other query errors occur.
        """
        eff_schema = override_schema or self.schema
        # Create a copy of pagination to avoid mutating the input object,
        # especially if it's used elsewhere or in retries.
        pagination_params = pagination.model_copy(deep=True)

        # Start with a base query, initially without loader options for count query efficiency
        base_query = self._query(override_schema=eff_schema, with_options=False)

        # Apply group_id filter if applicable
        group_filters = self._filter_builder()
        if group_filters:
            base_query = base_query.filter_by(**group_filters)

        # Apply text search if a search term is provided
        if search:
            base_query = self.add_search_to_query(base_query, eff_schema, search)

        # Default ordering if no specific order_by is provided and not searching
        # (search might imply relevance-based ordering handled by SearchFilter)
        if not pagination_params.order_by and not search:
            pagination_params.order_by = "created_at"  # Default sort for consistency

        # Apply advanced filters, ordering, and pagination limits
        # This method also calculates total count and pages.
        paginated_query, total_count, total_pages = self.add_pagination_to_query(base_query, pagination_params)

        # Apply loader options (e.g., for eager loading relationships) only to the final
        # query that fetches the items for the page, not to the count query.
        if hasattr(eff_schema, "loader_options") and callable(eff_schema.loader_options):
            final_query_with_options = paginated_query.options(*eff_schema.loader_options())
        else:
            final_query_with_options = paginated_query

        try:
            # Execute the query to get items for the current page
            db_items = self.session.execute(final_query_with_options).unique().scalars().all()
        except Exception as e:
            self._log_exception(e)  # Log the detailed exception
            self.session.rollback()  # Rollback session on error
            # Re-raise or raise a more specific HTTP exception if appropriate
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error fetching paginated data.") from e

        # Construct and return the pagination response object
        return PaginationBase(
            page=pagination_params.page,
            per_page=pagination_params.per_page,
            total=total_count,
            total_pages=total_pages,
            items=[eff_schema.model_validate(s) for s in db_items],  # Validate and serialize items
        )

    def add_pagination_to_query(self, query: Select, pagination: PaginationQuery) -> tuple[Select, int, int]:
        """
        Applies filtering, ordering, and pagination to a SQLAlchemy query.

        This method modifies the input `query` by:
        1. Applying advanced filters defined in `pagination.query_filter`.
        2. Calculating the total count of records matching the filters.
        3. Determining total pages based on `per_page`.
        4. Adjusting `page` and `per_page` for special values (-1 for all/last page).
        5. Applying ordering based on `pagination.order_by` and `pagination.order_direction`.
        6. Applying limit and offset for pagination.

        Args:
            query (Select): The base SQLAlchemy Select query to modify.
            pagination (PaginationQuery): Pydantic model with pagination, ordering,
                                          and filtering parameters.

        Returns:
            tuple[Select, int, int]: A tuple containing:
                - The modified SQLAlchemy Select query with pagination and ordering.
                - The total count of records (before pagination limit/offset).
                - The total number of pages.

        Raises:
            HTTPException: If `pagination.query_filter` is invalid.
        """
        # Apply advanced query filters if present
        if pagination.query_filter:
            try:
                query_filter_builder = QueryFilterBuilder(pagination.query_filter)
                query = query_filter_builder.filter_query(query, model=self.model, column_aliases=self.column_aliases)
            except ValueError as e:  # Catch specific errors from QueryFilterBuilder
                self.logger.error(f"Invalid query filter: {e}")
                # Raise HTTPException for bad client input
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        # Get the total count of records matching the query (before pagination)
        # Use a subquery for counting to ensure filters are applied correctly.
        count_subquery = query.with_only_columns(func.count(getattr(self.model, self.primary_key))).order_by(None).scalar_subquery()
        count = self.session.scalar(select(count_subquery)) or 0

        # Handle `per_page = -1` (meaning "all items")
        if pagination.per_page == -1:
            # If per_page is -1, set it to the total count to fetch all items.
            # Ensure it's at least 1 if count is 0 to avoid division by zero later.
            actual_per_page = count if count > 0 else 1
        else:
            actual_per_page = pagination.per_page

        # Calculate total pages
        try:
            total_pages = ceil(count / actual_per_page) if actual_per_page > 0 else 0
        except ZeroDivisionError:  # Should be caught by actual_per_page > 0
            total_pages = 0

        # Handle `page = -1` (meaning "last page")
        current_page = pagination.page
        if current_page == -1:
            current_page = total_pages if total_pages > 0 else 1

        # Ensure page number is valid (at least 1)
        if current_page < 1:
            current_page = 1

        # Apply ordering to the query
        query = self.add_order_by_to_query(query, pagination)

        # Apply limit and offset for pagination
        # Only apply if per_page was not -1 (i.e., not fetching all items on one page)
        if pagination.per_page != -1:
            query = query.limit(actual_per_page).offset((current_page - 1) * actual_per_page)

        return query, count, total_pages

    def add_order_attr_to_query(
        self,
        query: Select,
        order_attr: InstrumentedAttribute,  # The SQLAlchemy model attribute to order by
        order_dir: OrderDirection,  # asc or desc
        order_by_null: OrderByNullPosition | None,  # nulls first or nulls last
    ) -> Select:
        """
        Adds ordering for a single attribute to a SQLAlchemy query.

        Handles case-insensitive ordering for string types and null positioning.

        Args:
            query (Select): The SQLAlchemy Select query to modify.
            order_attr (InstrumentedAttribute): The model attribute to order by.
            order_dir (OrderDirection): The direction of ordering (asc or desc).
            order_by_null (OrderByNullPosition | None): How to position NULL values
                                                       ('first', 'last', or None for default).

        Returns:
            Select: The modified query with the specified ordering applied.
        """
        # Resolve column aliases if the order_attr key is an alias
        resolved_order_attr = self.column_aliases.get(order_attr.key, order_attr)

        # For string types, apply lower() for case-insensitive sorting
        # Check if resolved_order_attr is an InstrumentedAttribute and has a 'type'
        if hasattr(resolved_order_attr, "type") and isinstance(resolved_order_attr.type, sqltypes.String):
            attr_to_order = func.lower(resolved_order_attr)
        else:
            attr_to_order = resolved_order_attr

        # Apply ordering direction (asc/desc)
        if order_dir is OrderDirection.asc:
            ordered_expression = attr_to_order.asc()
        elif order_dir is OrderDirection.desc:
            ordered_expression = attr_to_order.desc()
        else:  # Should not happen if OrderDirection enum is used properly
            ordered_expression = attr_to_order

        # Apply null positioning if specified
        if order_by_null is OrderByNullPosition.first:
            ordered_expression = nulls_first(ordered_expression)
        elif order_by_null is OrderByNullPosition.last:
            ordered_expression = nulls_last(ordered_expression)

        return query.order_by(ordered_expression)

    def add_order_by_to_query(self, query: Select, request_query: RequestQuery) -> Select:
        """
        Adds ordering to a SQLAlchemy query based on `RequestQuery` parameters.

        Supports ordering by a single field, multiple comma-separated fields,
        and "random" ordering. Handles direction (asc/desc) and field name parsing.

        Args:
            query (Select): The SQLAlchemy Select query to modify.
            request_query (RequestQuery): Pydantic model containing ordering parameters
                                          (e.g., `order_by`, `order_direction`).

        Returns:
            Select: The modified query with ordering applied.

        Raises:
            HTTPException: If `request_query.order_by` contains an invalid field name
                           or format.
        """
        if not request_query.order_by:
            return query  # No ordering requested

        if request_query.order_by == "random":
            # Implement random ordering. This approach fetches all IDs, shuffles them using a seed,
            # and then orders by a CASE statement. This is database-agnostic and stable for pagination.
            # Note: This can be inefficient for very large tables.

            # Select only the primary key column for efficiency
            id_column = getattr(self.model, self.primary_key)
            temp_query = query.with_only_columns(id_column).order_by(None)  # Clear existing orders for ID fetching

            all_ids = self.session.execute(temp_query).scalars().all()
            if not all_ids:
                return query  # No items to order

            # Shuffle IDs based on a seed for reproducible "randomness" per seed
            order_indices = list(range(len(all_ids)))
            # Use provided seed or generate one if not available (e.g., from _random_seed)
            seed_value = request_query.pagination_seed or self._random_seed()
            random.seed(seed_value)
            random.shuffle(order_indices)

            # Create a mapping from ID to its random sort order
            random_order_map = dict(zip(all_ids, order_indices, strict=True))

            # Build a CASE statement to order by the shuffled map
            # Ensure id_column is correctly referenced from self.model for the CASE statement
            case_stmt = case(random_order_map, value=getattr(self.model, self.primary_key))
            return query.order_by(case_stmt)
        else:
            # Handle ordering by specific fields (comma-separated)
            order_by_fields = request_query.order_by.split(",")
            for order_by_statement in order_by_fields:
                order_by_statement = order_by_statement.strip()
                if not order_by_statement:
                    continue

                try:
                    # Parse "field:direction" format, e.g., "name:asc"
                    if ":" in order_by_statement:
                        field_name, direction_str = order_by_statement.split(":", 1)
                        order_direction = OrderDirection(direction_str.lower())
                    else:
                        field_name = order_by_statement
                        order_direction = request_query.order_direction  # Default direction

                    # Get the SQLAlchemy model attribute for the field_name
                    # QueryFilterBuilder can resolve nested fields like "parent.name"
                    _, model_attr, query_with_joins_if_any = QueryFilterBuilder.get_model_and_model_attr_from_attr_string(
                        field_name,
                        self.model,
                        query=query,  # Pass current query to allow joins to be added
                    )
                    query = query_with_joins_if_any  # Query might be updated with joins

                    # Add ordering for this attribute
                    query = self.add_order_attr_to_query(query, model_attr, order_direction, request_query.order_by_null_position)
                except ValueError as e:  # Catches invalid direction or field name issues from get_model_and_model_attr
                    self.logger.warning(f"Invalid order_by statement: '{order_by_statement}'. Error: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f'Invalid order_by statement "{request_query.order_by}": "{order_by_statement}" is invalid. Reason: {e}',
                    ) from e
            return query

    def add_search_to_query(self, query: Select, schema: type[Schema], search: str) -> Select:
        """
        Adds search filtering to a SQLAlchemy query.

        Utilizes `SearchFilter` to apply text search logic based on the provided
        search string and schema-defined searchable fields or normalization.

        Args:
            query (Select): The SQLAlchemy Select query to modify.
            schema (type[Schema]): The Pydantic schema associated with the model,
                                   used to determine searchable fields or normalization.
            search (str): The search string.

        Returns:
            Select: The modified query with search filters applied.
        """
        # SearchFilter's third arg is a bool flag: normalize characters when the schema
        # declares a custom `_normalize_search`. (Truthiness of the attribute was already the
        # de-facto behavior; make it an explicit bool so it type-checks.)
        normalize_characters = getattr(schema, "_normalize_search", None) is not None
        search_filter = SearchFilter(self.session, search, normalize_characters)
        return search_filter.filter_query_by_search(query, schema, self.model)


class GroupRepositoryGeneric(RepositoryGeneric[Schema, Model]):
    """
    A generic repository for resources that are scoped by a `group_id`.

    Inherits from `RepositoryGeneric` and requires `group_id` to be provided
    during initialization. It automatically applies `group_id` filtering to
    relevant operations.

    Type Parameters:
        Schema: The Pydantic schema used for reading/serializing data.
        Model: The SQLAlchemy model representing the database table.
        CreateSchema: The Pydantic schema used for creating new entities.
        UpdateSchema: The Pydantic schema used for updating existing entities.
    """

    def __init__(
        self,
        session: Session,
        primary_key: str,
        sql_model: type[Model],
        schema: type[Schema],
        *,  # Keyword-only arguments follow
        group_id: UUID4 | None | NotSet,  # group_id is mandatory or explicitly None/NotSet
    ) -> None:
        """
        Initializes the GroupRepositoryGeneric instance.

        Args:
            session (Session): The SQLAlchemy session.
            primary_key (str): Name of the primary key attribute of `sql_model`.
            sql_model (type[Model]): The SQLAlchemy model class.
            schema (type[Schema]): The Pydantic schema class for serialization.
            group_id (UUID4 | None | NotSet): The ID of the group to scope this
                repository to.
                - If `UUID4` or `None` (for system-level access where applicable),
                  it's stored in `_group_id`.
                - If `NOT_SET`, a `ValueError` is raised, as group context is expected.

        Raises:
            ValueError: If `group_id` is `NOT_SET`, indicating missing group context.
        """
        super().__init__(session, primary_key, sql_model, schema)
        if group_id is NOT_SET:
            # GroupRepositoryGeneric requires a group context (even if None for system/all)
            # NOT_SET implies the caller forgot to provide it.
            raise ValueError(f"group_id must be explicitly set (can be None) for {self.__class__.__name__}, but was NOT_SET.")
        self._group_id = group_id  # group_id can be None if explicitly passed as such
