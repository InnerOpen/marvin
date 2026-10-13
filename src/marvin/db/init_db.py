"""
This module handles the initialization and migration of the Marvin database.

It includes functions to:
- Connect to the database.
- Run Alembic migrations for the main application and any installed plugins.
- Initialize default data (e.g., default group and user).
- Initialize plugin-specific database schemas.
- Apply any necessary data fixes after migrations.
"""

import os
from collections.abc import Callable
from pathlib import Path
from time import sleep
from typing import Any

from alembic import command, config, script
from alembic.config import Config
from alembic.runtime import migration
from sqlalchemy import engine, orm, text, update

from marvin.core import root_logger
from marvin.core.config import AppPlugins, get_app_plugins, get_app_settings
from marvin.db.db_setup import session_context
from marvin.db.fixes.fix_migration_data import fix_migration_data
from marvin.db.models.groups import Groups
from marvin.repos.all_repositories import get_repositories
from marvin.repos.repository_factory import AllRepositories
from marvin.repos.seed.init_users import default_user_init
from marvin.repos.seed.workspace_data_seeder import WorkspaceDataSeeder
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.schemas.group.group import GroupCreate, GroupRead
from marvin.services.group.group_service import GroupService
from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, log_name_hint, platform_workspace
from marvin.services.seeders.seeder_service import SeederService

PROJECT_DIR = Path(__file__).parent.parent

logger = root_logger.get_logger()


def init_plugin_db(session: orm.Session, plugins: AppPlugins) -> None:
    """
    Initialize the database for all registered and enabled plugins.

    This function is called after the main application database has been initialized
    and migrated. It iterates through loaded plugins and calls their respective
    `init_db` functions if they exist.

    Args:
        session (orm.Session): The active SQLAlchemy session.
        plugins (AppPlugins): An AppPlugins instance containing loaded plugins.
    """
    settings = get_app_settings()
    if settings.PLUGIN_ENABLED:
        logger.info("-------Plugins: Init DB-------")
        for plugin_name, plugin in plugins.LOADED_PLUGINS.items():
            logger.debug(f"-------Initializing Plugin DB: {plugin_name}-------")
            plugin_dir = Path(os.path.dirname(plugin.__file__ or ""))
            plugin_db_path = str(plugin_dir / "db" / "init_db.py")

            if os.path.isfile(plugin_db_path):
                logger.debug(f"-------Loading Plugin DB: {plugin_name}-------")
                plugin.init_db(session)
            else:
                logger.debug(f"-------Plugin: Init_db not found: {plugin_name}-------")


def init_db(session: orm.Session) -> None:
    """
    Initializes the main application database with default data.

    This includes creating a default group, a default admin user, and seeding
    system entry types.

    Args:
        session (orm.Session): The active SQLAlchemy session.
    """
    settings = get_app_settings()

    instance_repos = get_repositories(session)

    platform_group = platform_workspace_init(instance_repos, settings.DEFAULT_GROUP)
    group_repos = get_repositories(session, group_id=platform_group.id)
    default_user_init(group_repos)

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
            workspace_seeder = WorkspaceDataSeeder(group_repos, logger)
            workspace_seeder.seed_from_directory(seed_dir)


def platform_workspace_init(repos: AllRepositories, name: str) -> GroupRead:
    """
    The platform (admin's) workspace, created and marked if the database has none.

    ``name`` (``settings.DEFAULT_GROUP``) is used only here, when a fresh install creates it; an
    existing platform workspace keeps whatever name it has.

    Args:
        repos (AllRepositories): The repository accessor for database operations.
        name (str): The name to give a newly created platform workspace.

    Returns:
        GroupRead: The existing or newly created platform workspace.
    """
    try:
        return GroupRead.model_validate(platform_workspace(repos.session))
    except PlatformWorkspaceMissing:
        pass
    logger.info(f"Creating the platform workspace '{name}'")
    group = GroupService.create_group(repos, GroupCreate(name=name))
    repos.session.execute(update(Groups).where(Groups.id == group.id).values(is_platform=True))
    repos.session.commit()
    return GroupRead.model_validate(platform_workspace(repos.session))


def safe_try(func: Callable) -> None:
    """
    Executes a function and logs any exceptions without raising them.

    Args:
        func (Callable): The function to execute.
    """
    try:
        func()
    except Exception as e:
        logger.error(f"Error calling '{func.__name__}': {e}")


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
    Alembic include_name hook to filter tables during autogeneration.

    This function is used by Alembic to decide which database objects should be
    considered when generating migration scripts. It ensures that tables not
    defined in the main SQLAlchemy metadata or plugin metadata (identified by
    a prefix) are ignored, preventing accidental dropping of unknown tables.

    Args:
        name (str): The name of the database object (e.g., table name).
        type_ (str): The type of the database object (e.g., "table", "column").
        parent_names (dict[str, Any]): A dictionary of parent object names.

    Returns:
        bool: True if the object should be included, False otherwise.
    """
    # TODO: This function relies on global `target_metadata` and `PLUGIN_PREFIX`
    # which are not defined in this file. This might indicate a refactoring need
    # or that these are expected to be globally available in the Alembic context.
    # For now, assuming they are available in the execution scope of Alembic.
    if type_ == "table":
        # Dynamically get target_metadata and PLUGIN_PREFIX if possible, or log a warning
        try:
            # This is a placeholder for how these might be accessed.
            # The actual mechanism might be different in Alembic's execution context.
            from marvin.db.models import SqlAlchemyBase as Base  # Assuming Base has the metadata

            target_metadata = Base.metadata
            # PLUGIN_PREFIX would likely come from settings or another global config
            settings = get_app_settings()
            PLUGIN_PREFIX = settings.PLUGIN_PREFIX
            return name in target_metadata.tables or name.startswith(PLUGIN_PREFIX or "")
        except ImportError:
            logger.warning("Could not import Base for target_metadata in include_name hook.")
            # Fallback or stricter behavior might be needed
            return False  # Or True, depending on desired safety if metadata can't be checked
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
    2. Gathers Alembic configuration paths for the main app and all plugins.
    3. For each Alembic configuration:
        - Sets up plugin-specific script locations and version tables if needed.
        - Checks if the database is at the latest revision.
        - If not, runs `alembic upgrade head`.
    4. Creates PostgreSQL extensions if using PostgreSQL.
    5. Applies any data fixes using `fix_migration_data`.
    6. If the database is new (no users), initializes it with `init_db`.
    7. Initializes plugin databases using `init_plugin_db`.

    Raises:
        ConnectionError: If the database connection cannot be established after multiple retries.
        Exception: If an Alembic configuration file path is invalid.
    """
    max_retry = 10
    wait_second = 1

    settings = get_app_settings()

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

        if settings.PLUGIN_ENABLED:
            logger.info("-------Plugins Alembic Enabled-------")
            plugins = get_app_plugins(settings.PLUGIN_PREFIX)
            for plugin_name, plugin in plugins.LOADED_PLUGINS.items():
                PLUGIN_DIR = Path(os.path.dirname(plugin.__file__ or ""))
                plugin_alembic_path = str(PLUGIN_DIR / "alembic.ini")

                if os.path.isfile(plugin_alembic_path):
                    plugin_name = plugin.__meta__["name"]
                    logger.debug(f"-------Adding Plugin Alembic: {plugin_name}-------")
                    alembic_cfg_paths.update({f"{plugin.__meta__['name']}": plugin_alembic_path})

        for name, alembic_cfg_path in alembic_cfg_paths.items():
            if not os.path.isfile(alembic_cfg_path):
                raise Exception("Provided alembic config path doesn't exist")

            alembic_cfg = Config(alembic_cfg_path)
            if name != "main" and os.path.isdir(str(PLUGIN_DIR / "alembic")):
                VERSION_TABLE = f"{name}_alembic_version"
                alembic_cfg.set_main_option("script_location", str(PLUGIN_DIR / "alembic"))
                alembic_cfg.set_main_option("version_table", VERSION_TABLE)
                alembic_cfg.set_main_option("include_name", "include_name")

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
                session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))

        db = get_repositories(session, group_id=None)

        safe_try(lambda: fix_migration_data(session))
        if db.users.get_all():
            logger.debug("Main Databse exists")
        else:
            logger.info("Main Database contains no users initializing...")
            init_db(session)
        log_name_hint(session, settings.DEFAULT_GROUP)

        if settings.PLUGIN_ENABLED:
            init_plugin_db(session, plugins)
