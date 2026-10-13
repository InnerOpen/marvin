"""
This module provides functions for initializing default and development users
in the Marvin application.

It includes utilities to:
- Define data for a set of sample demo users.
- Create a default administrative user.
- Conditionally create sample users only when the application is in demo mode.
"""

from marvin.core import root_logger
from marvin.core.config import get_app_settings
from marvin.core.security import hash_password  # For hashing default passwords
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.repos.repository_factory import AllRepositories

# Logger for this module
logger = root_logger.get_logger("init_users")
# Application settings instance
settings = get_app_settings()


def dev_users() -> list[dict]:
    """
    Provides a list of predefined user data for development and testing purposes.

    Each user dictionary contains necessary information like full name, username,
    email, a hashed default password, platform role, and workspace role. No group is named, so each
    lands in the platform workspace (found by its marker, see services.group.platform_workspace).

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a
                    development user's data.
    """
    return [
        {
            "full_name": "Jason",
            "username": "jason",
            "email": "jason@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),  # Use hashed default password
            "platform_role": PlatformRole.NONE,  # Standard user (no platform-level privileges)
            "admin": False,  # DEPRECATED: Use workspace roles instead
            "workspace_role": WorkspaceRole.ADMIN,  # Workspace administrator role
        },
        {
            "full_name": "Bob",
            "username": "bob",
            "email": "bob@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),
            "platform_role": PlatformRole.NONE,
            "admin": False,  # DEPRECATED
            "workspace_role": WorkspaceRole.EDITOR,  # Workspace editor role
        },
        {
            "full_name": "Sarah",
            "username": "sarah",
            "email": "sarah@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),
            "platform_role": PlatformRole.NONE,
            "admin": False,  # DEPRECATED
            "workspace_role": WorkspaceRole.AUTHOR,  # Workspace author role
        },
        {
            "full_name": "Sammy",
            "username": "sammy",
            "email": "sammy@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),
            "platform_role": PlatformRole.NONE,
            "admin": False,  # DEPRECATED
            "workspace_role": WorkspaceRole.VIEWER,  # Workspace viewer role (read-only)
        },
    ]


def default_user_init(db: AllRepositories) -> None:
    """
    Initializes the default administrative user and, in demo mode only,
    creates additional sample users.

    The default admin user is created with credentials specified in the application
    settings (e.g., `settings.DEFAULT_EMAIL`, `settings.DEFAULT_PASSWORD`).
    Development users are sourced from the `dev_users()` function.

    The default admin receives:
    - Platform role: SUPER_ADMIN (unrestricted platform-level access)
    - Workspace membership: OWNER role in the platform workspace

    Development users receive:
    - Platform role: NONE (standard users)
    - Workspace membership: Various roles (ADMIN, EDITOR, AUTHOR, VIEWER) for testing

    Args:
        db (AllRepositories): An instance of `AllRepositories` providing access
                              to the users repository for creating users.
    """
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    # Define the default administrative user's data
    default_user = {
        "full_name": "Change Me",  # Default full name, intended to be changed
        "username": "admin",  # Default admin username
        "email": settings.DEFAULT_EMAIL,
        "password": hash_password(settings.DEFAULT_PASSWORD or ""),
        "platform_role": PlatformRole.SUPER_ADMIN,  # Platform administrator with unrestricted access
        "admin": True,  # DEPRECATED: Use platform_role instead
        "is_superuser": True,  # DEPRECATED: Use platform_role instead
    }

    logger.info("Generating Default User (Platform Admin with SUPER_ADMIN role)")
    logger.info(f"Default admin credentials — email: {settings.DEFAULT_EMAIL}  password: {settings.DEFAULT_PASSWORD}")
    # Create the default admin user using the users repository
    admin_user = db.users.create(default_user)
    logger.info(f"Default admin user created: {admin_user.email} (platform_role={admin_user.platform_role.value})")

    # Create workspace membership for default admin (OWNER role in the platform workspace)
    admin_membership = WorkspaceMembers(
        session=db.session,
        user_id=admin_user.id,
        group_id=admin_user.group_id,
        workspace_role=WorkspaceRole.OWNER,
    )
    db.session.add(admin_membership)
    db.session.commit()
    logger.info(f"Workspace membership created: {admin_user.username} -> {admin_user.group} (OWNER)")

    # Sample users exist only for the demo experience. A real install (production or otherwise)
    # gets just the Admin — never the seeded cast.
    if settings.IS_DEMO:
        logger.info("Demo environment detected, creating sample users.")
        for user_data in dev_users():
            # Extract workspace_role before creating user (it's not a User model field)
            workspace_role = user_data.pop("workspace_role", WorkspaceRole.VIEWER)

            # Create the development user
            dev_user = db.users.create(user_data)
            logger.info(f"Development user created: {dev_user.email} / {settings.DEFAULT_PASSWORD} (platform_role={dev_user.platform_role.value})")

            # Create workspace membership for the dev user
            dev_membership = WorkspaceMembers(
                session=db.session,
                user_id=dev_user.id,
                group_id=dev_user.group_id,
                workspace_role=workspace_role,
            )
            db.session.add(dev_membership)
            db.session.commit()
            logger.info(f"Workspace membership created: {dev_user.username} -> {dev_user.group} ({workspace_role.value})")
