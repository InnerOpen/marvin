"""
AI provider factory — mirrors get_secret_backend() / get_storage_provider().

get_ai_provider()              — instantiate a provider from type + credentials
get_workspace_ai_provider()   — resolve the active provider for a workspace
platform_model()              — the platform's default model for a provider (platform credential mode)

Which class a type means comes from the registry (registry.py): core's built-ins, or the installed
plugin that replaced one. Each provider declares the credentials it needs; this module fills them.
"""

from typing import Any

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.services.plugin_loader import settings_source

from . import registry
from .base import AIConfigError, AIProvider

__all__ = ["AIConfigError", "AIDisabledError", "get_ai_provider", "get_workspace_ai_provider", "platform_credentials", "platform_model"]


class AIDisabledError(Exception):
    """Raised when AI is disabled for a workspace or not configured."""


def build_provider(provider_type: str, values: dict[str, Any]) -> AIProvider:
    """The provider for ``provider_type``, built from credential ``values`` (keyed by credential key).

    Declared defaults fill the gaps. A missing required credential is not refused here: the vendor's
    own error says so on the first call (and the provider's connection test reports it).
    """
    from marvin_integration_sdk.ai import read_credentials

    cls = registry.provider_class(provider_type)
    return cls.from_credentials(read_credentials(cls.credentials, values, require=False))


def get_ai_provider(
    provider_type: str,
    api_key: str | None = None,
    base_url: str | None = None,
    metadata: dict | None = None,
) -> AIProvider:
    """A configured provider: ``api_key`` and ``base_url`` as given, any other credential (Azure's
    ``api_version``) from ``metadata``. Raises ``AIConfigError`` for a type nothing provides."""
    return build_provider(provider_type, {**(metadata or {}), "api_key": api_key, "base_url": base_url})


def platform_credentials(provider_type: str) -> dict[str, Any]:
    """The platform's credentials for a provider: each declared credential from ``<SLUG>_<KEY>``
    (``OPENAI_API_KEY``, ``AZURE_API_VERSION``), Marvin's settings first, then the environment."""
    cls = registry.provider_class(provider_type)
    source = settings_source(get_app_settings())
    return {c.key: source.get(c.env(provider_type)) for c in cls.credentials}


def platform_model(provider_type: str | None = None) -> str | None:
    """The platform's default model for a provider (``AI_DEFAULT_PROVIDER`` when none is given):
    ``<SLUG>_MODEL`` (``OPENAI_MODEL``), else the provider's own default."""
    app = get_app_settings()
    provider_type = provider_type or getattr(app, "AI_DEFAULT_PROVIDER", "openai")
    configured = settings_source(app).get(f"{provider_type}_MODEL".upper().replace("-", "_"))
    if configured:
        return configured
    cls = registry.find_class(provider_type)
    return cls.default_model if cls else None


def get_workspace_ai_provider(session: Session, group_id: UUID4) -> AIProvider:
    """
    Resolve the active provider for a workspace, honouring credential_mode.

    Resolution order (from workspace_ai_settings):
      platform  → AppSettings credentials
      workspace → active ai_providers row, key resolved via resolve_secret()
    """
    from marvin.db.models.groups.ai_providers import AIProviderModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.secrets.resolver import resolve_secret

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()

    if not settings or not settings.enabled:
        raise AIDisabledError(f"AI is disabled for workspace {group_id}")

    if settings.credential_mode == "platform":
        provider_type = settings.provider or getattr(get_app_settings(), "AI_DEFAULT_PROVIDER", "openai")
        return build_provider(provider_type, platform_credentials(provider_type))

    if settings.credential_mode == "workspace":
        # Preferred: a full Providers row (supports base_url, api_version, multiple providers).
        provider_row = session.query(AIProviderModel).filter_by(group_id=group_id, is_default=True, enabled=True).first()
        if provider_row:
            api_key = resolve_secret(provider_row.secret_ref, group_id) if provider_row.secret_ref else None
            return get_ai_provider(
                provider_row.provider_type,
                api_key,
                provider_row.base_url,
                provider_row.metadata_json,
            )

        # Fallback: build from the simple AI Settings fields when no Providers row exists.
        # Covers key-only providers (OpenAI/Anthropic/Google); Ollama/Azure still need a
        # Providers row for base_url / api_version.
        if not settings.provider:
            raise AIConfigError(
                "No AI provider configured for this workspace. Set a provider and API-key "
                "secret in AI Settings, or add a provider under the Providers config."
            )
        api_key = resolve_secret(settings.secret_ref, group_id) if settings.secret_ref else None
        return get_ai_provider(settings.provider, api_key)

    raise AIDisabledError("No valid credential mode configured")


def validate_ai_config(app=None) -> list[str]:
    """Startup: load the AI provider plugins and check that ``AI_DEFAULT_PROVIDER`` names an installed
    provider. Raises ``AIConfigError`` otherwise (every platform-mode workspace would fail). Returns one
    line per provider for the startup log."""
    app = app or get_app_settings()
    reports = registry.load_plugins()
    registry.provider_class(getattr(app, "AI_DEFAULT_PROVIDER", "openai") or "openai")
    lines = []
    for slug in sorted(registry.plugins()):
        report = registry.report_for(slug)
        lines.append(f"{slug} ({'built in' if report is None else f'{report.distribution} {report.version}'})")
    lines += [f"plugin '{r.name}' failed to load: {r.error}" for r in reports if not r.ok]
    return lines
