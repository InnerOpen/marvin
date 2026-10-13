"""Site rebuild schemas: request a rebuild of the workspace's static site and read where it stands."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel
from marvin.services.event_bus_service.event_types import SiteRebuildChange


class SiteRebuildRequest(_MarvinModel):
    """Body of `POST /api/platform/site/rebuild` (optional)."""

    reason: str | None = Field(default=None, max_length=200)
    """Why — shown in the rebuild's change list, its toast and the event log. Default: who asked."""


class SiteRebuildTarget(_MarvinModel):
    """What builds the site when the rebuild is sent."""

    kind: Literal["webhook", "integration"]
    """An outgoing webhook (the host's deploy hook) or an integration action, either on `webhook_triggered`."""
    id: UUID4
    name: str | None = None
    provider: str | None = None
    """The integration's provider (e.g. `cloudflare_pages`); None for a webhook."""
    action: str | None = None
    """The integration action it runs (e.g. `deploy`); None for a webhook."""


class SiteRebuildRequested(_MarvinModel):
    """The rebuild was queued: it joins the workspace's pending rebuild, which goes out once requests go quiet."""

    requested: bool = True
    queued_at: datetime
    """When the pending rebuild was first requested — the same for every request that joins it."""
    last_requested_at: datetime
    expected_send_at: datetime
    """When it goes out if nothing else joins it (SITE_REBUILD_QUIET_SECONDS after the last request,
    at most SITE_REBUILD_MAX_WAIT_SECONDS after the first)."""
    request_count: int
    """How many requests the pending rebuild covers, this one included."""
    reason: str
    target: SiteRebuildTarget | None = None
    """What will build the site; None when there are several (all of them get it — see `targets`)."""
    targets: list[SiteRebuildTarget]


class SiteRebuildPending(_MarvinModel):
    """A queued rebuild that hasn't been sent yet."""

    queued_at: datetime
    last_requested_at: datetime
    expected_send_at: datetime
    request_count: int
    reason: str | None = None
    """The latest request's reason."""
    changes: list[SiteRebuildChange] = []
    """What it covers so far, newest last (capped)."""


class SiteRebuildSent(_MarvinModel):
    """The last rebuild sent to the deploy target (its `webhook_triggered` event)."""

    event_id: UUID4
    sent_at: datetime
    message: str
    request_count: int | None = None


class SiteBuildStatus(_MarvinModel):
    """The newest build or deploy event a host reported (`site_build_*` / `site_deployment_*`)."""

    event_id: UUID4
    event_type: str
    stage: Literal["build", "deployment"]
    status: Literal["started", "completed", "failed"]
    occurred_at: datetime
    message: str
    detail: str | None = None
    """Why it failed, when the host said."""
    deployment_id: str | None = None
    site_url: str | None = None


class SiteRebuildStatus(_MarvinModel):
    """`GET /api/platform/site/rebuild`: where the workspace's site rebuild stands."""

    configured: bool
    """Something builds the site when a rebuild is sent; when False a rebuild request is refused (409)."""
    target: SiteRebuildTarget | None = None
    targets: list[SiteRebuildTarget] = []
    quiet_seconds: int
    max_wait_seconds: int
    pending: SiteRebuildPending | None = None
    """The queued rebuild not sent yet; None when nothing is waiting."""
    last_sent: SiteRebuildSent | None = None
    last_build: SiteBuildStatus | None = None
    """None when no host reports builds back (see the publishing docs: build and deploy status)."""
