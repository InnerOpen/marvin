"""
This module provides custom FastAPI router and route classes to standardize
API route definitions within the Marvin application.

It includes:
- `BaseAPIRouter`: A base APIRouter with common configurations.
- `AdminAPIRouter`: An APIRouter that automatically adds admin authentication dependency.
- `UserAPIRouter`: An APIRouter that automatically adds general user authentication dependency.
- `MarvinCrudRoute`: A custom APIRoute class that adds 'last-modified' and cache-control
  headers to responses, particularly for CRUD operations involving models with an 'updatedAt' field.
"""

import contextlib
import json
from collections.abc import Callable  # For typing callables
from enum import Enum  # For using Enums in tags if needed
from json.decoder import JSONDecodeError  # For safely trying to decode JSON

from fastapi import APIRouter, Depends, Request, Response  # Core FastAPI components
from fastapi.routing import APIRoute  # For creating custom route class

# Marvin specific dependencies for authentication
from marvin.core.dependencies import get_current_superuser, get_current_user


class BaseAPIRouter(APIRouter):
    """
    A base `APIRouter` class for the Marvin application.

    This class can be used as a parent for other routers to ensure consistent
    base configurations or to add common utilities in the future. Currently, it
    primarily serves as a common ancestor.

    Args:
        tags (list[str | Enum] | None, optional): A list of tags to apply to
            all routes in this router. Useful for OpenAPI documentation grouping.
        prefix (str, optional): A URL prefix for all routes in this router.
        **kwargs: Additional keyword arguments accepted by FastAPI's `APIRouter`.
    """

    def __init__(self, tags: list[str | Enum] | None = None, prefix: str = "", **kwargs):
        super().__init__(tags=tags, prefix=prefix, **kwargs)


class AdminAPIRouter(BaseAPIRouter):
    """
    An `APIRouter` specifically for administrative routes.

    All routes defined using this router will automatically have the `get_admin_user`
    dependency, ensuring that only authenticated administrative users can access them.

    Args:
        tags (list[str | Enum] | None, optional): Tags for OpenAPI documentation.
        prefix (str, optional): URL prefix for these admin routes (e.g., "/admin").
        **kwargs: Additional keyword arguments for `APIRouter`.
    """

    def __init__(self, tags: list[str | Enum] | None = None, prefix: str = "", **kwargs):
        super().__init__(
            tags=tags,
            prefix=prefix,
            dependencies=[Depends(get_current_superuser)],  # Platform admin section: SUPER_ADMIN only
            **kwargs,
        )


class UserAPIRouter(BaseAPIRouter):
    """
    An `APIRouter` for routes that require general user authentication.

    All routes defined using this router will automatically have the `get_current_user`
    dependency, ensuring that only authenticated users can access them.

    Args:
        tags (list[str | Enum] | None, optional): Tags for OpenAPI documentation.
        prefix (str, optional): URL prefix for these user-specific routes.
        **kwargs: Additional keyword arguments for `APIRouter`.
    """

    def __init__(self, tags: list[str | Enum] | None = None, prefix: str = "", **kwargs):
        super().__init__(
            tags=tags,
            prefix=prefix,
            dependencies=[Depends(get_current_user)],  # Automatically protect routes with user auth
            **kwargs,
        )


class MarvinCrudRoute(APIRoute):
    """
    A custom `APIRoute` class designed to automatically add 'last-modified'
    and cache-control headers to HTTP responses.

    This route class is particularly useful for CRUD (Create, Read, Update, Delete)
    endpoints where indicating the last modification time of a resource and
    controlling client-side caching is beneficial.

    It inspects the JSON response body for an "updatedAt" field and uses its
    value for the 'last-modified' header. It also sets 'Cache-Control' to
    prevent caching of API responses by default.
    """

    def get_route_handler(self) -> Callable:
        """
        Overrides the default route handler to inject custom response processing logic.

        This method wraps the original FastAPI route handler. The wrapper attempts
        to parse the response body as JSON, extract an "updatedAt" field if present,
        and set the 'last-modified' and 'Cache-Control' headers accordingly.

        Returns:
            Callable: The custom route handler function that includes the response
                      header modification logic.
        """
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            """
            Custom route handler wrapper to modify response headers.
            """
            # Execute the original route handler to get the response
            response: Response = await original_route_handler(request)

            # Attempt to process the response body if it's likely JSON
            # Check content-type or just try-except decode if performance is not critical
            # For simplicity, using try-except here.
            # `contextlib.suppress` can be used to ignore JSONDecodeError if body is not JSON.
            with contextlib.suppress(JSONDecodeError, AttributeError, TypeError):  # Guard against non-JSON or non-dict body
                # Ensure response.body is accessible and is bytes; some responses might not have .body
                if hasattr(response, "body") and isinstance(response.body, bytes):
                    response_body_dict = json.loads(response.body.decode())  # Decode bytes to str, then parse JSON

                    if isinstance(response_body_dict, dict):
                        # Try to get 'updatedAt' for the 'last-modified' header
                        last_modified_value = response_body_dict.get("updatedAt")
                        if last_modified_value:  # Ensure it's not None or empty
                            response.headers["last-modified"] = str(last_modified_value)

                        # Force no-cache for all API responses to ensure clients get fresh data
                        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

            return response

        return custom_route_handler
