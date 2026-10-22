"""Installed plugins, as the platform admin sees them.

A plugin is a Python package the platform operator installs into the image (or a Helm init
container). Marvin discovers it through entry points at startup and offers what it registers to every
workspace, which then connects it under its own Integrations settings. Integration providers
(services/integrations), storage plugins (services/storage/registry.py: asset providers and backup
targets, used platform-wide) and AI providers (services/ai/registry.py: model vendors any workspace can
choose) are pluggable, so the admin keeps a single list of what is installed.
"""

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from marvin.db.models.groups.integrations import IntegrationModel
from marvin.schemas.admin.plugins import PluginProviderRead, PluginRead

logger = logging.getLogger(__name__)

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
        system_playbooks=_system_counts().get(plugin.slug, 0),
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
    from marvin.db.models.groups.ai_providers import AIProviderModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.registry import default_provider

    default = default_provider()
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
        system_playbooks=_system_counts().get(plugin.slug, 0),
        has_logo=_has_ai_logo(plugin.slug),
    )


def connected_workspaces(session: Session) -> dict[str, int]:
    """Provider slug → how many distinct workspaces have at least one connection to it."""
    rows = session.query(IntegrationModel.provider, sa.func.count(sa.distinct(IntegrationModel.group_id))).group_by(IntegrationModel.provider).all()
    return dict(rows)


def _has_ai_logo(slug: str) -> bool:
    from marvin.services.integrations import logos

    return logos.has_ai_logo(slug)


def _has_logo(slug: str) -> bool:
    from marvin.services.integrations import logos

    return logos.has_logo(slug)


def _system_counts() -> dict[str, int]:
    """Owner slug → how many system Playbooks its plugin gives every workspace."""
    from marvin.services.playbooks.system import SOURCE_PLUGIN, system_playbooks

    counts: dict[str, int] = {}
    for p in system_playbooks().values():
        if p.source == SOURCE_PLUGIN:
            counts[p.owner] = counts.get(p.owner, 0) + 1
    return counts


def _provider_read(provider: Any, usage: dict[str, int]) -> PluginProviderRead:
    # getattr with defaults: a provider built against an older SDK may predate `content`.
    return PluginProviderRead(
        slug=provider.slug,
        name=getattr(provider, "name", "") or provider.slug,
        icon=getattr(provider, "icon", "") or "",
        has_logo=_has_logo(provider.slug),
        actions=len(getattr(provider, "actions", ()) or ()),
        blueprints=len(getattr(provider, "content", ()) or ()),
        system_playbooks=_system_counts().get(provider.slug, 0),
        workspaces=usage.get(provider.slug, 0),
    )


def _package_key(package: str | None) -> str:
    return (package or "").lower().replace("_", "-")


def _latest_versions(session: Session) -> dict[str, str]:
    """{package: newer version} from the cached update check — never waits on GitHub (a stale cache is refreshed in the
    background). Empty when the check hasn't run or fails: the list still shows."""
    from marvin.services.plugin_updates import available_updates

    try:
        return {_package_key(u.package): u.latest for u in available_updates(session)}
    except Exception:  # noqa: BLE001 — update notices are a courtesy; they never break the plugin list
        session.rollback()
        logger.debug("plugin update lookup failed", exc_info=True)
        return {}


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
    latest = _latest_versions(session)
    for plugin in plugins:
        plugin.latest_version = latest.get(_package_key(plugin.package))
    return sorted(plugins, key=lambda p: (p.package or p.name).lower())
