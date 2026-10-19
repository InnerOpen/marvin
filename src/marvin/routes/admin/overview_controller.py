"""Admin → Overview's data: the health strip, every workspace at a glance, AI spend by day (services/admin_overview.py)."""

from datetime import date, datetime

from fastapi import APIRouter

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas._marvin import _MarvinModel

router = APIRouter(prefix="/overview")


class HealthDotRead(_MarvinModel):
    key: str
    label: str
    tone: str
    """ok, warn, bad or off."""
    href: str


class WorkspaceOverviewRead(_MarvinModel):
    id: str
    name: str
    slug: str
    entries: int
    members: int
    ai_spend_month: float
    ai_limit_month: float | None = None
    open_alerts: int
    last_activity: datetime | None = None


class SpendDayRead(_MarvinModel):
    day: date
    cost: float
    runs: int
    prompt_tokens: int
    cached_tokens: int


class SignInRead(_MarvinModel):
    user_id: str
    name: str
    username: str
    at: datetime


class PluginUpdateRead(_MarvinModel):
    package: str
    installed: str
    latest: str
    repo: str
    """owner/repo on GitHub."""


class AdminOverviewRead(_MarvinModel):
    health: list[HealthDotRead]
    workspaces: list[WorkspaceOverviewRead]
    spend: list[SpendDayRead]
    """The last 30 days of AI runs across the platform, oldest first."""
    sign_ins: list[SignInRead] = []
    """The most recent sign-ins, newest first."""
    plugin_updates: list[PluginUpdateRead] = []
    """Installed plugins with a newer release tag (checked every 12 hours)."""


@controller(router)
class AdminOverviewController(BaseAdminController):
    @router.get("", response_model=AdminOverviewRead, summary="Admin overview: health, workspaces, AI spend")
    def get_overview(self) -> AdminOverviewRead:
        from dataclasses import asdict

        from marvin.services.admin_overview import overview

        data = overview(self.session)
        return AdminOverviewRead(
            health=[HealthDotRead(**asdict(d)) for d in data.health],
            workspaces=[WorkspaceOverviewRead(**asdict(w)) for w in data.workspaces],
            spend=[SpendDayRead(**asdict(d)) for d in data.spend],
            sign_ins=[SignInRead(**asdict(s)) for s in data.sign_ins],
            plugin_updates=[PluginUpdateRead(**asdict(u)) for u in data.plugin_updates],
        )
