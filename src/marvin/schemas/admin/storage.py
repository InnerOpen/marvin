"""Schemas for asset storage as the platform admin sees it (/api/admin/storage)."""

from datetime import datetime

from marvin.schemas._marvin import _MarvinModel


class StorageSettingValue(_MarvinModel):
    """One setting a provider or target reads, as it is in effect: secrets masked (`****`), key ids cut to
    their last four characters. Read-only: settings come from the environment (the chart), not from here."""

    env: str
    """The environment variable, e.g. STORAGE_S3_BUCKET."""
    label: str = ""
    value: str | None = None
    """The effective value (the default when unset), masked when secret; null when unset with no default."""
    is_set: bool = False
    """Set in the environment (false: the default, or nothing)."""
    secret: bool = False
    help: str = ""


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
    settings: list[StorageSettingValue] = []
    """Its effective settings, read-only, as the backend reads them (secrets masked)."""


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


class StorageBackupTarget(_MarvinModel):
    """A backup target as its runs report it. The backend doesn't have the targets' environment (each
    CronJob has its own), so this is what the latest run recorded: never a key."""

    name: str
    type: str
    location: str | None = None
    """The target's own description, e.g. `s3://marvin-backups (….r2.cloudflarestorage.com)`."""
    settings: list[StorageSettingValue] = []
    """Its non-secret settings as the job read them (bucket, endpoint, region, prefix, …)."""
    state: str
    """ok, partial, failed, overdue or unknown — details on Admin → Backup health."""
    last_run_at: datetime | None = None


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
    backup_targets: list[StorageBackupTarget] = []
    """Backup targets that have recorded a run (the backend can't see the CronJobs themselves)."""


class StorageSettingsUpdate(_MarvinModel):
    upload_provider: str | None = None
    """An available provider's slug, or null to follow STORAGE_PROVIDER."""


class StorageWorkspaceUpdate(_MarvinModel):
    asset_public_base_url: str | None = None
    """An https URL serving the same bucket (an R2 custom domain, a Cloudflare for SaaS hostname), or null
    for the platform default."""


class StorageCheckStep(_MarvinModel):
    name: str
    """list, put, get or delete."""
    ok: bool
    ms: float
    """How long the step took, in milliseconds."""
    error: str | None = None
    """What went wrong, in plain words (e.g. "the key is invalid or revoked — update the Secret that holds it")."""
    code: str | None = None
    """The service's error code (InvalidAccessKeyId, AccessDenied, NoSuchBucket) or the exception's class."""


class StorageCheckResult(_MarvinModel):
    """Test connection: a tiny object listed, written, read back and deleted under `_marvin-healthcheck/`."""

    provider: str
    ok: bool
    key: str
    """The object used (deleted again, whatever happened)."""
    location: str | None = None
    checked_at: datetime
    steps: list[StorageCheckStep]
