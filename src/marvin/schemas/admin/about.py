"""
This module defines Pydantic schemas used for representing administrative "about"
information, application statistics, configuration status, and theme details
within the Marvin application.

These schemas are primarily used as response models for administrative endpoints.
"""

from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model for Marvin schemas


class AppStatistics(_MarvinModel):
    """
    Schema for comprehensive application statistics.
    """

    # User & Group stats
    total_users: int  # The total number of registered users in the system.
    total_groups: int  # The total number of groups/workspaces in the system.

    # Content stats
    total_entries: int  # The total number of content entries.
    total_collections: int  # The total number of collections.
    total_entry_types: int  # The total number of entry type definitions.

    # Asset & Resource stats
    total_assets: int  # The total number of uploaded assets/files.
    total_resources: int  # The total number of resources.

    # API & Integration stats
    total_api_tokens: int  # The total number of user API tokens.
    total_api_clients: int  # The total number of API clients.
    total_webhooks: int  # The total number of configured webhooks.

    # AI usage, aggregated across every account/workspace.
    total_ai_operations: int = 0  # Total AI executions run platform-wide.
    total_ai_tokens: int = 0  # Total AI tokens consumed platform-wide.
    total_ai_cost_usd: float = 0.0  # Total estimated AI cost (USD) platform-wide.


class AppInfo(_MarvinModel):
    """
    Schema for general application information.
    This model is often extended by more specific "about" info models.
    """

    production: bool  # Indicates if the application is running in production mode.
    version: str  # The current version of the application (e.g., "1.0.0", "develop").
    demo_status: bool  # Indicates if the application is running in demo mode.
    environment_label: str = ""  # Non-production instance tag (e.g. "DEV"); empty in production.
    allow_signup: bool  # Indicates if new user signups are currently allowed.
    default_group_slug: str | None = None  # Slug of the default group for new users, if applicable.
    default_household_slug: str | None = None  # Legacy or alternative naming for default group slug.
    enable_oidc: bool  # Indicates if OpenID Connect (OIDC) authentication is enabled.
    oidc_redirect: bool  # Indicates if automatic redirect to OIDC provider is enabled.
    oidc_provider_name: str  # Display name of the configured OIDC provider.
    enable_openai: bool  # Indicates if OpenAI integration is enabled.
    enable_openai_image_services: bool  # Indicates if OpenAI image-related services are specifically enabled.


class IndexedEmbeddingModel(_MarvinModel):
    """One embedding model that has vectors stored, and how many chunks."""

    model_id: str
    chunks: int


class EmbeddingsInfo(_MarvinModel):
    """The built-in embedding engine and what the search indexes were built with (read without loading the model)."""

    builtin_enabled: bool  # EMBEDDINGS_BUILTIN_ENABLED: workspaces use Marvin's own model rather than their AI provider's.
    builtin_available: bool  # Enabled and fastembed is installed, so the built-in model is what embeds.
    model: str | None = None  # The built-in model in use; None when it isn't (workspaces then use their provider's model).
    dimensions: int | None = None  # Numbers per vector for that model.
    engine: str = "fastembed"
    engine_version: str | None = None  # None when the package isn't installed.
    onnxruntime_version: str | None = None  # None when the package isn't installed.
    indexed_models: list[IndexedEmbeddingModel] = []  # Platform-wide, most chunks first; one that isn't `model` needs a reindex.


class AdminAboutInfo(AppInfo):
    """
    Schema for detailed application information, extending `AppInfo` with
    additional details relevant for administrators.
    """

    versionLatest: str  # The latest available version of the application (e.g., fetched from GitHub).
    api_port: int  # The port on which the API is running.
    api_docs: bool  # Indicates if API documentation (e.g., Swagger UI) is enabled.
    db_type: str  # The type of database being used (e.g., "sqlite", "postgres").
    db_url: str | None = None  # The database connection URL (potentially masked for security).
    build_id: str  # The Git commit hash or build identifier for the current application build.
    embeddings: EmbeddingsInfo | None = None  # The built-in embedding engine and the models the indexes were built with.


class CheckAppConfig(_MarvinModel):
    """
    Schema representing the status of various critical application configurations.
    Used to quickly assess if key features are configured and ready for use.
    """

    email_ready: bool  # True if SMTP email settings are configured and enabled.
    ldap_ready: bool  # True if LDAP authentication settings are configured and enabled.
    oidc_ready: bool  # True if OIDC authentication settings are configured and enabled.
    enable_openai: bool  # True if OpenAI integration is configured and enabled.
    base_url_set: bool  # True if the application's BASE_URL has been changed from its default value.
    is_up_to_date: bool  # True if the current application version is the latest available, or if it's a development build.
