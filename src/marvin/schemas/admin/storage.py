"""Schemas for asset storage as the platform admin sees it (/api/admin/storage)."""

from marvin.schemas._marvin import _MarvinModel


class StorageProviderOption(_MarvinModel):
    """An asset storage provider: whether it can take uploads now, and what is stored on it."""

    slug: str
    name: str
    source: str
    """"builtin", "core" (core's temporary s3), the plugin entry point that adds it, or "" when not installed."""
    available: bool
    """Installed and configured: it can take new uploads."""
    error: str | None = None
    """Why it can't (not installed, settings missing)."""
    assets: int = 0
    """Asset rows stored on it."""
    bytes: int = 0
    """Their total size."""
    library_files: int = 0
    """Character-library files stored on it."""


class StorageWorkspaceUsage(_MarvinModel):
    workspace_id: str
    workspace: str
    provider: str
    assets: int
    bytes: int


class StorageSettingsRead(_MarvinModel):
    """Where new uploads go. Existing files stay on the provider each row names; moving them is
    `python -m marvin.scripts.storage_migrate`."""

    env_default: str
    """STORAGE_PROVIDER: where uploads go until an admin chooses."""
    upload_provider: str | None = None
    """The admin's choice, null to follow STORAGE_PROVIDER."""
    effective_provider: str
    """Where new uploads go now."""
    warning: str | None = None
    """Set when the choice is unavailable and uploads fall back to STORAGE_PROVIDER."""
    providers: list[StorageProviderOption]
    workspaces: list[StorageWorkspaceUsage]


class StorageSettingsUpdate(_MarvinModel):
    upload_provider: str | None = None
    """An available provider's slug, or null to follow STORAGE_PROVIDER."""
