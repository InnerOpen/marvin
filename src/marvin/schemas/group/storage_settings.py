"""Schemas for a workspace's own asset storage (Workspace → Storage; services/storage/workspace_admin.py)."""

from datetime import datetime

from marvin.schemas._marvin import _MarvinModel


class WorkspaceStorageField(_MarvinModel):
    env: str
    label: str
    help: str = ""
    required: bool = False
    secret: bool = False
    fixed: bool = False
    """Names the bucket: can't change on an existing connection."""


class WorkspaceStorageProvider(_MarvinModel):
    slug: str
    name: str
    fields: list[WorkspaceStorageField] = []


class WorkspaceStorageConnectionRead(_MarvinModel):
    id: str
    plugin_slug: str
    label: str | None = None
    location: str
    """What rows stored through it record: ``ws:<id>``."""
    settings: dict[str, str] = {}
    secret_refs: dict[str, str] = {}
    """{setting: workspace secret slug} — never a value."""
    status: str
    verified_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None
    retired_at: datetime | None = None
    files: int = 0


class WorkspaceStoragePolicyRead(_MarvinModel):
    allowed: bool
    endpoint_policy: str


class WorkspaceStorageRead(_MarvinModel):
    policy: WorkspaceStoragePolicyRead
    mode: str
    """``platform`` or ``workspace``."""
    active_connection_id: str | None = None
    bundle_includes_own_bucket: bool = False
    providers: list[WorkspaceStorageProvider] = []
    connections: list[WorkspaceStorageConnectionRead] = []
    platform_files: int = 0
    can_edit: bool = False
    """OWNER (or a platform super admin): workspace ADMINs see the page but can't change it."""


class WorkspaceStorageConnectionCreate(_MarvinModel):
    plugin_slug: str = "s3"
    label: str | None = None
    settings: dict[str, str] = {}
    """Non-secret settings by name, e.g. STORAGE_S3_BUCKET."""
    secret_refs: dict[str, str] = {}
    """{setting: workspace secret slug} for the keys (create the secrets in Workspace → Secrets first)."""


class WorkspaceStorageConnectionUpdate(_MarvinModel):
    label: str | None = None
    settings: dict[str, str] | None = None
    secret_refs: dict[str, str] | None = None


class WorkspaceStorageCheckStep(_MarvinModel):
    name: str
    ok: bool
    ms: float = 0.0
    error: str | None = None
    code: str | None = None


class WorkspaceStorageConnectionCheck(_MarvinModel):
    ok: bool
    steps: list[WorkspaceStorageCheckStep] = []
    checked_at: str


class WorkspaceStorageModeUpdate(_MarvinModel):
    mode: str
    connection_id: str | None = None


class WorkspaceStoragePolicyUpdate(_MarvinModel):
    allowed: bool
    endpoint_policy: str = "known"


class WorkspaceStorageLocationCount(_MarvinModel):
    location: str
    files: int = 0
    bytes: int = 0


class WorkspaceStorageCopyPlan(_MarvinModel):
    """What copying the workspace's existing files into a bucket would do (nothing is copied to answer)."""

    connection_id: str
    files: int = 0
    bytes: int = 0
    by_location: list[WorkspaceStorageLocationCount] = []
    entries_with_links: int = 0
    """Entries whose content embeds a link to one of the workspace's files (those links keep working)."""
    uploads_go_here: bool = False
    ready: bool = False
    """The connection is verified."""


class WorkspaceStorageCopyStarted(_MarvinModel):
    task_id: str
    task_slug: str
    message: str
