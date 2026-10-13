from logging import Logger

from pydantic import ConfigDict

from marvin.core.config import get_app_dirs, get_app_plugins, get_app_settings
from marvin.core.root_logger import get_logger
from marvin.core.settings import AppPlugins, AppSettings
from marvin.core.settings.directories import AppDirectories


class BaseClient:
    _logger: Logger | None = None
    _settings: AppSettings | None = None
    _directories: AppDirectories | None = None
    _plugins: AppPlugins | None = None

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

    @property
    def plugins(self) -> AppPlugins:
        """
        Provides access to the Marvin application plugins.

        Initializes plugins on first access.
        """
        if not self._plugins:
            self._plugins = get_app_plugins()
        return self._plugins

    model_config = ConfigDict(arbitrary_types_allowed=True)
    """Pydantic model configuration to allow arbitrary types."""
