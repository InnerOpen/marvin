import os
from functools import lru_cache
from pathlib import Path

import dotenv

from marvin.core.settings import app_plugin_settings_constructor, app_settings_constructor

from .settings import AppDirectories, AppPlugins, AppSettings, PluginSettings

CWD = Path(__file__).parent
BASE_DIR = Path(os.getenv("BASE_DIR", CWD.parent.parent))
ENV = BASE_DIR.joinpath(".env")
ENV_SECRETS = BASE_DIR.joinpath(".env.secrets")

dotenv.load_dotenv(ENV)
PRODUCTION = os.getenv("PRODUCTION", "False").capitalize() == "True"
TESTING = os.getenv("TESTING", "False").capitalize() == "True"
DATA_DIR = os.getenv("DATA_DIR")
PLUGIN_DIR = os.getenv("PLUGIN_DIR")
SECRETS_DIR = Path(_secrets_dir) if (_secrets_dir := os.getenv("SECRETS_DIR")) else None


def determine_data_dir() -> Path:
    """Determine the data directory based on the environment."""
    global PRODUCTION, TESTING, BASE_DIR, DATA_DIR

    if TESTING:
        return BASE_DIR.joinpath(DATA_DIR if DATA_DIR else "tests", ".temp")

    if PRODUCTION:
        ## Make sure Path is absoulte
        return Path(DATA_DIR if DATA_DIR else BASE_DIR.joinpath("app", "data"))

    return Path(DATA_DIR if DATA_DIR else BASE_DIR.joinpath("dev", "data"))


def determin_plugin_dir() -> Path:
    """Determine the plugin directory based on the environment."""
    global PRODUCTION, TESTING, BASE_DIR, DATA_DIR

    if TESTING:
        return BASE_DIR.joinpath(DATA_DIR if DATA_DIR else "tests", ".temp")
    if PRODUCTION:
        return Path(DATA_DIR if DATA_DIR else BASE_DIR.joinpath("app", "plugins"))

    return BASE_DIR.joinpath("dev", "plugins")


@lru_cache
def get_app_dirs() -> AppDirectories:
    """Get the application directories."""
    return AppDirectories(determine_data_dir(), determin_plugin_dir())


@lru_cache
def get_app_settings(name: str | None = None) -> AppSettings:
    """Get the application settings."""
    return app_settings_constructor(
        env_file=ENV,
        env_secrets=ENV_SECRETS,
        secrets_dir=SECRETS_DIR,
        production=PRODUCTION,
        data_dir=determine_data_dir(),
    )


@lru_cache
def get_app_plugin_settings(
    name: str,
    version: str,
    description: str | None = None,
    author: str | None = None,
    author_email: str | None = None,
    env_file: Path | None = ENV,
    env_secrets: Path | None = ENV_SECRETS,
    secrets_dir: Path | None = SECRETS_DIR,
    settings_class: type[PluginSettings] = PluginSettings,
) -> PluginSettings:
    """Get the application plugin settings."""
    return app_plugin_settings_constructor(
        name=name,
        version=version,
        description=description,
        author=author,
        author_email=author_email,
        env_file=env_file,
        env_secrets=env_secrets,
        secrets_dir=secrets_dir,
        production=PRODUCTION,
        data_dir=determine_data_dir(),
        settings_class=settings_class,
    )


@lru_cache
def get_app_plugins(plugin_prefix: str) -> AppPlugins:
    """Get the application plugins."""
    return AppPlugins(determin_plugin_dir(), plugin_prefix)
