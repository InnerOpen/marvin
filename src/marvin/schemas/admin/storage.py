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


class StorageWorkspaceSettings(_MarvinModel):
    """A workspace's storage settings (platform admin)."""

    workspace_id: str
    workspace: str
    storage_code: str | None = None
    """The opaque first segment of the workspace's storage keys (and so of its file URLs)."""
    asset_public_base_url: str | None = None
    """The workspace's own public domain for files on a remote provider; null: remotePublicBaseUrl."""


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
    workspace_settings: list[StorageWorkspaceSettings] = []
    """Every workspace's key prefix and public domain."""
    remote_public_base_url: str | None = None
    """STORAGE_REMOTE_PUBLIC_URL: where remote files are served from when their workspace has no domain of its own."""


class StorageSettingsUpdate(_MarvinModel):
    upload_provider: str | None = None
    """An available provider's slug, or null to follow STORAGE_PROVIDER."""


class StorageWorkspaceUpdate(_MarvinModel):
    asset_public_base_url: str | None = None
    """An https URL serving the same bucket (an R2 custom domain, a Cloudflare for SaaS hostname), or null
    for the platform default."""
