"""
This module defines FastAPI routes for application-level "about" information
accessible to authenticated users within the Marvin application.

It provides endpoints to retrieve general application details (like version),
startup configuration information, and theme settings.
"""

from fastapi import APIRouter, Response

from marvin.core.config import get_app_settings
from marvin.core.settings.static import APP_VERSION  # Current application version
from marvin.routes._base import UserAPIRouter  # Base router for authenticated user endpoints
from marvin.schemas.app import AppInfo, AppTheme, LoginInfo  # Pydantic response models

# APIRouter for "about" section, prefixed with /about and using UserAPIRouter for auth
# All routes in this controller will be under /app/about due to UserAPIRouter in main app and this prefix.
router = UserAPIRouter(prefix="/about")

# Public router for theme endpoint (no auth required)
public_router = APIRouter(prefix="/about")


@public_router.get("/login-info", response_model=LoginInfo, summary="Get Login Page Configuration")
def get_login_info() -> LoginInfo:
    """Public endpoint returning OIDC/signup settings for the login page."""
    settings = get_app_settings()
    return LoginInfo(
        oidc_enabled=settings.OIDC_READY,
        oidc_provider_name=settings.OIDC_PROVIDER_NAME,
        oidc_auto_redirect=settings.OIDC_AUTO_REDIRECT,
        allow_signup=settings.ALLOW_SIGNUP,
        is_demo=settings.IS_DEMO,
    )


@public_router.post("/clear-cache", summary="Clear Settings Cache")
def clear_settings_cache() -> dict:
    """Clear the LRU cache for app settings (useful for development)."""
    get_app_settings.cache_clear()
    return {"message": "Settings cache cleared"}


@public_router.get("/version", summary="Get the running application version")
def get_app_version() -> dict[str, str]:
    """The backend's version string, unauthenticated. It is already public in the image tags;
    the admin frontend's update banner compares it across deploys (see /version.json there)."""
    return {"version": APP_VERSION}


@router.get("", response_model=AppInfo, summary="Get Basic Application Information")
def get_app_info() -> AppInfo:
    """
    Retrieves basic information about the application.

    This includes the application version and whether it's running in production mode.
    Accessible to any authenticated user.

    Returns:
        AppInfo: A Pydantic model containing the application version and production status.
    """
    settings = get_app_settings()  # Access application settings

    return AppInfo(
        version=APP_VERSION,  # From static settings
        production=settings.PRODUCTION,  # From dynamic settings
    )


@router.get("/startup-info", summary="Get Application Startup Information")
def get_startup_info():
    """
    Retrieves application startup information including all feature availability.

    Returns the full settings object with all feature flags and configuration status.
    Excludes sensitive fields like SECRET and ENV_SECRETS.
    Accessible to any authenticated user.

    Returns:
        dict: Settings dictionary with all feature flags and configuration (camelCase).
    """
    from humps import camelize

    settings = get_app_settings()

    # Get settings as dict, excluding sensitive fields
    data = settings.model_dump(
        exclude={"theme", "SECRET", "ENV_SECRETS", "_logger"},
        exclude_none=True,
    )

    # Add computed @property fields that aren't in model_dump
    # FeatureDetails is a NamedTuple, convert to dict with _asdict()
    data["SMTP_ENABLED"] = settings.SMTP_ENABLED
    data["SMTP_FEATURE"] = settings.SMTP_FEATURE._asdict() if settings.SMTP_FEATURE else None
    data["LDAP_ENABLED"] = settings.LDAP_ENABLED
    data["LDAP_FEATURE"] = settings.LDAP_FEATURE._asdict() if settings.LDAP_FEATURE else None
    data["OIDC_READY"] = settings.OIDC_READY
    data["OIDC_FEATURE"] = settings.OIDC_FEATURE._asdict() if settings.OIDC_FEATURE else None
    data["OPENAI_ENABLED"] = settings.OPENAI_ENABLED
    data["OPENAI_FEATURE"] = settings.OPENAI_FEATURE._asdict() if settings.OPENAI_FEATURE else None
    data["APPRISE_READY"] = settings.APPRISE_READY
    data["APPRISE_FEATURE"] = settings.APPRISE_FEATURE._asdict() if settings.APPRISE_FEATURE else None
    data["PLUGIN_ENABLED"] = settings.PLUGIN_ENABLED
    data["PLUGIN_FEATURE"] = settings.PLUGIN_FEATURE._asdict() if settings.PLUGIN_FEATURE else None

    # Convert keys to camelCase (lowercase first since env vars are SCREAMING_SNAKE_CASE)
    return {camelize(key.lower()): value for key, value in data.items()}


@public_router.get("/theme", response_model=AppTheme, summary="Get Application Theme Settings")
def get_app_theme(resp: Response) -> AppTheme:
    """
    Retrieves the current application theme settings.

    The theme settings are fetched from the application configuration.
    This endpoint also sets cache control headers to allow client-side caching
    of the theme information for a specified duration.
    Public endpoint - no authentication required.

    Args:
        resp (Response): The FastAPI Response object, used to set custom headers.

    Returns:
        AppTheme: A Pydantic model containing the application theme settings.
    """
    settings = get_app_settings()  # Access application settings

    # Set Cache-Control header to allow public caching for 1 week (604800 seconds)
    # max-age is in seconds. 604600 is slightly less than 7 days. Standard 7 days = 604800.
    resp.headers["Cache-Control"] = "public, max-age=604800"  # Corrected max-age

    # Return theme settings, unpacking the theme model from settings
    return AppTheme(**settings.theme.model_dump())
