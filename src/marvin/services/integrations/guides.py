"""How-to guides that integrations ship (SDK 0.9.0 ``IntegrationProvider.guide``): a markdown file in the plugin's
package on setting it up and using it well.

Two readers: the workflow authoring guide gives a connected integration's guide to the agent building a workflow
(services/automation/authoring.py), and the manual search indexes every installed one as a page
``plugins/<provider>.md`` (services/docs.py). The SDK reads the file (size cap, UTF-8, inside the package); a guide
it refuses is simply absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Guide:
    provider: str
    name: str  # the provider's name
    markdown: str
    source: str  # "the Slack plugin 0.4.0", for citing it


@lru_cache(maxsize=64)
def _read(provider) -> str | None:
    from marvin_integration_sdk import load_guide

    return load_guide(provider)


def _source(provider) -> str:
    from .loader import source_of

    found = source_of(provider.slug)
    return f"the {provider.name} plugin {found['version']}" if found and found.get("version") else f"the {provider.name} plugin"


def guide_for(provider_slug: str) -> Guide | None:
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    provider = INTEGRATION_REGISTRY.get(provider_slug)
    if provider is None or not getattr(provider, "guide", ""):
        return None
    markdown = _read(provider)
    return Guide(provider.slug, provider.name, markdown, _source(provider)) if markdown else None


def installed_guides() -> list[Guide]:
    """Every installed provider's guide, by provider slug."""
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    return [g for slug in sorted(INTEGRATION_REGISTRY) if (g := guide_for(slug)) is not None]
