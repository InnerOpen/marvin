"""
This module defines database provider settings for the Marvin application.

It includes an abstract base class `AbstractDBProvider` and concrete implementations
for SQLite (`SQLiteProvider`) and PostgreSQL (`PostgresProvider`).
A factory function `db_provider_factory` is provided to create instances
of these providers based on configuration.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from urllib import parse as urlparse

from pydantic import BaseModel, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    SQLite database provider.

    Attributes:
        data_dir (Path): The directory where the SQLite database file is stored.
        name (str): The name of the SQLite database file. Defaults to "marvin.db".
        prefix (str): An optional prefix for the database file name.
    """

    data_dir: Path
    name: str = "marvin.db"
    prefix: str = ""

    @property
    def db_path(self) -> Path:
        """Returns the full path to the SQLite database file."""
        return self.data_dir / f"{self.prefix}{self.name}"

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

        If `POSTGRES_URL_OVERRIDE` is set, it's used directly after ensuring
        the schema is 'postgres' and quoting the password. Otherwise, the URL is
        built from individual `POSTGRES_*` environment variables.

        Raises:
            ValueError: If `POSTGRES_URL_OVERRIDE` has an invalid schema.

        Returns:
            str: The PostgreSQL connection URL.
        """
        if self.POSTGRES_URL_OVERRIDE:
            url = self.POSTGRES_URL_OVERRIDE

            schema, remainder = url.split("://", 1)
            if schema != "postgresql":
                raise ValueError("POSTGRES_URL_OVERRIDE schema must be postgresql")

            remainder = remainder.split(":", 1)[1]
            password = remainder[: remainder.rfind("@")]
            quoted_password = urlparse.quote(password)

            safe_url = url.replace(password, quoted_password)

            return safe_url
        return str(
            PostgresDsn.build(
                scheme="postgresql",  # SQLAlchemy 2.0 dropped the "postgres" dialect alias
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


def db_provider_factory(provider_name: str, data_dir: Path, env_file: Path, env_encoding="utf-8") -> AbstractDBProvider:
    """
    Factory function to create a database provider instance.

    Args:
        provider_name (str): The name of the database provider ("postgres" or "sqlite").
        data_dir (Path): The application's data directory (used for SQLite).
        env_file (Path): The path to the .env file (used for PostgreSQL).
        env_encoding (str): The encoding of the .env file.

    Returns:
        AbstractDBProvider: An instance of the requested database provider.
    """
    if provider_name == "postgres":
        return PostgresProvider(_env_file=env_file, _env_file_encoding=env_encoding)
    return SQLiteProvider(data_dir=data_dir)
