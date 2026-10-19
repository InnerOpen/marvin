"""AI providers as plugins (services/ai/registry.py): core ships none (slice 5, 2026-10-11) — every vendor is an
installed `marvin.ai_providers` plugin (marvin-ai-openai, -anthropic, -google, -ollama), unknown slugs refused, and
everything that reads the registry — the
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
    """Stands in for marvin-ai-ollama: self-hosted, pulls models, a base URL instead of a key."""

    provider_type = "ollama"
    display_name = "Ollama (plugin)"
    credentials = (BASE_URL,)
    self_hosted = True
    supports_model_pull = True
    default_embedding_model = None

    def __init__(self, transport=None, api_key=None, base_url="http://localhost:11434"):
        super().__init__(transport, api_key)
        self._base_url = base_url

    @classmethod
    def from_credentials(cls, values):
        return cls(base_url=values.get("base_url") or "http://localhost:11434")


class PluginAnthropic(FakeAIProvider):
    """Stands in for marvin-ai-anthropic."""

    provider_type = "anthropic"
    display_name = "Anthropic"
    supports_embeddings = False
    default_model = "claude-sonnet-5"
    default_embedding_model = None
    prices = {"claude-sonnet-5": ModelPrice(input_per_1m=2.0, output_per_1m=10.0)}
    suggested_models = ("claude-sonnet-5",)


class PluginGoogle(FakeAIProvider):
    """Stands in for marvin-ai-google."""

    provider_type = "google"
    display_name = "Google Gemini"


OPENAI_PLUGIN = AIProviderPlugin(slug="openai", name="OpenAI (plugin)", provider=PluginOpenAI)
OLLAMA_PLUGIN = AIProviderPlugin(slug="ollama", name="Ollama (plugin)", provider=PluginOllama)
# What the image bakes in besides marvin-ai-openai (which tests add when they need it).
VENDORS = [
    ("anthropic", AIProviderPlugin(slug="anthropic", name="Anthropic", provider=PluginAnthropic), "marvin-ai-anthropic"),
    ("google", AIProviderPlugin(slug="google", name="Google Gemini", provider=PluginGoogle), "marvin-ai-google"),
    ("ollama", OLLAMA_PLUGIN, "marvin-ai-ollama"),
]
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
    """Stand-in `marvin.ai_providers` entry points: the anthropic / google / ollama plugins (stand-ins for the
    marvin-ai-* packages the image bakes in), plus whatever a test adds — never the real ones in the venv. A
    test clears the list for an install with no AI plugin. The registry reloads around the test."""
    real = importlib.metadata.entry_points
    installed: list[_EP] = [_EP(slug, plugin, dist=dist) for slug, plugin, dist in VENDORS]

    def fake(group=None, **kw):
        return list(installed) if group == "marvin.ai_providers" else real(group=group, **kw)

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    registry.reset()
    yield installed
    registry.reset()


def _settings(**update):
    return get_app_settings().model_copy(update=update)


# ── the registry ─────────────────────────────────────────────────────────────


def test_core_ships_no_ai_provider(entry_points):
    """Every vendor is a plugin: with none installed there is no provider at all."""
    entry_points.clear()
    registry.reset()
    assert registry.plugins() == {} and list(registry._builtins()) == []
    assert registry.find_class("anthropic") is None and registry.find_class("openai") is None


def test_the_vendor_plugins_are_plugins_with_their_package(entry_points):
    reports = {r.name: r for r in registry.load_plugins()}

    assert sorted(registry.plugins()) == ["anthropic", "google", "ollama"]
    assert all(reports[s].ok for s in ("anthropic", "google", "ollama"))
    assert registry.plugins()["ollama"].provider is PluginOllama
    assert registry.source_of("ollama") == "ollama" and registry.report_for("ollama").distribution == "marvin-ai-ollama"


def test_the_openai_plugin_adds_openai(entry_points):
    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))

    report = next(r for r in registry.load_plugins() if r.name == "openai")

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


def test_a_plugin_provider_builds_from_its_credentials(entry_points):
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


def test_prices_come_from_the_provider_and_core_keeps_no_table(entry_points):
    from marvin.services.ai import pricing
    from marvin.services.ai.pricing import estimate_cost

    assert not hasattr(pricing, "PRICING")  # every provider ships its own prices
    assert estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000) is None  # no plugin, no price (feed empty here)
    entry_points.append(_EP("openai", OPENAI_PLUGIN))
    registry.reset()
    assert estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000) == 2.0  # the plugin's own price
    assert estimate_cost("openai", "o3", 1_000_000, 1_000_000) is None  # not in the plugin: unpriced
    assert estimate_cost("anthropic", "claude-sonnet-5", 1_000_000, 1_000_000) == 12.0
    assert PluginOllama.self_hosted and estimate_cost("ollama", "llama3", 10, 10) == 0.0


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


def test_provider_types_list_the_installed_plugins(entry_points):
    from marvin.routes.ai.provider_types_controller import provider_types

    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai", version="0.1.0"))
    types = {t.slug: t for t in provider_types()}

    assert sorted(types) == ["anthropic", "google", "ollama", "openai"]
    assert (types["openai"].source, types["openai"].package, types["openai"].version) == ("plugin", "marvin-ai-openai", "0.1.0")
    assert types["openai"].default_model == "gpt-plugin"
    assert [c.key for c in types["openai"].credentials] == ["api_key", "base_url"] and types["openai"].credentials[0].secret
    assert types["anthropic"].source == "plugin" and "tool_calls" in types["anthropic"].capabilities
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

    report, found = next((r, f) for r, f in plugins._ai_sources() if r.distribution == "marvin-ai-openai")
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
    assert "openai (marvin-ai-openai 0.1.0)" in lines and "anthropic (marvin-ai-anthropic 0.1.0)" in lines
    assert "plugin 'broken' failed to load: nope" in lines


def test_an_unset_default_is_the_preferred_installed_provider(entry_points, caplog):
    """AI_DEFAULT_PROVIDER unset (2026-10-10; it used to mean `openai`, which core no longer ships): openai when a
    plugin provides it, else the next of anthropic, google, azure, ollama that is installed."""
    unset = SimpleNamespace(AI_DEFAULT_PROVIDER="", model_fields_set=set())

    assert registry.default_provider(unset) == "anthropic"  # no openai plugin here
    assert "default provider: anthropic (AI_DEFAULT_PROVIDER unset)" in factory.validate_ai_config(unset)

    entry_points.append(_EP("openai", OPENAI_PLUGIN, dist="marvin-ai-openai"))
    registry.reset()
    assert registry.default_provider(unset) == "openai"  # prod and dev set nothing and keep openai
    assert registry.default_provider(SimpleNamespace(AI_DEFAULT_PROVIDER="google")) == "google"


def test_an_explicit_default_nothing_provides_still_stops_startup(entry_points):
    with pytest.raises(AIConfigError):
        factory.validate_ai_config(SimpleNamespace(AI_DEFAULT_PROVIDER="openai", model_fields_set={"AI_DEFAULT_PROVIDER"}))


def test_with_no_provider_installed_startup_only_warns(entry_points, caplog, monkeypatch):
    monkeypatch.setattr(registry, "plugins", lambda: {})
    assert registry.default_provider(SimpleNamespace(AI_DEFAULT_PROVIDER="")) is None
    factory.validate_ai_config(SimpleNamespace(AI_DEFAULT_PROVIDER="", model_fields_set=set()))
    assert "no AI provider is installed" in caplog.text
