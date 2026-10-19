from sqlalchemy.exc import IntegrityError


class PermissionDenied(Exception):
    """
    This exception is raised when a user tries to access a resource that they do not have permission to access.
    """

    pass


class NoEntryFound(Exception):
    """
    This exception is raised when a user tries to access a resource that does not exist.
    """

    pass


class UserLockedOut(Exception):
    """Exception raised when a user is locked out."""

    ...


class MissingClaimException(Exception):
    """Exception raised when a required claim is missing."""

    ...


class SlugError(Exception):
    """Exception raised when a slug conflict occurs."""

    pass


class RateLimitError(Exception):
    """Exception raised when rate limit is exceeded."""

    pass


class VideoDownloadError(Exception):
    """Exception raised when video download fails."""

    pass


def registered_exceptions() -> dict:
    """Returns a dictionary of registered exceptions and their default messages."""
    return {
        PermissionDenied: "You do not have permission to perform this action",
        NoEntryFound: "The requested resource was not found",
        IntegrityError: "Database integrity error",
        SlugError: "A resource with this slug already exists",
        RateLimitError: "Rate limit exceeded. Please try again later",
        VideoDownloadError: "Failed to download video",
        UserLockedOut: "User account is locked",
        MissingClaimException: "Required authentication claim is missing",
    }
