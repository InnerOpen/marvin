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
from marvin.db.models.users.roles import PlatformRole
from marvin.repos.repository_factory import AllRepositories

# Logger for this module
logger = root_logger.get_logger("init_users")
# Application settings instance
settings = get_app_settings()


def dev_users() -> list[dict]:
    """
    Provides a list of predefined user data for development and testing purposes.

    Each user dictionary contains necessary information like full name, username,
    email, a hashed default password and platform role. None has a workspace: an admin invites them into one.

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
        },
        {
            "full_name": "Bob",
            "username": "bob",
            "email": "bob@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),
            "platform_role": PlatformRole.NONE,
            "admin": False,  # DEPRECATED
        },
        {
            "full_name": "Sarah",
            "username": "sarah",
            "email": "sarah@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),
            "platform_role": PlatformRole.NONE,
            "admin": False,  # DEPRECATED
        },
        {
            "full_name": "Sammy",
            "username": "sammy",
            "email": "sammy@example.com",
            "password": hash_password(settings.DEFAULT_PASSWORD or ""),
            "platform_role": PlatformRole.NONE,
            "admin": False,  # DEPRECATED
        },
    ]


def default_user_init(db: AllRepositories) -> None:
    """
    Initializes the default administrative user and, in demo mode only,
    creates additional sample users.

    The default admin user is created with credentials specified in the application
    settings (e.g., `settings.DEFAULT_EMAIL`, `settings.DEFAULT_PASSWORD`).
    Development users are sourced from the `dev_users()` function.

    The default admin receives the SUPER_ADMIN platform role (unrestricted platform-level access) and
    no workspace: a fresh install has none until the admin creates one in Admin.

    Development users receive the NONE platform role (standard users) and no workspace either.

    Args:
        db (AllRepositories): An instance of `AllRepositories` providing access
                              to the users repository for creating users.
    """
    # A fresh install has no workspace (decision 2026-10-18): the first super admin logs into Admin and
    # creates workspaces there, so the admin has no home and no membership.
    default_user = {
        "full_name": "Change Me",  # Default full name, intended to be changed
        "username": "admin",  # Default admin username
        "email": settings.DEFAULT_EMAIL,
        "password": hash_password(settings.DEFAULT_PASSWORD or ""),
        "platform_role": PlatformRole.SUPER_ADMIN,  # Platform administrator with unrestricted access
        "admin": True,  # DEPRECATED: Use platform_role instead
        "is_superuser": True,  # DEPRECATED: Use platform_role instead
        "group": None,
    }

    logger.info("Generating Default User (Platform Admin with SUPER_ADMIN role, no workspace)")
    logger.info(f"Default admin credentials — email: {settings.DEFAULT_EMAIL}  password: {settings.DEFAULT_PASSWORD}")
    admin_user = db.users.create(default_user)
    logger.info(f"Default admin user created: {admin_user.email} (platform_role={admin_user.platform_role.value})")

    # Sample users exist only for the demo experience, and they too start with no workspace: an
    # admin invites them into one. A real install (production or otherwise) gets just the Admin.
    if settings.IS_DEMO:
        logger.info("Demo environment detected, creating sample users.")
        for user_data in dev_users():
            dev_user = db.users.create({**user_data, "group": None})
            logger.info(f"Development user created: {dev_user.email} / {settings.DEFAULT_PASSWORD} (platform_role={dev_user.platform_role.value})")
