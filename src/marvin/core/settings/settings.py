"""
This module defines the main application settings for Marvin.

It includes Pydantic models for application settings (`AppSettings`) and plugin
settings (`PluginSettings`). It also provides helper classes and functions for
managing features, schedules, and sensitive data.

Settings are loaded from environment variables and .env files.
"""

import logging
import os
import secrets
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NamedTuple
from urllib.parse import urlparse

from dateutil.tz import tzlocal
from dotenv import dotenv_values
from pydantic import PlainSerializer, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .db_providers import AbstractDBProvider, db_provider_factory
from .theme import Theme


class ScheduleTime(NamedTuple):
    """
    Represents a specific time for scheduled tasks.

    Attributes:
        hour (int): The hour of the day (0-23).
        minute (int): The minute of the hour (0-59).
    """

    hour: int
    minute: int


class FeatureDetails(NamedTuple):
    """
    Represents the details of an application feature, including its status.

    Attributes:
        enabled (bool): Indicates if the feature is enabled or not.
        description (str | None): A short description explaining why the
                                 feature might be disabled or its current state.
    """

    enabled: bool
    """Indicates if the feature is enabled or not"""
    description: str | None
    """Short description describing why the feature is not ready"""

    def __str__(self) -> str:
        """Returns a string representation of the feature's status."""
        s = f"Enabled: {self.enabled}"
        if not self.enabled and self.description:
            s += f"\nReason: {self.description}"
        return s


MaskedNoneString = Annotated[
    str | None,
    PlainSerializer(lambda x: None if x is None else "*****", return_type=str | None),
]
"""
A Pydantic annotation for strings that should be masked (e.g., passwords)
when serialized, and also handles None values gracefully.
"""


def determine_secrets(data_dir: Path, production: bool) -> str:
    """
    Determines or generates the application's secret key.

    In non-production environments, a fixed test key is used.
    In production, it attempts to read the secret from a '.secret' file in the
    data directory. If the file doesn't exist, a new secret is generated and
    saved to the file.

    Args:
        data_dir (Path): The application's data directory.
        production (bool): Flag indicating if the application is in production mode.

    Returns:
        str: The application's secret key.
    """
    if not production:
        return "ssh-secret-test-key"  # Fixed secret for non-production

    secrets_file = data_dir.joinpath(".secret")
    if secrets_file.is_file():
        with open(secrets_file) as f:
            return f.read()
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(secrets_file, "w") as f:
            new_secret = secrets.token_hex(32)
            f.write(new_secret)
        return new_secret


class AppSettings(BaseSettings):
    """
    Main application settings.

    This class defines all configuration parameters for the Marvin application,
    loaded from environment variables and .env files. It uses Pydantic for
    data validation and management.
    """

    theme: Theme = Theme()
    """The application theme settings."""

    PRODUCTION: bool = False
    """Flag indicating if the application is running in production mode."""

    IS_DEMO: bool = False

    BASE_URL: str = "http://localhost:8080"
    """trailing slashes are trimmed (ex. `http://localhost:8080/` becomes ``http://localhost:8080`)"""

    FRONTEND_URL: str = "http://localhost:4322"
    """URL of the frontend app. Used for OIDC callback redirects in dev. In production same-origin deployments, set to BASE_URL."""

    SCHEDULER_ENABLED: bool = True
    """
    Whether this process runs the scheduler at all.

    Leadership is elected against the database, so leaving this on across every replica is safe —
    exactly one of them runs each tick. Turn it off to keep a process out of the election
    entirely, which is what you want when the scheduler runs as its own single-replica deployment
    and the API pods should only serve requests.
    """

    SCHEDULER_INTERVAL_SECONDS: int = 60
    """
    How often the scheduler runs its frequent tick — the loop that delivers webhooks, fires due
    scheduled tasks, and renews the leadership lease. Lower = snappier task delivery and lease
    renewal at more database load; higher = the reverse. Also the cadence at which a due scheduled
    task can fire, so tasks may run up to one interval late.
    """

    SCHEDULER_LEASE_TTL_SECONDS: int = 150
    """
    How long the scheduler leadership lease lasts before it must be renewed.

    The leader renews it from the frequent tick (SCHEDULER_INTERVAL_SECONDS), so this must outlast
    the gap between renews or leadership flaps between replicas. It is validated to be at least
    twice the interval — enough to survive one fully missed renew. Longer = a dead leader is
    replaced more slowly; shorter = faster failover but less headroom.
    """

    @field_validator("SCHEDULER_INTERVAL_SECONDS")
    @classmethod
    def _validate_scheduler_interval(cls, v: int) -> int:
        # A sanity floor so a misconfiguration can't hammer the database every second.
        if v < 10:
            raise ValueError("SCHEDULER_INTERVAL_SECONDS must be >= 10")
        return v

    @model_validator(mode="after")
    def _validate_scheduler_lease(self) -> "AppSettings":
        # The lease is renewed once per interval; to survive a single missed renew it must last at
        # least two intervals. Below that, a normal renew delay drops the lease and flaps leadership.
        floor = self.SCHEDULER_INTERVAL_SECONDS * 2
        if self.SCHEDULER_LEASE_TTL_SECONDS < floor:
            raise ValueError(
                f"SCHEDULER_LEASE_TTL_SECONDS ({self.SCHEDULER_LEASE_TTL_SECONDS}) must be >= 2x "
                f"SCHEDULER_INTERVAL_SECONDS ({self.SCHEDULER_INTERVAL_SECONDS}) = {floor}, or leadership flaps"
            )
        return self

    FRONTEND_PORT: int | None = None
    """
    Port the frontend server binds to on startup.

    Left unset it is derived from FRONTEND_URL, so that URL is the single knob: change the port
    there and the server actually listens on it. Set this explicitly only when the bind port has
    to differ from the advertised one — behind a proxy that terminates on 443 and forwards to a
    high port, for example, where FRONTEND_URL names the public address rather than the socket.
    """

    API_DOCS: bool = True

    SECRET: str

    ENV_SECRETS: OrderedDict | None = None

    API_HOST: str = "0.0.0.0"

    API_PORT: int = 8080

    # JWT token lifetime in hours
    # Security vs. UX trade-off considerations:
    #   - Shorter lifetime (1-8 hours): More secure, users must re-login more often
    #   - Longer lifetime (24-48 hours): Better UX, higher risk if token is compromised
    #   - Consider implementing refresh tokens for long-lived sessions with short access tokens
    # Current: 48 hours provides balance for internal tools, but evaluate based on:
    #   - Sensitivity of data accessed
    #   - User authentication patterns
    #   - Compliance requirements (SOC2, HIPAA, etc.)
    TOKEN_TIME: int = 48

    AUTO_MIGRATE: bool = True
    """Apply pending Alembic migrations automatically at startup.

    Set to false in development to get a review gate: the dev server reloads on file changes and
    runs migrations at startup, so a freshly generated revision otherwise reaches the database
    before anyone has read it. When off, startup logs which revisions are pending and leaves the
    schema alone — apply them yourself with `task py:migrate:apply`.
    Leave true for deployments, where migrating on boot is the desired behaviour."""

    LOG_CONFIG_OVERRIDE: Path | None = None
    """ path to custom logging configuration file"""

    LOG_LEVEL: str = "info"
    """ corresponds to standard Python Log levels """

    EVENT_LOG_RETENTION_DAYS: int = 90
    """ default retention for the event_log audit trail; the prune_event_logs task deletes
    rows older than this. 0 disables pruning (keep forever). Overridable per-task. """

    AI_EXECUTION_RETENTION_DAYS: int = 90
    """ default retention for ai_executions; the prune_ai_executions task deletes rows older
    than this. A workspace's logging_config.retention_days overrides it. 0 disables. """

    _logger: logging.Logger | None = None

    DAILY_SCHEDULE_TIME: str = "23:47"
    """Local server time, in HH:MM format. See `DAILY_SCHEDULE_TIME_UTC` for the parsed UTC equivalent"""

    GITHUB_VERSION_URL: str = "https://api.github.com/repos/InnerOpen/marvin/tags"

    GIT_COMMIT_HASH: str = "unknown"

    ALLOW_SIGNUP: bool = False

    DATA_DIR: Path | None = None
    """Root directory for application data (database, assets, seeds, etc.)"""

    SEED_ON_STARTUP: bool = False
    """Import workspace bundles from {DATA_DIR}/seeds on startup even in production.

    Off by default: outside production the seed directory is always imported, but a production
    instance ignores it so a stray bundle in the data volume can't silently import a workspace.
    Load bundles there through the admin backup/import endpoints, or set this to opt back in."""

    @property
    def logger(self) -> logging.Logger:
        """
        Provides a logger instance for the application.

        Initializes the root logger if it hasn't been already.

        Returns:
            logging.Logger: The application logger.
        """
        if self._logger is None:
            from marvin.core.root_logger import get_logger

            self._logger = get_logger()

        return self._logger

    @property
    def DAILY_SCHEDULE_TIME_UTC(self) -> ScheduleTime:
        """
        The `DAILY_SCHEDULE_TIME` converted to UTC and parsed into hours and minutes.

        The `DAILY_SCHEDULE_TIME` setting is expected to be in local server time.
        This property handles the conversion to UTC.

        Returns:
            ScheduleTime: The scheduled time in UTC.
        """

        # parse DAILY_SCHEDULE_TIME into hours and minutes
        try:
            hour_str, minute_str = self.DAILY_SCHEDULE_TIME.split(":")
            local_hour = int(hour_str)
            local_minute = int(minute_str)
        except ValueError:
            local_hour = 23
            local_minute = 45
            self.logger.exception(f"Unable to parse {self.DAILY_SCHEDULE_TIME=} as HH:MM; defaulting to {local_hour}:{local_minute}")

        # DAILY_SCHEDULE_TIME is in local time, so we convert it to UTC
        local_tz = tzlocal()

        now = datetime.now(local_tz)
        local_time = now.replace(hour=local_hour, minute=local_minute)
        utc_time = local_time.astimezone(UTC)

        self.logger.debug(f"Local time: {local_hour}:{local_minute} | UTC time: {utc_time.hour}:{utc_time.minute}")
        return ScheduleTime(utc_time.hour, utc_time.minute)
        # ===============================================

    # Security Configuration

    SECURITY_MAX_LOGIN_ATTEMPTS: int = 5

    SECURITY_USER_LOCKOUT_TIME: int = 24
    "time in hours"

    # Token Security Settings
    SECURITY_TOKEN_PREFIX_USER: str = "marvin_tk_"
    """Prefix for user API tokens (Personal Access Tokens). Default: marvin_tk_"""

    SECURITY_TOKEN_PREFIX_CLIENT: str = "marvin_sk_"
    """Prefix for API client secret keys. Default: marvin_sk_"""

    SECURITY_TOKEN_RANDOM_BYTES: int = 32
    """Number of random bytes for token generation (32 bytes = 43 chars base64url). Default: 32"""

    SECURITY_BCRYPT_ROUNDS: int = 12
    """Bcrypt cost factor (work factor). Higher = more secure but slower. Range: 4-31. Default: 12"""

    # ===============================================
    # Authentication Configuration

    AUTH_COOKIE_NAME: str = "marvin.access_token"
    """Name of the authentication cookie. Default: marvin.access_token"""

    # ===============================================
    # Publishing API Configuration

    PUBLISHING_DEFAULT_STATUS: str = "published"
    """Default entry status filter for publishing API. Default: published"""

    PUBLISHING_DEFAULT_PAGE_SIZE: int = 20
    """Default number of entries per page in publishing API. Default: 20"""

    PUBLISHING_MAX_PAGE_SIZE: int = 100
    """Maximum number of entries per page in publishing API. Default: 100"""

    PUBLISHING_UNKNOWN_ENTRY_TYPE: str = "unknown"
    """Fallback value when entry type is missing. Default: unknown"""

    # ===============================================
    # Storage Configuration

    STORAGE_PROVIDER: str = "local"
    """Storage provider to use: 'local' or 's3'. Default: local"""

    STORAGE_LOCAL_ROOT: Path | None = None
    """Root directory for local file storage. Defaults to {DATA_DIR}/assets"""

    STORAGE_LOCAL_PUBLIC_URL: str = "/assets"
    """Base URL for accessing local files. Default: /assets"""

    STORAGE_S3_ENDPOINT: str | None = None
    """S3-compatible endpoint URL (for R2, MinIO, etc). Optional for AWS S3."""

    STORAGE_S3_BUCKET: str | None = None
    """S3 bucket name. Required when STORAGE_PROVIDER=s3"""

    STORAGE_S3_REGION: str = "auto"
    """S3 region. Use 'auto' for Cloudflare R2. Default: auto"""

    STORAGE_S3_ACCESS_KEY: str | None = None
    """S3 access key ID. Required when STORAGE_PROVIDER=s3"""

    STORAGE_S3_SECRET_KEY: MaskedNoneString | None = None
    """S3 secret access key. Required when STORAGE_PROVIDER=s3. Masked in output."""

    STORAGE_REMOTE_PUBLIC_URL: str | None = None
    """Public base URL for remote storage assets (CDN, custom domain, etc). Works with S3, R2, MinIO, Spaces, etc. Optional."""

    # ===============================================
    # Secrets Backend Configuration

    SECRET_BACKEND: str = "database"
    """Secret storage backend: 'database' | 'disk' | 'env' | 'vault' | 'bitwarden'. Default: database"""

    SECRETS_DIR: Path | None = None
    """Directory for disk backend secret files. Defaults to {DATA_DIR}/secrets/"""

    # HashiCorp Vault
    VAULT_ADDR: str | None = None
    """Vault server URL. Required for vault backend. e.g. http://127.0.0.1:8200"""

    VAULT_TOKEN: MaskedNoneString | None = None
    """Vault authentication token. Required for vault backend. Masked in output."""

    VAULT_MOUNT: str = "secret"
    """Vault KV v2 mount path. Default: secret"""

    VAULT_PATH_PREFIX: str = "marvin"
    """Path prefix within the Vault mount. Default: marvin"""

    # Bitwarden Secrets Manager
    BITWARDEN_ACCESS_TOKEN: MaskedNoneString | None = None
    """Bitwarden machine account access token. Required for bitwarden backend. Masked in output."""

    BITWARDEN_PROJECT_ID: str | None = None
    """Bitwarden Secrets Manager project UUID to scope secrets to."""

    BITWARDEN_API_URL: str | None = None
    """Bitwarden API URL. Only needed for self-hosted instances."""

    BITWARDEN_IDENTITY_URL: str | None = None
    """Bitwarden Identity URL. Only needed for self-hosted instances."""

    # Asset Upload Configuration

    ASSET_MAX_FILE_SIZE: int = 100 * 1024 * 1024
    """Maximum file size for asset uploads in bytes. Default: 100MB"""

    ASSET_ALLOWED_MIME_TYPES: list[str] | None = None
    """List of allowed MIME types for uploads. None = allow all. Default: None"""

    # ===============================================
    # Testing Config

    TESTING: bool = False

    model_config = SettingsConfigDict(arbitrary_types_allowed=True, extra="allow")

    @field_validator("BASE_URL", "FRONTEND_URL")
    @classmethod
    def remove_trailing_slash(cls, v: str) -> str:
        """Pydantic validator to remove trailing slashes from URL settings."""
        if v and v[-1] == "/":
            return v[:-1]

        return v

    @model_validator(mode="after")
    def derive_frontend_port(self) -> "AppSettings":
        """Fill FRONTEND_PORT from FRONTEND_URL when it was not set explicitly.

        FRONTEND_URL advertised a port that nothing bound to, so changing it moved the OIDC
        redirect target while the server kept listening where it always had. Deriving the bind
        port from it makes the one setting mean what it says.
        """
        if self.FRONTEND_PORT is not None:
            return self

        parsed = urlparse(self.FRONTEND_URL)
        if parsed.port is not None:
            self.FRONTEND_PORT = parsed.port
        elif parsed.scheme == "https":
            self.FRONTEND_PORT = 443
        elif parsed.scheme == "http":
            self.FRONTEND_PORT = 80
        else:
            # Unparseable or scheme-less: keep the historical dev default rather than guess.
            self.FRONTEND_PORT = 4322

        return self

    @property
    def DOCS_URL(self) -> str | None:
        """URL for the FastAPI documentation (Swagger UI). Disabled if API_DOCS is False."""
        return "/docs" if self.API_DOCS else None

    @property
    def REDOC_URL(self) -> str | None:
        """URL for the ReDoc documentation. Disabled if API_DOCS is False."""
        return "/redoc" if self.API_DOCS else None

    # ===============================================
    # Database Config

    DB_ENGINE: str = "sqlite"
    """The database engine to use ('sqlite' or 'postgres')."""

    DB_POOL_SIZE: int = 5
    """SQLAlchemy connection pool size (number of persistent connections)."""

    DB_MAX_OVERFLOW: int = 10
    """Maximum number of connections above pool_size allowed before blocking."""

    DB_SQLITE_WAL_MODE: bool = True
    """Enable WAL journal mode for SQLite (allows concurrent reads during writes)."""

    DB_PROVIDER: AbstractDBProvider | None = None
    """The database provider instance, configured by `app_settings_constructor`."""

    @property
    def DB_URL(self) -> str | None:
        """The full database connection URL. Returns None if DB_PROVIDER is not set."""
        return self.DB_PROVIDER.db_url if self.DB_PROVIDER else None

    @property
    def DB_URL_PUBLIC(self) -> str | None:
        """A public version of the database URL (credentials masked). Returns None if DB_PROVIDER is not set."""
        return self.DB_PROVIDER.db_url_public if self.DB_PROVIDER else None

    DEFAULT_EMAIL: str = "changeme@example.com"
    """Default email for the initial admin user, if created."""

    DEFAULT_PASSWORD: str | None = None
    """
    Default password for the initial admin user, if created.

    Security: This is generated randomly at runtime rather than hardcoded.
    Set via environment variable DEFAULT_PASSWORD, or auto-generated if not set.
    The generated password is logged during database seeding for admin access.
    """

    def model_post_init(self, __context) -> None:
        """Generate default password if not provided via environment."""
        if not self.DEFAULT_PASSWORD:
            self.DEFAULT_PASSWORD = secrets.token_urlsafe(16)

    DEFAULT_GROUP: str = "Default"
    """Default group for the initial admin user, if created."""

    _DEFAULT_INTEGRATION_ID: str = "generic"
    """# Default identifier for integrations if not specified when creating an API token."""

    # ===============================================
    # Plugin Configurtion

    PLUGIN_PREFIX: str | None = "marvin_"

    @property
    def PLUGIN_ENABLED(self) -> bool:
        """Indicates if Plugin is configured and enabled."""
        return self.PLUGIN_FEATURE.enabled

    @property
    def PLUGIN_FEATURE(self) -> FeatureDetails:
        """Details about the PLUGIN feature status"""
        description = None
        required = {
            "PLUGIN_PREFIX": self.PLUGIN_PREFIX,
        }

        not_none = None not in required.values()
        if not not_none and not description:
            missing_values = [key for (key, value) in required.items() if value is None]
            description = f"Missing required values for {missing_values}"

        return FeatureDetails(
            enabled=not_none,
            description=description,
        )

    # ===============================================
    # Email Configuration

    EMAIL_TEMPLATE: str = "branded.html"
    """HTML wrapper template filename. Options bundled: branded.html, workspace.html, default.html.
    Set via EMAIL_TEMPLATE env var. Drop a custom file in the data templates dir to override."""
    SMTP_HOST: str | None = None
    """SMTP server hostname or IP address."""
    SMTP_PORT: str | None = "587"
    """SMTP server port."""
    SMTP_FROM_NAME: str | None = "Marvin"
    """The name to display in the 'From' field of emails."""
    SMTP_FROM_EMAIL: str | None = None
    """The email address to use in the 'From' field of emails."""
    SMTP_USER: MaskedNoneString = None
    """SMTP username for authentication (masked in logs/output)."""
    SMTP_PASSWORD: MaskedNoneString = None
    """SMTP password for authentication (masked in logs/output)."""
    SMTP_AUTH_STRATEGY: str | None = "TLS"
    """SMTP authentication strategy. Options: 'TLS', 'SSL', 'NONE'."""

    @property
    def SMTP_ENABLED(self) -> bool:
        """Indicates if SMTP is configured and enabled."""
        return self.SMTP_FEATURE.enabled

    @property
    def SMTP_FEATURE(self) -> FeatureDetails:
        """Details about the SMTP feature status, including validation."""
        return AppSettings.validate_smtp(
            self.SMTP_HOST,
            self.SMTP_PORT,
            self.SMTP_FROM_NAME,
            self.SMTP_FROM_EMAIL,
            self.SMTP_AUTH_STRATEGY,
            self.SMTP_USER,
            self.SMTP_PASSWORD,
        )

    @staticmethod
    def validate_smtp(
        host: str | None = None,
        port: str | None = None,
        from_name: str | None = None,
        from_email: str | None = None,
        strategy: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> FeatureDetails:
        """
        Validates that all necessary SMTP settings are provided.

        Args:
            host: SMTP host.
            port: SMTP port.
            from_name: SMTP from name.
            from_email: SMTP from email.
            strategy: SMTP authentication strategy.
            user: SMTP username.
            password: SMTP password.

        Returns:
            FeatureDetails: An object indicating if SMTP is enabled and a
                            description of any missing settings.
        """
        description = None
        required = {
            "SMTP_HOST": host,
            "SMTP_PORT": port,
            "SMTP_FROM_NAME": from_name,
            "SMTP_FROM_EMAIL": from_email,
            "SMTP_AUTH_STRATEGY": strategy,
        }
        missing_values = [key for (key, value) in required.items() if value is None]
        if missing_values:
            description = f"Missing required values for {missing_values}"

        if strategy and strategy.upper() in {"TLS", "SSL"}:
            required["SMTP_USER"] = user
            required["SMTP_PASSWORD"] = password
            if not description:
                missing_values = [key for (key, value) in required.items() if value is None]
                description = f"Missing required values for {missing_values} because SMTP_AUTH_STRATEGY is not None"

        not_none = "" not in required.values() and None not in required.values()

        return FeatureDetails(enabled=not_none, description=description)

    # ===============================================
    # LDAP Configuration

    LDAP_AUTH_ENABLED: bool = False
    LDAP_SERVER_URL: str | None = None
    LDAP_TLS_INSECURE: bool = False
    LDAP_TLS_CACERTFILE: str | None = None
    LDAP_ENABLE_STARTTLS: bool = False
    LDAP_BASE_DN: str | None = None
    LDAP_QUERY_BIND: str | None = None
    LDAP_QUERY_PASSWORD: MaskedNoneString = None
    LDAP_USER_FILTER: str | None = None
    LDAP_ADMIN_FILTER: str | None = None
    LDAP_ID_ATTRIBUTE: str = "uid"
    LDAP_MAIL_ATTRIBUTE: str = "mail"
    LDAP_NAME_ATTRIBUTE: str = "name"

    @property
    def LDAP_FEATURE(self) -> FeatureDetails:
        """Details about the LDAP feature status, including validation."""
        description = None if self.LDAP_AUTH_ENABLED else "LDAP_AUTH_ENABLED is false"
        required = {
            "LDAP_SERVER_URL": self.LDAP_SERVER_URL,
            "LDAP_BASE_DN": self.LDAP_BASE_DN,
            "LDAP_ID_ATTRIBUTE": self.LDAP_ID_ATTRIBUTE,
            "LDAP_MAIL_ATTRIBUTE": self.LDAP_MAIL_ATTRIBUTE,
            "LDAP_NAME_ATTRIBUTE": self.LDAP_NAME_ATTRIBUTE,
        }
        not_none = None not in required.values()
        if not not_none and not description:
            missing_values = [key for (key, value) in required.items() if value is None]
            description = f"Missing required values for {missing_values}"

        return FeatureDetails(
            enabled=self.LDAP_AUTH_ENABLED and not_none,
            description=description,
        )

    @property
    def LDAP_ENABLED(self) -> bool:
        """Indicates if LDAP authentication is configured and enabled."""
        return self.LDAP_FEATURE.enabled

    # ===============================================
    # OIDC Configuration
    OIDC_AUTH_ENABLED: bool = False
    """Flag to enable OpenID Connect (OIDC) authentication."""
    OIDC_CLIENT_ID: str | None = None
    """OIDC client ID."""
    OIDC_CLIENT_SECRET: MaskedNoneString = None
    """OIDC client secret (masked)."""
    OIDC_CONFIGURATION_URL: str | None = None
    """URL to the OIDC provider's configuration discovery document."""
    OIDC_SIGNUP_ENABLED: bool = True
    """Flag to allow new user sign-ups via OIDC."""
    OIDC_USER_GROUP: str | None = None
    """OIDC group claim value required for regular user access."""
    OIDC_ADMIN_GROUP: str | None = None
    """OIDC group claim value required for admin access."""
    OIDC_AUTO_REDIRECT: bool = False
    """Flag to automatically redirect to OIDC provider for login."""
    OIDC_PROVIDER_NAME: str = "OAuth"
    """Display name for the OIDC provider on the login page."""
    OIDC_REMEMBER_ME: bool = False
    """Flag to enable "remember me" functionality for OIDC logins."""
    OIDC_USER_CLAIM: str = "email"
    """The OIDC claim to use as the primary user identifier (e.g., 'email', 'sub')."""
    OIDC_NAME_CLAIM: str = "name"
    """The OIDC claim to use for the user's full name."""
    OIDC_GROUPS_CLAIM: str | None = "groups"
    """The OIDC claim containing the user's group memberships."""
    OIDC_SCOPES_OVERRIDE: str | None = None
    """Optional override for OIDC scopes (comma-separated)."""
    OIDC_TLS_CACERTFILE: str | None = None
    """Path to a CA certificate file for OIDC provider TLS validation."""

    @property
    def OIDC_REQUIRES_GROUP_CLAIM(self) -> bool:
        """Indicates if OIDC authentication requires group claim validation."""
        return self.OIDC_USER_GROUP is not None or self.OIDC_ADMIN_GROUP is not None

    @property
    def OIDC_FEATURE(self) -> FeatureDetails:
        """Details about the OIDC feature status, including validation."""
        description = None if self.OIDC_AUTH_ENABLED else "OIDC_AUTH_ENABLED is false"
        required = {
            "OIDC_CLIENT_ID": self.OIDC_CLIENT_ID,
            "OIDC_CLIENT_SECRET": self.OIDC_CLIENT_SECRET,
            "OIDC_CONFIGURATION_URL": self.OIDC_CONFIGURATION_URL,
            "OIDC_USER_CLAIM": self.OIDC_USER_CLAIM,
        }
        not_none = None not in required.values()
        if not not_none and not description:
            missing_values = [key for (key, value) in required.items() if value is None]
            description = f"Missing required values for {missing_values}"

        valid_group_claim = True
        if self.OIDC_REQUIRES_GROUP_CLAIM and self.OIDC_GROUPS_CLAIM is None:
            if not description:
                description = "OIDC_GROUPS_CLAIM is required when OIDC_USER_GROUP or OIDC_ADMIN_GROUP are provided"
            valid_group_claim = False

        return FeatureDetails(
            enabled=self.OIDC_AUTH_ENABLED and not_none and valid_group_claim,
            description=description,
        )

    @property
    def OIDC_READY(self) -> bool:
        """Indicates if OIDC authentication is configured and ready to use."""
        return self.OIDC_FEATURE.enabled

    # ===============================================
    # OpenAI Configuration

    OPENAI_BASE_URL: str | None = None
    """The base URL for the OpenAI API. Leave this unset for most use cases."""
    OPENAI_API_KEY: MaskedNoneString = None
    """Your OpenAI API key. Required to enable OpenAI features (masked)."""
    OPENAI_MODEL: str = "gpt-4o-mini"
    """Which OpenAI model to send requests to. Leave this unset for most use cases."""
    OPENAI_CUSTOM_HEADERS: dict[str, str] = {}
    """Custom HTTP headers to send with each OpenAI request."""
    OPENAI_CUSTOM_PARAMS: dict[str, Any] = {}
    """Custom HTTP parameters to send with each OpenAI request."""
    OPENAI_ENABLE_IMAGE_SERVICES: bool = True
    """Whether to enable image-related features in OpenAI."""
    OPENAI_WORKERS: int = 2
    """
    Number of OpenAI workers per request. Higher values may increase
    processing speed but will incur additional API costs.
    """
    OPENAI_SEND_DATABASE_DATA: bool = True
    """
    Sending database data may increase accuracy in certain requests
    but will incur additional API costs.
    """
    OPENAI_REQUEST_TIMEOUT: int = 60
    """
    The number of seconds to wait for an OpenAI request to complete before cancelling.
    """

    @property
    def OPENAI_FEATURE(self) -> FeatureDetails:
        """Details about the OpenAI feature status, including validation."""
        description = None
        if not self.OPENAI_API_KEY:
            description = "OPENAI_API_KEY is not set"
        elif not self.OPENAI_MODEL:  # Corrected: check if OPENAI_MODEL is not set
            description = "OPENAI_MODEL is not set"

        return FeatureDetails(
            enabled=bool(self.OPENAI_API_KEY and self.OPENAI_MODEL),
            description=description,
        )

    @property
    def OPENAI_ENABLED(self) -> bool:
        """Indicates if OpenAI integration is configured and enabled."""
        return self.OPENAI_FEATURE.enabled

    # ===============================================
    # Additional AI Providers (platform credential mode)

    AI_DEFAULT_PROVIDER: str = "openai"
    """Provider used by workspaces in platform credential mode (openai | anthropic | google)."""
    AI_ALLOW_WORKSPACE_CREDENTIALS: bool = True
    """Whether workspaces may use their own AI credentials (credential_mode='workspace').
    When false, only platform-provided credentials are allowed and the workspace option is
    rejected + hidden in the UI."""
    ANTHROPIC_API_KEY: MaskedNoneString = None
    """Anthropic API key for platform credential mode (masked)."""
    ANTHROPIC_BASE_URL: str | None = None
    """Override the Anthropic API base URL. Leave unset for the default endpoint."""
    ANTHROPIC_MODEL: str = "claude-sonnet-5"
    """Default Anthropic model for platform credential mode."""

    GOOGLE_API_KEY: MaskedNoneString = None
    """Google Gemini API key for platform credential mode (masked)."""
    GOOGLE_BASE_URL: str | None = None
    """Override the Google API base URL. Leave unset for the default endpoint."""
    GOOGLE_MODEL: str = "gemini-2.0-flash"
    """Default Google model for platform credential mode."""

    AZURE_API_KEY: MaskedNoneString = None
    """Azure OpenAI API key for platform credential mode (masked)."""
    AZURE_BASE_URL: str | None = None
    """Azure OpenAI endpoint, e.g. https://<resource>.openai.azure.com — required for the azure provider.
    Note: a custom api_version can only be set via a workspace provider row's metadata, not env;
    platform mode uses the provider default."""

    OLLAMA_API_KEY: MaskedNoneString = None
    """Unused — Ollama requires no API key. Declared so platform-mode credential lookup is explicit."""
    OLLAMA_BASE_URL: str | None = None
    """Ollama REST endpoint. Leave unset to use http://localhost:11434
    (e.g. http://host.docker.internal:11434 when the backend runs in Docker)."""

    AI_BUDGET_WARNING_PERCENT: float = 80.0
    """Percent (0-100) of a workspace's monthly AI cost limit at which to fire the
    `ai_budget_threshold_reached` event. Set to 0 to disable the early warning."""

    # ── Embeddings / RAG ──
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    """Embedding model for the OpenAI (and Azure) providers."""
    GOOGLE_EMBEDDING_MODEL: str = "models/text-embedding-004"
    """Embedding model for the Google provider."""
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    """Embedding model for the Ollama provider."""
    AI_RAG_TOP_K: int = 5
    """Number of similar chunks retrieved per RAG question."""
    AI_EMBED_CHUNK_SIZE: int = 1500
    """Max characters per embedded text chunk."""
    AI_EMBED_CHUNK_OVERLAP: int = 150
    """Character overlap between consecutive embedded chunks."""

    # ── Generation defaults ──
    AI_DEFAULT_TEMPERATURE: float = 0.7
    """Default sampling temperature for AI operations."""
    AI_DEFAULT_MAX_TOKENS: int | None = None
    """Default max output tokens for AI operations (None = provider default)."""

    # ===============================================
    # Apprise Configuration

    APPRISE_ENABLED: bool = True
    """Flag to enable Apprise notification service."""
    APPRISE_URL: str | None = None
    """Base URL for Apprise API server. If None, uses local Apprise library."""

    @property
    def APPRISE_FEATURE(self) -> FeatureDetails:
        """Details about the Apprise feature status."""
        description = None if self.APPRISE_ENABLED else "APPRISE_ENABLED is false"

        # Apprise is available if enabled (URL is optional - can use library directly)
        return FeatureDetails(
            enabled=self.APPRISE_ENABLED,
            description=description,
        )

    @property
    def APPRISE_READY(self) -> bool:
        """Indicates if Apprise notification service is configured and ready to use."""
        return self.APPRISE_FEATURE.enabled

    # ===============================================
    # TLS

    TLS_CERTIFICATE_PATH: str | os.PathLike[str] | None = None
    """Path where the TLS certificate resides."""

    TLS_PRIVATE_KEY_PATH: str | os.PathLike[str] | None = None
    """Path where the TLS private key resides."""


class PluginSettings(BaseSettings):
    """
    Base settings class for Marvin plugins.

    Plugins can inherit from this class to define their own specific settings,
    which will be loaded with a prefix based on the plugin's name.
    """

    # Plugin Name
    PLUGIN_NAME: str
    """The name of the plugin."""

    # Plugin Version
    PLUGIN_VERSION: str
    """The version of the plugin."""

    # Plugin Description
    PLUGIN_DESCRIPTION: str | None = None
    """An optional description of the plugin."""

    # Plugin Author
    PLUGIN_AUTHOR: str | None = None
    """The author of the plugin."""

    # Plugin Author Email
    PLUGIN_AUTHOR_EMAIL: str | None = None
    """The email address of the plugin author."""

    model_config = SettingsConfigDict(arbitrary_types_allowed=True, extra="allow")


def app_settings_constructor(
    data_dir: Path,
    production: bool,
    env_file: Path,
    env_secrets: Path,
    secrets_dir: Path | None,
    env_encoding: str = "utf-8",
) -> AppSettings:
    """
    Factory function to create and configure the main `AppSettings` object.

    This function handles the initialization of settings, including loading
    from .env files, determining the secret key, and configuring the database
    provider.

    Args:
        data_dir (Path): The application's data directory.
        production (bool): Flag indicating if in production mode.
        env_file (Path): Path to the main .env file.
        env_secrets (Path): Path to the .env.secrets file.
        secrets_dir (Path): Directory for storing secrets.
        env_encoding (str): Encoding for .env files.

    Returns:
        AppSettings: The configured application settings object.
    """

    app_settings = AppSettings(
        _env_file=env_file,  # type: ignore # pydantic-settings internal
        _env_file_encoding=env_encoding,  # type: ignore
        _secrets_dir=secrets_dir,  # type: ignore
        **{"SECRET": determine_secrets(data_dir, production)},
        **{"ENV_SECRETS": dotenv_values(env_secrets)},
        **{"DATA_DIR": data_dir},
    )

    app_settings.DB_PROVIDER = db_provider_factory(
        app_settings.DB_ENGINE or "sqlite",
        data_dir,
        env_file=env_file,
        env_encoding=env_encoding,
    )
    return app_settings


def app_plugin_settings_constructor(
    name: str,
    version: str,
    env_file: Path | None,
    data_dir: Path,
    production: bool,
    env_secrets: Path | None,
    secrets_dir: Path | None,
    env_encoding: str = "utf-8",
    description: str | None = None,
    author: str | None = None,
    author_email: str | None = None,
    env_nested_delimiter: str = "__",
    settings_class: type[PluginSettings] = PluginSettings,  # Changed default to PluginSettings
) -> PluginSettings:
    """
    Factory function to create and configure `PluginSettings` objects.

    This function handles the initialization of plugin-specific settings,
    loading from .env files with a plugin-specific prefix.

    Args:
        name (str): The name of the plugin.
        version (str): The version of the plugin.
        env_file (Path): Path to the main .env file.
        data_dir (Path): The application's data directory.
        production (bool): Flag indicating if in production mode.
        env_secrets (Path): Path to the .env.secrets file.
        secrets_dir (Path): Directory for storing secrets.
        env_encoding (str): Encoding for .env files.
        description (str | None): Optional description of the plugin.
        author (str | None): Optional author of the plugin.
        author_email (str | None): Optional author email of the plugin.
        env_nested_delimiter (str): Delimiter for nested environment variables.
        settings_class (type[PluginSettings]): The specific PluginSettings subclass
                                               to instantiate. Defaults to `PluginSettings`.

    Returns:
        PluginSettings: The configured plugin settings object.
    """
    app_settings = settings_class(
        PLUGIN_NAME=name,
        PLUGIN_VERSION=version,
        PLUGIN_DESCRIPTION=description,
        PLUGIN_AUTHOR=author,
        PLUGIN_AUTHOR_EMAIL=author_email,
        _env_prefix=name.upper() + "_",
        _env_file=env_file,  # type: ignore
        _env_file_encoding=env_encoding,  # type: ignore
        _secrets_dir=secrets_dir,  # type: ignore
        _env_nested_delimiter=env_nested_delimiter,
        **{"SECRET": determine_secrets(data_dir, production)},
        **{"ENV_SECRETS": dotenv_values(env_secrets)},
    )

    return app_settings
