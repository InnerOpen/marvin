"""
This module handles the initialization and migration of the Marvin database.

It includes functions to:
- Connect to the database.
- Run Alembic migrations for the main application.
- Initialize default data (the first super admin and the system entry types; no workspace).
"""

import os
from pathlib import Path
from time import sleep
from typing import Any

from alembic import command, config, script
from alembic.config import Config
from alembic.runtime import migration
from sqlalchemy import engine, orm, select, text

from marvin.core import root_logger
from marvin.core.config import get_app_settings
from marvin.db.db_setup import session_context
from marvin.db.models.groups import Groups
from marvin.repos.all_repositories import get_repositories
from marvin.repos.seed.init_users import default_user_init
from marvin.repos.seed.workspace_data_seeder import WorkspaceDataSeeder
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.services.seeders.seeder_service import SeederService

PROJECT_DIR = Path(__file__).parent.parent

logger = root_logger.get_logger()


def init_db(session: orm.Session) -> None:
    """
    Initializes the main application database with default data.

    This includes creating the first super admin (no workspace: they log into Admin and create
    workspaces there) and seeding system entry types.

    Args:
        session (orm.Session): The active SQLAlchemy session.
    """
    settings = get_app_settings()

    instance_repos = get_repositories(session, group_id=None)

    default_user_init(instance_repos)

    # Seed system-level entry types (globally available to all workspaces)
    system_seeder_service = SeederService(instance_repos)  # Use instance_repos (no group_id) for system types
    system_seeder_service.seed_system_entry_types("system_entry_types")

    # Seed workspace-specific data from seeds directory if it exists.
    #
    # This imports *anything* matching workspace-*.json/zip in {DATA_DIR}/seeds, on every startup.
    # That is a dev/bootstrap convenience and must not fire implicitly on a production instance —
    # a stray bundle in the data volume would silently import a whole workspace. Production loads
    # bundles explicitly through the admin backup/import endpoints instead. Set SEED_ON_STARTUP=true
    # to opt back in (e.g. to provision a demo instance from a bundle).
    data_dir = settings.DATA_DIR
    if data_dir and (not settings.PRODUCTION or settings.SEED_ON_STARTUP):
        seed_dir = Path(data_dir) / "seeds"
        if seed_dir.exists():
            logger.info(f"Seeding workspace data from: {seed_dir}")

            # Use instance_repos (no group_id) so loader can create/find workspaces
            workspace_loader = WorkspaceSeedLoader(instance_repos, logger)

            # Load JSON seed files
            for seed_file in sorted(seed_dir.glob("workspace-*.json")):
                workspace_loader.load_seed_file(seed_file)

            # Load zip bundle seed files (include assets)
            for zip_file in sorted(seed_dir.glob("workspace-*.zip")):
                workspace_loader.load_seed_zip(zip_file)

            # Also process legacy entry-only seeds
            # They name no workspace, so they go into the oldest one (made by the bundles above);
            # a fresh install has none, and then there is nothing to seed them into.
            first_workspace = session.execute(select(Groups.id).order_by(Groups.created_at).limit(1)).scalar()
            if first_workspace is None:
                logger.info("No workspace exists: skipping the legacy entry-only seeds.")
            else:
                WorkspaceDataSeeder(get_repositories(session, group_id=first_workspace), logger).seed_from_directory(seed_dir)


def warn_if_retired_default_group() -> None:
    """One startup warning while the retired ``DEFAULT_GROUP`` is still set (env or ``.env``).

    A fresh install no longer creates a workspace, so the setting names nothing. It is not an error:
    ``extra="allow"`` keeps old environments booting, and this tells whoever owns them to drop it.
    """
    if os.environ.get("DEFAULT_GROUP") is not None or "DEFAULT_GROUP" in (get_app_settings().model_extra or {}):
        logger.warning(
            "DEFAULT_GROUP is set but no longer used: a fresh install creates no workspace (sign in to Admin and "
            "create one). Remove DEFAULT_GROUP (chart value config.platformWorkspaceName) from the environment."
        )


def connect(session: orm.Session) -> bool:
    """
    Checks if a connection can be established to the database.

    Args:
        session (orm.Session): The SQLAlchemy session to use for the connection test.

    Returns:
        bool: True if the connection is successful, False otherwise.
    """
    try:
        session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        return False


def include_name(name: str, type_: str, parent_names: dict[str, Any]) -> bool:
    """
    Alembic include_name hook to filter tables during migration checks.

    Only tables defined in the main SQLAlchemy metadata are considered, so unknown tables
    are ignored rather than treated as drift.

    Args:
        name (str): The name of the database object (e.g., table name).
        type_ (str): The type of the database object (e.g., "table", "column").
        parent_names (dict[str, Any]): A dictionary of parent object names.

    Returns:
        bool: True if the object should be included, False otherwise.
    """
    if type_ == "table":
        from marvin.db.models import SqlAlchemyBase as Base

        return name in Base.metadata.tables
    return True


def pending_revisions(alembic_cfg: config.Config) -> list[str]:
    """Revision ids the database has not applied yet, oldest first.

    Used to report what a review gate is holding back. Best-effort: reporting must never be
    the reason startup fails, so any problem resolving history yields an empty list.
    """
    try:
        directory = script.ScriptDirectory.from_config(alembic_cfg)
        connectable = engine.create_engine(get_app_settings().DB_URL)
        with connectable.connect() as connection:
            ctx = migration.MigrationContext.configure(
                connection=connection,
                opts={
                    "version_table": alembic_cfg.get_main_option("version_table") or "alembic_version",
                    "include_name": include_name,
                },
            )
            current_rev = ctx.get_current_revision()
        # iterate_revisions(upper, lower) walks head -> lower, excluding lower itself.
        # Reverse it so the report reads in the order they'd be applied.
        revisions = directory.iterate_revisions("heads", current_rev)
        return [rev.revision for rev in reversed(list(revisions))]
    except Exception:  # pragma: no cover - diagnostics only
        return []


def db_is_at_head(alembic_cfg: config.Config) -> bool:
    """
    Checks if the database is migrated to the latest Alembic revision (head).

    Args:
        alembic_cfg (config.Config): The Alembic configuration object.

    Returns:
        bool: True if the database is at the head revision, False otherwise.

    Raises:
        ValueError: If the database URL is not configured.
    """
    settings = get_app_settings()
    url = settings.DB_URL
    if not url:
        raise ValueError("No database url found")

    connectable = engine.create_engine(url)  # Note: global `engine` is used here
    directory = script.ScriptDirectory.from_config(alembic_cfg)
    with connectable.connect() as connection:
        context = migration.MigrationContext.configure(
            connection=connection,
            opts={
                "version_table": alembic_cfg.get_main_option("version_table") or "alembic_version",
                "include_name": include_name,
            },
        )
        return set(context.get_current_heads()) == set(directory.get_heads())


def main() -> None:
    """
    Main database initialization and migration function.

    This function performs the following steps:
    1. Waits for a successful database connection.
    2. Gathers Alembic configuration paths for the main app.
    3. For each Alembic configuration:
        - Checks if the database is at the latest revision.
        - If not, runs `alembic upgrade head`.
    4. Creates PostgreSQL extensions if using PostgreSQL.
    5. If the database is new (no users), initializes it with `init_db`.

    Raises:
        ConnectionError: If the database connection cannot be established after multiple retries.
        Exception: If an Alembic configuration file path is invalid.
    """
    max_retry = 10
    wait_second = 1

    with session_context() as session:
        while True:
            if connect(session):
                logger.info("Database connection established.")
                break

            logger.error("Database connection failed - exiting application.")
            max_retry -= 1

            sleep(wait_second)

            if max_retry == 0:
                raise ConnectionError("Database connection failed - exiting application.")

        alembic_cfg_paths = {"main": os.getenv("ALEMBIC_CONFIG_FILE", default=str(PROJECT_DIR / "alembic.ini"))}

        for name, alembic_cfg_path in alembic_cfg_paths.items():
            if not os.path.isfile(alembic_cfg_path):
                raise Exception("Provided alembic config path doesn't exist")

            alembic_cfg = Config(alembic_cfg_path)
            if db_is_at_head(alembic_cfg):
                logger.debug(f"Migration not needed for {name}.")
            elif not get_app_settings().AUTO_MIGRATE:
                # Review gate. The dev server reloads on file changes and this runs at startup,
                # so a freshly generated revision would otherwise hit the database before anyone
                # had read it. With AUTO_MIGRATE off, say what's pending and let a human apply it.
                pending = pending_revisions(alembic_cfg)
                logger.warning(
                    "AUTO_MIGRATE is off and %s has %d pending migration(s): %s. "
                    "Review them, then apply with `task py:migrate:apply`. "
                    "The app is running against an OUT-OF-DATE schema until you do.",
                    name,
                    len(pending),
                    ", ".join(pending) or "unknown",
                )
            else:
                logger.debug(f"Migration needed. Performing migration for {name}...")
                command.upgrade(alembic_cfg, "head")

            if session.get_bind().name == "postgresql":
                # pg_trgm backs fuzzy search; SQLite has no equivalent and searches by tokenized LIKE instead
                # (schemas/response/query_search.py).
                session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))

        db = get_repositories(session, group_id=None)

        if db.users.get_all():
            logger.debug("Main Databse exists")
        else:
            logger.info("Main Database contains no users initializing...")
            init_db(session)
        warn_if_retired_default_group()
