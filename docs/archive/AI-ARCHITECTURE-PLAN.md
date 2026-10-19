# Marvin AI Platform — Architecture Plan

> **Status:** Phases 1–7 implemented and verified against a live model (text, vision, and RAG
> operations all confirmed end-to-end). Phase 8 (agents) not started.
> **Scope:** Provider-agnostic AI as a first-class Marvin subsystem.

---

## Backlog / Deferred

Consciously parked items, most-actionable first. Details live in the linked sections.

| Item | Why deferred | Revisit when | Section |
|---|---|---|---|
| **AI event types + emission** | §15 describes `ai_operation_executed` / `ai_operation_failed` events, but the execute path emits none — needs `EventTypes` enum values + DB seed rows + emit calls | Wiring webhooks / subscriptions / notifications to AI activity | §15 |
| **Auto-embed-on-publish** | Event-bus trigger not wired (depends on AI event emission above) | RAG answers go stale between reindexes | §17, Phase 7 |
| **Phase 8 — Agents** | Largest/most speculative; not started | A multi-step workflow need appears | §18, Phase 8 |
| **pgvector on Postgres** | JSON + numpy cosine works on both DBs; pgvector adds a dialect fork | A workspace hits ~tens of thousands of embedded chunks and the numpy full-scan slows | §17, Phase 7 |
| **Form-submission AI review** | No submissions UI, and forms may fold into `entry_types` | The forms-vs-`entry_types` direction settles | Phase 5 |
| **`/api/ai/settings` route move** | Legacy `/api/groups/ai-settings` still in use | SDK/UI fully migrated | §12 |
| **Capability check beyond vision** | Only `requires_vision` gated so far | Operations declare further capability needs (e.g. tools) | §7 |

---

## 1. Existing Architecture Review

### What Marvin Already Has (Do Not Duplicate)

| Concern | Existing Location | Reuse |
|---|---|---|
| Credential storage | `workspace_secrets` + pluggable backends | ✅ AI providers reference secrets by slug |
| `{{SLUG}}` interpolation | `services/secrets/resolver.py` → `resolve(value, group_id)` | ✅ Prompt templates use this |
| Workspace-scoped config | `workspace_ai_settings` (just built) | ✅ Policy layer done |
| Role hierarchy | `WorkspaceRole` OWNER > ADMIN > EDITOR > AUTHOR > VIEWER | ✅ Gates AI operations |
| Event bus | `EventBusService` + `EventTypes` enum | ✅ Emit on execution |
| Audit log | `EventLogModel` (group-scoped, indexed) | ✅ AI execution events land here |
| Content objects | Entries, Assets, Resources, Collections, Forms | ✅ Context sources |
| Entry type capabilities | `capabilities_json` on `EntryTypeModel` | ✅ Declare AI operation support |
| Publishing API | `/api/publish/{slug}/*` (read-only, site-client token) | ✅ External consumers invoke AI via SDK |
| SDK patterns | `workspace.entries`, `workspace.assets`, etc. | ✅ Follow for `workspace.ai.*` |

### What Does Not Exist Yet

- AI provider abstraction service
- AI operation registry (named, typed operations)
- Context builder
- Execution log table
- MCP server (package installed but no code)
- Actions system (planned, not built)
- RAG / embeddings

---

## 2. AI as a Workspace Subsystem

AI slots into Marvin as a sibling subsystem:

```
Workspace
├── Entries
├── Assets
├── Resources
├── Forms
├── Collections
├── Publishing
├── Secrets          ← AI providers reference these
├── Variables        ← Prompt templates interpolate these
├── Settings
│   └── AI Settings  ← workspace_ai_settings (done)
└── AI               ← new subsystem
    ├── Providers
    ├── Models
    ├── Operations
    └── Executions
```

**Integration points with existing features:**

- **Entry Types** declare supported operations in `capabilities_json`
- **Entries** are context sources and output targets
- **Assets** support vision operations (alt text, describe, OCR)
- **Resources** support enrichment operations
- **Forms** submit → AI classifies / routes / extracts
- **Variables** inject workspace context into prompts (`{{SITE_NAME}}`, `{{COMPANY_NAME}}`)
- **Secrets** store provider API keys (never stored in AI tables directly)
- **Event bus** receives `ai_operation_executed` / `ai_operation_failed` events
- **Scheduled tasks** can trigger AI operations on a cron
- **MCP** exposes operations to external assistants when built

---

## 3. Secrets Integration

AI providers **never store raw API keys**. They store a `secret_ref` (slug) pointing to a `WorkspaceSecret`. Resolution at call time uses the existing resolver:

```python
# services/secrets/resolver.py — already exists
from marvin.services.secrets.resolver import resolve_secret, resolve

# In AI provider factory — single line, no new code:
api_key = resolve_secret(provider_row.secret_ref, group_id)
```

`resolve_secret(slug, group_id)` calls `get_secret_backend().get(slug, group_id)` internally — handles all backends (database, disk, vault, bitwarden, env) transparently. No need to call `get_secret_backend()` directly from the AI layer.

Example workspace secrets for AI:
```
OPENAI_API_KEY        → sk-proj-...
ANTHROPIC_API_KEY     → sk-ant-...
GEMINI_API_KEY        → AIza...
AZURE_OPENAI_KEY      → abc123...
OLLAMA_TOKEN          → (empty for local)
```

The `secret_ref` value stored in `ai_providers.secret_ref` is just the slug string `"OPENAI_API_KEY"`. The actual key is resolved at inference time and **never logged, never cached in the execution record**.

**Platform-level fallback** (for workspaces using `credential_mode = "platform"`): the factory
reads `AppSettings.{PROVIDER}_API_KEY` / `{PROVIDER}_BASE_URL` by convention. **Today only
`OPENAI_*` fields exist in `AppSettings`, so platform mode is effectively OpenAI-only** —
other providers (Anthropic, Google, Azure, Ollama) require `credential_mode = "workspace"`
until their `AppSettings` fields are added. The provider factory checks
`workspace_ai_settings.credential_mode` first.

---

## 4. Variables Integration

All prompt templates support `{{SLUG}}` interpolation via the **same resolver used by webhooks and email templates**:

```python
from marvin.services.secrets.resolver import resolve, resolve_dict

# Interpolate a prompt template string:
system_prompt = resolve(raw_template, group_id=group_id)

# Interpolate with per-call dynamic context (e.g. entry title, current date):
prompt = resolve(raw_template, group_id=group_id, context={
    "current_date": "2026-07-16",
    "entry_title": entry.title,
})
```

Resolution order (already implemented in `resolver.py`):
1. Per-call `context` dict (lowercase keys — dynamic runtime values)
2. Workspace Secrets (uppercase slugs — `allow_secrets=True` by default)
3. Workspace Variables (uppercase slugs — plain-text config)

Available variable sources during prompt construction:

```
{{SITE_NAME}}          → GroupPreferences.site_title
{{SITE_DESCRIPTION}}   → GroupPreferences.site_description
{{WORKSPACE_NAME}}     → Groups.name
{{CURRENT_DATE}}       → injected at runtime by context builder
{{COMPANY_NAME}}       → WorkspaceVariable "COMPANY_NAME"
{{CONTACT_EMAIL}}      → WorkspaceVariable or GroupPreferences.site_contact_email
{{SITE_LOCALE}}        → GroupPreferences.site_locale
```

Resolution order: WorkspaceSecrets > WorkspaceVariables > GroupPreferences fields > built-in injections. This matches the existing `resolve()` behaviour.

Site-level context (tone, audience, writing style) should be stored in `GroupPreferences.site_metadata_json` under an `ai` key rather than introducing new columns:

```json
{
  "ai": {
    "tone": "professional",
    "audience": "architects",
    "writing_style": "concise",
    "preferred_language": "en-US"
  }
}
```

These become `{{AI_TONE}}`, `{{AI_AUDIENCE}}` etc. after the context builder extracts them, or they are injected into the system prompt directly by the context builder.

---

## 5. Workspace AI Policy (workspace_ai_settings)

Already built. Current fields cover:
- `enabled` / `credential_mode` / `provider` / `model` / `secret_ref`
- `approval_mode` (suggest-only | allow-draft-update | allow-automatic-update)
- `invocation_sources` JSON
- `budget_config` / `logging_config` / `moderation_config`

**Resolution precedence at call time:**
```
Operation override → workspace_ai_settings → platform AppSettings defaults
```

The `workspace_ai_settings` row is the single source of truth for workspace AI policy. No new settings table is needed.

---

## 6. Provider Abstraction

> **Shipped in Phases 1–3 — doc reconciled.** The implementation refined this section:
> `CompletionResult` gained `total_tokens`; the structured path is now `execute_operation()`
> (returns parsed output **plus** usage) rather than `complete_structured()`; `test_connection`
> returns `(bool, message)`. Vision capability moved to the model layer (§7). Reflected below.

```python
# services/ai/providers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str | list  # list for multimodal

@dataclass
class CompletionOptions:
    max_tokens: int | None = None
    temperature: float = 0.7
    top_p: float = 1.0

@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    raw: dict  # full provider response

class AIProvider(ABC):
    slug: str
    display_name: str
    # Vision is a MODEL property (see §7) and lives on ai_models rows.
    # The provider declares only what it cannot know per-model:
    supports_structured_output: bool = False  # native json_schema / tool_use available

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        model: str,
        options: CompletionOptions,
    ) -> CompletionResult: ...

    @abstractmethod
    def execute_operation(
        self,
        messages: list[Message],
        model: str,
        output_schema: dict,
        options: CompletionOptions,
    ) -> tuple[dict, CompletionResult]: ...
    # Returns (parsed_output, result_with_usage). Replaces the earlier
    # complete_structured(), which returned a bare dict and dropped token usage —
    # a cost-tracking blind spot. Providers with native structured output override
    # this; the base class falls back to complete() + JSON parse.

    @abstractmethod
    def list_models(self) -> list[str]: ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]: ...  # (success, message)
```

**Concrete providers:**

```python
# services/ai/providers/openai_provider.py
class OpenAIProvider(AIProvider):
    slug = "openai"
    supports_structured_output = True  # via response_format

# services/ai/providers/anthropic_provider.py
class AnthropicProvider(AIProvider):
    slug = "anthropic"
    supports_structured_output = True  # via tool_use

# services/ai/providers/ollama_provider.py
class OllamaProvider(AIProvider):
    slug = "ollama"
    # base_url from provider config (e.g. http://localhost:11434)

# services/ai/providers/google_provider.py
class GoogleProvider(AIProvider):
    slug = "google"

# services/ai/providers/azure_provider.py
class AzureOpenAIProvider(AIProvider):
    slug = "azure"
    # base_url and api_version from provider config
```

**Provider factory** — same pattern as `get_secret_backend()` and `get_storage_provider()`:

```
services/ai/
├── base.py              # AIProvider ABC + Message / CompletionResult dataclasses
├── factory.py           # get_ai_provider() — mirrors get_secret_backend()
└── providers/
    ├── openai.py
    ├── anthropic.py
    ├── google.py
    ├── azure.py
    └── ollama.py
```

```python
# services/ai/factory.py

def get_ai_provider(
    provider_type: str,
    api_key: str,
    base_url: str | None = None,
) -> AIProvider:
    """
    Return a configured AIProvider — mirrors get_secret_backend() / get_storage_provider().
    Lazy imports keep unused provider SDKs out of the import graph.
    """
    if provider_type == "openai":
        from .providers.openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key)

    if provider_type == "anthropic":
        from .providers.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=api_key)

    if provider_type == "google":
        from .providers.google import GoogleProvider
        return GoogleProvider(api_key=api_key)

    if provider_type == "azure":
        from .providers.azure import AzureOpenAIProvider
        return AzureOpenAIProvider(api_key=api_key, base_url=base_url)

    if provider_type == "ollama":
        from .providers.ollama import OllamaProvider
        return OllamaProvider(base_url=base_url or "http://localhost:11434")

    raise ValueError(f"Unknown AI provider type: {provider_type}")


def get_workspace_ai_provider(session: Session, group_id: UUID) -> AIProvider:
    """
    Resolve the active provider for a workspace, honouring credential_mode.
    Calls get_ai_provider() after resolving credentials from Secrets.
    """
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.secrets.resolver import resolve_secret

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()

    if not settings or not settings.enabled:
        raise AIDisabledError(f"AI is disabled for workspace {group_id}")

    if settings.credential_mode == "platform":
        app = get_app_settings()
        provider_type = settings.provider or app.AI_DEFAULT_PROVIDER
        api_key = getattr(app, f"{provider_type.upper()}_API_KEY", None)
        return get_ai_provider(provider_type, api_key)

    if settings.credential_mode == "workspace":
        provider_row = (
            session.query(AIProviderModel)
            .filter_by(group_id=group_id, is_default=True, enabled=True)
            .first()
        )
        if not provider_row:
            raise AIConfigError("No default provider configured for this workspace")
        api_key = resolve_secret(provider_row.secret_ref, group_id)
        return get_ai_provider(provider_row.provider_type, api_key, provider_row.base_url)

    raise AIDisabledError("No valid credential mode configured")
```

### Provider Isolation & Optional SDKs

**Import boundary.** A module under `providers/` may import only `..base` and its own
provider SDK — **nothing else from `marvin`**. This one-line rule gives the entire benefit
of a "provider-agnostic core" (the reason one might reach for a separate `marvin-ai-core`
package) with none of the packaging cost. Enforced by review + grep, not by a package split.

**Optional dependencies.** Provider SDKs ship as extras — `marvin[openai]`,
`marvin[anthropic]`, `marvin[google]`, `marvin[all-ai]`. The lazy imports in `get_ai_provider()`
already assume this: installing Marvin never imports `openai` unless a workspace selects it,
and a missing SDK raises a clean ImportError with an install hint.

---

## 7. Model Abstraction

Models are configured per-provider. Each `ai_providers` row has an associated set of `ai_models` rows.

**Selection hierarchy:**
1. Operation-level override (`operation.model_requirements.preferred_model`)
2. Workspace default (`workspace_ai_settings.model`)
3. Provider default model (`ai_models.is_default = True` for this provider)

Models expose capability flags: `supports_vision`, `supports_tools`, `context_window`,
`max_output_tokens`.

**Capability source of truth = `ai_models` rows.** Capability is a *model* property, not a
provider one (`gpt-4o` has vision, `o1-mini` does not — both are `openai`). The provider
class declares only `supports_structured_output` (whether native structured output exists
at all). Operations declare requirements (`requires_vision`, etc.); before calling, the
executor validates `required ⊆ available` against the selected model row and returns a clear
422 on mismatch. **(Implemented in `routes/ai/operations_controller.py` via
`_validate_model_capabilities()`; currently gates `requires_vision`, extend to further
capability flags as operations declare them. When no `ai_models` row exists for the model —
platform mode or an ad-hoc override — the check cannot assert incompatibility and allows the
call through.)**

Well-known model slugs (display only, not validated server-side):
`gpt-4o`, `gpt-4.1`, `claude-sonnet-5`, `claude-opus-4-8`, `gemini-1.5-pro`, `llama3.2`, `mistral-large`

---

## 8. AI Operations Architecture

Operations are **named, typed, system-defined capabilities** — not arbitrary prompts.

### Operation Registry

```python
# services/ai/operations/registry.py

OPERATION_REGISTRY: dict[str, type[AIOperation]] = {}

def register_operation(slug: str):
    def decorator(cls):
        OPERATION_REGISTRY[slug] = cls
        return cls
    return decorator

def get_operation(slug: str) -> AIOperation:
    if slug not in OPERATION_REGISTRY:
        raise OperationNotFoundError(slug)
    return OPERATION_REGISTRY[slug]()
```

### Base Operation

```python
class AIOperation(ABC):
    slug: str
    name: str
    description: str
    input_schema: dict        # JSON Schema
    output_schema: dict       # JSON Schema — structured output preferred
    min_role: WorkspaceRole = WorkspaceRole.AUTHOR
    supports_entity_types: list[str] = []  # "entry" | "asset" | "resource" | "form_submission"
    requires_vision: bool = False

    @abstractmethod
    def build_context(self, entity, ctx: ContextBuilder) -> OperationContext: ...

    @abstractmethod
    def build_prompt(self, input: dict, context: OperationContext) -> list[Message]: ...

    def validate_input(self, input: dict) -> dict:
        # jsonschema validate against self.input_schema
        ...

    def validate_output(self, output: dict) -> dict:
        # jsonschema validate against self.output_schema
        ...
```

### System Operations (Phase 1)

| slug | Entity Types | Output |
|---|---|---|
| `generate-summary` | entry, resource | `{summary: str, word_count: int}` |
| `generate-tags` | entry, resource, asset | `{tags: [str]}` |
| `rewrite-entry` | entry | `{title: str, body: str, changes: [str]}` |
| `improve-writing` | entry | `{improved: str, suggestions: [str]}` |
| `generate-alt-text` | asset (image) | `{alt_text: str, description: str}` |
| `describe-image` | asset (image) | `{description: str, detected_objects: [str], colors: [str]}` |
| `generate-entry` | entry_type → entry | `{title: str, data: {}}` |
| `review-entry` | entry | `{score: int, issues: [str], suggestions: [str]}` |
| `extract-metadata` | entry, resource | `{metadata: {}}` |
| `classify-form-submission` | form_submission | `{category: str, confidence: float, tags: [str]}` |
| `summarize-form-submission` | form_submission | `{summary: str, sentiment: str, action_required: bool}` |
| `detect-spam` | form_submission | `{is_spam: bool, confidence: float, reasons: [str]}` |
| `generate-description` | resource, asset | `{description: str}` |
| `enrich-resource-metadata` | resource | `{metadata: {}}` |
| `answer-workspace-question` | — (context: workspace) | `{answer: str, sources: [str]}` |

### Entry Type Integration

Entry Types declare supported operations in `capabilities_json`:

```json
{
  "publishable": true,
  "submittable": false,
  "routable": true,
  "ai_operations": ["generate-summary", "generate-tags", "improve-writing", "review-entry"]
}
```

This avoids a junction table and keeps entry type capabilities co-located.

---

## 9. Prompt Architecture

### Prompt Template Structure

Each operation owns its prompt template in code (Phase 1). Templates are multi-part:

```python
SYSTEM_PROMPT = """
You are an AI assistant for {workspace_name}.
Tone: {ai_tone}
Audience: {ai_audience}
Language: {site_locale}
Today's date: {current_date}
""".strip()

USER_PROMPT = """
Operation: Summarize the following entry.

Entry Title: {entry_title}
Entry Type: {entry_type}
Content:
{entry_content}

{related_entries_section}

Return a JSON object matching this schema:
{output_schema}
""".strip()
```

### Variable Resolution

Before prompt construction, `ContextBuilder.build()` produces an `OperationContext` containing resolved values. The prompt builder substitutes them using the existing `resolve()` service rather than raw string formatting — this handles secrets/variable priority and redaction.

### Structured Output

All operations that return structured data use provider-native structured output mechanisms:
- **OpenAI**: `response_format: { type: "json_schema", json_schema: {...} }`
- **Anthropic**: tool_use with a single `structured_output` tool
- **Ollama**: `format: "json"` + schema in prompt
- **Fallback**: parse JSON from text response with retry on parse failure

---

## 10. Context Builder

```python
# services/ai/context.py

class ContextBuilder:
    def __init__(self, session: Session, group_id: UUID):
        self._session = session
        self._group_id = group_id
        self._parts: list[ContextPart] = []

    def with_entry(self, entry_id: UUID) -> ContextBuilder:
        # loads entry + entry_type schema, structures as ContextPart
        ...

    def with_related_entries(self, entry_id: UUID, limit: int = 5) -> ContextBuilder:
        # loads entries in same collections as entry_id
        ...

    def with_assets(self, entry_id: UUID) -> ContextBuilder:
        # loads entry_assets, includes mime_type and filename
        ...

    def with_resources(self, entry_id: UUID) -> ContextBuilder:
        # loads entry_resources with resource metadata
        ...

    def with_collection(self, collection_id: UUID) -> ContextBuilder:
        # loads collection + up to N entries
        ...

    def with_form_submission(self, submission_id: UUID) -> ContextBuilder:
        ...

    def with_site_settings(self) -> ContextBuilder:
        # loads GroupPreferences (site_title, site_description, site_metadata_json.ai)
        ...

    def with_variables(self, slugs: list[str] | None = None) -> ContextBuilder:
        # loads WorkspaceVariables (optionally filtered)
        ...

    def with_workspace_info(self) -> ContextBuilder:
        # loads Groups.name, slug
        ...

    def inject(self, key: str, value: str) -> ContextBuilder:
        # runtime injections: current_date, current_user, etc.
        ...

    def build(self) -> OperationContext:
        # resolves all parts, returns structured OperationContext
        ...

@dataclass
class OperationContext:
    workspace_name: str
    site_title: str | None
    site_description: str | None
    ai_tone: str | None
    ai_audience: str | None
    site_locale: str
    current_date: str
    variables: dict[str, str]
    entry: EntryContext | None
    related_entries: list[EntryContext]
    assets: list[AssetContext]
    resources: list[ResourceContext]
    form_submission: FormSubmissionContext | None
    raw_parts: list[ContextPart]  # for custom serialisation
```

**Key principle:** Context is assembled as structured Python objects, not concatenated strings. Each operation controls how it formats context into messages. This allows operations to be selective (a tag generator doesn't need all related entries; a review operation does).

---

## 11. SDK Design

> **Shipped as `platform.ai.*` (Phase 4).** The plan originally named this `workspace.ai.*`,
> but AI endpoints are session/role-authed and reachable only through the session-authed
> `PlatformClient` — not the site-token publish `Workspace`. So the module lives on
> `PlatformClient` alongside `platform.secrets` / `platform/admin`. Naming reconciled below.

```ts
// platform.ai.*

const platform = createPlatformClient();  // session-authed (user token / cookies)

// ── Settings ──────────────────────────────────────────────────────────
platform.ai.settings.get()                     // GET /api/groups/ai-settings  (see note)
platform.ai.settings.update(patch)             // PATCH /api/groups/ai-settings

// ── Providers ─────────────────────────────────────────────────────────
platform.ai.providers.list()                   // GET /api/ai/providers
platform.ai.providers.get(id)                  // GET /api/ai/providers/{id}
platform.ai.providers.create(data)             // POST /api/ai/providers
platform.ai.providers.update(id, patch)        // PATCH /api/ai/providers/{id}
platform.ai.providers.delete(id)               // DELETE /api/ai/providers/{id}
platform.ai.providers.test(id)                 // POST /api/ai/providers/{id}/test

// ── Models (nested under a provider) ──────────────────────────────────
platform.ai.providers.models.list(providerId)
platform.ai.providers.models.create(providerId, data)
platform.ai.providers.models.update(providerId, modelId, patch)
platform.ai.providers.models.delete(providerId, modelId)

// ── Operations ────────────────────────────────────────────────────────
platform.ai.operations.list()                  // GET /api/ai/operations
platform.ai.operations.get(slug)               // GET /api/ai/operations/{slug}
platform.ai.operations.execute(slug, {         // POST /api/ai/operations/{slug}/execute
  entityType: 'entry',
  entityId: '...',
  input: { ... },
  modelOverride: 'gpt-4o',  // optional; NOT options.model
})  // → returns a COMPLETED AIExecution (runs synchronously)

// ── Executions ────────────────────────────────────────────────────────
platform.ai.executions.list(params?)           // GET /api/ai/executions
platform.ai.executions.get(id)                 // GET /api/ai/executions/{id}
platform.ai.executions.delete(id)              // DELETE /api/ai/executions/{id}
```

**Deviations from the original plan, reconciled to the shipped backend:**
- **Settings** target `/api/groups/ai-settings` — the `/api/ai/settings` path (§12) is not built.
- **No `ai.usage` module** — `GET /api/ai/usage` (§12/§16) is not implemented.
- **Execute** takes a flat `modelOverride` (not a nested `options.model`) and returns a
  *completed* execution, not a `pending` one — the call runs synchronously.
- **`operations.list/get`** return raw **snake_case** dicts (`input_schema`, `min_role`,
  `requires_vision`, …); every other AI response is camelCase.

Type definitions follow existing SDK conventions — response types are camelCase (backend
`_MarvinModel` uses `alias_generator=camelize` + `populate_by_name=True`), and `executions.list`
query params are snake_case (query params bypass the alias generator).

---

## 12. REST API Design

All routes under `/api/ai/` (workspace-scoped, session auth):

```
# Policy
GET    /api/ai/settings
PATCH  /api/ai/settings

# Providers
GET    /api/ai/providers
POST   /api/ai/providers
GET    /api/ai/providers/{id}
PATCH  /api/ai/providers/{id}
DELETE /api/ai/providers/{id}
POST   /api/ai/providers/{id}/test

# Models (nested under provider)
GET    /api/ai/providers/{id}/models
POST   /api/ai/providers/{id}/models
PATCH  /api/ai/providers/{id}/models/{model_id}
DELETE /api/ai/providers/{id}/models/{model_id}

# Operations (read-only, system-defined)
GET    /api/ai/operations
GET    /api/ai/operations/{slug}

# Execution
POST   /api/ai/operations/{slug}/execute
  Request:  { entity_type, entity_id, input, options? }
  Response: AIExecution (initial, status=pending)

# Executions
GET    /api/ai/executions?operation_slug=&status=&entity_id=&limit=&offset=
GET    /api/ai/executions/{id}
DELETE /api/ai/executions/{id}

# Usage summary (admin)
GET    /api/ai/usage?period=month&year=2026&month=7
```

**Migration note:** `/api/groups/ai-settings` (currently live) should eventually redirect to `/api/ai/settings`. Leave it in place until the SDK is updated.

---

## 13. Database Schema

### New Tables

```sql
-- ai_providers
-- One row per provider configuration per workspace
CREATE TABLE ai_providers (
    id          CHAR(32) PRIMARY KEY,
    group_id    CHAR(32) NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        VARCHAR NOT NULL,
    slug        VARCHAR NOT NULL,
    provider_type VARCHAR NOT NULL,  -- openai|anthropic|google|azure|ollama|custom
    secret_ref  VARCHAR,             -- slug of a WorkspaceSecret (API key)
    base_url    VARCHAR,             -- for Ollama, Azure, custom endpoints
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json JSON,              -- provider-specific extras (api_version, org_id, etc.)
    created_at  DATETIME,
    update_at   DATETIME,
    UNIQUE(group_id, slug)
);

-- ai_models
-- Models available under a provider
CREATE TABLE ai_models (
    id              CHAR(32) PRIMARY KEY,
    provider_id     CHAR(32) NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
    group_id        CHAR(32) NOT NULL,  -- denormalised for easy workspace queries
    name            VARCHAR NOT NULL,
    model_id        VARCHAR NOT NULL,   -- actual API identifier (e.g. "gpt-4o")
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    context_window  INTEGER,
    max_output_tokens INTEGER,
    supports_vision BOOLEAN NOT NULL DEFAULT FALSE,
    supports_tools  BOOLEAN NOT NULL DEFAULT FALSE,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      DATETIME,
    update_at       DATETIME,
    UNIQUE(provider_id, model_id)
);

-- ai_executions
-- Immutable audit log of every AI call
CREATE TABLE ai_executions (
    id              CHAR(32) PRIMARY KEY,
    group_id        CHAR(32) NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    operation_slug  VARCHAR NOT NULL,
    provider_type   VARCHAR NOT NULL,
    model_id        VARCHAR NOT NULL,
    status          VARCHAR NOT NULL DEFAULT 'pending',
                    -- pending|running|completed|failed|cancelled
    triggered_by    CHAR(32),           -- user_id, nullable for scheduled/system
    trigger_type    VARCHAR NOT NULL,   -- api|action|scheduler|mcp|renderer
    entity_type     VARCHAR,            -- entry|asset|resource|form_submission|null
    entity_id       CHAR(32),
    input_json      JSON,               -- stored only if logging_config.log_inputs
    output_json     JSON,               -- stored only if logging_config.log_outputs
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    total_tokens    INTEGER,
    estimated_cost_usd DECIMAL(10, 8),
    duration_ms     INTEGER,
    error_message   VARCHAR,
    metadata_json   JSON,
    started_at      DATETIME,
    completed_at    DATETIME,
    created_at      DATETIME,
    update_at       DATETIME
);
CREATE INDEX ix_ai_executions_group_id ON ai_executions(group_id);
CREATE INDEX ix_ai_executions_group_status ON ai_executions(group_id, status);
CREATE INDEX ix_ai_executions_entity ON ai_executions(entity_type, entity_id);
CREATE INDEX ix_ai_executions_created ON ai_executions(group_id, created_at DESC);
```

### Existing Tables (No Change)

- `workspace_ai_settings` — workspace policy (done)
- `workspace_secrets` — provider API keys (reused)
- `workspace_variables` — prompt context (reused)
- `group_preferences` — site context injected into prompts (reused, add `metadata_json.ai`)

### Entry Type Capabilities (Extend, No New Table)

Add AI operation support to `capabilities_json` on `entry_types`:
```json
{
  "publishable": true,
  "submittable": false,
  "routable": true,
  "ai_operations": ["generate-summary", "generate-tags", "improve-writing"]
}
```

No new junction table needed for Phase 1.

---

## 14. Permission Model

### Workspace Role Gates

| Role | Can Do |
|---|---|
| VIEWER (1) | Read execution history only |
| AUTHOR (2) | Execute AI operations (output = suggestions only) |
| EDITOR (3) | Execute AI + apply drafts (if approval_mode allows) |
| ADMIN (4) | Configure providers, models, settings; delete executions |
| OWNER (5) | All above + override budget limits |

### Approval Mode Enforcement

`workspace_ai_settings.approval_mode` controls what the execute endpoint does with output:

- **`suggest-only`** — operation returns output as a suggestion payload. Nothing is written. The caller (frontend, SDK, Action) decides what to do. Safe for all roles.
- **`allow-draft-update`** — operation may write output to a draft entry. Requires EDITOR+. Published entries are never touched.
- **`allow-automatic-update`** — operation may write output without human review. Requires ADMIN+ AND explicit operation flag `allows_automatic = True`. Only appropriate for low-risk operations (tag generation, metadata enrichment).

Each operation also declares its own `min_role`. The effective gate is `max(operation.min_role, approval_mode_required_role)`.

### API Key (Site Client) Access

Site clients (publishing API tokens) cannot invoke AI operations. AI is a platform capability, not a publishing capability. External consumers use MCP or the platform SDK (session auth).

---

## 15. Execution Logging

Every `POST /api/ai/operations/{slug}/execute` creates an `ai_executions` row immediately with `status=pending`. This ensures every call is traceable even if it fails.

Lifecycle:
```
pending → running → completed
                 ↘ failed
                 ↘ cancelled (if workspace AI disabled mid-flight)
```

Logging policy from `workspace_ai_settings.logging_config`:

| Field | Default | Effect |
|---|---|---|
| `log_inputs` | `false` | Store `input_json` in execution row |
| `log_outputs` | `false` | Store `output_json` in execution row |
| `retention_days` | `90` | Scheduled task prunes rows older than N days |
| `redact_patterns` | `[]` | Regex list applied to input/output before storage |

**What is NEVER logged regardless of settings:**
- Resolved secret values (API keys)
- Raw provider credentials
- Any value from `workspace_secrets`

AI executions also emit an event to the existing event bus (`ai_operation_executed` or `ai_operation_failed`) which lands in `EventLogModel`. The event payload includes operation slug, entity type/id, status, and token usage — no content.

---

## 16. Cost Tracking

Token usage is returned by every provider response and stored in `ai_executions` (`prompt_tokens`, `completion_tokens`, `total_tokens`).

**Estimated cost** is calculated at write time using a hardcoded price table maintained in code:

```python
PROVIDER_PRICING: dict[str, dict[str, ModelPricing]] = {
    "openai": {
        "gpt-4o": ModelPricing(input_per_1m=2.50, output_per_1m=10.00),
        "gpt-4.1": ModelPricing(input_per_1m=2.00, output_per_1m=8.00),
        ...
    },
    "anthropic": {
        "claude-sonnet-5": ModelPricing(input_per_1m=3.00, output_per_1m=15.00),
        ...
    },
}
```

This is approximate and updated with SDK/server upgrades. It is NOT real-time. Cost stored as `estimated_cost_usd DECIMAL(10, 8)`.

**Monthly budget enforcement** from `workspace_ai_settings.budget_config`:

```json
{
  "max_tokens_per_request": 4096,
  "max_requests_per_day": 500,
  "max_cost_per_month_usd": 50.00
}
```

The execute endpoint checks against a rolling aggregate query on `ai_executions` before calling the provider. If over budget, return `429 Too Many Requests` with budget details in the response.

**Usage summary endpoint** (`GET /api/ai/usage`) aggregates by operation, provider, and entity type for a given period — useful for workspace admins.

---

## 17. Future RAG Architecture

Design only. Do not implement until Phase 7.

### Embedding Storage

```sql
-- ai_embeddings (Phase 7)
CREATE TABLE ai_embeddings (
    id          CHAR(32) PRIMARY KEY,
    group_id    CHAR(32) NOT NULL,
    entity_type VARCHAR NOT NULL,  -- entry|resource|asset
    entity_id   CHAR(32) NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_text  TEXT NOT NULL,
    embedding   JSON NOT NULL,     -- float array; pgvector column on PostgreSQL
    model_id    VARCHAR NOT NULL,  -- embedding model used
    dimensions  INTEGER NOT NULL,
    created_at  DATETIME,
    UNIQUE(entity_type, entity_id, chunk_index, model_id)
);
```

On PostgreSQL: use `pgvector` extension, `embedding vector(1536)` column, `ivfflat` index. On SQLite: store as JSON float array, compute cosine similarity in Python (acceptable for small workspaces).

### Embedding Triggers

Entries and resources trigger embedding generation on publish via event bus:
`entry_published` → `embed_entry_operation` (background scheduled task) → chunks text → calls embedding endpoint → stores in `ai_embeddings`.

### Context Builder Integration

```python
ctx.with_semantic_search(query="user's question", limit=5, entity_types=["entry", "resource"])
# ↑ queries ai_embeddings for nearest chunks, adds to context
```

### RAG Operation

`answer-workspace-question` operation becomes RAG-powered:
1. Embed user query
2. Find top-K similar chunks
3. Build context with those chunks + source metadata
4. Generate answer with citations

---

## 18. Future Agent Architecture

Design only. Do not implement until Phase 8.

### Agent as Workflow

```
AgentDefinition:
  name, slug, description
  trigger: EventType | CronSchedule | APICall
  steps: [
    { type: "ai_operation", slug: "classify-form-submission", input_mapping: {...} },
    { type: "condition", field: "output.category", operator: "eq", value: "inquiry" },
    { type: "ai_operation", slug: "generate-summary", ... },
    { type: "webhook", ... },
    { type: "human_approval", timeout_hours: 24 },
    { type: "entry_update", field_mappings: {...} },
  ]
```

Each AI step in an agent creates an `ai_executions` row with `trigger_type = "agent"`. Agent state is tracked separately in an `agent_executions` table. Human approval steps integrate with the existing notification system.

### MCP Integration

When the MCP server is built, it exposes AI operations as tools:

```
Tool: marvin_execute_operation
  Parameters: { operation_slug, entity_type, entity_id, input }
  Returns: AIExecution result

Tool: marvin_list_operations
  Returns: list of available operations with schemas
```

The MCP server calls the same `/api/ai/operations/{slug}/execute` endpoint using a platform-level API key. All executions are tracked with `trigger_type = "mcp"`.

---

## 19. Migration Strategy

### Phase 1 — Foundation (done)
- [x] `ai_providers` + `ai_models` tables + migrations
- [x] Provider abstraction service (`services/ai/providers/`)
- [x] Provider factory (resolves from `workspace_ai_settings`)
- [x] `ai_providers` API routes (`/api/ai/providers/*`) — full CRUD + `/test` + nested models
- [x] Migrate `/api/groups/ai-settings` → kept alive, move to `/api/ai/settings` deferred
- [x] Provider SDKs declared as optional extras (`marvin[openai|anthropic|google|ollama|all-ai]`)

### Phase 2 — Operations + Execution
- [ ] Operation registry (`services/ai/operations/`)
- [ ] System operations (5–8 initial: summary, tags, alt-text, improve-writing, classify-form)
- [ ] `ai_executions` table + migration
- [ ] Execute endpoint (`POST /api/ai/operations/{slug}/execute`)
- [ ] Execution history endpoint

### Phase 3 — Context + Prompts
- [ ] `ContextBuilder` service
- [ ] Variable interpolation in prompts
- [ ] Site AI context from `GroupPreferences.site_metadata_json.ai`
- [ ] Entry type `capabilities_json.ai_operations` declaration
- [ ] Cost estimation and budget enforcement

### Phase 4 — SDK (done)
- [x] `platform.ai.*` SDK module (settings, providers+models, operations, executions) — shipped in MarvinSDK `src/platform/ai/`
- [x] Typed request/response types (hand-written camelCase in `src/platform/ai/types.ts`)
- [x] Publishing API remains AI-free (AI lives on session-authed `PlatformClient`, not the publish `Workspace`)

### Phase 5 — Frontend Integration
- [x] Editor toolbar AI buttons (respect `invocation_sources.editor`) — "Generate summary" on the entry editor
- [x] Asset detail AI panel — "Generate alt text" on image assets
- [ ] Form submission AI review panel — **skipped for now.** No submissions UI exists, and forms
      may fold into `entry_types` ("Form" type / renderer-core) rather than a standalone feature.
      Revisit once that direction settles; classify/summarize/detect-spam ops already exist backend-side.
- [x] Execution history UI — `/workspace/settings/ai-executions`

All shipped surfaces gate on workspace AI enabled + auth (+ `invocationSources` where relevant).

### Phase 6 — Asset + Resource Operations (done)
- [x] Vision operations — `ImagePart` multimodal content; every provider translates it to its
      SDK shape; `generate-alt-text` (now truly multimodal) + `describe-image`. Gated by the §7
      capability check; image bytes loaded from storage via `ContextBuilder.with_asset_images()`.
- [x] Resource enrichment operations — `enrich-resource-metadata` (+ `with_resource` loader)
- [x] Fixed a latent Phase 3 bug: `ContextBuilder` referenced non-existent model classes and
      queried association tables incorrectly — the entire execute path was broken until now.

### Phase 7 — RAG (done, SQLite-compatible)
- [~] pgvector on PostgreSQL — **deferred**; embeddings stored as `sa.JSON()` float arrays with
      cosine in Python (numpy). Works on SQLite + Postgres; migrate to pgvector only if scale demands.
- [x] Embedding pipeline — provider `embed()` (OpenAI/Azure/Google/Ollama), `index_entity`
      (chunk→embed→upsert into `ai_embeddings`), `POST /api/ai/embeddings/reindex` (EDITOR+)
- [x] Semantic search context source — `ContextBuilder.with_semantic_search` (cosine top-k → `OperationContext.retrieved`)
- [x] `answer-workspace-question` as RAG operation — `requires_retrieval`; answers from retrieved chunks with [n] citations
- [x] Scheduled RAG reindex — `ai_reindex_embeddings` scheduled-task handler (workspace or all-workspaces; emits `ai_embeddings_reindexed`)
- [ ] Auto-embed-on-publish (event-bus trigger) — not yet wired; reindex is manual + scheduled for now

### Phase 8 — Agents (future)
- [ ] Agent definition model
- [ ] Step executor
- [ ] Human approval workflow
- [ ] MCP tool exposure

---

## 20. Architectural Improvements

Observations from the architecture review that apply beyond AI:

1. **`/api/groups/*` vs `/api/platform/*` naming** is confusing. Groups = workspaces. Consider a deprecation path to `GET /api/workspace/secrets`, `/api/workspace/variables` etc. AI uses the opportunity to start clean with `/api/ai/*`.

2. **`workspace_ai_settings.credential_mode = "disabled"` is redundant** with `enabled = false`. Already removed from the UI. Remove from the schema in a future migration.

3. **Entry type `capabilities_json`** already exists but is not strongly typed. Define a `WorkspaceCapabilitiesSchema` Pydantic model to validate it at write time — prevents silent capability flag typos.

4. **Operations as system entry types analogy** — system entry types use `group_id=NULL, is_system=True`. AI operations follow the same pattern if they become DB rows: workspace-level customisation inherits from system defaults.

5. **Budget enforcement via scheduled tasks** — the existing `ScheduledTasksRepository` can host a daily usage aggregation job without new infrastructure.

6. **Provider test endpoint** (`POST /api/ai/providers/{id}/test`) is the equivalent of the existing secrets `reveal` endpoint — it validates a connection without exposing the key.

7. **Renderers stay independent** — renderer packages call `workspace.ai.operations.execute()` from the SDK. No AI logic lives in renderer packages. The renderer simply knows which operation slug to invoke and what to do with the suggestion output.

### Rejected Alternatives

8. **Rejected: separate provider packages.** Splitting into `marvin-ai-core` +
   `marvin-ai-{openai,anthropic,…}` uv packages was considered and rejected. The AI
   subsystem is defined by its coupling to Entries/Assets/Secrets/Variables/roles (§2), so
   a standalone "core" is not extractable without dragging half the app with it. Lazy imports
   (§6) + optional extras already deliver optional dependencies; separate packages add N
   pyproject files, cross-package version pins, and build targets for no hobby-scale gain.

9. **Rejected: entry-point / plugin discovery.** Entry points solve registering providers you
   *can't edit the registry for* — a third-party ecosystem. Every provider here is
   first-party, so the greppable switch-factory (§6) is strictly simpler and easier to debug.

10. **Rejected: building on LangChain.** LangChain's value (a unified provider interface) is
    exactly the thin layer §6 owns; adopting it as "just another provider" would be a fat
    adapter that contradicts the thin-adapter rule and adds transitive deps. Kept only as a
    theoretical last-resort adapter for a provider with no usable official SDK — not planned.

---

## Summary

| Layer | Status | Built On |
|---|---|---|
| Workspace AI policy | ✅ Done | `workspace_ai_settings` |
| Provider storage | 🔲 Phase 1 | `ai_providers` + Secrets |
| Model storage | 🔲 Phase 1 | `ai_models` |
| Provider abstraction | 🔲 Phase 1 | New `services/ai/` |
| Operation registry | 🔲 Phase 2 | New, system-defined |
| Execution log | 🔲 Phase 2 | `ai_executions` |
| Context builder | 🔲 Phase 3 | Existing Entries/Assets/Variables |
| Budget enforcement | 🔲 Phase 3 | `workspace_ai_settings.budget_config` |
| SDK | 🔲 Phase 4 | Existing SDK patterns |
| Frontend | 🔲 Phase 5 | Existing component patterns |
| RAG | 🔲 Phase 7 | pgvector + embedding pipeline |
| Agents | 🔲 Phase 8 | Event bus + human approval |
