"""
This module provides a credentials-based authentication provider for Marvin.

It allows users to authenticate using their username and password stored in the
application's database. It also handles login attempt tracking and user locking
to prevent brute-force attacks.
"""

from datetime import timedelta
from logging import Logger

from pydantic import ConfigDict
from sqlalchemy.orm.session import Session

from marvin.core.config import get_app_dirs, get_app_settings
from marvin.core.root_logger import get_logger
from marvin.core.security.hasher import get_hasher
from marvin.core.security.providers.auth_providers import AuthProvider
from marvin.core.settings import AppSettings
from marvin.core.settings.directories import AppDirectories
from marvin.db.models.users.users import AuthMethod
from marvin.repos.all_repositories import get_repositories
from marvin.schemas.user.auth import CredentialsRequest


class CredentialsProvider(AuthProvider[CredentialsRequest]):
    """Authentication provider that authenticates a user the database using username/password combination"""

    _logger: Logger | None = None
    _settings: AppSettings | None = None
    _directories: AppDirectories | None = None

    def __init__(self, session: Session, data: CredentialsRequest) -> None:
        """
        Initializes the CredentialsProvider.

        Args:
            session (Session): SQLAlchemy session.
            data (CredentialsRequest): The credentials request data containing
                                       username and password.
        """
        super().__init__(session, data)

    @property
    def logger(self) -> Logger:
        """
        Provides access to the Marvin application logger.

        Initializes the logger on first access.
        """
        if not self._logger:
            self._logger = get_logger("credentials_provider")
        return self._logger

    @property
    def settings(self) -> AppSettings:
        """
        Provides access to the Marvin application settings.

        Initializes settings on first access.
        """
        if not self._settings:
            self._settings = get_app_settings()
        return self._settings

    @property
    def directories(self) -> AppDirectories:
        """
        Provides access to the Marvin application directories.

        Initializes directories on first access.
        """
        if not self._directories:
            self._directories = get_app_dirs()
        return self._directories

    model_config = ConfigDict(arbitrary_types_allowed=True)
    """Pydantic model configuration to allow arbitrary types."""

    def authenticate(self) -> tuple[str, timedelta] | None:
        """
        Attempts to authenticate a user using the provided username and password.

        It performs the following checks:
        - Retrieves the user by username or email.
        - Verifies that the user's authentication method is 'MARVIN'.
        - Checks if the user is locked out due to excessive login attempts.
        - Verifies the provided password against the stored hashed password.
        - Updates login attempt counts and locks the user if necessary.

        Returns:
            tuple[str, timedelta] | None: A tuple containing the access token and
                                         its expiration delta if authentication is
                                         successful, otherwise None.
        """
        db = get_repositories(self.session, group_id=None)
        user = self.try_get_user(self.data.username)

        if not user:
            self.verify_fake_password()
            return None

        if user.auth_method != AuthMethod.MARVIN:
            self.verify_fake_password()
            self.logger.warning("Found user but their auth method is not 'MARVIN'. Unable to continue with credentials login")
            return None

        # Repeated failures are counted and refused by sign-in throttling before this runs
        # (services/security/login_throttle.py, POST /api/auth/token): no per-user counter here.
        if not CredentialsProvider.verify_password(self.data.password, user.password):
            return None

        if user.login_attemps:  # a count from before throttling: a successful sign-in clears it
            user = db.users.update(user.id, {"login_attemps": 0, "locked_at": None})
        return self.get_access_token(user, self.data.remember_me)  # type: ignore

    def verify_fake_password(self):
        """
        Performs a fake password verification to mitigate timing attacks.

        This method is called when a user is not found or has an invalid
        authentication method. It computes a password hash to ensure that
        the response time is relatively constant, making it harder for
        attackers to enumerate users or determine authentication methods
        based on timing differences.
        """
        # To prevent user enumeration we perform the verify_password computation to ensure
        # server side time is relatively constant and not vulnerable to timing attacks.
        CredentialsProvider.verify_password(
            "abc123cba321",  # A dummy password
            "$2b$12$JdHtJOlkPFwyxdjdygEzPOtYmdQF5/R5tHxw5Tq8pxjubyLqdIX5i",  # A dummy hash
        )

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Compares a plain string password with a hashed password.

        Args:
            plain_password (str): The plain text password.
            hashed_password (str): The hashed password.

        Returns:
            bool: True if the passwords match, False otherwise.
        """
        return get_hasher().verify(plain_password, hashed_password)
