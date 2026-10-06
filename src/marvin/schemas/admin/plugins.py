"""Schemas for the platform's installed plugins (admin: /api/admin/plugins)."""

from typing import Literal

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel

PluginKind = Literal["integration", "storage", "ai_provider"]
"""What a plugin extends: integration providers, storage (asset providers / backup targets); AI providers are next."""


class PluginProviderRead(_MarvinModel):
    """One provider a plugin registers, and how many workspaces have connected it."""

    slug: str
    name: str
    icon: str = ""
    """The provider's emoji — the fallback when it has no accepted logo."""
    has_logo: bool = False
    actions: int = 0
    blueprints: int = 0
    """Content blueprints the provider offers workspaces on connect."""
    workspaces: int = 0
    """Distinct workspaces with at least one connection to this provider."""
    provides: list[str] = Field(default_factory=list)
    """Storage plugins: what it offers, "assets" (an asset storage provider) and/or "backups" (a backup target)."""
    in_use: list[str] = Field(default_factory=list)
    """Storage plugins: what the platform uses it for — "assets" when it is the active STORAGE_PROVIDER."""


class PluginRead(_MarvinModel):
    """An installed plugin package, as the platform operator installed it."""

    name: str
    """The entry-point name the package registers under."""
    package: str | None = None
    version: str | None = None
    kind: PluginKind
    ok: bool
    error: str | None = None
    """Why the plugin failed to load, when it did — it is skipped, not fatal."""
    providers: list[PluginProviderRead] = Field(default_factory=list)
