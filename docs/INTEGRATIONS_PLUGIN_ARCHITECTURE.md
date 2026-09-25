# Integrations as installable packages — plugin architecture plan

> **Accuracy note (2026-09-25).** Where this document says the core polls providers and dispatches
> `PolledEvent`s, it describes an intent that was never built — nothing calls `poll()`. Scheduled
> provider work runs through the `run_integration_action` scheduled-task handler instead. A provider
> may also declare the workspace content its actions need (`content = (ContentBlueprint(...),)`),
> which core offers on the integration's card for the workspace to apply; see INTEGRATIONS_DESIGN.md.

## Goal

Make integrations **install/uninstall packages**, decoupled from the core codebase, so:

- The core repo/install doesn't grow with every integration.
- Each deployment installs only the integrations it needs (à la carte).
- Integrations version and ship independently — first-party or third-party.
- Adding one needs **zero** core and **zero** frontend changes (the catalog is data-driven).

The Phase-A registry (`INTEGRATION_REGISTRY` + `@register_provider` + the data-driven `/providers`
catalog) is already the plugin API. This plan turns "built into core" into "discovered from whatever
is installed" — and, crucially, tightens the plugin *contract* so plugins don't depend on core at all.

---

## The key improvement: a DB-free, core-free plugin contract

Today `IntegrationContext` hands providers a SQLAlchemy `Session` and the `EventBusService`. But the
two real providers never use them:

- RSS `poll()` **returns** `PolledEvent`s; `check()` fetches a URL. No DB, no bus.
- Vercel `run_action()` POSTs the hook with the secret; `check()` validates it. No DB, no bus.

So the contract can be **pure**: a provider receives only `config`, the resolved `secret`, and a
`logger`, and it **returns** results/events. **Core** owns everything stateful — resolving secrets,
persisting rows, dispatching returned events onto the bus, logging executions.

Why this matters:

- **No coupling to core.** A plugin imports a tiny SDK, not `marvin.*`. It never sees the DB schema,
  so core internals can change without breaking plugins.
- **Security boundary.** A plugin can't touch the database or arbitrary workspace data — it gets one
  secret and one config blob, and returns a value. Blast radius is small.
- **Slim dependency.** The contract package pulls in nothing heavy (no FastAPI, no SQLAlchemy), so a
  "POST a webhook" plugin stays tiny.

### Revised contract (lives in the SDK package)

```python
# marvin_integration_sdk/base.py  — zero heavy deps
@dataclass(frozen=True)
class CredentialField: key: str; label: str; help: str = ""; required: bool = True
@dataclass(frozen=True)
class ProviderEvent:   key: str; label: str; description: str = ""
@dataclass(frozen=True)
class ProviderAction:  key: str; label: str; description: str = ""; input_schema: dict = field(default_factory=dict)

@dataclass
class PolledEvent:     event_key: str; dedup_key: str; message: str = ""; payload: dict = field(default_factory=dict)

@dataclass
class IntegrationContext:            # <-- narrowed: no session, no event_bus
    config: dict
    secret: str | None
    logger: Logger
    http: HttpHelper               # core-supplied: timeouts, retries, SSRF guards (see below)

class IntegrationProvider(ABC):
    slug: str; name: str; description: str = ""; category: str = "destination"
    config_schema: dict = {}
    credentials: tuple[CredentialField, ...] = ()
    emits: tuple[ProviderEvent, ...] = ()
    actions: tuple[ProviderAction, ...] = ()

    def check(self, ctx) -> tuple[str, str | None]: ...          # health
    def run_action(self, key, args, ctx) -> dict: ...            # outbound; returns result
    def poll(self, ctx) -> list[PolledEvent]: return []          # inbound; RETURNS events, core dispatches
    def on_webhook(self, payload, ctx) -> PolledEvent | None: ...  # inbound push
    def info(self) -> dict: ...                                  # catalog projection

INTEGRATION_REGISTRY: dict[str, IntegrationProvider] = {}
def register_provider(cls): INTEGRATION_REGISTRY[cls.slug] = cls(); return cls
```

Core builds the `IntegrationContext` (resolving `secret_ref` → value), calls the provider, and — for
`poll()`/`on_webhook()` — takes the returned `PolledEvent`s and dispatches them on the bus itself.
Providers stay stateless and portable.

### The `http` helper (DECIDED — SDK-provided)

Almost every integration calls an external API, and hand-rolled HTTP is the most common footgun
(no timeout, following redirects into internal hosts, retry storms). So the SDK defines an `HttpHelper`
interface and core supplies the implementation on `ctx.http`:

```python
class HttpHelper(Protocol):
    def get(self, url, *, headers=None, timeout=15) -> Response: ...
    def post(self, url, *, json=None, data=None, headers=None, timeout=15) -> Response: ...
```

Core's implementation enforces sane timeouts, bounded retries, a size cap, and an **SSRF guard**
(block requests to private/link-local ranges unless explicitly allowed). Plugins get safe HTTP for
free and can't easily be turned into a request-forging vector. Plugins *may* still use their own
client, but the ergonomic, blessed path is `ctx.http`.

---

## Package topology

Three layers, three package kinds:

```
marvin-integration-sdk         (NEW, tiny)  the contract: base classes, dataclasses, register.
   ▲                                         Zero heavy deps. Semver'd. Plugins + core depend on it.
   │ depends on
   ├── marvin (core)            discovers installed providers via entry points; owns persistence,
   │                            secret resolution, event dispatch, the API, the UI catalog.
   │
   └── marvin-integration-*     (MANY)  one package per integration (slack, algolia, netlify, …).
       e.g. marvin-integration-slack   Depends only on the SDK + its own libs (e.g. slack_sdk).
```

- **`marvin-integration-sdk`** — the stable contract. Core re-exports it (`from marvin_integration_sdk import ...`)
  so built-ins and plugins use the exact same base.
- **Built-ins (rss, vercel)** — move to depend on the SDK too; ship inside core as the reference
  providers (always present, and they dogfood the contract).
- **Plugins** — separate distributions. Each declares an entry point:

```toml
# marvin-integration-slack/pyproject.toml
[project.entry-points."marvin.integrations"]
slack = "marvin_integration_slack:SlackProvider"

[project.dependencies]
marvin-integration-sdk = ">=1,<2"
slack_sdk = ">=3"
```

**Where the packages live** (DECIDED — separate repo per integration): each integration is its own git
repo and its own published distribution, for maximum decoupling and independent lifecycles. That
includes the two current built-ins: **rss and vercel become the first two standalone plugin repos**
(`marvin-integration-rss`, `marvin-integration-vercel`) — they double as the reference implementations
that dogfood the contract. Core ships with **no** integrations bundled; it can list rss/vercel as
recommended/default installs (via an optional dependency group) so a fresh install isn't empty, but
they're still separate, uninstallable packages. Core stays truly slim.

---

## Discovery & lifecycle (core side)

Replace the hardcoded `providers/__init__.py` import with resilient entry-point discovery, run once at
startup:

```python
def load_providers() -> list[LoadReport]:
    reports = []
    # 1) built-ins (always) — direct import so they exist even if metadata is odd
    import marvin.integrations.builtins  # registers rss, vercel
    # 2) installed plugins via entry points
    for ep in importlib.metadata.entry_points(group="marvin.integrations"):
        try:
            register_provider(ep.load())
            reports.append(LoadReport(ep.name, dist_version(ep), ok=True))
        except Exception as e:                     # a broken plugin must NOT crash startup
            log.warning("integration plugin %s failed to load: %s", ep.name, e)
            reports.append(LoadReport(ep.name, None, ok=False, error=str(e)))
    return reports
```

- **Install:** `uv add marvin-integration-slack` → restart → Slack appears in the catalog. No core/UI change.
- **Uninstall:** `uv remove …` → restart → gone.
- **Resilient:** one bad plugin logs and is skipped; the rest load.

### Install/uninstall = package change + restart (be honest)

Python can't cleanly hot-unload modules, so adding/removing a *provider type* needs a restart — same as
pytest/Airflow. Note the distinction the UI already gives you: **enabling/disabling a configured
connection is fully runtime** (the toggle). Only introducing a brand-new provider type needs a bounce.
(Hot-reload is possible-ish via subprocess isolation later; out of scope for v1.)

### Orphaned connections

If a provider is uninstalled while `integrations` rows still reference its slug, the API must degrade
gracefully instead of 500ing:

- List/read: mark such rows `status = "unavailable"`, surface "Provider 'slug' is not installed."
- Block check/run-action with a clear 409 ("provider not installed").
- The UI shows the card greyed with a "Reinstall the package or delete this integration" note.

This means the controller stops calling `get_provider()` unguarded — it treats "missing provider" as a
first-class state.

---

## New introspection surface

- `GET /api/integrations/plugins` → installed plugin packages: name, version, provider slugs, and load
  status/error. Admin visibility into what's installed and whether anything failed to load.
- `GET /api/integrations/providers` (exists) → usable provider catalog, unchanged.

Frontend: an "Installed plugins" panel in the Integrations admin (list + version + load errors). The
provider catalog and configure form need **no** changes — still schema-driven.

---

## Trust & security (v1 stance)

Installing a package runs its code in-process with backend access. For v1: **trust installed packages**
— installing is a deliberate admin/deploy action (same trust level as any dependency). Document it
plainly. Later options, in order of effort:

1. An allowlist setting (`INTEGRATIONS_ALLOW = ["slack", "algolia"]`) to gate which installed providers
   are permitted to register.
2. Out-of-process execution via **MCP** — Marvin already treats MCP servers as external capability
   providers. Heavy/untrusted/cross-language integrations become MCP servers: separate process, crash-
   isolated, sandboxable, any language. Use the in-process plugin path for lightweight trusted
   providers; MCP for the rest. (This is the natural "second tier" and needs no new concept.)

---

## Authoring experience

- **Template package** `contrib/marvin-integration-template/` — copyable skeleton: `pyproject.toml`
  with the entry point, one `provider.py`, a README, a tiny test. "Create an integration" becomes:
  copy the template, fill in `check`/`run_action` (or `poll`), rename, publish.
- A short **authoring guide**: the contract, the `config_schema` → auto-form mapping, how secrets are
  injected, how `poll()` events become automations, testing locally against a dev Marvin.

---

## Phasing

- **Phase 1 — extract the contract SDK (no behavior change).** Create `marvin-integration-sdk` with the
  base classes/dataclasses/register and the **narrowed** `IntegrationContext` (drop session/event_bus).
  Move rss/vercel onto it; core builds the narrow context; core dispatches `poll()` results. Prove the
  two built-ins still work. This is the load-bearing refactor and de-risks everything.
- **Phase 2 — entry-point discovery + resilience + orphans.** `load_providers()` scans entry points;
  broken plugins are skipped; orphaned connections degrade gracefully; `GET /plugins` introspection +
  the admin "Installed plugins" panel.
- **Phase 3 — the authoring loop.** Publish the SDK; scaffold `marvin-integration-template`; build ONE
  real external plugin (e.g. `marvin-integration-slack` or a trivial `example`) in `contrib/`,
  `uv add` it, and watch it appear in the catalog with zero core changes — the proof.
- **Phase 4 (later, optional).** Allowlist trust control; MCP-backed out-of-process providers; explore
  hot-reload via subprocess isolation.

---

## Decisions

Resolved:

- **Package layout** → **separate repo per integration** (incl. rss/vercel extracted as the first two).
- **Trust model (v1)** → **trust installed packages**; allowlist deferred to Phase 4.
- **SDK context** → include a core-supplied **`http` helper** (timeouts, retries, SSRF guard).

Still open:

1. **SDK package home & name** — `marvin-integration-sdk` (working name) published where? PyPI (public,
   lets third parties build integrations) vs a private index like the npm packages (first-party only for
   now). Recommend **matching wherever the npm SDK/CLI publish** unless you want a public plugin
   ecosystem out of the gate.
