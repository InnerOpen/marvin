"""Content validation service for schema-driven entries.

This service validates entry content (data_json) against entry type schemas (schema_json).
It ensures that:
- Required fields are present
- Field values match expected types
- Validation constraints are met (min/max, patterns, options, etc.)
"""

import re
from datetime import datetime
from typing import Any

from marvin.schemas.platform.entry_type_schema import (
    AssetFieldSchema,
    AssetListFieldSchema,
    BooleanFieldSchema,
    DateFieldSchema,
    DateTimeFieldSchema,
    EmbedFieldSchema,
    EntryTypeSchemaDefinition,
    FieldSchema,
    JsonFieldSchema,
    MarkdownFieldSchema,
    NumberFieldSchema,
    ResourceFieldSchema,
    ResourceListFieldSchema,
    SelectFieldSchema,
    TextareaFieldSchema,
    TextFieldSchema,
)
from marvin.services import BaseService


class ContentValidationError(ValueError):
    """Raised when entry content fails schema validation."""

    def __init__(self, field_key: str, message: str):
        """Initialize validation error.

        Args:
            field_key: The field that failed validation
            message: Description of the validation failure
        """
        self.field_key = field_key
        self.message = message
        super().__init__(f"Field '{field_key}': {message}")


class ContentValidator(BaseService):
    """Service for validating entry content against entry type schemas."""

    def _validate_string_constraints(
        self,
        field_key: str,
        value: Any,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
    ) -> None:
        """Validate string type and length/pattern constraints.

        Args:
            field_key: The field name for error messages
            value: The value to validate
            min_length: Minimum string length (optional)
            max_length: Maximum string length (optional)
            pattern: Regex pattern to match (optional)

        Raises:
            ContentValidationError: If validation fails
        """
        if not isinstance(value, str):
            raise ContentValidationError(
                field_key,
                f"Expected string, got {type(value).__name__}",
            )

        # Check length constraints
        if min_length is not None and len(value) < min_length:
            raise ContentValidationError(
                field_key,
                f"String length {len(value)} is less than minimum {min_length}",
            )

        if max_length is not None and len(value) > max_length:
            raise ContentValidationError(
                field_key,
                f"String length {len(value)} exceeds maximum {max_length}",
            )

        # Check pattern
        if pattern is not None:
            try:
                if not re.match(pattern, value):
                    raise ContentValidationError(
                        field_key,
                        f"Value does not match pattern: {pattern}",
                    )
            except re.error as e:
                raise ContentValidationError(
                    field_key,
                    f"Invalid regex pattern in schema: {e}",
                ) from e

    def validate_content(
        self,
        schema_definition: EntryTypeSchemaDefinition,
        data_json: dict[str, Any],
    ) -> None:
        """Validate entry content against schema definition.

        Args:
            schema_definition: The entry type's schema definition
            data_json: The entry's content data to validate

        Raises:
            ContentValidationError: If validation fails
        """
        # Check for required fields
        for field in schema_definition.get_required_fields():
            if field.key not in data_json or data_json[field.key] is None:
                raise ContentValidationError(
                    field.key,
                    "Required field is missing or null",
                )

        # Validate each field present in data_json
        for field_key, field_value in data_json.items():
            field_schema = schema_definition.get_field(field_key)

            # Unknown fields are allowed (for flexibility)
            # They'll be stored but won't be validated against schema
            if field_schema is None:
                self.logger.debug(f"Field '{field_key}' not in schema, allowing as custom field")
                continue

            # Skip validation for null values (unless field is required, checked above)
            if field_value is None:
                continue

            # Validate based on field type
            self._validate_field(field_schema, field_value)

    def _validate_field(self, field_schema: FieldSchema, value: Any) -> None:
        """Validate a single field value against its schema.

        Args:
            field_schema: The field's schema definition
            value: The field value to validate

        Raises:
            ContentValidationError: If validation fails
        """
        field_key = field_schema.key

        # Dispatch to type-specific validator
        if isinstance(field_schema, TextFieldSchema | TextareaFieldSchema):
            self._validate_text_field(field_schema, value)
        elif isinstance(field_schema, MarkdownFieldSchema):
            self._validate_markdown_field(field_schema, value)
        elif isinstance(field_schema, NumberFieldSchema):
            self._validate_number_field(field_schema, value)
        elif isinstance(field_schema, BooleanFieldSchema):
            self._validate_boolean_field(field_schema, value)
        elif isinstance(field_schema, SelectFieldSchema):
            self._validate_select_field(field_schema, value)
        elif isinstance(field_schema, DateFieldSchema):
            self._validate_date_field(field_schema, value)
        elif isinstance(field_schema, DateTimeFieldSchema):
            self._validate_datetime_field(field_schema, value)
        elif isinstance(field_schema, JsonFieldSchema):
            self._validate_json_field(field_schema, value)
        elif isinstance(field_schema, EmbedFieldSchema):
            self._validate_embed_field(field_schema, value)
        elif isinstance(field_schema, AssetFieldSchema | ResourceFieldSchema):
            self._validate_reference_field(field_schema, value, is_list=False)
        elif isinstance(field_schema, AssetListFieldSchema | ResourceListFieldSchema):
            self._validate_reference_field(field_schema, value, is_list=True)
        else:
            # Unknown field type - should not happen with discriminated union
            self.logger.warning(f"Unknown field type for field '{field_key}': {type(field_schema)}")

    def _validate_reference_field(self, field_schema: FieldSchema, value: Any, is_list: bool) -> None:
        """Asset/resource reference: an id string, or a list of id strings for list variants."""
        if is_list:
            if not isinstance(value, list):
                raise ContentValidationError(field_schema.key, f"Expected a list of ids, got {type(value).__name__}")
            for item in value:
                if not isinstance(item, str):
                    raise ContentValidationError(field_schema.key, "Each item must be an id string")
        elif not isinstance(value, str):
            raise ContentValidationError(field_schema.key, f"Expected an id string, got {type(value).__name__}")

    def _validate_text_field(self, field_schema: TextFieldSchema | TextareaFieldSchema, value: Any) -> None:
        """Validate text or textarea field."""
        self._validate_string_constraints(
            field_key=field_schema.key,
            value=value,
            min_length=field_schema.min,
            max_length=field_schema.max,
            pattern=getattr(field_schema, "pattern", None),
        )

    def _validate_markdown_field(self, field_schema: MarkdownFieldSchema, value: Any) -> None:
        """Validate markdown field (string type)."""
        if not isinstance(value, str):
            raise ContentValidationError(
                field_schema.key,
                f"Expected string, got {type(value).__name__}",
            )

    def _validate_embed_field(self, field_schema: EmbedFieldSchema, value: Any) -> None:
        """Embed field: a supported media link (empty = unset), from an allowed provider when the field limits them."""
        from marvin.services.media_embeds.matcher import match_url
        from marvin.services.media_embeds.providers import PROVIDERS

        if not isinstance(value, str):
            raise ContentValidationError(field_schema.key, f"Expected a media link, got {type(value).__name__}")
        if not value.strip():
            return
        match = match_url(value)
        if match is None:
            names = ", ".join(p.name for p in PROVIDERS.values())
            raise ContentValidationError(field_schema.key, f"Not a supported media link. Supported: {names}.")
        if field_schema.providers and match.provider.key not in field_schema.providers:
            allowed = ", ".join(PROVIDERS[k].name for k in field_schema.providers if k in PROVIDERS)
            raise ContentValidationError(field_schema.key, f"{match.provider.name} links aren't allowed here (allowed: {allowed}).")

    def _validate_number_field(self, field_schema: NumberFieldSchema, value: Any) -> None:
        """Validate number field."""
        if not isinstance(value, int | float):
            raise ContentValidationError(
                field_schema.key,
                f"Expected number, got {type(value).__name__}",
            )

        # Check range constraints
        if field_schema.min is not None and value < field_schema.min:
            raise ContentValidationError(
                field_schema.key,
                f"Value {value} is less than minimum {field_schema.min}",
            )

        if field_schema.max is not None and value > field_schema.max:
            raise ContentValidationError(
                field_schema.key,
                f"Value {value} exceeds maximum {field_schema.max}",
            )

    def _validate_boolean_field(self, field_schema: BooleanFieldSchema, value: Any) -> None:
        """Validate boolean field."""
        if not isinstance(value, bool):
            raise ContentValidationError(
                field_schema.key,
                f"Expected boolean, got {type(value).__name__}",
            )

    def _validate_select_field(self, field_schema: SelectFieldSchema, value: Any) -> None:
        """Validate select field."""
        if field_schema.multiple:
            # Multiple selection - expect list
            if not isinstance(value, list):
                raise ContentValidationError(
                    field_schema.key,
                    f"Expected list for multiple select, got {type(value).__name__}",
                )

            # Check each value is a valid option
            for item in value:
                if not isinstance(item, str):
                    raise ContentValidationError(
                        field_schema.key,
                        f"Expected string in list, got {type(item).__name__}",
                    )
                if item not in field_schema.options:
                    raise ContentValidationError(
                        field_schema.key,
                        f"Value '{item}' is not a valid option. Valid options: {field_schema.options}",
                    )
        else:
            # Single selection - expect string
            if not isinstance(value, str):
                raise ContentValidationError(
                    field_schema.key,
                    f"Expected string, got {type(value).__name__}",
                )

            if value not in field_schema.options:
                raise ContentValidationError(
                    field_schema.key,
                    f"Value '{value}' is not a valid option. Valid options: {field_schema.options}",
                )

    def _validate_date_field(self, field_schema: DateFieldSchema, value: Any) -> None:
        """Validate date field.

        Accepts ISO 8601 date strings (YYYY-MM-DD) or datetime objects.
        """
        if isinstance(value, datetime):
            return

        if isinstance(value, str):
            # Try parsing as ISO 8601 date
            try:
                datetime.fromisoformat(value.split("T")[0])  # Take date part only
                return
            except ValueError as e:
                raise ContentValidationError(
                    field_schema.key,
                    f"Invalid date format. Expected ISO 8601 (YYYY-MM-DD): {e}",
                ) from e

        raise ContentValidationError(
            field_schema.key,
            f"Expected date string or datetime, got {type(value).__name__}",
        )

    def _validate_datetime_field(self, field_schema: DateTimeFieldSchema, value: Any) -> None:
        """Validate datetime field.

        Accepts ISO 8601 datetime strings or datetime objects.
        """
        if isinstance(value, datetime):
            return

        if isinstance(value, str):
            # Try parsing as ISO 8601 datetime
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                return
            except ValueError as e:
                raise ContentValidationError(
                    field_schema.key,
                    f"Invalid datetime format. Expected ISO 8601: {e}",
                ) from e

        raise ContentValidationError(
            field_schema.key,
            f"Expected datetime string or datetime, got {type(value).__name__}",
        )

    def _validate_json_field(self, field_schema: JsonFieldSchema, value: Any) -> None:
        """Validate JSON field.

        Accepts any JSON-serializable value (dict, list, string, number, bool, null).
        No strict type checking - free-form JSON.
        """
        # Any value is valid for JSON field
        # Python dict/list/str/int/float/bool/None all serialize to JSON
        pass

    def validate_form_submission(
        self,
        schema_definition: Any,  # FormSchemaDefinition
        submission_data: dict[str, Any],
    ) -> None:
        """Validate form submission against form schema definition.

        Args:
            schema_definition: The form's schema definition (FormSchemaDefinition)
            submission_data: The submitted form data to validate

        Raises:
            ContentValidationError: If validation fails
        """
        # Check for required fields
        for field in schema_definition.fields:
            if field.required:
                value = submission_data.get(field.key)
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ContentValidationError(
                        field.key,
                        f"Required field '{field.label}' is missing or empty",
                    )

        # Validate each submitted field
        for field_key, field_value in submission_data.items():
            # Find field definition
            field_def = next((f for f in schema_definition.fields if f.key == field_key), None)

            # Unknown fields are silently ignored (honeypot, etc.)
            if field_def is None:
                continue

            # Skip null values (unless required, checked above)
            if field_value is None:
                continue

            # Validate based on field type
            self._validate_form_field(field_def, field_value)

    def _validate_form_field(self, field_def: Any, value: Any) -> None:
        """Validate a single form field value.

        Args:
            field_def: The field definition from FormSchemaDefinition
            value: The field value to validate

        Raises:
            ContentValidationError: If validation fails
        """
        field_key = field_def.key

        # Type-specific validation
        if field_def.type in ("text", "textarea", "tel", "url"):
            if not isinstance(value, str):
                raise ContentValidationError(field_key, f"Expected string, got {type(value).__name__}")

            # Check validation constraints
            if field_def.validation:
                if "minLength" in field_def.validation and len(value) < field_def.validation["minLength"]:
                    raise ContentValidationError(
                        field_key,
                        f"Must be at least {field_def.validation['minLength']} characters",
                    )

                if "maxLength" in field_def.validation and len(value) > field_def.validation["maxLength"]:
                    raise ContentValidationError(
                        field_key,
                        f"Must be no more than {field_def.validation['maxLength']} characters",
                    )

                if "pattern" in field_def.validation:
                    if not re.match(field_def.validation["pattern"], value):
                        raise ContentValidationError(field_key, "Invalid format")

        elif field_def.type == "email":
            if not isinstance(value, str):
                raise ContentValidationError(field_key, "Expected email string")

            # Basic email validation
            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, value):
                raise ContentValidationError(field_key, "Invalid email address")

        elif field_def.type == "number":
            if not isinstance(value, int | float):
                # Try to convert string to number
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    raise ContentValidationError(field_key, "Expected number") from None

            if field_def.validation:
                if "min" in field_def.validation and value < field_def.validation["min"]:
                    raise ContentValidationError(field_key, f"Must be at least {field_def.validation['min']}")

                if "max" in field_def.validation and value > field_def.validation["max"]:
                    raise ContentValidationError(field_key, f"Must be no more than {field_def.validation['max']}")

        elif field_def.type == "checkbox":
            if not isinstance(value, bool):
                # Accept "true"/"false" strings
                if isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes")
                else:
                    raise ContentValidationError(field_key, "Expected boolean")

        elif field_def.type in ("select", "radio"):
            if not isinstance(value, str):
                raise ContentValidationError(field_key, "Expected string")

            # Check value is in options
            if field_def.options and value not in field_def.options:
                raise ContentValidationError(field_key, f"Invalid option: {value}")


def validate_entry_content(
    schema_definition: EntryTypeSchemaDefinition,
    data_json: dict[str, Any],
) -> None:
    """Helper function to validate entry content.

    Args:
        schema_definition: The entry type's schema definition
        data_json: The entry's content data to validate

    Raises:
        ContentValidationError: If validation fails
    """
    validator = ContentValidator()
    validator.validate_content(schema_definition, data_json)
