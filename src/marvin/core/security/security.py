"""
This module provides core security functionalities for the Marvin application.

It includes functions for:
- Authentication provider selection (LDAP or credentials-based).
- Access token creation (JWT).
- File-specific token creation.
- Password hashing.
- Generation of URL-safe tokens.
"""

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from sqlalchemy.orm.session import Session

from marvin.core import root_logger
from marvin.core.config import get_app_settings
from marvin.core.security.hasher import get_hasher
from marvin.schemas.user.auth import CredentialsRequest, CredentialsRequestForm

# JWT algorithm constant - DO NOT CHANGE without migration plan
# Used for encoding/decoding JWT tokens across the application
JWT_ALGORITHM = "HS256"

# Legacy alias for backward compatibility (deprecated - use JWT_ALGORITHM)
ALGORITHM = JWT_ALGORITHM

logger = root_logger.get_logger("security")


def get_auth_provider(session: Session, data: CredentialsRequestForm):
    """
    Returns the appropriate authentication provider based on application settings.

    If LDAP is enabled in settings, it returns an LDAPProvider.
    Otherwise, it returns a CredentialsProvider.

    Args:
        session (Session): SQLAlchemy session.
        data (CredentialsRequestForm): The credentials request form data.

    Returns:
        AuthProvider: The selected authentication provider.
    """
    # Import here to avoid circular dependency with repos
    from marvin.core.security.providers.credentials_provider import CredentialsProvider
    # from marvin.core.security.providers.ldap_provider import LDAPProvider

    settings = get_app_settings()

    credentials_request = CredentialsRequest(**data.__dict__)
    if settings.LDAP_ENABLED:
        from marvin.core.security.providers.ldap_provider import LDAPProvider

        return LDAPProvider(session, credentials_request)

    return CredentialsProvider(session, credentials_request)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Creates a JWT access token.

    Args:
        data (dict): The data to include in the token payload.
        expires_delta (timedelta | None, optional): The token expiration time.
            Defaults to the value specified in application settings.

    Returns:
        str: The encoded JWT access token.
    """
    settings = get_app_settings()

    to_encode = data.copy()
    expires_delta = expires_delta or timedelta(hours=settings.TOKEN_TIME)

    expire = datetime.now(UTC) + expires_delta

    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET, algorithm=ALGORITHM)


def validate_file_path(file_path: Path, allowed_base: Path) -> Path:
    """
    Validates that a file path is within an allowed base directory and doesn't contain path traversal.

    Args:
        file_path (Path): The file path to validate.
        allowed_base (Path): The base directory that file_path must be within.

    Returns:
        Path: The resolved absolute path if valid.

    Raises:
        ValueError: If the path is outside the allowed directory or contains traversal attempts.
    """
    # Resolve to absolute paths
    abs_path = file_path.resolve()
    abs_base = allowed_base.resolve()

    # Check if path is within allowed base directory
    try:
        abs_path.relative_to(abs_base)
    except ValueError:
        raise ValueError(f"Path {file_path} is outside allowed directory {allowed_base}") from None

    return abs_path


def create_file_token(file_path: Path, allowed_base: Path) -> str:
    """
    Creates a short-lived JWT access token specifically for accessing a file.

    Args:
        file_path (Path): The path to the file.
        allowed_base (Path): The base directory that file_path must be within.

    Returns:
        str: The encoded JWT file access token.

    Raises:
        ValueError: If file_path is invalid or outside allowed_base.
    """
    file_path = validate_file_path(file_path, allowed_base)

    token_data = {"file": str(file_path)}
    return create_access_token(token_data, expires_delta=timedelta(minutes=30))


def hash_password(password: str) -> str:
    """Takes in a raw password and hashes it. Used prior to saving a new password to the database."""
    return get_hasher().hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifies a password against a bcrypt hash.

    Used for validating API client tokens and user passwords.

    Args:
        password (str): The plaintext password or token to verify.
        hashed (str): The bcrypt hash to verify against.

    Returns:
        bool: True if the password matches the hash, False otherwise.
    """
    return get_hasher().verify(password, hashed)


def url_safe_token() -> str:
    """Generates a cryptographic token without embedded data. Used for password reset tokens and invitation tokens"""
    return secrets.token_urlsafe(24)
