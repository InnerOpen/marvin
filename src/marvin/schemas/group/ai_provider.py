"""Pydantic schemas for AI providers and models."""

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel

# ── Models ─────────────────────────────────────────────────────────────────


class AIModelCreate(_MarvinModel):
    name: str
    model_id: str
    is_default: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_vision: bool = False
    supports_tools: bool = False
    enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


class AIModelUpdate(_MarvinModel):
    name: str | None = None
    model_id: str | None = None
    is_default: bool | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_vision: bool | None = None
    supports_tools: bool | None = None
    enabled: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class AIModelRead(AIModelCreate):
    id: UUID4
    provider_id: UUID4
    group_id: UUID4

    model_config = ConfigDict(from_attributes=True)


# ── Providers ───────────────────────────────────────────────────────────────


class AIProviderCreate(_MarvinModel):
    name: str
    slug: str
    provider_type: str
    """An installed AI provider's slug (GET /api/ai/provider-types): openai, anthropic, google, azure, ollama, or a plugin's."""
    secret_ref: str | None = None
    base_url: str | None = None
    enabled: bool = True
    is_default: bool = False
    metadata_json: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class AIProviderUpdate(_MarvinModel):
    name: str | None = None
    slug: str | None = None
    provider_type: str | None = None
    secret_ref: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    metadata_json: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class AIProviderRead(AIProviderCreate):
    id: UUID4
    group_id: UUID4
    models: list[AIModelRead] = []

    model_config = ConfigDict(from_attributes=True)


class AIProviderTestResult(_MarvinModel):
    success: bool
    message: str
    available_models: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class InstalledModels(_MarvinModel):
    """The models actually present in the workspace's active provider (e.g. Ollama's /api/tags)."""

    provider_type: str
    supports_pull: bool = False
    models: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class ModelPullRequest(_MarvinModel):
    name: str  # e.g. "qwen3-coder" or "nomic-embed-text"

    model_config = ConfigDict(from_attributes=True)


class ModelPullStatus(_MarvinModel):
    """Progress of a background model pull. Poll until `done`."""

    id: str
    name: str
    status: str  # pulling | success | error
    detail: str = ""  # latest provider status line
    completed: int = 0
    total: int = 0
    percent: int = 0
    error: str | None = None
    done: bool = False

    model_config = ConfigDict(from_attributes=True)


# ── Provider types (the registry: built-ins + installed plugins) ───────────


class AICredentialRead(_MarvinModel):
    """One credential a provider type needs. ``api_key`` comes from a secret; ``base_url`` and any option
    (``api_version``) from the provider row (options in its metadata)."""

    key: str
    label: str = ""
    secret: bool = False
    required: bool = False
    default: str | None = None
    help: str = ""


class AIProviderTypeRead(_MarvinModel):
    """An AI provider this platform can use: built into core, or an installed plugin."""

    slug: str
    name: str
    description: str = ""
    source: str
    """"builtin" (core) or "plugin" (an installed ``marvin.ai_providers`` package)."""
    package: str | None = None
    version: str | None = None
    capabilities: list[str] = []
    """What it can do: "vision", "structured_output", "embeddings", "tool_calls", "model_pull"."""
    credentials: list[AICredentialRead] = []
    default_model: str | None = None
    suggested_models: list[str] = []
    """Models the AI settings' picker offers; any other id the vendor accepts still works."""
    self_hosted: bool = False
