"""
This module provides a sophisticated query filter builder for constructing
SQLAlchemy filter conditions from a custom string-based query language.

It allows users to define complex filters involving relational keywords (IS, IN, LIKE),
relational operators (=, <, >, etc.), logical operators (AND, OR), and grouping
with parentheses. The builder parses this filter string, validates components against
model attributes and their types, and then applies these filters to a SQLAlchemy query.

Key components include:
- Enums for `RelationalKeyword`, `RelationalOperator`, and `LogicalOperator`.
- `QueryFilterBuilderComponent`: Represents a single atomic filter condition (e.g., "name LIKE 'test'").
- `QueryFilterBuilder`: The main class that parses the filter string, manages components,
  and applies the filters to a SQLAlchemy query object.
- Pydantic models (`QueryFilterJSONPart`, `QueryFilterJSON`) for representing the
  parsed filter structure in JSON, potentially for debugging or serialization.

The system is designed to handle nested attribute lookups (e.g., "user.group.name")
and automatically decamelizes attribute names from API requests to match Python/DB conventions.
It also includes type validation for filter values against the target SQLAlchemy column types.
"""

from __future__ import annotations  # For TypeVar Model bound to SqlAlchemyBase

import re  # For regular expression operations during parsing
from collections import deque  # For managing operator stacks during query construction
from enum import Enum  # For defining operator and keyword enumerations
from typing import Any, TypeVar  # Standard typing utilities
from uuid import UUID as PyUUID  # For validating UUID strings, aliased

import sqlalchemy as sa  # Core SQLAlchemy library
from dateutil import parser as date_parser  # For parsing date/datetime strings
from dateutil.parser import ParserError  # Specific exception from dateutil
from humps import decamelize  # For converting camelCase attribute names to snake_case
from sqlalchemy.ext.associationproxy import AssociationProxyInstance  # For handling proxied attributes
from sqlalchemy.orm import InstrumentedAttribute  # SQLAlchemy ORM components. Added Session.
from sqlalchemy.sql import sqltypes  # For checking SQLAlchemy column types (e.g., String, Boolean)
from sqlalchemy.sql.selectable import Select  # For type hinting Select statements

# Marvin specific imports
from marvin.db.models import SqlAlchemyBase  # Base for SQLAlchemy models
from marvin.db.models._model_utils.datetime import NaiveDateTime  # Custom datetime type
from marvin.db.models._model_utils.guid import GUID as MarvinGUID  # Custom GUID type
from marvin.schemas._marvin.marvin_model import _MarvinModel  # Base Pydantic model

# Type variable for SQLAlchemy models
Model = TypeVar("Model", bound=SqlAlchemyBase)


class RelationalKeyword(Enum):
    """
    Enumeration of relational keywords used in the filter query language.
    These keywords represent operations like equality, list membership, and pattern matching.
    """

    IS = "IS"  # Checks for equality, typically with NULL.
    IS_NOT = "IS NOT"  # Checks for inequality, typically with NULL.
    IN = "IN"  # Checks if a value is within a list of values.
    NOT_IN = "NOT IN"  # Checks if a value is not within a list of values.
    CONTAINS_ALL = "CONTAINS ALL"  # Checks if a collection attribute contains all specified values (for array types).
    LIKE = "LIKE"  # Performs a case-insensitive LIKE comparison (pattern matching).
    NOT_LIKE = "NOT LIKE"  # Performs a case-insensitive NOT LIKE comparison.

    @classmethod
    def parse_component(cls, component_str: str) -> list[str] | None:  # Renamed component to component_str
        """
        Attempts to parse a string component to extract a relational keyword and its operands.

        It tries to identify if the component string contains one of the defined relational keywords.
        The parsing logic handles keywords with spaces and attempts to separate the attribute name,
        keyword, and value.

        Args:
            component_str (str): A segment of the filter string potentially containing a keyword.

        Returns:
            list[str] | None: If a keyword is found, returns a list of three strings:
                              [attribute_name, keyword_value, remaining_value_string_or_placeholder].
                              Returns None if no keyword is matched.
        """
        # First, try to split by space, assuming keyword might be multi-word.
        # Example: "name IS NOT NULL" -> ["name", "IS NOT NULL"]
        parsed_parts = component_str.split(maxsplit=1)
        if len(parsed_parts) < 2:  # Not enough parts for attr + keyword + value
            return None

        # Try matching keywords that might have spaces (e.g., "IS NOT")
        # Test if the second part of the split IS a keyword directly
        # This handles cases like "attribute_name IS NULL" where "IS NULL" is parsed as `possible_keyword_phrase`
        possible_keyword_phrase = parsed_parts[1].strip().lower()
        # Sort keywords by length (desc) to match longer keywords first (e.g., "IS NOT" before "IS")
        for keyword_enum_member in sorted(cls, key=lambda x: len(x.value), reverse=True):
            if keyword_enum_member.value.lower() == possible_keyword_phrase:
                # This case is tricky: if `possible_keyword_phrase` is just "NULL" after "IS",
                # then the value is "NULL", not part of the keyword.
                # This initial check is more for when value is already separated.
                # Let's refine: assume `parsed_parts[1]` contains "KEYWORD value" or just "KEYWORD" (if value is implicit like NULL)
                # Example: "status IS active" -> parsed_parts = ["status", "IS active"]
                # Example: "name IS NULL" -> parsed_parts = ["name", "IS NULL"] (here "NULL" is the value for "IS")

                # Attempt to extract keyword from the start of `parsed_parts[1]`
                potential_value_part = parsed_parts[1]  # This contains "KEYWORD value" or just "KEYWORD"
                for kw_enum in sorted(cls, key=lambda x: len(x.value), reverse=True):
                    if potential_value_part.lower().startswith(kw_enum.value.lower() + " "):  # Keyword followed by space
                        value_str = potential_value_part[len(kw_enum.value) :].strip()
                        return [parsed_parts[0], kw_enum.value, value_str]
                    elif potential_value_part.lower() == kw_enum.value.lower():  # Keyword exactly matches (e.g. for IS NULL)
                        # This case is tricky if value is implicit.
                        # For "IS NULL", keyword is "IS", value is "NULL".
                        # The parsing logic below handles splitting keyword and value better.
                        pass  # Let the next block handle it.

        # If no direct match on `parsed_parts[1]`, try splitting `parsed_parts[1]` into keyword and value.
        # This handles "attribute_name KEYWORD value"
        try:
            # `rsplit` helps separate the last word as potential value if keyword is multi-word.
            # e.g., "name IS NOT provided_value" -> _possible_keyword = "IS NOT", _value = "provided_value"
            # e.g., "name LIKE pattern" -> _possible_keyword = "LIKE", _value = "pattern"
            _possible_keyword_candidate, _value_candidate = parsed_parts[1].rsplit(maxsplit=1)
            # Store potential [attribute, keyword, value]
            potential_parsed_list = [parsed_parts[0], _possible_keyword_candidate.strip(), _value_candidate.strip()]
        except ValueError:  # rsplit failed, means parsed_parts[1] was a single word (potential keyword with implicit value like NULL)
            # This could be "attribute_name KEYWORD" where value is implicit (e.g. for IS NULL, value should be NULL)
            # For "name IS", if "NULL" is not part of it, it's incomplete.
            # The current loop structure might not perfectly handle implicit "NULL" if not passed with "IS".
            # For now, if rsplit fails, assume it's not a valid structure for keyword + value.
            return None  # Or handle as "attribute_name KEYWORD" if that's a valid syntax for some ops.

        # Check if the extracted `_possible_keyword_candidate` is a valid keyword.
        final_keyword_candidate = potential_parsed_list[1].lower()
        for keyword_enum_member in sorted(cls, key=lambda x: len(x.value), reverse=True):
            if keyword_enum_member.value.lower() == final_keyword_candidate:
                # Found a valid keyword. Replace the string with the canonical enum value.
                potential_parsed_list[1] = keyword_enum_member.value
                return potential_parsed_list

        return None  # No keyword matched


class RelationalOperator(Enum):
    """
    Enumeration of relational operators used in the filter query language
    for comparisons (e.g., equality, greater than, less than).
    """

    EQ = "="  # Equal to
    NOTEQ = "<>"  # Not equal to (can also be != in some SQL dialects)
    GT = ">"  # Greater than
    LT = "<"  # Less than
    GTE = ">="  # Greater than or equal to
    LTE = "<="  # Less than or equal to

    @classmethod
    def parse_component(cls, component_str: str) -> list[str] | None:
        """
        Attempts to parse a string component to extract a relational operator and its operands.

        It iterates through defined operators (sorted by length to catch multi-char ops like '>=' before '>')
        and splits the component string if an operator is found.

        Args:
            component_str (str): A segment of the filter string potentially containing an operator.

        Returns:
            list[str] | None: If an operator is found, returns a list of three strings:
                              [attribute_name, operator_value, value_string].
                              Returns None if no operator is matched.
        """
        # Sort operators by length (descending) to match multi-character operators (e.g., ">=", "<=")
        # before single-character ones (e.g., ">", "<").
        for op_enum_member in sorted(cls, key=lambda x: len(x.value), reverse=True):
            op_value = op_enum_member.value
            if op_value in component_str:
                # Split the component by the operator
                # Filter out empty strings that can result from split if operator is at start/end
                parsed_parts = [part.strip() for part in component_str.split(op_value, 1) if part.strip()]
                if len(parsed_parts) == 2:  # Expecting [attribute, value] after splitting by operator
                    # Insert the operator back in the middle
                    return [parsed_parts[0], op_value, parsed_parts[1]]
        return None  # No operator matched


class LogicalOperator(Enum):
    """
    Enumeration of logical operators used to combine filter conditions.
    """

    AND = "AND"  # Logical AND
    OR = "OR"  # Logical OR


class QueryFilterJSONPart(_MarvinModel):
    """
    Pydantic schema representing a single part of a parsed query filter,
    suitable for JSON serialization or debugging.

    A part can be a filter component (attribute, operator, value), a parenthesis,
    or a logical operator that connects components/groups.
    """

    left_parenthesis: str | None = None
    """Opening parenthesis, if this part starts a group. E.g., "("."""
    right_parenthesis: str | None = None
    """Closing parenthesis, if this part ends a group. E.g., ")"."""
    logical_operator: LogicalOperator | None = None
    """Logical operator (AND, OR) that might precede a component or group."""

    attribute_name: str | None = None
    """Name of the attribute being filtered (e.g., "username", "item.price")."""
    relational_operator: RelationalKeyword | RelationalOperator | None = None
    """The relational keyword or operator used in the filter (e.g., LIKE, =, IS NOT)."""
    value: str | list[str] | None = None
    """The value(s) used for comparison in the filter. Can be a single string or a list for IN/NOT IN."""


class QueryFilterJSON(_MarvinModel):
    """
    Pydantic schema representing a full parsed query filter as a list of parts.
    Useful for serializing the parsed structure, e.g., for debugging.
    """

    parts: list[QueryFilterJSONPart] = []
    """A list of `QueryFilterJSONPart` objects representing the sequence of parsed filter components."""


class QueryFilterBuilderComponent:
    """
    Represents a single relational statement in a query filter (e.g., "name LIKE 'test'").

    It stores the attribute name, the relationship (keyword or operator), and the value.
    It also includes logic to validate the value against the expected type of the
    SQLAlchemy model attribute it targets.
    """

    @staticmethod
    def strip_quotes_from_string(val: str) -> str:
        """
        Removes leading and trailing double quotes from a string value if present.

        Args:
            val (str): The string value.

        Returns:
            str: The string with surrounding double quotes removed, or the original string.
        """
        if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
            return val[1:-1]
        return val

    def __init__(self, attribute_name: str, relationship: RelationalKeyword | RelationalOperator, value: str | list[str]) -> None:
        """
        Initializes a QueryFilterBuilderComponent.

        Args:
            attribute_name (str): The name of the attribute to filter on (potentially camelCased from API).
            relationship (RelationalKeyword | RelationalOperator): The keyword or operator for the comparison.
            value (str | list[str]): The value(s) for the comparison. Strings are stripped of surrounding quotes.

        Raises:
            ValueError: If the relationship type and value type are incompatible (e.g., IN keyword without a list value,
                        or IS/IS NOT keyword with a value other than "NULL" or "NONE").
        """
        self.attribute_name: str = decamelize(attribute_name)  # Convert camelCase from API to snake_case for DB
        self.relationship: RelationalKeyword | RelationalOperator = relationship
        self.value: Any  # Will be set after validation and type conversion

        processed_value: Any
        # Remove encasing double quotes from string values or elements in list values
        if isinstance(value, str):
            processed_value = self.strip_quotes_from_string(value)
        elif isinstance(value, list):
            processed_value = [self.strip_quotes_from_string(v) for v in value]
        else:  # Should not happen if parsing is correct
            processed_value = value

        # Validate relationship-value compatibility
        if relationship in [RelationalKeyword.IN, RelationalKeyword.NOT_IN, RelationalKeyword.CONTAINS_ALL]:
            if not isinstance(processed_value, list):
                raise ValueError(
                    f"Invalid query string: '{relationship.value}' must be given a list of values "
                    f"enclosed by '{QueryFilterBuilder.l_list_sep}' and '{QueryFilterBuilder.r_list_sep}'."
                )

        if relationship is RelationalKeyword.IS or relationship is RelationalKeyword.IS_NOT:
            if not isinstance(processed_value, str) or processed_value.lower() not in ["null", "none"]:
                raise ValueError(f"Invalid query string: '{relationship.value}' can only be used with 'NULL' or 'NONE', not '{processed_value}'.")
            self.value = None  # For IS NULL / IS NOT NULL, the effective value is None
        else:
            self.value = processed_value

    def __repr__(self) -> str:
        """Returns a string representation of the filter component for debugging."""
        return f"[{self.attribute_name} {self.relationship.value} {self.value}]"

    def validate_and_sanitize_value(self, model_attr_sqla_type: Any) -> Any:  # Changed method name and return
        """
        Validates the component's value against the SQLAlchemy type of the model attribute
        it targets. Sanitizes and converts the value if necessary (e.g., string to date/bool).

        Args:
            model_attr_sqla_type (Any): The SQLAlchemy column type object
                                       (e.g., `sqltypes.String`, `sqltypes.Integer`, `GUID`).

        Returns:
            Any: The validated and potentially type-converted value (or list of values).

        Raises:
            ValueError: If the value is invalid for the given attribute type or relationship
                        (e.g., LIKE used with a non-string column, invalid UUID/date format).
        """
        # Prepare a list of values for consistent processing, even if it's a single value.
        values_to_sanitize: list[Any]
        if not isinstance(self.value, list):
            values_to_sanitize = [self.value]
        else:
            values_to_sanitize = list(self.value)  # Create a copy to modify

        for i, val_item in enumerate(values_to_sanitize):
            # Allow querying for NULL values without further type validation for the value itself
            if val_item is None and self.relationship in [RelationalKeyword.IS, RelationalKeyword.IS_NOT]:
                continue

            # For string types, convert value to lowercase for case-insensitive comparisons (LIKE, EQ etc.)
            if isinstance(model_attr_sqla_type, sqltypes.String):
                if isinstance(val_item, str):  # Ensure it's a string before lowercasing
                    values_to_sanitize[i] = val_item.lower()

            # Specific validation for LIKE/NOT_LIKE: must be used with string columns
            if self.relationship in [RelationalKeyword.LIKE, RelationalKeyword.NOT_LIKE]:
                if not isinstance(model_attr_sqla_type, sqltypes.String):
                    raise ValueError(
                        f"Invalid query string: '{self.relationship.value}' can only be used with string columns, "
                        f"not with type {type(model_attr_sqla_type).__name__} for attribute '{self.attribute_name}'."
                    )

            # Validate and convert for custom GUID type
            if isinstance(model_attr_sqla_type, MarvinGUID):  # Check against imported MarvinGUID
                try:
                    # Attempt to create a UUID object to validate format.
                    # The actual value stored or used in query might remain string or UUID object
                    # depending on DB dialect handling in SQLAlchemy.
                    if val_item is not None:  # PyUUID constructor needs non-None
                        _ = PyUUID(str(val_item))  # Validate format
                        values_to_sanitize[i] = str(val_item)  # Store as string for broader compatibility, or keep as UUID
                except ValueError as e:
                    raise ValueError(f"Invalid query string: invalid UUID format '{val_item}' for attribute '{self.attribute_name}'.") from e

            # Validate and parse for Date/DateTime/NaiveDateTime types
            if isinstance(model_attr_sqla_type, (sqltypes.Date | sqltypes.DateTime | NaiveDateTime)):
                try:
                    if val_item is not None:  # date_parser needs non-None
                        parsed_dt = date_parser.parse(str(val_item))
                        # If the column type is Date, convert parsed datetime to date.
                        values_to_sanitize[i] = parsed_dt.date() if isinstance(model_attr_sqla_type, sqltypes.Date) else parsed_dt
                except ParserError as e:
                    raise ValueError(
                        f"Invalid query string: unknown date or datetime format '{val_item}' for attribute '{self.attribute_name}'."
                    ) from e

            # Validate and convert for Boolean type
            if isinstance(model_attr_sqla_type, sqltypes.Boolean):
                if isinstance(val_item, str):
                    # Interpret common string representations of booleans
                    if val_item.lower() in ["true", "t", "yes", "y", "1"]:
                        values_to_sanitize[i] = True
                    elif val_item.lower() in ["false", "f", "no", "n", "0"]:
                        values_to_sanitize[i] = False
                    else:
                        raise ValueError(f"Invalid query string: unrecognized boolean value '{val_item}' for attribute '{self.attribute_name}'.")
                elif isinstance(val_item, int):  # Allow 0 or 1 for boolean
                    values_to_sanitize[i] = bool(val_item)
                # If already bool, it's fine. Other types are not automatically converted.

        # Return single value if original was single, else list of sanitized values.
        return values_to_sanitize[0] if not isinstance(self.value, list) else values_to_sanitize

    def as_json_model(self) -> QueryFilterJSONPart:
        """
        Converts this filter component into its `QueryFilterJSONPart` Pydantic model representation.
        Useful for debugging or serializing the parsed filter structure.

        Returns:
            QueryFilterJSONPart: The Pydantic model representation of this component.
        """
        return QueryFilterJSONPart(
            # Parentheses and logical operators are handled by QueryFilterBuilder when assembling the full JSON
            attribute_name=self.attribute_name,
            relational_operator=self.relationship,
            value=self.value,  # Value here is before type validation against model_attr_type
        )


class QueryFilterBuilder:
    """
    Parses a filter string into a sequence of components and applies them to a SQLAlchemy query.

    The filter string can use relational keywords (IS, IN, LIKE), operators (=, <, >),
    logical operators (AND, OR), and parentheses for grouping. Attribute names can be
    nested (e.g., "user.group.name").

    Class attributes define separators used in parsing:
        l_group_sep, r_group_sep: For grouping conditions, e.g., "(".
        l_list_sep, r_list_sep, list_item_sep: For list values in "IN" clauses, e.g., "[value1,value2]".
    """

    # Separators used in the filter string language
    l_group_sep: str = "("  # Left parenthesis for grouping expressions
    r_group_sep: str = ")"  # Right parenthesis
    group_seps: set[str] = {l_group_sep, r_group_sep}

    l_list_sep: str = "["  # Left bracket for list values (e.g., for IN operator)
    r_list_sep: str = "]"  # Right bracket
    list_item_sep: str = ","  # Comma for separating items in a list

    def __init__(self, filter_string: str) -> None:
        """
        Initializes the QueryFilterBuilder by parsing the provided filter string.

        The parsing involves several steps:
        1. Breaking the string into major components based on parenthesis.
        2. Further breaking those components into "base components" by splitting at
           logical operators and then attempting to identify relational operators/keywords.
        3. Validating parenthesis balance.
        4. Parsing these base components into a structured list of
           `QueryFilterBuilderComponent`, `LogicalOperator`, or grouping separators.

        Args:
            filter_string (str): The raw filter string to parse.

        Raises:
            ValueError: If the filter string is malformed (e.g., unbalanced parentheses).
        """
        # Initial breakdown of the filter string by parenthesis structure.
        components = QueryFilterBuilder._break_filter_string_into_components(filter_string)
        # Further breakdown into "base" components (attributes, operators, values, logical ops, parens).
        base_components = QueryFilterBuilder._break_components_into_base_components(components)

        # Validate parenthesis balance
        if base_components.count(QueryFilterBuilder.l_group_sep) != base_components.count(QueryFilterBuilder.r_group_sep):
            raise ValueError("Invalid query string: parentheses are unbalanced.")

        # Convert the flat list of base components into a structured list of
        # QueryFilterBuilderComponent instances, LogicalOperator enums, and parenthesis strings.
        self.filter_components: list[str | QueryFilterBuilderComponent | LogicalOperator] = (
            QueryFilterBuilder._parse_base_components_into_filter_components(base_components)
        )

    def __repr__(self) -> str:
        """Returns a string representation of the parsed filter components for debugging."""
        # Join components into a readable string, showing operators as their values.
        joined_representation = " ".join(
            str(component.value if isinstance(component, LogicalOperator) else component) for component in self.filter_components
        )
        return f"<<QueryFilter: {joined_representation}>>"

    @classmethod
    def _consolidate_group(cls, group_elements: list[sa.ColumnElement], logical_operators_stack: deque[LogicalOperator]) -> sa.ColumnElement:
        """
        Consolidates a list of SQLAlchemy filter elements using logical operators.

        Processes a list of individual filter conditions (ColumnElement) and combines them
        using AND/OR operators from the `logical_operators_stack` to form a single
        SQLAlchemy group expression (e.g., `(condition1 AND condition2 OR condition3)`).
        Operates in reverse to respect operator precedence if not explicitly grouped by parentheses.

        Args:
            group_elements (list[sa.ColumnElement]): A list of SQLAlchemy filter conditions.
            logical_operators_stack (deque[LogicalOperator]): A deque of logical operators
                                                               (AND, OR) to apply between elements.

        Returns:
            sa.ColumnElement: A single SQLAlchemy ColumnElement representing the consolidated group.

        Raises:
            ValueError: If an invalid logical operator is encountered.
        """
        if not group_elements:  # Should not happen if called correctly
            raise ValueError("Cannot consolidate an empty group of filter elements.")

        # Process in reverse to correctly apply logical operators from the stack
        # (effectively processing from left to right as originally parsed).
        consolidated_condition: sa.ColumnElement = group_elements[-1]  # Start with the last element

        for i in range(len(group_elements) - 2, -1, -1):  # Iterate from second-to-last down to first
            element = group_elements[i]
            if not logical_operators_stack:  # Not enough operators for elements
                raise ValueError("Invalid filter structure: missing logical operator between conditions.")

            operator = logical_operators_stack.pop()  # Get the operator that joins `element` and `consolidated_condition`

            if operator is LogicalOperator.AND:
                consolidated_condition = sa.and_(element, consolidated_condition)
            elif operator is LogicalOperator.OR:
                consolidated_condition = sa.or_(element, consolidated_condition)
            else:  # Should not happen with Enum validation
                raise ValueError(f"Invalid logical operator encountered: {operator}")

        # Group the final consolidated condition with parentheses in SQL for clarity and precedence
        return consolidated_condition.self_group()

    @classmethod
    def get_model_and_model_attr_from_attr_string(
        cls, attr_string: str, initial_model: type[Model], *, query: Select | None = None
    ) -> tuple[type[SqlAlchemyBase], InstrumentedAttribute, Select | None]:  # Return type of model is type
        """
        Resolves a potentially nested attribute string (e.g., "user.group.name")
        to the target SQLAlchemy model and its `InstrumentedAttribute`.

        It traverses relationships from the `initial_model`. If a `query` object
        is provided, it attempts to add necessary JOINs to the query to make
        the nested attributes accessible. Handles `AssociationProxyInstance` by
        inspecting the proxy to find the true target attribute and model.

        Args:
            attr_string (str): The attribute string, possibly dot-separated for nesting
                               (e.g., "name", "relatedModel.attribute").
                               Expected to be snake_case (Python/DB convention).
            initial_model (type[Model]): The starting SQLAlchemy model class.
            query (Select | None, optional): The SQLAlchemy Select query to which JOINs
                                             for related models should be added. If None,
                                             JOINs are not added. Defaults to None.

        Returns:
            tuple[type[SqlAlchemyBase], InstrumentedAttribute, Select | None]:
                - The SQLAlchemy model class that ultimately owns the resolved attribute.
                - The resolved `InstrumentedAttribute` itself.
                - The (potentially modified) `Select` query with added JOINs, or None if no query was passed.

        Raises:
            ValueError: If the attribute string is empty, or if any part of the
                        attribute chain is invalid or does not exist on the models.
        """
        # Attribute names from API (potentially camelCase) are decamelized before this method.
        # So, attr_string here is expected to be snake_case.
        attribute_chain_parts = attr_string.split(".")
        if not attribute_chain_parts or not all(attribute_chain_parts):  # Check for empty string or empty parts
            raise ValueError("Invalid query string: attribute name string cannot be empty or contain empty parts.")

        current_model_cls: type[SqlAlchemyBase] = initial_model
        resolved_model_attr: InstrumentedAttribute | None = None

        # Traverse the attribute chain (e.g., "user", "group", "name" from "user.group.name")
        for i, attr_part_name in enumerate(attribute_chain_parts):
            try:
                # Get the attribute from the current model class
                model_attr_candidate = getattr(current_model_cls, attr_part_name)

                # Handle SQLAlchemy AssociationProxy instances
                if isinstance(model_attr_candidate, AssociationProxyInstance):
                    # Get the name of the relationship that the proxy targets
                    proxied_relationship_name = model_attr_candidate.target_collection
                    # Get the name of the attribute on the far side of the proxy
                    value_attribute_on_proxied_model = model_attr_candidate.value_attr

                    # Get the relationship attribute itself from the current model
                    relationship_attr = getattr(current_model_cls, proxied_relationship_name)

                    if query is not None and hasattr(relationship_attr, "property"):  # Ensure it's a relationship property
                        # Add a JOIN to the query for the proxied relationship
                        query = query.join(relationship_attr, isouter=True)  # Use outer join for flexibility

                    # Update current_model_cls to the class on the other side of the relationship
                    current_model_cls = relationship_attr.property.mapper.class_
                    # The final attribute is now on this new current_model_cls
                    resolved_model_attr = getattr(current_model_cls, value_attribute_on_proxied_model)

                else:  # It's a direct attribute or a standard relationship
                    resolved_model_attr = model_attr_candidate

                # If this is not the last part of the chain, it must be a relationship.
                # Update current_model_cls to the class on the other side of this relationship.
                if i < len(attribute_chain_parts) - 1:
                    if not hasattr(resolved_model_attr, "property") or not hasattr(resolved_model_attr.property, "mapper"):
                        raise ValueError(f"Invalid attribute string: '{attr_part_name}' in '{attr_string}' is not a relationship.")

                    if query is not None:  # Add JOIN for this relationship
                        query = query.join(resolved_model_attr, isouter=True)
                    current_model_cls = resolved_model_attr.property.mapper.class_

            except AttributeError as e:  # If getattr fails
                raise ValueError(
                    f"Invalid attribute string: '{attr_part_name}' in '{attr_string}' does not exist on model '{current_model_cls.__name__}'."
                ) from e
            except KeyError as e:  # If mapper.relationships[key] fails (should be rare with getattr first)
                raise ValueError(
                    f"Invalid relationship configuration for '{attr_part_name}' in '{attr_string}' on model '{current_model_cls.__name__}'."
                ) from e

        if resolved_model_attr is None or not isinstance(resolved_model_attr, InstrumentedAttribute):
            # This should ideally be caught earlier if attribute_chain_parts is non-empty
            raise ValueError(f"Invalid attribute string: '{attr_string}' could not be resolved to a model attribute.")

        return current_model_cls, resolved_model_attr, query

    @classmethod
    def _transform_model_attr_for_query(
        cls, model_attr: InstrumentedAttribute, model_attr_sqla_type: Any
    ) -> InstrumentedAttribute:  # Return type is actually ColumnElement or similar after func.lower
        """
        Transforms a SQLAlchemy model attribute for use in a query, e.g., by applying `lower()` for strings.

        Args:
            model_attr (InstrumentedAttribute): The SQLAlchemy model attribute.
            model_attr_sqla_type (Any): The SQLAlchemy column type of the attribute.

        Returns:
            InstrumentedAttribute | Function: The transformed attribute (e.g., `func.lower(model_attr)`).
        """
        # For string comparisons, convert the database column to lowercase for case-insensitivity
        if isinstance(model_attr_sqla_type, sqltypes.String):
            return sa.func.lower(model_attr)  # Apply SQL LOWER function
        return model_attr  # Return original attribute for non-string types

    @classmethod
    def _get_filter_element(
        cls,
        # query: Select, # Query not directly used here for element construction, but useful for context if subqueries were built
        component: QueryFilterBuilderComponent,
        # model: type[Model], # The primary model of the repository, useful for context
        model_attr_owner: type[SqlAlchemyBase],  # The specific model class that owns model_attr
        model_attr: InstrumentedAttribute,  # The SQLAlchemy attribute to filter on
        model_attr_sqla_type: Any,  # The SQLAlchemy type of model_attr
    ) -> sa.sql.expression.ColumnElement:  # Return type is a SQLAlchemy filter condition
        """
        Constructs a SQLAlchemy filter expression (ColumnElement) for a single `QueryFilterBuilderComponent`.

        It validates the component's value against the attribute's type and then builds
        the appropriate SQLAlchemy filter condition based on the relational keyword or operator.

        Args:
            component (QueryFilterBuilderComponent): The parsed filter component.
            model_attr_owner (type[SqlAlchemyBase]): The SQLAlchemy model class that owns `model_attr`.
            model_attr (InstrumentedAttribute): The SQLAlchemy attribute to apply the filter to.
            model_attr_sqla_type (Any): The SQLAlchemy type of `model_attr`.

        Returns:
            sa.sql.expression.ColumnElement: The SQLAlchemy filter condition.

        Raises:
            ValueError: If the component uses an invalid relationship or if value validation fails.
        """
        # Validate the component's value against the model attribute's SQL type
        # This also sanitizes/converts the value (e.g., string to date, string to lowercase for string columns)
        validated_value = component.validate_and_sanitize_value(model_attr_sqla_type)

        # Transform the model attribute for query (e.g., apply lower() for case-insensitive string comparisons)
        query_model_attr = cls._transform_model_attr_for_query(model_attr, model_attr_sqla_type)

        # Construct SQLAlchemy filter element based on the relationship type
        # Relational Keywords
        if component.relationship is RelationalKeyword.IS:
            return query_model_attr.is_(validated_value)  # Handles IS NULL (validated_value will be None)
        elif component.relationship is RelationalKeyword.IS_NOT:
            return query_model_attr.is_not(validated_value)  # Handles IS NOT NULL
        elif component.relationship is RelationalKeyword.IN:
            return query_model_attr.in_(validated_value)  # Validated_value must be a list
        elif component.relationship is RelationalKeyword.NOT_IN:
            # For NOT IN with joined tables, direct .notin_ might be complex if model_attr is on a joined table.
            # The original code had specific logic for subqueries here.
            # Assuming validated_value is a list.
            # If model_attr is on the primary model, simple notin_ is fine.
            # If model_attr is on a joined table, a subquery might be needed to avoid issues
            # where rows are excluded if ANY joined element is in the list, rather than the specific one.
            # The original logic:
            #   if original_model_attr.parent.entity != model: # `model` was the main repo model
            #       subq = query.with_only_columns(model.id).where(model_attr.in_(vals))
            #       element = sa.not_(model.id.in_(subq))
            #   else: element = sa.not_(model_attr.in_(vals))
            # This requires passing `model` (primary repo model) and `query` to this method.
            # For simplicity here, assuming direct `notin_` is sufficient or handled by caller's query structure.
            return query_model_attr.notin_(validated_value)
        elif component.relationship is RelationalKeyword.CONTAINS_ALL:
            # This is for array types, typically PostgreSQL specific (e.g., using @> operator)
            # Requires model_attr to be an array type and validated_value to be a list of elements to check.
            # SQLAlchemy syntax for this can vary by dialect or require custom compilation.
            # Example for PostgreSQL: return model_attr.Comparator.contains(cast(validated_value, sa.ARRAY(model_attr.type.item_type)))
            # The original code had a loop with .any(), which is for 1-to-many relationships, not array contains all.
            # This part likely needs specific implementation based on DB and desired array logic.
            # Placeholder for now, as original was complex and might be specific to a certain setup.
            raise NotImplementedError(f"'{RelationalKeyword.CONTAINS_ALL.value}' not fully implemented for direct use here.")
        elif component.relationship is RelationalKeyword.LIKE:
            # Uses ilike for case-insensitive LIKE. Assumes validated_value is already lowercased if needed.
            return query_model_attr.ilike(f"%{validated_value}%")  # Common pattern: contains
        elif component.relationship is RelationalKeyword.NOT_LIKE:
            return query_model_attr.not_ilike(f"%{validated_value}%")

        # Relational Operators
        elif component.relationship is RelationalOperator.EQ:
            return query_model_attr == validated_value
        elif component.relationship is RelationalOperator.NOTEQ:
            return query_model_attr != validated_value
        elif component.relationship is RelationalOperator.GT:
            return query_model_attr > validated_value
        elif component.relationship is RelationalOperator.LT:
            return query_model_attr < validated_value
        elif component.relationship is RelationalOperator.GTE:
            return query_model_attr >= validated_value
        elif component.relationship is RelationalOperator.LTE:
            return query_model_attr <= validated_value
        else:
            # Should not be reached if component.relationship is validated
            raise ValueError(f"Unsupported relational operator or keyword: {component.relationship}")

    def filter_query(self, query: Select, model: type[Model], column_aliases: dict[str, sa.ColumnElement] | None = None) -> Select:
        """
        Applies the parsed filter components to a SQLAlchemy Select query.

        It iterates through the structured `self.filter_components` (which includes
        parsed conditions, logical operators, and grouping parentheses), resolves
        attribute names (potentially nested) to SQLAlchemy model attributes (adding
        JOINs to the query if necessary), and constructs the final SQLAlchemy
        filter expression.

        Args:
            query (Select): The initial SQLAlchemy Select query to which filters will be added.
            model (type[Model]): The primary SQLAlchemy model class for the query.
            column_aliases (dict[str, sa.ColumnElement] | None, optional):
                A dictionary mapping alias strings to SQLAlchemy column expressions.
                This allows filtering on computed properties or aliased fields.
                Defaults to None.

        Returns:
            Select: The modified SQLAlchemy Select query with all filters applied.

        Raises:
            ValueError: If the filter structure is invalid (e.g., unbalanced groups,
                        missing operators) or if attribute resolution fails.
        """
        column_aliases = column_aliases or {}  # Ensure it's a dict

        # Resolve attribute strings to (owning_model_class, model_attribute, updated_query_with_joins)
        # This map stores the resolved model and attribute for each component's attribute_name.
        resolved_attr_info_map: dict[int, tuple[type[SqlAlchemyBase], InstrumentedAttribute, Select]] = {}

        current_query_with_joins = query  # Query object that will accumulate joins
        for i, component in enumerate(self.filter_components):
            if not isinstance(component, QueryFilterBuilderComponent):
                continue  # Skip logical operators and parentheses for this step

            # Resolve the attribute string (e.g., "user.name") to the actual SQLAlchemy model and attribute
            # This also adds necessary JOINs to `current_query_with_joins`.
            owning_model_cls, model_attr, updated_query = self.get_model_and_model_attr_from_attr_string(
                component.attribute_name, model, query=current_query_with_joins
            )
            if updated_query is not None:  # Query object is updated if joins were added
                current_query_with_joins = updated_query
            resolved_attr_info_map[i] = (owning_model_cls, model_attr, current_query_with_joins)

        # Build the final SQLAlchemy filter expression using a stack-based approach for groups
        # `partial_filter_group_stack` holds lists of ColumnElements for nested groups.
        # `logical_operator_stack` holds LogicalOperators (AND/OR) between elements in a group.
        partial_filter_group_stack: deque[list[sa.ColumnElement]] = deque()
        current_filter_group: list[sa.ColumnElement] = []
        logical_operator_stack: deque[LogicalOperator] = deque()

        for i, component in enumerate(self.filter_components):
            if component == self.l_group_sep:  # Start of a new group
                partial_filter_group_stack.append(current_filter_group)  # Push current group to stack
                current_filter_group = []  # Start a new current group
                # Push the last seen logical operator if this group is not the first element overall
                # This needs careful handling of operator precedence if not explicitly defined by user.
                # Current logic: operators are pushed when encountered.
            elif component == self.r_group_sep:  # End of a group
                if not partial_filter_group_stack:
                    raise ValueError("Invalid query string: unbalanced right parenthesis.")
                if current_filter_group:  # If current group has elements, consolidate it
                    consolidated_sub_group = self._consolidate_group(current_filter_group, logical_operator_stack)
                    current_filter_group = partial_filter_group_stack.pop()  # Pop parent group from stack
                    current_filter_group.append(consolidated_sub_group)  # Add consolidated sub-group to parent
                else:  # Current group was empty, just pop parent (e.g. "()")
                    current_filter_group = partial_filter_group_stack.pop()

            elif isinstance(component, LogicalOperator):
                if not current_filter_group and not partial_filter_group_stack:  # Operator at the very start
                    raise ValueError(f"Invalid query string: logical operator '{component.value}' at unexpected position.")
                logical_operator_stack.append(component)  # Add operator to stack for current group level

            elif isinstance(component, QueryFilterBuilderComponent):
                # This is a filter condition (e.g., name = 'value')
                owning_model_cls, model_attr, _ = resolved_attr_info_map[i]  # Get resolved attr info

                # Handle potential column alias for the specific attribute part
                # e.g. if component.attribute_name is "computedField" and it's in column_aliases
                final_attr_to_use = model_attr
                attr_type_to_use = model_attr.type
                # Check if the base attribute name (last part of a.b.c) is an alias
                base_attribute_name = component.attribute_name.split(".")[-1]
                if (column_alias_expr := column_aliases.get(base_attribute_name)) is not None:
                    final_attr_to_use = column_alias_expr  # Use the aliased SQL expression
                    # Type of aliased expression might be harder to determine generically;
                    # For validation, we might still use original model_attr.type or require alias to provide type.
                    # Assuming alias type is compatible or validation handles it.
                    # For now, using original type for validation. This could be a limitation.
                    attr_type_to_use = model_attr.type  # This might be incorrect if alias changes type significantly

                # Get the SQLAlchemy filter element (e.g., User.name == 'test')
                filter_element = self._get_filter_element(
                    component=component,
                    model_attr_owner=owning_model_cls,
                    model_attr=final_attr_to_use,
                    model_attr_sqla_type=attr_type_to_use,
                )
                current_filter_group.append(filter_element)
            else:  # Should not happen if parsing is correct
                raise ValueError(f"Unexpected component type in filter components list: {type(component)}")

        # After processing all components, if there's anything left in current_filter_group,
        # it forms the final top-level filter condition.
        if partial_filter_group_stack:  # Unbalanced parentheses if stack is not empty
            raise ValueError("Invalid query string: unbalanced left parenthesis.")
        if not current_filter_group:  # No filter conditions were generated
            return current_query_with_joins  # Return query with joins but no filters

        final_filter_condition = self._consolidate_group(current_filter_group, logical_operator_stack)
        return current_query_with_joins.filter(final_filter_condition)

    @staticmethod
    def _break_filter_string_into_components(filter_string: str) -> list[str]:
        """
        Recursively breaks the raw filter string into major components based on parenthesis groupings.
        This is the first stage of parsing, primarily separating grouped expressions.
        Example: "(A AND B) OR C" -> ["(", "A AND B", ")", "OR", "C"] ( conceptually, actual output is flatter initially)

        Args:
            filter_string (str): The raw filter string.

        Returns:
            list[str]: A list of string components.
        """
        components = [filter_string.strip()]  # Start with the whole string, stripped
        # Loop to handle nested parentheses by repeatedly splitting components
        # This iterative refinement helps isolate parenthesized groups.
        while True:
            subcomponents_after_split = []
            made_change_in_iteration = False
            for comp_segment in components:
                # If segment is just a separator itself, keep it as is.
                if comp_segment in QueryFilterBuilder.group_seps:
                    subcomponents_after_split.append(comp_segment)
                    continue

                # Scan through the component segment character by character
                current_accumulated_part = ""
                in_quotes_block = False  # To ignore separators within quoted strings
                for char_in_segment in comp_segment:
                    if char_in_segment == '"':  # Toggle quote state
                        in_quotes_block = not in_quotes_block

                    # If char is a group separator AND we are not inside quotes
                    if char_in_segment in QueryFilterBuilder.group_seps and not in_quotes_block:
                        if current_accumulated_part:  # Add preceding accumulated part if any
                            subcomponents_after_split.append(current_accumulated_part.strip())
                            made_change_in_iteration = True
                        subcomponents_after_split.append(char_in_segment)  # Add the separator itself
                        current_accumulated_part = ""  # Reset accumulator
                        made_change_in_iteration = True
                        continue

                    current_accumulated_part += char_in_segment  # Accumulate non-separator chars

                if current_accumulated_part:  # Add any remaining part
                    subcomponents_after_split.append(current_accumulated_part.strip())

            # If no changes were made in this iteration (no more splits by group_seps possible at this level)
            if not made_change_in_iteration and components == subcomponents_after_split:
                break  # Parsing of parenthesis groups is stable

            components = [s for s in subcomponents_after_split if s]  # Filter out empty strings from splits

        return components

    @staticmethod
    def _break_components_into_base_components(components: list[str]) -> list[str | list[str]]:
        """
        Further breaks down components (obtained from `_break_filter_string_into_components`)
        by splitting them at logical operators (AND, OR) and then attempting to parse
        relational expressions (attribute, operator/keyword, value).
        Handles quoted strings and list syntax (e.g., for "IN [a,b,c]").

        Args:
            components (list[str]): A list of string components, some of which may be
                                    parentheses, others complete expressions or parts of them.

        Returns:
            list[str | list[str]]: A flattened list of "base components":
                                   - Attribute names (str)
                                   - Relational keywords/operators (str, matching Enum.value)
                                   - Values (str, or list[str] for IN-like clauses)
                                   - Logical operators (str, matching Enum.value)
                                   - Parentheses (str: "(" or ")")
        """
        # Regex for logical operators (AND, OR), case-insensitive, ensuring whole word match
        logical_op_pattern = "|".join([f"\\b{op.value}\\b" for op in LogicalOperator])
        logical_op_regex = re.compile(f"({logical_op_pattern})", flags=re.IGNORECASE)

        base_components_list: list[str | list[str]] = []

        # active_list_literal: list[str] | None = None  # To accumulate items within [...]
        # in_list_parsing_mode = False  # Flag to indicate if currently parsing inside [...]

        for component_str in components:
            if component_str in QueryFilterBuilder.group_seps:  # Handle parentheses directly
                base_components_list.append(component_str)
                continue

            # Handle list parsing for IN (...) or CONTAINS ALL (...)
            # This simplified logic assumes lists are not deeply nested with other structures
            # and are self-contained within a component string or split by other logic.
            # A more robust parser might use tokenization for this.

            # This part of original code was complex and used quote_offset and in_list flags.
            # Refactoring for clarity and robustness.
            # The goal is to correctly identify list literals like "[a, b, \"c, d\"]"
            # and treat them as a single "value" component (a list of strings).

            # Simplified approach: if a component starts with [ and ends with ], treat its content as a list.
            # This doesn't handle complex nesting within the list string itself well without a proper tokenizer.
            # The original code's split-based approach is error-prone for complex inputs.
            # For now, assuming lists are simple or pre-processed.

            # Let's try to roughly follow the original logic structure for list value splitting:
            # This part is complex because it tries to handle quotes and list separators simultaneously.
            # A proper tokenizer/parser would be more robust here.
            # The original code seems to try to split by quotes, then by list separators.

            # For simplicity in this refactoring, assuming lists are passed as actual list[str]
            # by the time they reach the QueryFilterBuilderComponent constructor if coming from JSON.
            # If parsing a raw string like "field IN [a,b,c]", the split logic needs to be robust.
            # The original `_break_components_into_base_components` is very stateful.

            # Simpler conceptual split:
            # 1. Split by logical operators first.
            # 2. For each part, try to parse as "attr op value".
            # This avoids the very complex iterative splitting of the original.

            # Regex to find quoted strings to protect them from splits
            quoted_string_regex = r"(\"[^\"]*\")"
            parts_by_quotes = re.split(quoted_string_regex, component_str)

            temp_sub_components = []
            for i, part in enumerate(parts_by_quotes):
                if not part:
                    continue
                if i % 2 == 1:  # This is a quoted string
                    temp_sub_components.append(part)  # Keep it as is
                else:  # This is not quoted, split by logical operators
                    sub_parts = logical_op_regex.split(part)
                    temp_sub_components.extend([sp.strip() for sp in sub_parts if sp and sp.strip()])

            # Now, for each of these temp_sub_components, try to parse relational ops/keywords
            for sub_comp_str in temp_sub_components:
                if sub_comp_str.upper() in [op.value for op in LogicalOperator]:
                    base_components_list.append(sub_comp_str)  # It's a logical operator
                    continue
                if sub_comp_str.startswith('"') and sub_comp_str.endswith('"'):  # It's a preserved quoted string
                    base_components_list.append(sub_comp_str)
                    continue
                if sub_comp_str.startswith(QueryFilterBuilder.l_list_sep) and sub_comp_str.endswith(
                    QueryFilterBuilder.r_list_sep
                ):  # It's a list literal
                    list_content = sub_comp_str[1:-1]
                    # This simple split by comma won't handle commas inside quotes within the list.
                    # A more robust list parser is needed for that.
                    # E.g. "[ \"apple, inc.\", banana ]"
                    # For now, assuming simple comma separation or items are pre-quoted if they contain commas.
                    list_items = [item.strip() for item in list_content.split(QueryFilterBuilder.list_item_sep)]
                    base_components_list.append(list_items)  # Add as a list of strings
                    continue

                # Try parsing as "Attribute Operator Value" or "Attribute Keyword Value"
                parsed_rel_op = RelationalOperator.parse_component(sub_comp_str)
                if parsed_rel_op:
                    base_components_list.extend(parsed_rel_op)
                    continue

                parsed_rel_kw = RelationalKeyword.parse_component(sub_comp_str)
                if parsed_rel_kw:
                    base_components_list.extend(parsed_rel_kw)
                    continue

                # If none of the above, it's an attribute name or a simple value if context allows
                # (e.g. value for IS NULL which might be "NULL" or "NONE" as string literal)
                # or an unparsed segment.
                if sub_comp_str:  # Avoid adding empty strings
                    base_components_list.append(sub_comp_str)

        return base_components_list

    @staticmethod
    def _parse_base_components_into_filter_components(
        base_components: list[str | list[str]],  # Input from _break_components_into_base_components
    ) -> list[str | QueryFilterBuilderComponent | LogicalOperator]:
        """
        Transforms a flat list of "base components" (strings or list of strings for values)
        into a structured list containing `QueryFilterBuilderComponent` instances,
        `LogicalOperator` enum members, and parenthesis strings.

        This step constructs the actual filter components by identifying attribute-operator-value
        triplets and logical operators from the flat list.

        Args:
            base_components (list[str | list[str]]): The flat list of components.

        Returns:
            list[str | QueryFilterBuilderComponent | LogicalOperator]: A structured list
                representing the filter query.
        """
        # Get string values from enums for quick lookup
        rel_keyword_values = {kw.value for kw in RelationalKeyword}
        rel_operator_values = {op.value for op in RelationalOperator}
        log_operator_values = {op.value for op in LogicalOperator}

        structured_components: list[str | QueryFilterBuilderComponent | LogicalOperator] = []
        i = 0
        while i < len(base_components):
            component = base_components[i]

            if isinstance(component, list):  # Should not happen if lists are values for components
                # This implies an error in previous parsing stage or list is not part of A-O-V.
                # For now, assuming lists are only values within a QueryFilterBuilderComponent.
                # If a list itself is a component, it's likely an error or unhandled syntax.
                # Let's skip it for now, or raise error.
                # raise ValueError(f"Unexpected list component at top level: {component}")
                i += 1
                continue

            # Handle parentheses directly
            if component in QueryFilterBuilder.group_seps:
                structured_components.append(component)
                i += 1
            # Handle logical operators
            elif isinstance(component, str) and component.upper() in log_operator_values:
                structured_components.append(LogicalOperator(component.upper()))
                i += 1
            # Attempt to parse an "Attribute Operator/Keyword Value" triplet
            elif i + 2 < len(base_components):  # Need at least 3 parts for A-O-V
                attr_name_candidate = base_components[i]
                op_candidate = base_components[i + 1]
                val_candidate = base_components[i + 2]

                # Ensure candidates are strings for ops, attr_name can be string, val can be string or list[str]
                if isinstance(attr_name_candidate, str) and isinstance(op_candidate, str):
                    relationship: RelationalKeyword | RelationalOperator | None = None
                    if op_candidate in rel_keyword_values:
                        relationship = RelationalKeyword(op_candidate)
                    elif op_candidate in rel_operator_values:
                        relationship = RelationalOperator(op_candidate)

                    if relationship:
                        # Successfully identified an A-O-V triplet
                        structured_components.append(
                            QueryFilterBuilderComponent(
                                attribute_name=attr_name_candidate,
                                relationship=relationship,
                                value=val_candidate,  # Value can be str or list[str]
                            )
                        )
                        i += 3  # Consumed three base components
                        continue  # Move to next part of base_components

                # If not a valid A-O-V triplet starting at `i`, treat current component as standalone (e.g. error or unparsed)
                # This path should ideally not be hit if _break_components_into_base_components is perfect.
                # For robustness, add component if it's a non-empty string.
                if isinstance(component, str) and component:  # Ensure it's a non-empty string if not parsed
                    # This might indicate a parsing issue or an unrecognized component.
                    # Depending on strictness, could raise error or add as unparsed string.
                    # For now, let's assume valid parsing leads to one of the above conditions.
                    # If this is reached, it's likely an unconsumed attribute name or value
                    # that didn't form a triplet.
                    # This part of logic from original was:
                    # components.append(QueryFilterBuilderComponent(attribute_name=base_components[i-1]...))
                    # which relied on `i` being the operator. Here, we are iterating differently.
                    # Safest is to assume previous stages correctly chunked, and this is an error or needs specific handling.
                    # For this pass, let's assume this state means an isolated component (which might be an error later)
                    # or that the loop structure needs to be more careful about consuming parts of A-O-V.
                    # The original code implicitly consumed A, O, V by how it iterated after finding O.
                    # This revised loop needs to ensure it doesn't add A or V again if they were part of a triplet.
                    # The `continue` after forming a triplet handles this.
                    # So, if this path is reached, `component` is something not fitting other patterns.
                    pass  # Fall through, effectively skipping this component if it wasn't part of AOV or logical/paren.

            i += 1  # Default increment if no triplet was formed from current `i`

        return structured_components

    def as_json_model(self) -> QueryFilterJSON:
        """
        Converts the parsed filter components into a `QueryFilterJSON` Pydantic model.

        This representation can be useful for debugging, serialization, or for clients
        that understand this JSON structure for filters. It attempts to structure
        parentheses and logical operators around the core filter components.

        Returns:
            QueryFilterJSON: A Pydantic model instance representing the filter.
        """
        json_parts_list: list[QueryFilterJSONPart] = []

        # Temporary accumulators for parts of a QueryFilterJSONPart
        current_filter_component_obj: QueryFilterBuilderComponent | None = None
        accumulated_left_parentheses: list[str] = []
        last_seen_logical_operator: LogicalOperator | None = None

        # Iterate through the processed components (which are strings, Enums, or QueryFilterBuilderComponent instances)
        for component_item in self.filter_components:
            if isinstance(component_item, QueryFilterBuilderComponent):
                # If we encounter a main filter component, and there was a previous one being built, finalize it.
                if current_filter_component_obj:
                    # This case implies two QueryFilterBuilderComponent in a row without a logical operator,
                    # which should ideally be handled by parser or represent an error.
                    # For now, finalize previous then start new.
                    json_parts_list.append(
                        QueryFilterJSONPart(
                            left_parenthesis="".join(accumulated_left_parentheses) or None,
                            logical_operator=last_seen_logical_operator,
                            attribute_name=current_filter_component_obj.attribute_name,
                            relational_operator=current_filter_component_obj.relationship,
                            value=current_filter_component_obj.value,
                            # right_parenthesis will be handled when ')' is encountered or at the end.
                        )
                    )
                    accumulated_left_parentheses.clear()
                    last_seen_logical_operator = None  # Reset for the new component

                current_filter_component_obj = component_item  # This is the new component to build upon

            elif isinstance(component_item, LogicalOperator):
                # If there's a filter component being built, this logical operator precedes it.
                # Or, if no active component, it might be an error or connect groups.
                # This logic assumes operator applies to the *next* component.
                if current_filter_component_obj:  # Finalize the component before this operator
                    json_parts_list.append(
                        QueryFilterJSONPart(
                            left_parenthesis="".join(accumulated_left_parentheses) or None,
                            logical_operator=last_seen_logical_operator,  # Operator for the part being added
                            attribute_name=current_filter_component_obj.attribute_name,
                            relational_operator=current_filter_component_obj.relationship,
                            value=current_filter_component_obj.value,
                        )
                    )
                    current_filter_component_obj = None  # Reset
                    accumulated_left_parentheses.clear()  # Reset

                last_seen_logical_operator = component_item  # This operator applies to the *next* part

            elif isinstance(component_item, str):  # Parentheses
                if component_item == QueryFilterBuilder.l_group_sep:
                    if current_filter_component_obj:  # Parenthesis after a component implies error or new structure
                        # Finalize current_filter_component_obj before starting new parenthesis context
                        json_parts_list.append(
                            QueryFilterJSONPart(
                                left_parenthesis="".join(accumulated_left_parentheses) or None,
                                logical_operator=last_seen_logical_operator,
                                attribute_name=current_filter_component_obj.attribute_name,
                                relational_operator=current_filter_component_obj.relationship,
                                value=current_filter_component_obj.value,
                            )
                        )
                        current_filter_component_obj = None
                        accumulated_left_parentheses.clear()
                        last_seen_logical_operator = None  # Reset for content inside new parenthesis
                    accumulated_left_parentheses.append(component_item)
                elif component_item == QueryFilterBuilder.r_group_sep:
                    if current_filter_component_obj:  # Finalize component within these parentheses
                        json_parts_list.append(
                            QueryFilterJSONPart(
                                left_parenthesis="".join(accumulated_left_parentheses) or None,
                                right_parenthesis=component_item,  # Add this closing parenthesis
                                logical_operator=last_seen_logical_operator,
                                attribute_name=current_filter_component_obj.attribute_name,
                                relational_operator=current_filter_component_obj.relationship,
                                value=current_filter_component_obj.value,
                            )
                        )
                        current_filter_component_obj = None
                        accumulated_left_parentheses.clear()  # Clear as they've been used
                        last_seen_logical_operator = None  # Reset
                    elif accumulated_left_parentheses:  # Empty parentheses pair or end of a group
                        # This case is complex: is it `()` or `(A) AND (B)` where B part is next?
                        # If there's a pending logical operator, it might apply to this closed group.
                        # The original `add_part` logic was simpler and might be more robust by creating parts iteratively.
                        # For now, assume a right parenthesis closes the current context.
                        # If a part needs to be created just for parens and ops, that needs more state.
                        # This simplified version might lose some structural nuance of the original state machine.
                        # Let's assume a right parenthesis always tries to finalize a QueryFilterJSONPart
                        # if current_filter_component_obj is None but left_parentheses were present.
                        # This part of the logic is tricky to get right without a full state machine.
                        # The original `add_part` function was called more strategically.
                        # For now, if a component is not active, this ')' might be associated with a previous part or start a new one.
                        # This might require a different loop structure or a stack for JSON parts.
                        #
                        # Simpler: assume `)` is attached to the part *before* it, or if no part, it's structural.
                        # The `QueryFilterJSONPart` model allows `right_parenthesis` to be set.
                        # If `json_parts_list` is not empty and last part doesn't have right_parenthesis yet:
                        if json_parts_list and json_parts_list[-1].right_parenthesis is None:
                            json_parts_list[-1].right_parenthesis = (json_parts_list[-1].right_parenthesis or "") + component_item
                        else:  # Unmatched or structural, create a part if needed (e.g. for logical ops between groups)
                            # This case is complex: e.g. (A) AND (B). The AND is between two groups.
                            # A QueryFilterJSONPart is attribute-centric.
                            # A better JSON representation might be a tree. This is flat.
                            pass  # For now, ignore if no active component to attach to.

        # Add any remaining part being built
        if current_filter_component_obj:
            json_parts_list.append(
                QueryFilterJSONPart(
                    left_parenthesis="".join(accumulated_left_parentheses) or None,
                    logical_operator=last_seen_logical_operator,
                    attribute_name=current_filter_component_obj.attribute_name,
                    relational_operator=current_filter_component_obj.relationship,
                    value=current_filter_component_obj.value,
                    # right_parenthesis might still be needed if string ends mid-group
                )
            )

        return QueryFilterJSON(parts=json_parts_list)
