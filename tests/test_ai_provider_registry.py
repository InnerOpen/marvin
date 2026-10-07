"""AI providers as plugins (services/ai/registry.py): core's built-ins, installed `marvin.ai_providers`
plugins replacing them by slug, unknown slugs refused, and everything that reads the registry — the
factory's credential modes, prices, embedding and model defaults, the provider-types list, the admin
Plugins page and the startup check. The fake provider is the SDK's (`marvin_integration_sdk.ai.fake`):
no vendor, no network."""

import importlib.metadata
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from marvin_integration_sdk.ai import API_KEY, BASE_URL, AIConfigError, AIProviderPlugin, Credential, Message, ModelPrice
from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport

from marvin.core.config import get_app_settings
from marvin.services.ai import factory, registry
from marvin.services.ai.providers.ollama import OllamaProvider
from marvin.services.ai.providers.openai import OpenAIProvider


class PluginOpenAI(FakeAIProvider):
    """Stands in for marvin-ai-openai's `openai`: same slug, its own prices and defaults."""

    provider_type = "openai"
    display_name = "OpenAI (plugin)"
    credentials = (API_KEY, BASE_URL)
    prices = {"gpt-4o": ModelPrice(input_per_1m=1.0, output_per_1m=1.0)}
    default_model = "gpt-plugin"
    default_embedding_model = "embed-plugin"

    def __init__(self, transport=None, api_key=None, base_url=None):
        super().__init__(transport, api_key)
        self.base_url = base_url

    @classmethod
    def from_credentials(cls, values):
        return cls(api_key=values.get("api_key"), base_url=values.get("base_url"))


class Mistralish(FakeAIProvider):
    """A vendor core has never heard of, with an option credential."""

    provider_type = "mistralish"
    display_name = "Mistralish"
    credentials = (API_KEY, Credential("region", default="eu"))

    @classmethod
    def from_credentials(cls, values):
        provider = cls(api_key=values.get("api_key"))
        provider.region = values.get("region")
        return provider


OPENAI_PLUGIN = AIProviderPlugin(slug="openai", name="OpenAI (plugin)", provider=PluginOpenAI)
MISTRALISH = AIProviderPlugin(slug="mistralish", name="Mistralish", provider=Mistralish)


class _EP:
    def __init__(self, name, exported, dist="marvin-ai-fake", version="0.1.0"):
        self.name, self._exported = name, exported
        self.dist = SimpleNamespace(name=dist, version=version)

    def load(self):
        if isinstance(self._exported, Exception):
            raise self._exported
        return self._exported


@pytest.fixture
def entry_points(monkeypatch):
    """Stand-in `marvin.ai_providers` entry points (none unless a test adds some, even when a real AI
    plugin is installed in the venv); the registry reloads around the test."""
    real = importlib.metadata.entry_points
    installed: list[_EP] = []

    def fake(group=None, **kw):
        return list(installed) if group == "marvin.ai_providers" else real(group=group, **kw)

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    registry.reset()
    yield installed
    registry.reset()


def _settings(**update):
    return get_app_settings().model_copy(update=update)


# ── the registry ─────────────────────────────────────────────────────────────


def test_core_providers_are_built_in(entry_points):
    assert sorted(registry.plugins()) == ["anthropic", "azure", "google", "ollama", "openai"]
    assert registry.plugins()["openai"].provider is OpenAIProvider
    assert registry.source_of("openai") == registry.CORE
    assert registry.load_plugins() == []  # built-ins are not installed packages
    assert registry.report_for("openai") is None


def test_a_plugin_replaces_the_built_in_with_its_slug(entry_points):
    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))

    [report] = registry.load_plugins()

    assert report.ok and report.slugs == ["openai"]
    assert registry.plugins()["openai"].provider is PluginOpenAI
    assert registry.source_of("openai") == "openai"
    assert registry.report_for("openai").distribution == "marvin-ai-openai"
    assert registry.plugins()["anthropic"].provider.__name__ == "AnthropicProvider"  # the rest stay built in


def test_a_new_vendor_is_added_and_a_callable_entry_point_works(entry_points):
    entry_points.append(_EP("mistralish", lambda: MISTRALISH))

    registry.load_plugins()

    assert registry.provider_class("mistralish") is Mistralish


def test_two_plugins_cant_share_a_slug_and_the_first_stays(entry_points):
    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai"))
    entry_points.append(_EP("openai-fork", OPENAI_PLUGIN, dist="marvin-ai-openai-fork"))

    reports = {r.distribution: r for r in registry.load_plugins()}

    assert reports["marvin-ai-openai"].ok
    assert not reports["marvin-ai-openai-fork"].ok
    assert "already provided by plugin 'openai'" in reports["marvin-ai-openai-fork"].error
    assert registry.source_of("openai") == "openai"


def test_a_broken_plugin_is_reported_not_fatal(entry_points):
    entry_points.append(_EP("broken", ImportError("No module named 'vendor_sdk'")))
    entry_points.append(_EP("wrong", object()))

    reports = {r.name: r for r in registry.load_plugins()}

    assert not reports["broken"].ok and "vendor_sdk" in reports["broken"].error
    assert not reports["wrong"].ok and "AIProviderPlugin" in reports["wrong"].error
    assert "openai" in registry.plugins()


def test_an_unknown_provider_is_refused_naming_what_is_installed(entry_points):
    with pytest.raises(AIConfigError) as err:
        factory.get_ai_provider("other", "key")
    assert "'other'" in str(err.value) and "anthropic, azure, google, ollama, openai" in str(err.value)
    assert isinstance(err.value, ValueError)  # what the factory raised before the registry


# ── building a provider: credentials ─────────────────────────────────────────


def test_get_ai_provider_fills_declared_credentials(entry_points):
    entry_points.append(_EP("mistralish", MISTRALISH))

    provider = factory.get_ai_provider("mistralish", "test-key", metadata={"region": "us"})
    assert (type(provider), provider.api_key, provider.region) == (Mistralish, "test-key", "us")
    assert factory.get_ai_provider("mistralish", "test-key").region == "eu"  # the declared default


def test_built_ins_build_as_they_did(entry_points):
    openai = factory.get_ai_provider("openai", "test-key", "http://localhost:8000/v1")
    assert (openai._api_key, openai._base_url, openai._responses) == ("test-key", "http://localhost:8000/v1", False)
    azure = factory.get_ai_provider("azure", "test-key", "https://x.openai.azure.com", {"api_version": "2025-01-01"})
    assert azure._api_version == "2025-01-01"
    assert factory.get_ai_provider("azure", "test-key", "https://x.openai.azure.com")._api_version == "2024-02-01"
    assert factory.get_ai_provider("ollama")._base_url == "http://localhost:11434"


def test_platform_credentials_read_slug_named_settings(entry_points, monkeypatch):
    monkeypatch.setattr(factory, "get_app_settings", lambda: _settings(OPENAI_API_KEY="platform-key", OPENAI_BASE_URL=None))
    monkeypatch.setenv("AZURE_API_VERSION", "2025-03-01")

    assert factory.platform_credentials("openai") == {"api_key": "platform-key", "base_url": None}
    assert factory.platform_credentials("azure")["api_version"] == "2025-03-01"


class _Session:
    """Just enough of a session for get_workspace_ai_provider: one row per model class."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        row = self.rows.get(model.__name__)
        return SimpleNamespace(filter_by=lambda **kw: SimpleNamespace(first=lambda: row))


def test_platform_mode_uses_the_plugin_that_replaced_the_built_in(entry_points, monkeypatch):
    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai"))
    monkeypatch.setattr(factory, "get_app_settings", lambda: _settings(OPENAI_API_KEY="platform-key", AI_DEFAULT_PROVIDER="openai"))
    settings = SimpleNamespace(enabled=True, credential_mode="platform", provider=None)

    provider = factory.get_workspace_ai_provider(_Session({"WorkspaceAISettingsModel": settings}), uuid.uuid4())

    assert isinstance(provider, PluginOpenAI) and provider.api_key == "platform-key"


def test_workspace_mode_builds_from_the_provider_row(entry_points, monkeypatch):
    entry_points.append(_EP("mistralish", MISTRALISH))
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, group_id: f"value-of-{ref}")
    settings = SimpleNamespace(enabled=True, credential_mode="workspace", provider=None, secret_ref=None)
    row = SimpleNamespace(provider_type="mistralish", secret_ref="mistral-key", base_url=None, metadata_json={"region": "ap"})

    provider = factory.get_workspace_ai_provider(_Session({"WorkspaceAISettingsModel": settings, "AIProviderModel": row}), uuid.uuid4())

    assert (type(provider), provider.api_key, provider.region) == (Mistralish, "value-of-mistral-key", "ap")


def test_a_workspace_on_a_provider_that_is_no_longer_installed_gets_a_clear_error(entry_points):
    settings = SimpleNamespace(enabled=True, credential_mode="workspace", provider="gone", secret_ref=None)

    with pytest.raises(AIConfigError, match="unknown AI provider 'gone'"):
        factory.get_workspace_ai_provider(_Session({"WorkspaceAISettingsModel": settings}), uuid.uuid4())


def test_the_plugin_answers_through_the_factory(entry_points):
    entry_points.append(_EP("openai", OPENAI_PLUGIN))
    provider = factory.get_ai_provider("openai", "test-key")
    provider.transport = ScriptedTransport()
    provider.transport.reply_text("Hello from the plugin.")

    assert provider.complete([Message("user", "hi")], "gpt-4o").content == "Hello from the plugin."


# ── prices, models, embeddings ───────────────────────────────────────────────


def test_prices_come_from_the_provider_then_cores_table(entry_points):
    from marvin.services.ai.pricing import estimate_cost

    assert estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000) == 12.5  # built in: core's table
    entry_points.append(_EP("openai", OPENAI_PLUGIN))
    registry.reset()
    assert estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000) == 2.0  # the plugin's own price
    assert estimate_cost("openai", "o3", 1_000_000, 1_000_000) == 50.0  # not in the plugin: core's fallback
    assert estimate_cost("openai", "gpt-9", 10, 10) is None
    assert OllamaProvider.self_hosted and estimate_cost("ollama", "llama3", 10, 10) == 0.0


def test_a_new_vendor_without_a_price_is_unpriced_not_free(entry_points):
    from marvin.services.ai.pricing import estimate_cost

    entry_points.append(_EP("mistralish", MISTRALISH))
    assert estimate_cost("mistralish", "fake-model", 1_000_000, 0) == 1.0
    assert estimate_cost("mistralish", "large", 10, 10) is None


def test_platform_model_setting_then_the_providers_default(entry_points, monkeypatch):
    entry_points.append(_EP("mistralish", MISTRALISH))
    monkeypatch.setattr(factory, "get_app_settings", lambda: _settings(OPENAI_MODEL="gpt-from-settings", AI_DEFAULT_PROVIDER="openai"))

    assert factory.platform_model() == "gpt-from-settings"
    assert factory.platform_model("mistralish") == "fake-model"
    monkeypatch.setenv("MISTRALISH_MODEL", "mistral-from-env")
    assert factory.platform_model("mistralish") == "mistral-from-env"
    assert factory.platform_model("gone") is None


def test_embedding_model_setting_then_the_providers_default(entry_points):
    from marvin.services.ai.embeddings import default_embedding_model

    assert default_embedding_model("openai") == get_app_settings().OPENAI_EMBEDDING_MODEL
    assert default_embedding_model("anthropic") is None
    entry_points.append(_EP("mistralish", MISTRALISH))
    registry.reset()
    assert default_embedding_model("mistralish") == "fake-embed"


# ── what reads the registry: provider types, validation, admin, startup ─────


def test_provider_types_list_built_ins_and_plugins(entry_points):
    from marvin.routes.ai.provider_types_controller import provider_types

    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))
    types = {t.slug: t for t in provider_types()}

    assert sorted(types) == ["anthropic", "azure", "google", "ollama", "openai"]
    assert (types["openai"].source, types["openai"].package, types["openai"].version) == ("plugin", "marvin-ai-openai", "0.1.0")
    assert types["openai"].default_model == "gpt-plugin"
    assert [c.key for c in types["openai"].credentials] == ["api_key", "base_url"] and types["openai"].credentials[0].secret
    assert types["anthropic"].source == "builtin" and "tool_calls" in types["anthropic"].capabilities
    assert types["ollama"].self_hosted and "model_pull" in types["ollama"].capabilities
    assert "claude-sonnet-5" in types["anthropic"].suggested_models


def test_choosing_a_provider_that_is_not_installed_is_refused(entry_points):
    from marvin.routes.groups.ai_settings_controller import AISettingsController
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    ctrl = SimpleNamespace(
        _require_admin=lambda: None, _allow_workspace_credentials=lambda: True, _settings_row=lambda: SimpleNamespace(provider="openai")
    )
    with pytest.raises(HTTPException) as exc:
        AISettingsController.update_ai_settings(ctrl, WorkspaceAISettingsUpdate(provider="other"))
    assert exc.value.status_code == 422 and "available: anthropic" in exc.value.detail


def test_a_provider_row_of_an_unknown_type_is_refused(entry_points, monkeypatch):
    import marvin.routes.ai.providers_controller as pc
    from marvin.schemas.group.ai_provider import AIProviderCreate

    monkeypatch.setattr(pc, "_require_admin", lambda *a: None)
    ctrl = SimpleNamespace(user=SimpleNamespace(), group_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        pc.AIProvidersController.create_provider(ctrl, AIProviderCreate(name="X", slug="x", provider_type="custom"))
    assert exc.value.status_code == 422 and "'custom'" in exc.value.detail


def test_admin_plugins_list_ai_provider_plugins(entry_points, monkeypatch):
    import marvin.services.plugins as plugins

    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))
    monkeypatch.setattr(plugins, "ai_provider_workspaces", lambda session: {"openai": 3})

    [(report, found)] = plugins._ai_sources()
    read = plugins._ai_provider_read(found[0], {"openai": 3})

    assert (report.distribution, report.version) == ("marvin-ai-openai", "0.1.0")
    assert (read.slug, read.workspaces) == ("openai", 3)
    assert read.provides == ["vision", "structured_output", "embeddings", "tool_calls"]


def test_startup_refuses_an_unknown_default_provider(entry_points):
    with pytest.raises(AIConfigError, match="'gone'"):
        factory.validate_ai_config(_settings(AI_DEFAULT_PROVIDER="gone"))

    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))
    entry_points.append(_EP("broken", ImportError("nope")))
    registry.reset()
    lines = factory.validate_ai_config(_settings(AI_DEFAULT_PROVIDER="openai"))
    assert "openai (marvin-ai-openai 0.1.0)" in lines and "anthropic (built in)" in lines
    assert "plugin 'broken' failed to load: nope" in lines


def test_an_installed_marvin_ai_openai_matches_the_built_ins_it_replaces():
    """With marvin-ai-openai installed (it replaces core's openai and azure), runs are priced as before and
    the providers read the same settings and offer the same capabilities. Skipped when it isn't installed."""
    plugin = pytest.importorskip("marvin_ai_openai")
    from marvin.services.ai.pricing import PRICING
    from marvin.services.ai.providers.azure import AzureOpenAIProvider

    assert plugin.OpenAIProvider.prices == PRICING["openai"]
    assert plugin.AzureOpenAIProvider.prices == PRICING["azure"]
    for theirs, ours in ((plugin.OpenAIProvider, OpenAIProvider), (plugin.AzureOpenAIProvider, AzureOpenAIProvider)):
        assert [(c.env(theirs.provider_type), c.secret, c.default) for c in theirs.credentials] == [
            (c.env(ours.provider_type), c.secret, c.default) for c in ours.credentials
        ]
        assert theirs.capabilities() == ours.capabilities()
        assert (theirs.default_model, theirs.default_embedding_model, theirs.suggested_models) == (
            ours.default_model,
            ours.default_embedding_model,
            ours.suggested_models,
        )
