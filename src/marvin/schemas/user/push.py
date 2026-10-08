"""Schemas for Web Push in Profile → Notifications (/api/self/push): whether the server has push, the signed-in
user's devices and which kinds of push they take. See services/web_push.py."""

from datetime import datetime

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class PushDeviceRead(_MarvinModel):
    id: UUID4
    label: str | None = None
    endpoint: str
    """The push service URL — lets a browser recognise its own subscription in the list."""
    user_agent: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    last_success_at: datetime | None = None
    failure_count: int = 0
    """Failed sends since the last success."""


class PushCategoryRead(_MarvinModel):
    key: str
    label: str
    description: str
    enabled: bool


class PushSettingsRead(_MarvinModel):
    enabled: bool
    """The server has Web Push configured; without it there's nothing to turn on."""
    public_key: str | None = None
    """The VAPID public key browsers subscribe with (``applicationServerKey``)."""
    categories: list[PushCategoryRead] = Field(default_factory=list)
    devices: list[PushDeviceRead] = Field(default_factory=list)


class PushSubscriptionKeys(_MarvinModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionCreate(_MarvinModel):
    """A browser's PushSubscription (``subscription.toJSON()``) plus what to call the device."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushSubscriptionKeys
    user_agent: str | None = Field(default=None, max_length=1000)
    label: str | None = Field(default=None, max_length=120)
    replaces: str | None = Field(default=None, max_length=2048)
    """The endpoint the browser rotated away from (``pushsubscriptionchange``), removed if it's yours."""


class PushPreferencesUpdate(_MarvinModel):
    categories: dict[str, bool]
    """Kind key → on/off; a kind left out keeps its setting."""


class PushTestResult(_MarvinModel):
    devices: int
    """How many of your devices the test is going to (sent in the background)."""


class PushApprovalAction(_MarvinModel):
    token: str = Field(min_length=1, max_length=128)
    """The single-use token the approval's notification carries."""


class PushApprovalResult(_MarvinModel):
    decision: str
    message: str
    """The confirmation notification's line ("Approved — moved 78 entries to the Trash")."""
    url: str
    """The conversation, for the notification to open."""
    badge: int | None = None
    """The workspace's inbox count, for the app icon (when it is the person's current workspace)."""
