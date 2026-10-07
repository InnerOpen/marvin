"""Installed plugins, as the platform admin sees them.

A plugin is a Python package the platform operator installs into the image (or a Helm init
container). Marvin discovers it through entry points at startup and offers what it registers to every
workspace, which then connects it under its own Integrations settings. Integration providers
(services/integrations), storage plugins (services/storage/registry.py: asset providers and backup
targets, used platform-wide) and AI providers (services/ai/registry.py: model vendors any workspace can
choose) are pluggable, so the admin keeps a single list of what is installed.
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from marvin.db.models.groups.integrations import IntegrationModel
from marvin.schemas.admin.plugins import PluginProviderRead, PluginRead

KIND_INTEGRATION = "integration"
KIND_STORAGE = "storage"
KIND_AI_PROVIDER = "ai_provider"


def _integration_sources() -> list[tuple[Any, list[Any]]]:
    """Each integration plugin's load report, with the provider instances it registered.

    Integrations are optional: with no provider package installed the SDK is absent, so there is
    nothing to report rather than an import error.
    """
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return []

    from marvin.services.integrations import INTEGRATION_REGISTRY, load_reports

    return [(report, [INTEGRATION_REGISTRY[slug] for slug in report.slugs if slug in INTEGRATION_REGISTRY]) for report in load_reports()]


def _storage_sources() -> list[tuple[Any, list[Any]]]:
    """Each storage plugin's load report, with the StoragePlugin it registered (built-ins aren't
    installed packages, so they don't appear)."""
    from marvin.services.storage import registry

    found = registry.plugins()
    return [
        (report, [found[slug] for slug in report.slugs if slug in found and registry.source_of(slug) == report.name])
        for report in registry.load_plugins()
    ]


def _active_storage_provider() -> str:
    """Where new uploads go: the admin's choice (Admin → Storage), else STORAGE_PROVIDER."""
    from marvin.services.storage.provider_factory import upload_target

    return upload_target().effective


def _storage_provider_read(plugin: Any, active: str) -> PluginProviderRead:
    return PluginProviderRead(
        slug=plugin.slug,
        name=plugin.name or plugin.slug,
        provides=[side for side, cls in (("assets", plugin.provider), ("backups", plugin.target)) if cls is not None],
        # Backup targets are configured per CronJob (Helm values), which the backend can't see yet.
        in_use=["assets"] if plugin.slug == active and plugin.provider is not None else [],
    )


def _ai_sources() -> list[tuple[Any, list[Any]]]:
    """Each AI provider plugin's load report, with the AIProviderPlugin it registered (core's built-ins
    aren't installed packages, so they don't appear)."""
    from marvin.services.ai import registry

    found = registry.plugins()
    return [
        (report, [found[slug] for slug in report.slugs if slug in found and registry.source_of(slug) == report.name])
        for report in registry.load_plugins()
    ]


def ai_provider_workspaces(session: Session) -> dict[str, int]:
    """Provider slug → how many workspaces have AI on and choose it: their AI settings' provider (the
    platform default when unset, in platform mode), or a default provider row in workspace mode."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_providers import AIProviderModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    default = getattr(get_app_settings(), "AI_DEFAULT_PROVIDER", "openai")
    rows = {r.group_id: r.provider_type for r in session.query(AIProviderModel).filter_by(is_default=True, enabled=True)}
    counts: dict[str, int] = {}
    for s in session.query(WorkspaceAISettingsModel).filter_by(enabled=True):
        slug = rows.get(s.group_id) if s.credential_mode == "workspace" and s.group_id in rows else s.provider or default
        counts[slug] = counts.get(slug, 0) + 1
    return counts


def _ai_provider_read(plugin: Any, usage: dict[str, int]) -> PluginProviderRead:
    return PluginProviderRead(
        slug=plugin.slug,
        name=plugin.name or plugin.slug,
        provides=[name for name, on in plugin.provider.capabilities().items() if on],
        workspaces=usage.get(plugin.slug, 0),
    )


def connected_workspaces(session: Session) -> dict[str, int]:
    """Provider slug → how many distinct workspaces have at least one connection to it."""
    rows = session.query(IntegrationModel.provider, sa.func.count(sa.distinct(IntegrationModel.group_id))).group_by(IntegrationModel.provider).all()
    return dict(rows)


def _has_logo(slug: str) -> bool:
    from marvin.services.integrations import logos

    return logos.has_logo(slug)


def _provider_read(provider: Any, usage: dict[str, int]) -> PluginProviderRead:
    # getattr with defaults: a provider built against an older SDK may predate `content`.
    return PluginProviderRead(
        slug=provider.slug,
        name=getattr(provider, "name", "") or provider.slug,
        icon=getattr(provider, "icon", "") or "",
        has_logo=_has_logo(provider.slug),
        actions=len(getattr(provider, "actions", ()) or ()),
        blueprints=len(getattr(provider, "content", ()) or ()),
        workspaces=usage.get(provider.slug, 0),
    )


def installed_plugins(session: Session) -> list[PluginRead]:
    """Every installed plugin package — including ones that failed to load — sorted by name."""
    usage = connected_workspaces(session)
    plugins = [
        PluginRead(
            name=report.name,
            package=report.distribution,
            version=report.version,
            kind=KIND_INTEGRATION,
            ok=report.ok,
            error=report.error,
            providers=[_provider_read(p, usage) for p in providers],
        )
        for report, providers in _integration_sources()
    ]
    active = _active_storage_provider()
    plugins += [
        PluginRead(
            name=report.name,
            package=report.distribution,
            version=report.version,
            kind=KIND_STORAGE,
            ok=report.ok,
            error=report.error,
            providers=[_storage_provider_read(p, active) for p in found],
        )
        for report, found in _storage_sources()
    ]
    ai_usage = ai_provider_workspaces(session)
    plugins += [
        PluginRead(
            name=report.name,
            package=report.distribution,
            version=report.version,
            kind=KIND_AI_PROVIDER,
            ok=report.ok,
            error=report.error,
            providers=[_ai_provider_read(p, ai_usage) for p in found],
        )
        for report, found in _ai_sources()
    ]
    return sorted(plugins, key=lambda p: (p.package or p.name).lower())
