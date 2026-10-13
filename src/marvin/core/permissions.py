"""
API Client Permission Checking

Utilities for validating API client permissions against requested resources.
"""

from fastapi import HTTPException, status


class PermissionChecker:
    """Helper class for checking API client permissions."""

    def __init__(self, permissions: dict):
        """
        Initialize with API client's permissions dict.

        Args:
            permissions: The permissions JSON from api_clients table
        """
        self.permissions = permissions or {}

    def has_permission(self, permission: str) -> bool:
        """
        Check if a specific permission is granted.

        Args:
            permission: The permission key (e.g., "read:published_entries")

        Returns:
            True if permission is granted, False otherwise
        """
        return self.permissions.get(permission, False) is True

    def require_permission(self, permission: str, resource: str = "this resource") -> None:
        """
        Require a specific permission or raise 403.

        Args:
            permission: The permission key required
            resource: Human-readable resource name for error message

        Raises:
            HTTPException: 403 Forbidden if permission not granted
        """
        if not self.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API client does not have permission to access {resource}. Required: {permission}",
            )

    def require_any_permission(self, permissions: list[str], resource: str = "this resource") -> None:
        """
        Require at least one of the specified permissions or raise 403.

        Useful when multiple permissions can grant access to the same resource.

        Args:
            permissions: List of permission keys (any one grants access)
            resource: Human-readable resource name for error message

        Raises:
            HTTPException: 403 Forbidden if none of the permissions are granted
        """
        if not any(self.has_permission(perm) for perm in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API client does not have permission to access {resource}. Required one of: {', '.join(permissions)}",
            )


# Standard permission keys
class Permissions:
    """Standard permission key constants for API clients."""

    # Entry permissions
    READ_PUBLISHED_ENTRIES = "read:published_entries"
    READ_DRAFT_ENTRIES = "read:draft_entries"
    READ_ALL_ENTRIES = "read:all_entries"
    # Public submission → creates an inbox entry of a submittable entry type ("form" submit).
    WRITE_PUBLIC_ENTRIES = "write:public_entries"

    # Collection permissions
    READ_COLLECTIONS = "read:collections"

    # Asset permissions
    READ_ASSETS = "read:assets"

    # Resource permissions
    READ_RESOURCES = "read:resources"

    # Form permissions
    READ_FORMS = "read:forms"
    WRITE_FORMS = "write:forms"
    WRITE_FORM_SUBMISSIONS = "write:form_submissions"
    READ_FORM_SUBMISSIONS = "read:form_submissions"
