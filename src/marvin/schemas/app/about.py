"""
This module defines Pydantic schemas for application-level "about" information
within the Marvin application.

These schemas are typically used as response models for public or user-facing
endpoints that provide general details about the application, its version,
theme, and certain configuration statuses.

Note: Some model names in this file (e.g., `AppInfo`, `AppTheme`, `AdminAboutInfo`,
`CheckAppConfig`, `AppStatistics`) overlap with those in `marvin.schemas.admin.about`.
The definitions here might be intended for different contexts (e.g., less detailed
views for non-admin users) or could indicate a need for consolidation if they
serve identical purposes. This documentation reflects the models as defined in this specific file.
"""

from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model for Marvin schemas


class LoginInfo(_MarvinModel):
    """Public login page configuration — no auth required."""

    oidc_enabled: bool = False
    oidc_provider_name: str = "OAuth"
    oidc_auto_redirect: bool = False
    allow_signup: bool = False
    is_demo: bool = False  # Demo mode seeds sample users; the login page shows their credentials only then.


class AppStatistics(_MarvinModel):
    """
    Schema for basic application statistics.

    NOTE: This model is currently defined without any fields (pass).
    It might be a placeholder for future implementation or defined elsewhere
    with actual fields (e.g., in `marvin.schemas.admin.about.AppStatistics`).
    """

    pass


class AppInfo(_MarvinModel):
    """
    Schema for general, publicly accessible application information.
    """

    production: bool  # Indicates if the application is running in production mode.
    version: str  # The current version of the application (e.g., "1.0.0", "develop").


class AppTheme(_MarvinModel):
    """
    Schema defining the complete color system for the application's light and dark themes.
    Includes background, surface, text, border, and accent colors.
    Actual color values are defined in core/settings/theme.py
    """

    # Light theme - Background & Surface
    light_bg: str
    light_panel: str
    light_panel_secondary: str

    # Light theme - Text & Borders
    light_text: str
    light_text_muted: str
    light_border: str

    # Light theme - Accent Colors
    light_primary: str
    light_accent: str
    light_secondary: str
    light_success: str
    light_info: str
    light_warning: str
    light_error: str

    # Dark theme - Background & Surface
    dark_bg: str
    dark_panel: str
    dark_panel_secondary: str

    # Dark theme - Text & Borders
    dark_text: str
    dark_text_muted: str
    dark_border: str

    # Dark theme - Accent Colors
    dark_primary: str
    dark_accent: str
    dark_secondary: str
    dark_success: str
    dark_info: str
    dark_warning: str
    dark_error: str


class FeatureStatus(_MarvinModel):
    """Schema for feature status with enabled flag and optional description."""

    enabled: bool
    description: str | None = None


class AppStartupInfo(_MarvinModel):
    """
    Schema for information relevant to the application's startup state.

    Includes feature flags and configuration status for various integrations.
    """

    # SMTP / Email
    smtp_enabled: bool
    """Whether SMTP email is configured and enabled."""
    smtp_feature: FeatureStatus | None = None
    """Detailed SMTP feature status."""

    # LDAP Authentication
    ldap_enabled: bool = False
    """Whether LDAP authentication is configured and enabled."""
    ldap_feature: FeatureStatus | None = None
    """Detailed LDAP feature status."""

    # OIDC Authentication
    oidc_enabled: bool = False
    """Whether OIDC authentication is configured and enabled."""
    oidc_feature: FeatureStatus | None = None
    """Detailed OIDC feature status."""

    # OpenAI Integration
    openai_enabled: bool = False
    """Whether OpenAI integration is configured and enabled."""
    openai_feature: FeatureStatus | None = None
    """Detailed OpenAI feature status."""

    # Plugin System
    plugin_enabled: bool = False
    """Whether the plugin system is enabled."""
    plugin_feature: FeatureStatus | None = None
    """Detailed plugin feature status."""


class AdminAboutInfo(AppInfo):  # Note: This extends the AppInfo defined *in this file*.
    """
    Schema for detailed application information, extending the local `AppInfo`.
    This version is likely intended for administrative contexts, providing more
    details than the basic `AppInfo`.

    If `marvin.schemas.admin.about.AdminAboutInfo` is the canonical version,
    this might be a subset or an alternative definition.
    """

    versionLatest: str  # The latest available version of the application.
    api_port: int  # The port on which the API is running.
    api_docs: bool  # Indicates if API documentation (e.g., Swagger UI) is enabled.
    db_type: str  # The type of database being used (e.g., "sqlite", "postgres").
    db_url: str | None = None  # The database connection URL (potentially masked).
    build_id: str  # The Git commit hash or build identifier for the current build.
    # Note: This model lacks fields like `default_group` and OIDC/OpenAI flags
    # that are present in `marvin.schemas.admin.about.AdminAboutInfo`.


class CheckAppConfig(_MarvinModel):
    """
    Schema representing the status of various critical application configurations.
    This version is likely for user-facing checks or a subset of admin checks.

    If `marvin.schemas.admin.about.CheckAppConfig` is the canonical version,
    this might be a subset or an alternative definition.
    """

    email_ready: bool  # True if SMTP email settings are configured and enabled.
    ldap_ready: bool  # True if LDAP authentication settings are configured and enabled.
    oidc_ready: bool  # True if OIDC authentication settings are configured and enabled.
    enable_openai: bool  # True if OpenAI integration is configured and enabled.
    base_url_set: bool  # True if the application's BASE_URL has been changed from its default.
    is_up_to_date: bool  # True if the current application version is the latest or a dev build.
