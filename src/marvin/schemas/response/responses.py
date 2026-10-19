"""
This module defines standardized Pydantic response schemas for common API
feedback scenarios within the Marvin application.

It includes models for:
- `ErrorResponse`: A structured error response.
- `SuccessResponse`: A generic success response, often with a message.
- `FileTokenResponse`: A response for operations that return a file access token.

Each model includes a `respond` class method as a convenient way to construct
and serialize the response, particularly useful when providing detail payloads
for FastAPI's `HTTPException`.
"""

from typing import Any  # For generic type hints

from pydantic import BaseModel  # Using Pydantic's BaseModel directly for simple responses


class ErrorResponse(BaseModel):  # Can use BaseModel if no _MarvinModel specific features needed
    """
    Standardized schema for API error responses.
    Provides a user-friendly message, an error flag, and optional exception details.
    """

    message: str
    """A human-readable message describing the error."""
    error: bool = True
    """A boolean flag indicating that this is an error response. Defaults to True."""
    exception: str | None = None
    """Optional string representation of the exception that occurred, useful for debugging."""

    @classmethod
    def respond(cls, message: str, exception: str | None = None) -> dict[str, Any]:  # Return type Any for dict values
        """
        Helper method to create an `ErrorResponse` instance and return its dictionary
        representation.

        This is particularly useful for constructing the `detail` field of FastAPI's
        `HTTPException`.

        Args:
            message (str): The error message.
            exception (str | None, optional): Optional string representation of the exception.
                                              Defaults to None.

        Returns:
            dict[str, Any]: A dictionary representing the error response.
        """
        return cls(message=message, exception=exception).model_dump()


class SuccessResponse(BaseModel):  # Can use BaseModel if no _MarvinModel specific features needed
    """
    Standardized schema for generic API success responses.
    Provides a success message and an error flag set to False.
    """

    message: str
    """A human-readable message indicating the success of the operation."""
    error: bool = False
    """A boolean flag indicating a successful response. Defaults to False."""

    @classmethod
    def respond(cls, message: str = "Operation successful.") -> dict[str, Any]:  # Added default message, return type Any
        """
        Helper method to create a `SuccessResponse` instance and return its dictionary
        representation.

        Args:
            message (str, optional): The success message. Defaults to "Operation successful.".

        Returns:
            dict[str, Any]: A dictionary representing the success response.
        """
        return cls(message=message).model_dump()
