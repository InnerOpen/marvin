"""
This module serves as the entry point for the `marvin.services` package.

It defines the `BaseService` class, which provides common functionalities and
attributes (like logger, settings, and directory configurations) intended to be
inherited by all other service classes within this package. This promotes
consistency and reduces boilerplate in concrete service implementations.
"""

from logging import Logger  # For type hinting the logger attribute

from pydantic import ConfigDict

# Marvin core components for accessing application-wide configurations and utilities
from marvin.core.config import AppDirectories, AppSettings, get_app_dirs, get_app_settings
from marvin.core.root_logger import get_logger  # For obtaining a logger instance


class BaseService:
    """
    A base class for all service layer classes in the Marvin application.

    This class provides common attributes that services might need, such as:
    - A logger instance for logging messages.
    - Access to application settings (`AppSettings`).
    - Access to application directory configurations (`AppDirectories`).

    Services inheriting from `BaseService` will automatically have these
    attributes initialized and available for use.
    """

    _logger: Logger | None = None
    _settings: AppSettings | None = None
    _directories: AppDirectories | None = None

    @property
    def logger(self) -> Logger:
        """
        Provides access to the Marvin application logger.

        Initializes the logger on first access.
        """
        if not self._logger:
            self._logger = get_logger()
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
