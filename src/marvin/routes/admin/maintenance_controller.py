"""
This module defines the FastAPI controller for administrative maintenance tasks
within the Marvin application.

It provides read-only endpoints for administrators: storage usage summaries,
directory sizes and system statistics. Cleanup *actions* (temp files, revoked tokens,
old events, VACUUM) are scheduled tasks — Admin → Scheduled Tasks → Run Now — so they
share its execution log, config and retention (services/scheduled_tasks/handlers/maintenance.py).
It also includes a utility function for tailing log files (not exposed via HTTP).
"""

from pathlib import Path  # For path manipulation

import sqlalchemy as sa
from fastapi import APIRouter
from pydantic import BaseModel  # For stats response model

# Marvin specific imports
from marvin.pkgs.stats import fs_stats  # Filesystem statistics utilities
from marvin.routes._base import BaseAdminController, controller  # Base admin controller
from marvin.schemas.admin import MaintenanceSummary  # Pydantic schema for maintenance summary
from marvin.schemas.admin.maintenance import DatabaseReport, MaintenanceStorageDetails  # Schema for storage details

# APIRouter for admin maintenance section, prefixed with /maintenance
# All routes here will be under /admin/maintenance.
router = APIRouter(prefix="/maintenance")


class SystemStats(BaseModel):
    """System statistics response model."""

    users_count: int
    groups_count: int
    entries_count: int
    assets_count: int
    api_tokens_count: int
    webhooks_count: int
    database_size: str
    database_path: str
    assets_size: str
    assets_path: str
    backups_size: str
    backups_path: str
    total_size: str
    data_dir_path: str


def tail_log(log_file: Path, n: int) -> list[str]:
    """
    Reads the last N lines from a log file.

    Args:
        log_file (Path): The Path object pointing to the log file.
        n (int): The number of lines to read from the end of the file.

    Returns:
        list[str]: A list of the last N lines from the file, or a list
                   containing a "no log file found" message if the file
                   does not exist.
    """
    try:
        with open(log_file, encoding="utf-8") as f:  # Added encoding for robustness
            lines = f.readlines()
    except FileNotFoundError:
        return [f"Log file not found: {log_file}"]  # More informative message
    except Exception as e:  # Catch other potential read errors
        return [f"Error reading log file {log_file}: {e}"]

    return lines[-n:]  # Return the last n lines


@controller(router)
class AdminMaintenanceController(BaseAdminController):
    """
    Controller for administrative maintenance operations.

    Provides endpoints for viewing storage statistics (cleanup runs as scheduled tasks).
    All operations require administrator privileges.
    """

    @router.get("/database", response_model=DatabaseReport, summary="Database size, its largest tables and what trims each")
    def get_database_report(self) -> DatabaseReport:
        """The database's size, its largest tables (size, estimated rows, share of the whole) and, for each, the system
        task that trims it with its retention and last/next run — or none, for a table that only grows. Also the
        cleanup tasks that don't trim a table (temporary files, the planner's statistics)."""
        from marvin.services.database_report import database_report

        return database_report(self.session)

    @router.get("", response_model=MaintenanceSummary, summary="Get Maintenance Summary")
    def get_maintenance_summary(self) -> MaintenanceSummary:
        """
        Retrieves a summary of maintenance-related information.

        Currently, this includes the total size of the main application data directory.
        Accessible only by administrators.

        Returns:
            MaintenanceSummary: A Pydantic model containing the data directory size.
        """
        data_dir = self.directories.DATA_DIR  # Access DATA_DIR via base controller
        return MaintenanceSummary(
            data_dir_size=fs_stats.pretty_size(fs_stats.get_dir_size(data_dir)),
        )

    @router.get("/storage", response_model=MaintenanceStorageDetails, summary="Get Storage Details")
    def get_storage_details(self) -> MaintenanceStorageDetails:
        """
        Retrieves detailed storage usage for various application directories.

        This includes the size of the temporary, backups, seeds, and plugins directories.
        Sizes are returned in a human-readable format (e.g., MB, GB).
        Accessible only by administrators.

        Returns:
            MaintenanceStorageDetails: A Pydantic model containing the sizes of key directories.
        """
        dirs = self.directories  # Access application directories via base controller
        return MaintenanceStorageDetails(
            temp_dir_size=fs_stats.pretty_size(fs_stats.get_dir_size(dirs.TEMP_DIR)),
            backups_dir_size=fs_stats.pretty_size(fs_stats.get_dir_size(dirs.BACKUP_DIR)),
            seeds_dir_size=fs_stats.pretty_size(fs_stats.get_dir_size(dirs.SEED_DIR)),
            plugin_dir_size=fs_stats.pretty_size(fs_stats.get_dir_size(dirs.PLUGIN_DIR)),
        )

    @router.get("/stats", response_model=SystemStats, summary="Get System Statistics")
    def get_system_stats(self) -> SystemStats:
        """
        Retrieves system-wide statistics including database counts and storage sizes.

        Returns counts for users, groups, entries, assets, API tokens, and webhooks,
        along with storage usage information.
        Accessible only by administrators.

        Returns:
            SystemStats: A Pydantic model containing system statistics and storage info.
        """
        from marvin.db.db_setup import session_context
        from marvin.db.models.groups.groups import Groups
        from marvin.db.models.groups.webhooks import GroupWebhooksModel
        from marvin.db.models.platform.assets import Assets
        from marvin.db.models.platform.entries import Entries
        from marvin.db.models.users.users import LongLiveToken, Users

        # Count records using SQLAlchemy
        with session_context() as session:
            users_count = session.query(Users).count()
            groups_count = session.query(Groups).count()
            entries_count = session.query(Entries).count()
            assets_count = session.query(Assets).count()
            api_tokens_count = session.query(LongLiveToken).count()
            webhooks_count = session.query(GroupWebhooksModel).count()

        # Get directory sizes
        dirs = self.directories
        data_dir_size = fs_stats.get_dir_size(dirs.DATA_DIR)
        backups_size = fs_stats.get_dir_size(dirs.BACKUP_DIR)

        # For assets, check if there's an assets directory in data
        assets_dir = dirs.DATA_DIR / "assets"
        assets_size = fs_stats.get_dir_size(assets_dir) if assets_dir.exists() else 0

        # Database size, as Postgres counts it (0 when it can't say).
        try:
            db_size = int(self.session.execute(sa.text("SELECT pg_database_size(current_database())")).scalar() or 0)
        except Exception:  # noqa: BLE001 — a stat, never a failed page
            self.session.rollback()
            db_size = 0

        total_size = data_dir_size

        return SystemStats(
            users_count=users_count,
            groups_count=groups_count,
            entries_count=entries_count,
            assets_count=assets_count,
            api_tokens_count=api_tokens_count,
            webhooks_count=webhooks_count,
            database_size=fs_stats.pretty_size(db_size),
            database_path=self.session.get_bind().url.render_as_string(hide_password=True),
            assets_size=fs_stats.pretty_size(assets_size),
            assets_path=str(assets_dir),
            backups_size=fs_stats.pretty_size(backups_size),
            backups_path=str(dirs.BACKUP_DIR),
            total_size=fs_stats.pretty_size(total_size),
            data_dir_path=str(dirs.DATA_DIR),
        )
