# AI provider plugins — writing a model vendor for Marvin

A model vendor (OpenAI, Anthropic, Google, Ollama…) is a **site-wide plugin**, like an integration
(see INTEGRATIONS_PLUGIN_ARCHITECTURE.md) or a storage plugin. Only a platform admin installs one —
in the container image or through the chart's `plugins.packages`. Every workspace can then choose it
in **Settings → AI**, with the platform's credentials or its own. One package per vendor.

Why: a vendor change (a renamed parameter, a new model, a new price) used to need a Marvin release.
With the vendor in a plugin it is a plugin release.

## The contract

It lives in the plugin SDK, `marvin_integration_sdk.ai` (0.8+), which Marvin core pins as a
dependency. Core re-exports it from `marvin.services.ai.base`, so core code keeps importing from there.

- **`AIProvider`**: implement `complete`, `complete_structured`, `list_models` and `test_connection`
  (which reports, never raises). Add `complete_with_tools`, `embed` and `pull_model` when the matching
  capability flag is on; the defaults raise `NotImplementedError`, and the conformance kit checks that
  the flags tell the truth both ways. `execute_operation` has a default (complete, then parse JSON);
  override it when the vendor has native structured output.
- **Vendor-neutral types**: `Message` (`role`, `content` as text or a list of text and `ImagePart`,
  `tool_calls`, `tool_call_id`), `ToolDefinition`, `ToolCall`, `CompletionOptions` (a limit or a
  temperature only when one is configured — leave the rest to the model), `CompletionResult` (text,
  token usage, tool calls, why it stopped).
- **Capability flags**: `supports_vision`, `supports_structured_output`, `supports_embeddings`,
  `supports_tool_calls`, `supports_model_pull`. Marvin only offers what they say (the agent loop needs
  tool calls; RAG needs embeddings).
- **Credentials** (`Credential`): `api_key` (a secret), `base_url`, or an option such as Azure's
  `api_version`. Build the provider from them in `from_credentials(values)`.
- **Prices** (`prices = {model_id: ModelPrice(...)}`, USD per million tokens) or `self_hosted = True`.
- **Models**: `default_model`, `suggested_models` (the AI settings' picker), `default_embedding_model`.
- **The plugin**: `AIProviderPlugin(slug=..., name=..., provider=...)`, where `slug` is the provider's
  `provider_type`, exported from a `marvin.ai_providers` entry point.

```toml
[project.entry-points."marvin.ai_providers"]
acme = "acme_marvin:plugin"
```

The SDK README has a full example.

## How Marvin picks a provider

`services/ai/registry.py` holds what this platform has:

1. **Core's built-ins**: `openai`, `azure`, `anthropic`, `google`, `ollama`. They stay in core until
   their plugins are installed everywhere, so nothing changes the day a plugin arrives.
2. **Installed plugins**, from the `marvin.ai_providers` entry points (the shared plugin loader,
   `services/plugin_loader.py`). A plugin whose slug matches a built-in **replaces** it: the startup log
   says `AI provider plugin 'openai' replaces core's built-in 'openai'`. Two plugins can't share a
   slug (the first one stays; the other is reported as failed). A plugin that fails to import is
   logged and listed on **Admin → Plugins** as failed, and never stops startup.
3. **Unknown slugs are refused**, naming what is installed. Startup stops when `AI_DEFAULT_PROVIDER`
   names a provider nothing provides (like an unknown `STORAGE_PROVIDER`). AI Settings and the
   Providers config refuse to *choose* one (422). A workspace already set to a provider that has since
   been uninstalled gets a clear error on its next AI call, never a silent switch to another vendor.

Credential modes work as before:

- **platform**: the workspace's provider (else `AI_DEFAULT_PROVIDER`) with the platform's credentials,
  read per declared credential from `<SLUG>_<KEY>` — Marvin's settings first, then the environment
  (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `AZURE_API_VERSION`, `ACME_API_KEY` for a plugin). The model
  is `<SLUG>_MODEL`, else the provider's `default_model`.
- **workspace**: the workspace's default Providers row (key from its secret, `base_url`, options from
  its metadata), else the AI Settings provider + secret.

A missing required credential isn't refused when the provider is built; the vendor's own error says
so on the first call, and **Test connection** reports it.

## Prices

`estimate_cost` asks the provider first (its `prices`, or 0 when `self_hosted`). While the built-ins
are still in core, core's `pricing.py` table is the fallback for a model the provider has no price for.
A model with no price anywhere is shown as "—" (unpriced), never as free. Still to come (the plan's
Pricing section): admin overrides, a daily price feed, and reconciling with what the vendor billed.

## Testing a provider

Never call the vendor in tests. The conformance kit (`marvin_integration_sdk.ai.testing`) runs over a
fake of the vendor's server: implement `FakeTransport` (queue neutral replies — "answer this text",
"call this tool", "list these models", "fail with 401" — answer them in your wire format, and record
the request) and subclass `AIProviderContract`. With an httpx-based vendor SDK the fake is an
`httpx.MockTransport` handed to the client, so the SDK's own encoding and parsing are exercised.
`marvin-ai-openai`'s `tests/fake_server.py` is a worked example.

Marvin's own tests use the SDK's `FakeAIProvider` + `ScriptedTransport`
(`marvin_integration_sdk.ai.fake`): every answer scripted, every request recorded.

## Installing one

```yaml
plugins:
  packages:
    - https://github.com/InnerOpen/marvin-integration-sdk/archive/refs/heads/develop.tar.gz
    - https://github.com/InnerOpen/marvin-ai-openai/archive/refs/heads/main.tar.gz
```

The init container installs the plugin into `/plugins`, which goes on `PYTHONPATH` **ahead of** the
image's site-packages. It runs in the backend image, constrained to the versions the image already
has, and then drops every package the image has: `openai`, `pydantic`, `httpx`, `anyio` and the SDK
come from the image, and only `marvin_ai_openai` stays in `/plugins`. A plugin that needs versions the
image doesn't have fails the install (the rollout stops, old pods keep serving) instead of replacing
Marvin's own.

**Admin → Plugins** lists the package with kind *AI provider*, its capabilities and how many
workspaces use it; `GET /api/ai/provider-types` (what AI Settings reads) lists every provider, built in
or installed, with its source, version, credentials and suggested models.
