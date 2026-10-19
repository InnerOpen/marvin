# Integrations — data model & provider registry (design sketch)

## Mental model

An **Integration** is one *credentialed connection to a named external service*, stored per
workspace. It is not a new subsystem — it is a thin object that plugs a third-party service into
the four primitives Marvin already has:

| Primitive (exists today)                        | What an integration contributes            |
|-------------------------------------------------|--------------------------------------------|
| Secret backends — `resolve_secret(slug, gid)`   | its credentials, via a `secret_ref` slug   |
| Event bus — `EventBusService.dispatch(...)`     | inbound events it emits onto the bus        |
| Automation actions (discriminated `kind` union) | outbound actions it exposes to workflows    |
| Tool registry / MCP projection                  | tools it projects to the agent (optional)   |

The **instance** (below) is user data: "*my* Vercel deploy hook." The **provider** (registry) is
code: "what a Vercel integration *is* — what creds it needs, what it can do." Same split as
`ai_providers` rows vs the provider SDK classes, and `OPERATION_REGISTRY` vs an `ai_executions` row.

---

## 1. Data model

### SQLAlchemy — `IntegrationModel`

One row = one configured connection. Credentials never live here; only a `secret_ref` slug that the
existing secret backend resolves. Mirrors `GroupPreferencesModel` conventions (GUID pk, `group_id`
FK, `auto_init`, `sa.JSON` — never JSONB, per the SQLite/PG portability rule).

```python
# src/marvin/db/models/groups/integrations.py
class IntegrationModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "integrations"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id"), nullable=False, index=True)
    group: Mapped["Groups"] = orm.relationship("Groups", back_populates="integrations")

    provider: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)  # registry key, e.g. "vercel_deploy"
    name: Mapped[str] = mapped_column(sa.String, nullable=False)                  # user label, e.g. "Prod site"
    slug: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)      # stable ref for automations

    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    # Non-secret settings for this instance, shape validated by the provider's config_schema.
    config: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # Slug the secret backend resolves for this instance's credential (token/app-password/etc).
    secret_ref: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    # Health, written by the provider's check(); surfaced in the UI.
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="unconfigured")  # ok|error|unconfigured
    last_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_integration_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None: ...
```

### Pydantic schemas (`_MarvinModel`, camelCase out)

```python
class IntegrationCreate(_MarvinModel):
    provider: str
    name: str
    config: dict = Field(default_factory=dict)
    credential: SecretStr | None = None   # write-only; stored via secret backend, never read back

class IntegrationRead(_MarvinModel):
    id: UUID4
    provider: str
    name: str
    slug: str
    enabled: bool
    config: dict | None = None
    has_credential: bool                  # NOT the value — just whether a secret_ref resolves
    status: str
    last_checked_at: datetime | None = None
    last_error: str | None = None
    # Enriched from the provider so the UI can render the card without a second call:
    capabilities: "IntegrationCapabilities"

class IntegrationUpdate(_MarvinModel):
    name: str | None = None
    enabled: bool | None = None
    config: dict | None = None
    credential: SecretStr | None = None   # present ⇒ rotate the secret
```

**Credential flow:** `credential` comes in on create/update → written with
`get_secret_backend().set(secret_ref, value, group_id)` → the row keeps only `secret_ref`.
Reads resolve lazily at use time via `resolve_secret(secret_ref, group_id)`. Same discipline as
`ai_providers.secret_ref`, so vault/bitwarden/db backends all work unchanged.

---

## 2. Provider registry

Copy of the `OPERATION_REGISTRY` / tool-registry pattern: a dict keyed by provider slug, a
`register_provider` class decorator, `get_provider` / `list_providers`, and an `.info()` for
projection to the frontend and (optionally) MarvinMCP.

```python
# src/marvin/services/integrations/base.py
INTEGRATION_REGISTRY: dict[str, "IntegrationProvider"] = {}

def register_provider(cls):
    INTEGRATION_REGISTRY[cls.slug] = cls()
    return cls

def get_provider(slug: str) -> "IntegrationProvider":
    if slug not in INTEGRATION_REGISTRY:
        raise KeyError(f"integration provider '{slug}' not found. have: {list(INTEGRATION_REGISTRY)}")
    return INTEGRATION_REGISTRY[slug]

def list_providers() -> list["IntegrationProvider"]:
    return list(INTEGRATION_REGISTRY.values())
```

### The capability declaration — what a provider *is*

A provider declares three capability surfaces, each optional. This is the whole point: the provider
is a **manifest**, and the existing engines (event bus, automation, tools) do the work.

```python
@dataclass(frozen=True)
class ProviderEvent:
    """An inbound event this integration can drop on the bus (polled or webhook-pushed)."""
    key: str            # e.g. "rss.item_published"
    label: str
    description: str

@dataclass(frozen=True)
class ProviderAction:
    """An outbound action this integration exposes to automation workflows."""
    key: str            # e.g. "trigger_deploy"  → surfaces as automation kind "integration:<slug>:<key>"
    label: str
    description: str
    input_schema: dict  # JSON schema for the action's args (validated before run)

@dataclass(frozen=True)
class CredentialField:
    """What secret this provider needs (drives the create form + secret_ref storage)."""
    key: str            # "token", "app_password", "api_key"
    label: str
    help: str = ""
    required: bool = True
```

> **Accuracy note (2026-09-25).** This document predates the implementation and has drifted in two
> places. The real contract is `marvin_integration_sdk` — treat that package as the source of truth.
> Specifically: `IntegrationContext` carries `config`, `secret`, `logger` and `http` only (no
> session, no event bus, no ids — a provider must not reach into the database), and **nothing calls
> `poll()`**: there is no provider polling loop. A provider runs on demand (the action endpoint), on
> an event (subscriptions), or on a schedule via the `run_integration_action` scheduled-task handler.

### The provider ABC

```python
@dataclass
class IntegrationContext:
    """Resolved per-call context handed to provider methods (cf. OperationContext / ToolContext)."""
    integration_id: UUID4
    group_id: UUID4
    slug: str
    config: dict
    secret: str | None            # already resolved via resolve_secret(secret_ref, group_id)
    session: Session
    event_bus: "EventBusService"
    logger: Logger

class IntegrationProvider(ABC):
    slug: str                     # registry key, e.g. "vercel_deploy"
    name: str                     # "Vercel Deploy Hook"
    description: str
    category: str                 # "source" | "destination" | "capability" | "notify" — drives UI grouping
    config_schema: dict = {}      # JSON schema for `config`, validated on create/update
    credentials: tuple[CredentialField, ...] = ()
    emits: tuple[ProviderEvent, ...] = ()
    actions: tuple[ProviderAction, ...] = ()
    content: tuple[ContentBlueprint, ...] = ()   # workspace content the actions depend on (see below)
    projects_tools: tuple[str, ...] = ()   # tool-registry slugs this integration lights up (optional)

    # --- lifecycle ---
    def check(self, ctx: IntegrationContext) -> tuple[str, str | None]:
        """Health probe → (status, error). Called on save + on a schedule. Default: assume ok."""
        return ("ok", None)

    # --- outbound: run an action declared in `actions` (called by the automation engine) ---
    def run_action(self, key: str, args: dict, ctx: IntegrationContext) -> dict:
        raise NotImplementedError

    # --- inbound: for polled sources, produce events to dispatch (called by the scheduler) ---
    def poll(self, ctx: IntegrationContext) -> list["PolledEvent"]:
        return []

    # --- inbound: for webhook-pushed sources, translate a raw payload into a bus event ---
    def on_webhook(self, payload: dict, ctx: IntegrationContext) -> "PolledEvent | None":
        return None

    def info(self) -> dict:
        return {
            "slug": self.slug, "name": self.name, "description": self.description,
            "category": self.category, "config_schema": self.config_schema,
            "credentials": [asdict(c) for c in self.credentials],
            "emits": [asdict(e) for e in self.emits],
            "actions": [asdict(a) for a in self.actions],
        }
```

### Declaring the workspace content an integration needs

A provider can never create anything — no session, no repositories. If its actions read or write
entries (the Instagram auto-reply reads keyword rules and writes a reply log), it **declares** the
entry types, collections and scheduled tasks they depend on:

```python
content = (
    ContentBlueprint(
        kind="entry_type",                       # entry_type | collection | scheduled_task
        slug="ig-reply-log",
        name="IG Reply Log",
        description="One entry per DM sent.",
        payload={"name": "IG Reply Log", "schema_json": {...}},
    ),
    ContentBlueprint(
        kind="collection",
        slug="social-sent",
        name="Social — Sent",
        requires=("entry_type:ig-reply-log",),   # applied in dependency order
        payload={"is_smart": True, "smart_rules": {"entry_types": ["ig-reply-log"]}},
    ),
)
```

Core surfaces these as blueprints (`services/blueprints/`), filed under the provider's own category,
and the integration's card lists them as *"what this needs to work"* with an apply button. Rules:

- **Never automatic.** Installing an integration creates nothing; the workspace applies it.
- **Create missing, never overwrite.** A workspace that customised its copy keeps it across provider
  upgrades, and re-applying is a safe no-op.
- **A provider owns its own names** (`ig-reply-log` is Instagram's business). Anything belonging to
  the workspace — which of *their* entry types a rule should track — is asked for via `parameters`,
  never guessed.

### Wiring into the four primitives (no new plumbing)

- **Outbound (automation):** add one action `kind` to the existing discriminated union —
  `IntegrationAction(kind="integration", integration_slug=..., action=..., args={...})`. The
  automation runner resolves the row, builds `IntegrationContext`, calls `provider.run_action(...)`.
  Every provider action is instantly usable in any workflow, zero per-provider automation code.
- **Inbound (event bus):** `poll()` results and `on_webhook()` translations are dispatched with
  `event_bus.dispatch(integration_id=<slug>, group_id=..., event_type=..., ...)` — the
  `integration_id` param already exists. From there they fan out to subscribers exactly like
  incoming-webhook events (see the ingress model). Automations subscribe to
  `integration:<slug>:<event.key>`.
- **Credentials:** `secret_ref` → `resolve_secret`. Nothing new.
- **Tools (optional):** `projects_tools` lets an integration enable tool-registry entries for the
  agent when connected — same projection MarvinMCP already does.

---

## 3. Endpoints (mirror of `/ai/operations` + `/ai/tools`)

```
GET    /api/integrations/providers            # [provider.info()]  — the catalog for the "add" screen
GET    /api/integrations                      # [IntegrationRead]  — this workspace's connections
POST   /api/integrations                      # create (writes secret via backend)
PATCH  /api/integrations/{id}                 # update / rotate credential / toggle
DELETE /api/integrations/{id}                 # remove (+ delete secret_ref)
POST   /api/integrations/{id}/check           # run provider.check(), persist status
POST   /api/integrations/{id}/actions/{key}   # manual test-fire of an action
```

`GET /providers` is the projection endpoint — the Integrations tab renders cards straight from it,
so a new provider appears in the UI with zero frontend changes (same win as operations/tools).

---

## 4. Two-provider MVP (proves the whole shape)

1. **`vercel_deploy` (destination/action)** — `credentials=(token or hook-url,)`,
   `actions=(trigger_deploy,)`. Wire an automation: *on entry published → integration action
   trigger_deploy*. This is the honest version of "custom domains" — rebuild the real site on
   publish.
2. **`rss` (source/event)** — `config={feed_url}`, `emits=(rss.item_published,)`, implemented via
   `poll()` on a schedule. Dispatches bus events an automation turns into draft entries.

One outbound + one inbound exercises `run_action`, `poll`, the event-bus dispatch, secret storage,
health `check`, and the provider→automation and provider→event-bus seams — without building the
long-tail catalog.

## Deliberately out of scope (link, don't duplicate)

Publishing API clients, SMTP profiles, and LDAP/OIDC auth are already first-class. If a unified
"Connections" view is wanted, link to them from the Integrations tab — do not reimplement. Auth is
platform-level, not per-workspace, and stays in admin.
```
