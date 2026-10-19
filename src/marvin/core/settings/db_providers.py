"""
This module defines database provider settings for the Marvin application.

It includes an abstract base class `AbstractDBProvider` and concrete implementations
for SQLite (`SQLiteProvider`) and PostgreSQL (`PostgresProvider`).
A factory function `db_provider_factory` is provided to create instances
of these providers based on configuration, and `resolve_engine` decides which
engine a given environment means.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from urllib import parse as urlparse

from pydantic import BaseModel, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The driver named outright: a bare ``postgresql://`` means psycopg2 to SQLAlchemy 2.0 but psycopg 3 to 2.1,
# and psycopg2-binary is the one Marvin ships (the SDK/docs jobs resolve SQLAlchemy afresh with pip).
_SCHEME = "postgresql+psycopg2"

SQLITE = "sqlite"
POSTGRES = "postgres"
ENGINES = (SQLITE, POSTGRES)


def resolve_engine(env: Mapping[str, str] | None = None) -> str:
    """The database engine an environment means: ``sqlite`` or ``postgres``.

    An explicit ``DB_ENGINE`` wins. Unset (or empty), the engine is ``postgres`` when the environment
    configures a server (``POSTGRES_SERVER`` or ``POSTGRES_URL_OVERRIDE``) and ``sqlite`` otherwise, so a fresh
    install runs on a file with no setup while an install that already points at Postgres keeps using it.
    Every place that reads the engine goes through here.

    Raises:
        ValueError: ``DB_ENGINE`` names something other than ``sqlite`` or ``postgres``.
    """
    env = os.environ if env is None else env
    explicit = (env.get("DB_ENGINE") or "").strip().lower()
    if explicit:
        if explicit not in ENGINES:
            raise ValueError(f"DB_ENGINE={explicit!r}: the engines are 'sqlite' and 'postgres'.")
        return explicit
    if (env.get("POSTGRES_SERVER") or "").strip() or (env.get("POSTGRES_URL_OVERRIDE") or "").strip():
        return POSTGRES
    return SQLITE


def engine_is_explicit(env: Mapping[str, str] | None = None) -> bool:
    """Whether ``DB_ENGINE`` was set, as opposed to ``resolve_engine`` choosing by the auto rule."""
    env = os.environ if env is None else env
    return bool((env.get("DB_ENGINE") or "").strip())


class AbstractDBProvider(ABC):
    """
    Abstract base class for database providers.

    Defines the interface for accessing database connection URLs.
    """

    @property
    @abstractmethod
    def db_url(self) -> str:
        """The full database connection URL, including credentials."""
        ...

    @property
    @abstractmethod
    def db_url_public(self) -> str:
        """A "public" version of the database URL, with credentials masked."""
        ...


class SQLiteProvider(AbstractDBProvider, BaseModel):
    """
    SQLite database provider: one file, ``marvin.db`` in the data directory unless ``path`` names another.

    Attributes:
        data_dir (Path): The directory where the SQLite database file is stored.
        name (str): The name of the SQLite database file. Defaults to "marvin.db".
        prefix (str): An optional prefix for the database file name.
        path (Path | None): ``DB_SQLITE_PATH``: the database file, when it is not ``data_dir / name``.
    """

    data_dir: Path
    name: str = "marvin.db"
    prefix: str = ""
    path: Path | None = None

    @property
    def db_path(self) -> Path:
        """Returns the full path to the SQLite database file."""
        return self.path or self.data_dir / f"{self.prefix}{self.name}"

    @property
    def db_url(self) -> str:
        """Returns the SQLite connection URL."""
        return f"sqlite:///{str(self.db_path.absolute())}"

    @property
    def db_url_public(self) -> str:
        """Returns the SQLite connection URL (same as db_url for SQLite)."""
        return self.db_url


class PostgresProvider(AbstractDBProvider, BaseSettings):
    """
    PostgreSQL database provider.

    Reads connection details from environment variables or a .env file.
    Allows overriding the full URL with `POSTGRES_URL_OVERRIDE`.

    Attributes:
        POSTGRES_USER (str): PostgreSQL username.
        POSTGRES_PASSWORD (str): PostgreSQL password.
        POSTGRES_SERVER (str): PostgreSQL server hostname or IP address.
        POSTGRES_PORT (str): PostgreSQL server port.
        POSTGRES_DB (str): PostgreSQL database name.
        POSTGRES_URL_OVERRIDE (str | None): If set, overrides all other
                                          connection parameters with this full URL.
    """

    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: SecretStr = ""
    POSTGRES_SERVER: str = ""
    POSTGRES_PORT: str = ""
    POSTGRES_DB: str = ""
    POSTGRES_URL_OVERRIDE: str | None = None

    # extra="ignore": this provider shares the app .env, so it must NOT absorb unrelated keys
    # (e.g. OPENAI_API_KEY, DEFAULT_PASSWORD) — otherwise they land in model_dump and leak.
    model_config = SettingsConfigDict(arbitrary_types_allowed=True, extra="ignore")

    @property
    def db_url(self) -> str:
        """
        Constructs the PostgreSQL connection URL.

        If `POSTGRES_URL_OVERRIDE` is set, it's used after checking the schema
        (`postgresql` or `postgresql+psycopg2`, always returned as the latter) and
        quoting the password. Otherwise, the URL is built from individual
        `POSTGRES_*` environment variables.

        Raises:
            ValueError: If `POSTGRES_URL_OVERRIDE` has an invalid schema.

        Returns:
            str: The PostgreSQL connection URL.
        """
        if self.POSTGRES_URL_OVERRIDE:
            url = self.POSTGRES_URL_OVERRIDE

            schema, remainder = url.split("://", 1)
            if schema not in ("postgresql", _SCHEME):
                raise ValueError(f"POSTGRES_URL_OVERRIDE schema must be postgresql or {_SCHEME}")

            remainder = remainder.split(":", 1)[1]
            password = remainder[: remainder.rfind("@")]
            quoted_password = urlparse.quote(password)

            safe_url = url.replace(password, quoted_password)

            return f"{_SCHEME}://{safe_url.split('://', 1)[1]}"  # the driver named, whichever form was given
        return str(
            PostgresDsn.build(
                scheme=_SCHEME,
                username=self.POSTGRES_USER,
                password=urlparse.quote(self.POSTGRES_PASSWORD.get_secret_value()),
                host=f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}",
                path=f"{self.POSTGRES_DB or ''}",
            )
        )

    @property
    def db_url_public(self) -> str:
        """
        Returns a "public" version of the PostgreSQL connection URL.

        This masks the username and password in the URL string.

        Returns:
            str: The public PostgreSQL connection URL.
        """
        user = self.POSTGRES_USER
        # db_url embeds the URL-quoted secret value — mask against that exact form (SecretStr and the
        # raw value are not str, and the quoted form is what actually appears in the URL).
        password = urlparse.quote(self.POSTGRES_PASSWORD.get_secret_value())
        return self.db_url.replace(user, "*********", 1).replace(password, "***********", 1)


def db_provider_factory(
    provider_name: str, data_dir: Path, env_file: Path, env_encoding="utf-8", sqlite_path: Path | None = None
) -> AbstractDBProvider:
    """
    Factory function to create a database provider instance.

    Args:
        provider_name (str): The name of the database provider ("postgres" or "sqlite").
        data_dir (Path): The application's data directory (used for SQLite).
        env_file (Path): The path to the .env file (used for PostgreSQL).
        env_encoding (str): The encoding of the .env file.
        sqlite_path (Path | None): ``DB_SQLITE_PATH``, when the SQLite file is not ``data_dir / marvin.db``.

    Returns:
        AbstractDBProvider: An instance of the requested database provider.

    Raises:
        ValueError: ``provider_name`` is neither ``sqlite`` nor ``postgres``.
    """
    if provider_name == POSTGRES:
        return PostgresProvider(_env_file=env_file, _env_file_encoding=env_encoding)
    if provider_name == SQLITE:
        return SQLiteProvider(data_dir=data_dir, path=sqlite_path)
    raise ValueError(f"DB_ENGINE={provider_name!r}: the engines are 'sqlite' and 'postgres'.")
