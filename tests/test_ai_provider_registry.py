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


class PluginOllama(FakeAIProvider):
    """A plugin taking over a built-in's slug."""

    provider_type = "ollama"
    display_name = "Ollama (plugin)"


OPENAI_PLUGIN = AIProviderPlugin(slug="openai", name="OpenAI (plugin)", provider=PluginOpenAI)
OLLAMA_PLUGIN = AIProviderPlugin(slug="ollama", name="Ollama (plugin)", provider=PluginOllama)
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
    """OpenAI and Azure OpenAI are the marvin-ai-openai plugin: without it core has neither."""
    assert sorted(registry.plugins()) == ["anthropic", "google", "ollama"]
    assert registry.plugins()["ollama"].provider is OllamaProvider
    assert registry.source_of("ollama") == registry.CORE
    assert registry.load_plugins() == []  # built-ins are not installed packages
    assert registry.report_for("ollama") is None
    assert registry.find_class("openai") is None and registry.find_class("azure") is None


def test_a_plugin_replaces_the_built_in_with_its_slug(entry_points):
    entry_points.append(_EP("ollama", OLLAMA_PLUGIN, dist="marvin-ai-ollama", version="0.1.0"))

    [report] = registry.load_plugins()

    assert report.ok and report.slugs == ["ollama"]
    assert registry.plugins()["ollama"].provider is PluginOllama
    assert registry.source_of("ollama") == "ollama"
    assert registry.report_for("ollama").distribution == "marvin-ai-ollama"
    assert registry.plugins()["anthropic"].provider.__name__ == "AnthropicProvider"  # the rest stay built in


def test_the_openai_plugin_adds_openai(entry_points):
    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))

    [report] = registry.load_plugins()

    assert report.ok and registry.provider_class("openai") is PluginOpenAI
    assert registry.source_of("openai") == "openai"


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
    assert "anthropic" in registry.plugins()


def test_an_unknown_provider_is_refused_naming_what_is_installed(entry_points):
    with pytest.raises(AIConfigError) as err:
        factory.get_ai_provider("other", "key")
    assert "'other'" in str(err.value) and "anthropic, google, ollama" in str(err.value)
    assert isinstance(err.value, ValueError)  # what the factory raised before the registry


# ── building a provider: credentials ─────────────────────────────────────────


def test_get_ai_provider_fills_declared_credentials(entry_points):
    entry_points.append(_EP("mistralish", MISTRALISH))

    provider = factory.get_ai_provider("mistralish", "test-key", metadata={"region": "us"})
    assert (type(provider), provider.api_key, provider.region) == (Mistralish, "test-key", "us")
    assert factory.get_ai_provider("mistralish", "test-key").region == "eu"  # the declared default


def test_built_ins_build_as_they_did(entry_points):
    assert factory.get_ai_provider("ollama")._base_url == "http://localhost:11434"


def test_platform_credentials_read_slug_named_settings(entry_points, monkeypatch):
    entry_points.append(_EP("openai", OPENAI_PLUGIN))
    entry_points.append(_EP("mistralish", MISTRALISH))
    monkeypatch.setattr(factory, "get_app_settings", lambda: _settings(OPENAI_API_KEY="platform-key", OPENAI_BASE_URL=None))
    monkeypatch.setenv("MISTRALISH_REGION", "ap")

    assert factory.platform_credentials("openai") == {"api_key": "platform-key", "base_url": None}
    assert factory.platform_credentials("mistralish")["region"] == "ap"


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

    assert estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000) == 12.5  # no plugin: core's table
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

    assert sorted(types) == ["anthropic", "google", "ollama", "openai"]
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


def test_startup_only_warns_when_the_default_provider_was_never_chosen(entry_points, caplog):
    """AI_DEFAULT_PROVIDER left at its default (`openai`) on an install without the OpenAI plugin: start, say so."""
    default_only = SimpleNamespace(AI_DEFAULT_PROVIDER="openai", model_fields_set=set())

    lines = factory.validate_ai_config(default_only)

    assert "anthropic (built in)" in lines
    assert "platform AI is off until a plugin provides 'openai'" in caplog.text
    with pytest.raises(AIConfigError):  # chosen explicitly: a misconfiguration, as before
        factory.validate_ai_config(SimpleNamespace(AI_DEFAULT_PROVIDER="openai", model_fields_set={"AI_DEFAULT_PROVIDER"}))
