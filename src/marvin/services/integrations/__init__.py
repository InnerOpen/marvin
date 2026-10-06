"""Workspace integrations — credentialed connections to external services.

Integrations are a **plugin-only** feature: core ships no providers. The provider *contract* (base
classes, registry, dataclasses, http interface) lives in the standalone ``marvin_integration_sdk``
package, which core pins as a dependency (it also carries the storage contract). Install a provider
(e.g. ``marvin-integration-slack``) and it registers on startup.

This package always imports cleanly. When the SDK is importable it re-exports the contract, supplies
the core ``http`` helper, discovers providers, and exposes ``INTEGRATIONS_AVAILABLE = True``. The
``False`` branch (only ``INTEGRATIONS_AVAILABLE`` defined) remains for an environment installed
without the pinned dependencies.
"""

import importlib.util

INTEGRATIONS_AVAILABLE: bool = importlib.util.find_spec("marvin_integration_sdk") is not None

__all__ = ["INTEGRATIONS_AVAILABLE"]

if INTEGRATIONS_AVAILABLE:
    from marvin_integration_sdk import (
        INTEGRATION_REGISTRY,
        CredentialField,
        HttpHelper,
        IntegrationContext,
        IntegrationProvider,
        PolledEvent,
        ProviderAction,
        ProviderEvent,
        Response,
        get_provider,
        list_providers,
        register_provider,
    )

    from .capability import CapabilityHandler, integrations_providing
    from .http_client import MarvinHttpHelper, build_http
    from .loader import ProviderLoadReport, load_providers

    # Discover installed-plugin providers once, at import time.
    load_providers()

    def load_reports() -> list["ProviderLoadReport"]:
        """The per-source provider load reports (installed plugins)."""
        return load_providers()

    __all__ += [
        "INTEGRATION_REGISTRY",
        "CredentialField",
        "ProviderEvent",
        "ProviderAction",
        "PolledEvent",
        "IntegrationContext",
        "IntegrationProvider",
        "HttpHelper",
        "Response",
        "register_provider",
        "get_provider",
        "list_providers",
        "MarvinHttpHelper",
        "build_http",
        "ProviderLoadReport",
        "load_providers",
        "load_reports",
        "CapabilityHandler",
        "integrations_providing",
    ]
