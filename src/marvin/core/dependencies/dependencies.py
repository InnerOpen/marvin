import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import fastapi
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from jwt.exceptions import PyJWTError
from pydantic import UUID4
from sqlalchemy.orm.session import Session

from marvin.core import root_logger
from marvin.core.config import get_app_dirs, get_app_settings
from marvin.core.security.security import JWT_ALGORITHM
from marvin.db.db_setup import generate_session
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.repos.all_repositories import get_repositories
from marvin.schemas.group import GroupRead
from marvin.schemas.user import PrivateUser, TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
oauth2_scheme_soft_fail = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)
publishing_bearer_scheme = HTTPBearer(
    scheme_name="PublishingAPIToken",
    description="API client token (marvin_sk_ prefix) for Publishing API access",
)
ALGORITHM = JWT_ALGORITHM  # Import from central location
app_dirs = get_app_dirs()
settings = get_app_settings()
logger = root_logger.get_logger("dependencies")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def is_logged_in(token: str = Depends(oauth2_scheme_soft_fail), session=Depends(generate_session)) -> bool:
    """
    When you need to determine if the user is logged in, but don't need the user, you can use this
    function to return a boolean value to represent if the user is logged in. No Auth exceptions are raised
    if the user is not logged in. This behavior is not the same as 'get_current_user'

    Args:
        token (str, optional): [description]. Defaults to Depends(oauth2_scheme_soft_fail).
        session ([type], optional): [description]. Defaults to Depends(generate_session).

    Returns:
        bool: True = Valid User / False = Not User
    """
    # Check if this is an API token (starts with configured user token prefix)
    if token and token.startswith(settings.SECURITY_TOKEN_PREFIX_USER):
        try:
            repos = get_repositories(session, group_id=None)
            token_model = repos.api_tokens.validate_token(plaintext_token=token)
            return token_model is not None
        except Exception:
            logger.debug(
                "Unexpected error validating API token in is_logged_in",
                exc_info=True,
                extra={"dependency": "is_logged_in", "token_type": "api_token"},
            )
            return False

    try:
        payload = jwt.decode(token, settings.SECRET, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        long_token: str = payload.get("long_token")

        if long_token is not None:
            try:
                if validate_long_live_token(session, token, payload.get("id")):
                    return True
            except Exception:
                logger.debug(
                    "Unexpected error validating long-lived token in is_logged_in",
                    exc_info=True,
                    extra={"dependency": "is_logged_in", "token_type": "long_lived"},
                )
                return False

        return user_id is not None

    except Exception:
        logger.debug(
            "Unexpected error decoding JWT in is_logged_in",
            exc_info=True,
            extra={"dependency": "is_logged_in", "token_type": "jwt"},
        )
        return False


async def get_public_group(group_slug: str = fastapi.Path(...), session=Depends(generate_session)) -> GroupRead:
    """
    FastAPI dependency to get a public group by its slug.

    Args:
        group_slug (str): The slug of the group.
        session: SQLAlchemy session dependency.

    Raises:
        HTTPException: If the group is not found or is private.

    Returns:
        GroupRead: The public group.
    """
    repos = get_repositories(session)
    group = repos.groups.get_by_slug_or_id(group_slug)

    if not group or (group.preferences and group.preferences.private_group):
        raise HTTPException(404, "Group not found")
    else:
        return group


async def try_get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme_soft_fail),
    session=Depends(generate_session),
) -> PrivateUser | None:
    """
    FastAPI dependency to try to get the current user.

    This dependency will not raise an exception if the user is not authenticated.

    Args:
        request (Request): The FastAPI request object.
        token (str, optional): The OAuth2 token. Defaults to Depends(oauth2_scheme_soft_fail).
        session: SQLAlchemy session dependency.

    Returns:
        PrivateUser | None: The current user if authenticated, otherwise None.
    """
    try:
        return await get_current_user(request, token, session)
    except Exception:
        logger.debug(
            "Unable to get current user in try_get_current_user (expected behavior)",
            exc_info=True,
            extra={"dependency": "try_get_current_user"},
        )
        return None


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme_soft_fail),
    session=Depends(generate_session),
) -> PrivateUser:
    """
    FastAPI dependency to get the current authenticated user.

    It tries to get the token from the Authorization header or a cookie.

    Args:
        request (Request): The FastAPI request object.
        token (str | None, optional): The OAuth2 token. Defaults to Depends(oauth2_scheme_soft_fail).
        session: SQLAlchemy session dependency.

    Raises:
        HTTPException: If the user is not authenticated or the token is invalid.

    Returns:
        PrivateUser: The authenticated user.
    """
    if token is None and settings.AUTH_COOKIE_NAME in request.cookies:
        # Try extract from cookie
        token = request.cookies.get(settings.AUTH_COOKIE_NAME, "")
    else:
        token = token or ""

    # Check if this is an API token (starts with configured user token prefix)
    if token.startswith(settings.SECURITY_TOKEN_PREFIX_USER):
        # This is a long-lived API token, not a JWT
        # Validate it directly using the repository
        repos = get_repositories(session, group_id=None)
        try:
            token_model = repos.api_tokens.validate_token(plaintext_token=token)
            if not token_model:
                raise credentials_exception

            # Update last_used_at is handled by validate_token
            session.commit()
            return token_model.user
        except Exception as e:
            raise credentials_exception from e

    try:
        payload = jwt.decode(token, settings.SECRET, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        long_token: str | None = payload.get("long_token")

        if long_token is not None:
            return validate_long_live_token(session, token, payload.get("id"))

        if user_id is None:
            raise credentials_exception

        token_data = TokenData(user_id=user_id)
    except PyJWTError as e:
        raise credentials_exception from e

    repos = get_repositories(session, group_id=None)

    user = repos.users.get_one(token_data.user_id, "id", any_case=False)

    # If we don't commit here, lazy-loads from user relationships will leave some table lock in postgres
    # which can cause quite a bit of pain further down the line
    session.commit()
    if user is None:
        raise credentials_exception
    return user


async def get_integration_id(token: str = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency to get the integration ID from the token.

    Args:
        token (str): The OAuth2 token. Defaults to Depends(oauth2_scheme).

    Raises:
        HTTPException: If the token is invalid.

    Returns:
        str: The integration ID.
    """
    try:
        decoded_token = jwt.decode(token, settings.SECRET, algorithms=[ALGORITHM])
        return decoded_token.get("integration_id", settings._DEFAULT_INTEGRATION_ID)

    except PyJWTError as e:
        raise credentials_exception from e


async def get_admin_user(current_user: PrivateUser = Depends(get_current_user)) -> PrivateUser:
    """
    FastAPI dependency to ensure the current user is an admin.

    Args:
        current_user (PrivateUser): The current authenticated user. Defaults to Depends(get_current_user).

    Raises:
        HTTPException: If the user is not an admin.

    Returns:
        PrivateUser: The admin user.
    """
    if not current_user.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return current_user


async def get_current_superuser(current_user: PrivateUser = Depends(get_current_user)) -> PrivateUser:
    """
    FastAPI dependency to ensure the current user is a super admin (platform administrator).

    Super admins have platform-level privileges:
    - Can view and manage all workspaces (not scoped to group_id)
    - Can create/edit/delete workspaces
    - Can manage workspace settings for any workspace
    - Can perform platform-level operations

    Regular admins (admin=True, is_superuser=False) are workspace-level admins
    scoped to their own group_id.

    Args:
        current_user (PrivateUser): The current authenticated user.

    Raises:
        HTTPException: If the user is not a super admin (403 Forbidden).

    Returns:
        PrivateUser: The super admin user.
    """
    # Use platform_role for authorization (preferred), with fallback to deprecated is_superuser
    if current_user.platform_role != PlatformRole.SUPER_ADMIN and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin privileges required. This operation requires platform-level access.",
        )
    return current_user


async def get_platform_admin(current_user: PrivateUser = Depends(get_current_user)) -> PrivateUser:
    """
    FastAPI dependency to ensure the current user is a platform administrator.

    Alias for get_current_superuser using the new role-based terminology.

    Args:
        current_user (PrivateUser): The current authenticated user.

    Raises:
        HTTPException: If the user is not a platform admin (403 Forbidden).

    Returns:
        PrivateUser: The platform admin user.
    """
    return await get_current_superuser(current_user)


def require_workspace_role(required_role: WorkspaceRole, allow_platform_admin: bool = True):
    """
    Factory function to create a FastAPI dependency that requires a specific workspace role.

    Creates a dependency that checks if the current user has at least the required role
    in the specified workspace. Platform admins can optionally bypass this check.

    Usage:
        @router.get("/workspace/{workspace_id}/settings")
        async def get_settings(
            workspace_id: UUID4,
            user: PrivateUser = Depends(require_workspace_role(WorkspaceRole.ADMIN))
        ):
            ...

    Args:
        required_role (WorkspaceRole): The minimum role required (OWNER, ADMIN, EDITOR, AUTHOR, VIEWER).
        allow_platform_admin (bool): If True, platform admins bypass role check. Defaults to True.

    Returns:
        Callable: A FastAPI dependency function.
    """

    async def check_workspace_role(
        workspace_id: UUID4 = fastapi.Path(..., description="Workspace ID"),
        current_user: PrivateUser = Depends(get_current_user),
    ) -> PrivateUser:
        """
        Check if user has required role in workspace.

        Args:
            workspace_id: The workspace to check permissions for.
            current_user: The authenticated user.

        Raises:
            HTTPException: 403 if user lacks required role.

        Returns:
            PrivateUser: The authenticated user with verified permissions.
        """
        # Platform admins have access to all workspaces (if allowed)
        if allow_platform_admin and current_user.platform_role == PlatformRole.SUPER_ADMIN:
            return current_user

        # Check workspace role
        if not current_user.has_workspace_role(workspace_id, required_role):
            user_role = current_user.get_workspace_role(workspace_id)
            if user_role is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You are not a member of this workspace.",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required role: {required_role.value}, your role: {user_role.value}",
                )

        return current_user

    return check_workspace_role


def require_workspace_member(allow_platform_admin: bool = True):
    """
    Factory function to create a FastAPI dependency that requires workspace membership.

    Ensures the user is a member of the workspace (any role). Platform admins
    can optionally bypass this check.

    Usage:
        @router.get("/workspace/{workspace_id}/content")
        async def get_content(
            workspace_id: UUID4,
            user: PrivateUser = Depends(require_workspace_member())
        ):
            ...

    Args:
        allow_platform_admin (bool): If True, platform admins bypass check. Defaults to True.

    Returns:
        Callable: A FastAPI dependency function.
    """

    async def check_membership(
        workspace_id: UUID4 = fastapi.Path(..., description="Workspace ID"),
        current_user: PrivateUser = Depends(get_current_user),
    ) -> PrivateUser:
        """
        Check if user is a member of the workspace.

        Args:
            workspace_id: The workspace to check membership for.
            current_user: The authenticated user.

        Raises:
            HTTPException: 403 if user is not a member.

        Returns:
            PrivateUser: The authenticated user.
        """
        # Platform admins have access to all workspaces (if allowed)
        if allow_platform_admin and current_user.platform_role == PlatformRole.SUPER_ADMIN:
            return current_user

        # Check if user has any role in the workspace
        user_role = current_user.get_workspace_role(workspace_id)
        if user_role is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You are not a member of this workspace.",
            )

        return current_user

    return check_membership


# Convenience dependencies for common workspace roles


def require_workspace_owner(allow_platform_admin: bool = True):
    """Require OWNER role in workspace. Platform admins can bypass if allowed."""
    return require_workspace_role(WorkspaceRole.OWNER, allow_platform_admin)


def require_workspace_admin(allow_platform_admin: bool = True):
    """Require ADMIN role or higher in workspace. Platform admins can bypass if allowed."""
    return require_workspace_role(WorkspaceRole.ADMIN, allow_platform_admin)


def require_workspace_editor(allow_platform_admin: bool = True):
    """Require EDITOR role or higher in workspace. Platform admins can bypass if allowed."""
    return require_workspace_role(WorkspaceRole.EDITOR, allow_platform_admin)


def require_workspace_author(allow_platform_admin: bool = True):
    """Require AUTHOR role or higher in workspace. Platform admins can bypass if allowed."""
    return require_workspace_role(WorkspaceRole.AUTHOR, allow_platform_admin)


def require_workspace_viewer(allow_platform_admin: bool = True):
    """Require VIEWER role or higher (any workspace member) in workspace. Platform admins can bypass if allowed."""
    return require_workspace_role(WorkspaceRole.VIEWER, allow_platform_admin)


def validate_long_live_token(session: Session, client_token: str, user_id: str) -> PrivateUser:
    """
    Validates a long-lived API token using bcrypt hash verification.

    Security model (upgraded):
    - Tokens are bcrypt-hashed in database (no plaintext storage)
    - Validates by checking hash against all enabled, non-revoked tokens
    - Updates last_used_at timestamp on successful validation
    - Returns user object for authentication

    Args:
        session (Session): SQLAlchemy session.
        client_token (str): The plaintext token provided by the client (format: marvin_tk_...).
        user_id (str): The user ID from JWT payload.

    Raises:
        HTTPException: 401 if token is invalid, revoked, or not found.

    Returns:
        PrivateUser: The user associated with the valid token.
    """
    from pydantic import UUID4

    repos = get_repositories(session, group_id=None)

    # Use repository's validate_token method which handles hash verification
    # and updates last_used_at
    token_model = repos.api_tokens.validate_token(
        plaintext_token=client_token,
        user_id=UUID4(user_id),  # Scope to claimed user for performance
    )

    if not token_model:
        # Token invalid, revoked, or doesn't belong to user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API token.")

    # Verify token belongs to the claimed user (defense in depth)
    if str(token_model.user_id) != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token does not belong to this user.")

    # Return the user associated with the token
    return token_model.user


def validate_file_token(token: str | None = None) -> Path:
    """
    Args:
        token (Optional[str], optional): _description_. Defaults to None.

    Raises:
        HTTPException: 400 Bad Request when no token or the file doesn't exist
        HTTPException: 401 Unauthorized when the token is invalid
    """
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST)

    try:
        payload = jwt.decode(token, settings.SECRET, algorithms=[ALGORITHM])
        file_path = Path(payload.get("file"))
    except PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="could not validate file token",
        ) from e

    if not file_path.exists():
        raise HTTPException(status.HTTP_400_BAD_REQUEST)

    return file_path


@contextmanager
def get_temporary_zip_path(auto_unlink=True) -> Generator[Path, None, None]:
    """
    Context manager to get a temporary path for a zip file.

    Args:
        auto_unlink (bool, optional): Whether to automatically delete the file on exit. Defaults to True.

    Yields:
        Generator[Path, None, None]: The path to the temporary zip file.
    """
    app_dirs.TEMP_DIR.mkdir(exist_ok=True, parents=True)
    temp_path = app_dirs.TEMP_DIR.joinpath("my_zip_archive.zip")
    try:
        yield temp_path
    finally:
        if auto_unlink:
            temp_path.unlink(missing_ok=True)


@contextmanager
def get_temporary_path(auto_unlink=True) -> Generator[Path, None, None]:
    """
    Context manager to get a temporary directory path.

    Args:
        auto_unlink (bool, optional): Whether to automatically delete the directory on exit. Defaults to True.

    Yields:
        Generator[Path, None, None]: The path to the temporary directory.
    """
    temp_path = app_dirs.TEMP_DIR.joinpath(uuid4().hex)
    temp_path.mkdir(exist_ok=True, parents=True)
    try:
        yield temp_path
    finally:
        if auto_unlink:
            rmtree(temp_path)


def temporary_file(ext: str = "") -> Callable[[], Generator[tempfile._TemporaryFileWrapper, None, None]]:
    """
    Returns a context manager that yields a temporary file with the specified extension.

    The file is created in the application's temporary directory and is deleted on exit.

    Args:
        ext (str, optional): The file extension. Defaults to "".

    Returns:
        Callable[[], Generator[tempfile._TemporaryFileWrapper, None, None]]: A context manager function.
    """

    def func():
        temp_path = app_dirs.TEMP_DIR.joinpath(uuid4().hex + ext)
        temp_path.touch()

        with tempfile.NamedTemporaryFile(mode="w+b", suffix=ext) as f:
            try:
                yield f
            finally:
                temp_path.unlink(missing_ok=True)

    return func


# ===============================================
# Publishing API Dependencies
# ===============================================


async def get_publishing_context(
    workspace_slug: str,
    credentials: fastapi.security.HTTPAuthorizationCredentials = Depends(publishing_bearer_scheme),
    session: Session = Depends(generate_session),
) -> tuple:
    """
    Validate API client token for publishing API and return context.

    This dependency:
    1. Validates the API client token from Authorization header
    2. Ensures the token is an API client token (marvin_sk_ prefix)
    3. Verifies the workspace_slug matches the client's workspace
    4. Updates last_used_at timestamp
    5. Creates a PermissionChecker from the client's permissions
    6. Returns (api_client, group, permission_checker) tuple for use in publishing routes

    Args:
        workspace_slug: The workspace slug from URL path
        credentials: HTTPBearer credentials from Authorization header
        session: Database session

    Returns:
        tuple: (api_client model, group model, PermissionChecker instance)

    Raises:
        HTTPException 401: Missing, invalid, or expired token
        HTTPException 403: Workspace mismatch or insufficient permissions
    """
    token = credentials.credentials

    # Check token prefix to ensure it's an API client token
    if not token.startswith(settings.SECURITY_TOKEN_PREFIX_CLIENT):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Publishing API requires API client token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate token using repository (no group_id scope for initial lookup)
    repos = get_repositories(session, group_id=None)
    api_client = repos.api_clients.validate_token(plaintext_token=token)

    if not api_client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API client token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get the group and verify workspace slug matches. A renamed workspace's former slug still
    # resolves to it, so a site configured with the old slug keeps working.
    from marvin.services.group.workspace_rename import find_group_by_slug

    group_model = find_group_by_slug(session, workspace_slug)

    if not group_model:
        # Return 404 instead of 403 to not leak workspace existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Verify the client's group matches the requested workspace
    if str(api_client.group_id) != str(group_model.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API client does not have access to this workspace",
        )

    # Create PermissionChecker from API client's permissions
    from marvin.core.permissions import PermissionChecker

    permission_checker = PermissionChecker(api_client.permissions)

    # Note: last_used_at is already updated by validate_token()
    # Return the database model instead of schema so publishing routes can access slug
    return api_client, group_model, permission_checker
