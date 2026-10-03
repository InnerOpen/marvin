"""Installed plugins, as the platform admin sees them.

A plugin is a Python package the platform operator installs into the image (or a Helm init
container). Marvin discovers it through entry points at startup and offers what it registers to every
workspace, which then connects it under its own Integrations settings. Integration providers
(services/integrations) are the only pluggable kind today; other kinds, such as AI providers, join
here so the admin keeps a single list of what is installed.
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from marvin.db.models.groups.integrations import IntegrationModel
from marvin.schemas.admin.plugins import PluginProviderRead, PluginRead

KIND_INTEGRATION = "integration"


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


def connected_workspaces(session: Session) -> dict[str, int]:
    """Provider slug → how many distinct workspaces have at least one connection to it."""
    rows = session.query(IntegrationModel.provider, sa.func.count(sa.distinct(IntegrationModel.group_id))).group_by(IntegrationModel.provider).all()
    return dict(rows)


def _provider_read(provider: Any, usage: dict[str, int]) -> PluginProviderRead:
    # getattr with defaults: a provider built against an older SDK may predate `content`.
    return PluginProviderRead(
        slug=provider.slug,
        name=getattr(provider, "name", "") or provider.slug,
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
    return sorted(plugins, key=lambda p: (p.package or p.name).lower())
