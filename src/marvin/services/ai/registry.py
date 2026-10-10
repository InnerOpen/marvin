"""The AI providers this platform has: core's built-ins, plus whatever installed plugins add.

A model vendor is a site-wide plugin (``marvin.ai_providers`` entry points, the contract in
``marvin_integration_sdk.ai``), installed by the platform operator; every workspace can then choose it.
Core ships built-in providers for anthropic, google and ollama; OpenAI and Azure OpenAI come only from the
``marvin-ai-openai`` plugin (the chart installs it by default). An installed plugin with a built-in's slug
**replaces** it. Two plugins can't share a slug (the first one stays). An unknown slug is refused, naming
what is installed — never a silent fallback to another vendor.
"""

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from marvin_integration_sdk.ai import ENTRY_POINT_GROUP, AIConfigError, AIProvider, AIProviderPlugin

from marvin.services.plugin_loader import PluginLoadReport, load_entry_points

# Plain stdlib logging: importing this must not build app settings (same rule as the storage registry).
logger = logging.getLogger(__name__)

CORE = "core"
"""The source of a built-in provider (a plugin's source is its entry-point name)."""

_plugins: dict[str, AIProviderPlugin] = {}
_sources: dict[str, str] = {}
_reports: list[PluginLoadReport] | None = None


def _builtins() -> Iterator[AIProviderPlugin]:
    from .providers.anthropic import AnthropicProvider
    from .providers.google import GoogleProvider
    from .providers.ollama import OllamaProvider

    for cls in (AnthropicProvider, GoogleProvider, OllamaProvider):
        yield AIProviderPlugin(slug=cls.provider_type, name=cls.display_name, provider=cls)


def register(plugin: AIProviderPlugin, source: str) -> None:
    """Add a provider under its slug: a plugin replaces core's built-in of the same slug; any other clash
    is refused."""
    current = _sources.get(plugin.slug)
    if current not in (None, CORE):
        raise ValueError(f"AI provider slug {plugin.slug!r} is already provided by plugin '{current}'")
    if current == CORE:
        logger.info(f"AI provider plugin '{source}' replaces core's built-in '{plugin.slug}'")
    _plugins[plugin.slug] = plugin
    _sources[plugin.slug] = source


def _register_entry_point(ep: Any) -> list[str]:
    exported = ep.load()
    plugin = exported if isinstance(exported, AIProviderPlugin) else exported() if callable(exported) else exported
    if not isinstance(plugin, AIProviderPlugin):
        raise TypeError(f"entry point must export an AIProviderPlugin (or a callable returning one), got {type(plugin).__name__}")
    register(plugin, ep.name)
    return [plugin.slug]


def load_plugins(force: bool = False) -> list[PluginLoadReport]:
    """Register the built-ins and every installed AI provider plugin, once. Returns the plugins' load
    reports (built-ins aren't installed packages, so they have none)."""
    global _reports
    if _reports is not None and not force:
        return _reports
    _plugins.clear()
    _sources.clear()
    for plugin in _builtins():
        register(plugin, CORE)
    _reports = load_entry_points(ENTRY_POINT_GROUP, _register_entry_point, label="AI provider")
    return _reports


def plugins() -> Mapping[str, AIProviderPlugin]:
    load_plugins()
    return dict(_plugins)


# The platform default when AI_DEFAULT_PROVIDER is unset: the first of these that is installed, else the first
# installed provider by name. openai first keeps every install that relied on the old hard-coded default as it was.
DEFAULT_PREFERENCE = ("openai", "anthropic", "google", "azure", "ollama")


def default_provider(app=None) -> str | None:
    """The platform's default provider: AI_DEFAULT_PROVIDER when set (installed or not — startup says so), else
    the preferred installed one, else None (no provider installed). `app`: the settings to read (default: the
    app's)."""
    if app is None:
        from marvin.core.config import get_app_settings

        app = get_app_settings()
    configured = (getattr(app, "AI_DEFAULT_PROVIDER", "") or "").strip()
    if configured:
        return configured
    installed = plugins()
    return next((slug for slug in DEFAULT_PREFERENCE if slug in installed), None) or next(iter(sorted(installed)), None)


def source_of(slug: str) -> str | None:
    load_plugins()
    return _sources.get(slug)


def report_for(slug: str) -> PluginLoadReport | None:
    """The load report of the installed package that provides ``slug`` (None for a built-in)."""
    source = source_of(slug)
    return next((r for r in load_plugins() if r.name == source and slug in r.slugs), None)


def provider_class(slug: str) -> type[AIProvider]:
    """The provider class for ``slug``. Raises ``AIConfigError`` saying what is installed."""
    load_plugins()
    plugin = _plugins.get(slug or "")
    if plugin is None:
        raise AIConfigError(f"unknown AI provider {slug!r}: no installed AI provider plugin provides it (available: {', '.join(sorted(_plugins))})")
    return plugin.provider


def find_class(slug: str | None) -> type[AIProvider] | None:
    """``provider_class`` without the error: None when nothing provides ``slug``."""
    load_plugins()
    plugin = _plugins.get(slug or "")
    return plugin.provider if plugin else None


def reset() -> None:
    """Forget what was loaded, so the next access loads again."""
    global _reports
    _reports = None
    _plugins.clear()
    _sources.clear()
