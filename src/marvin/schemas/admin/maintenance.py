"""
This module defines Pydantic schemas for representing administrative maintenance
information within the Marvin application.

These schemas are used as response models for endpoints that provide details
about storage usage and potentially application logs.
"""

from datetime import datetime

from pydantic import UUID4

from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model for Marvin schemas


class MaintenanceSummary(_MarvinModel):
    """
    Schema for a summary of maintenance information, currently focused on data directory size.
    """

    data_dir_size: str  # The total size of the main application data directory, presented as a human-readable string (e.g., "1.2 GB").


class MaintenanceStorageDetails(_MarvinModel):
    """
    Schema providing detailed storage usage for various key application directories.
    All sizes are presented as human-readable strings.
    """

    temp_dir_size: str  # Size of the temporary directory.
    backups_dir_size: str  # Size of the backups directory.
    seeds_dir_size: str  # Size of the seeds directory (for initial data).
    plugin_dir_size: str  # Size of the plugins directory.


class CleanupTaskRead(_MarvinModel):
    """A system scheduled task that cleans something up, as Database & cleanup shows it."""

    id: UUID4
    slug: str
    name: str
    enabled: bool
    retention: str | None = None
    """What it trims, in words ("older than 90 days", "revoked over 30 days ago"); None for a task that isn't a retention."""
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_status: str | None = None


class DatabaseTableRead(_MarvinModel):
    """One of the database's largest tables."""

    name: str
    label: str | None = None
    """What it holds, in words; None for a table the report has no description for."""
    size_bytes: int
    """Data, indexes and TOAST together."""
    rows: int
    """The planner's live-row estimate (within a few percent)."""
    share: float
    """Its part of the whole database, 0–1."""
    kept_by: CleanupTaskRead | None = None
    """The system task that trims it; None: nothing does."""
    kind: str = "content"
    """"log" (records that pile up: without a cleanup it only grows) or "content" (kept on purpose)."""


class DatabaseReport(_MarvinModel):
    """Admin → Database & cleanup."""

    size_bytes: int
    tables: list[DatabaseTableRead]
    other_cleanup: list[CleanupTaskRead]
    """The cleanup tasks that don't trim a table (temp files, the planner's statistics)."""
