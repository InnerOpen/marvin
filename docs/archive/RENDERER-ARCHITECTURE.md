# Renderer Architecture for Marvin

**Status**: Implemented (Phases 1–6 complete)
**Created**: 2026-07-12
**Author**: Claude (architectural review)
**Last Updated**: 2026-07-12

---

## Part 1: Architectural Review of the Current State

### What exists today

Marvin has seven core objects: Workspace (Group), Site (GroupPreferences), Collection, Entry, EntryType, Asset, and Resource. Forms exist as a separate eighth table.

Entry Types define content structure via `schema_json`, which stores an `EntryTypeSchemaDefinition` — a list of typed field definitions (text, textarea, markdown, number, boolean, select, date, datetime, json). The content validator enforces this schema against `entries.data_json` at write time.

The Publishing API serves entries as JSON. The `entry_type` field is exposed as a bare slug string (`"page"`, `"article"`, `"project"`). No rendering hints, presentation metadata, or component directives are attached.

External sites receive structured data and are entirely responsible for deciding how to render it. There is no mechanism — in the backend, SDK, or CLI — that connects an entry type to a frontend component, template, or rendering strategy.

### What this means

Marvin is a well-designed headless CMS with a clean data model. The gap is that as entry types diversify (embeds, forms, products, events, navigation items), every consuming frontend must independently solve the same problem: "given an entry of type X, which component renders it?" There is no shared vocabulary for this mapping, no way to validate that a frontend can actually render all entry types in a workspace, and no mechanism for distributing reusable rendering implementations.

### Forms as a case study

Forms are currently a separate database table (`forms`) with their own `schema_json`, `settings_json`, `status`, `submissions_count`, and their own API surface. This is the pattern that should not proliferate. A Form is conceptually an Entry with a specific entry type that happens to have:
- A schema defining form fields
- A renderer that displays an interactive form
- A capability: submittable (accepts POST data)
- Configuration: CAPTCHA, rate limits, notifications

If the renderer architecture works, Forms should eventually collapse into Entry Types with `renderer: "form"` and `capabilities: { submittable: true }`, with submission handling moving to a generic endpoint keyed on entry type capabilities rather than a dedicated `/forms` route.

---

## Part 2: Critical Evaluation of the Proposed Ideas

### 1. Should renderers be defined on Entry Types?

**Yes.** This is the correct level of abstraction. Renderers describe *how a category of content behaves on the frontend*, which is exactly what Entry Types model. An individual Entry should not override its renderer — that would create inconsistency within a type. The Entry Type says "all FAQs render as collapsible accordions"; individual FAQ entries just provide the Q&A data.

**One nuance**: the renderer should be optional. Many entry types (especially custom workspace-specific ones) may not need a renderer declaration — the frontend handles them with a generic/default component. Only entry types that require specialized rendering behavior need to declare one.

### 2. Should renderer packages be distributed through npm?

**Yes, but not exclusively.** npm is the right distribution mechanism for JavaScript/TypeScript frontend ecosystems. However, renderer packages should be *optional* — a frontend can always implement renderers locally without installing a package. The package system provides convenience and reuse, not enforcement.

**Avoid**: making npm the only way to provide a renderer. The package reference on an Entry Type should be informational metadata ("this entry type expects the `@inneropen/marvin-renderers-core` package"), not a hard runtime dependency managed by Marvin itself.

### 3. Should renderers use Web Components internally?

**No, not as the primary strategy.** Web Components provide framework independence in theory, but in practice:
- Shadow DOM creates styling isolation problems that fight against site-level design systems
- Server-side rendering (SSR) support is weak — Astro, Next.js, and SvelteKit all SSR natively but Web Components require hydration workarounds
- Slot-based composition is limited compared to framework-native patterns
- Developer experience is poor compared to framework-native components — no JSX, no reactive primitives, manual lifecycle management

**Better alternative**: Renderer packages should export *framework-native components* (Astro, React, Vue, Svelte) with a shared core logic layer (plain TypeScript/JavaScript) that handles data transformation, validation, and non-UI concerns. This is the pattern used by Radix (React), Melt UI (Svelte), and Headless UI (React/Vue) — shared logic, framework-native rendering.

### 4. Should framework adapters exist?

**Yes, but as separate entry points within a package, not as a wrapper layer.** A renderer package like `@inneropen/marvin-renderers-core` could export:

```
@inneropen/marvin-renderers-core/astro
@inneropen/marvin-renderers-core/react
@inneropen/marvin-renderers-core/logic   (framework-agnostic data layer)
```

This avoids the "universal component" trap while still sharing the non-rendering logic. Start with Astro only (your current frontend), add React when there is a real consumer.

### 5. Should the SDK expose renderer requirements?

**Yes, but keep the API surface small.** The SDK should expose entry type metadata (which it already does — `MarvinEntryType` includes `schemaJson`). Adding `renderer`, `rendererConfig`, and `capabilities` to the entry type response is sufficient. A dedicated `renderers.required()` method is premature — it's a convenience that can be built from `entryTypes.list()` on the consumer side.

**Recommended**: Extend the existing `MarvinEntryType` interface rather than creating a new `renderers` namespace.

### 6. Should the CLI manage renderer installation?

**Not yet.** `marvin renderers sync` that inspects a workspace and installs npm packages crosses a boundary — it makes Marvin a package manager, which is complex and fragile. Better to start with:
- `marvin renderers list` — show which renderers the workspace requires (read-only)
- `marvin renderers validate` — check if a local project has the required packages installed

`sync` (auto-installing packages) can come later if `validate` proves insufficient. Let the developer run `npm install` themselves — it's one command and they control it.

### 7. Should builds validate renderer availability?

**Yes.** This is high-value and low-cost. A build-time check that says "your workspace uses entry type `shopify-product` which requires renderer `shopify-product`, but no renderer is registered for it" prevents silent failures in production. This belongs in a framework integration package (e.g., `@inneropen/marvin-astro`), not in the core SDK.

### 8. Should Entry Types describe capabilities?

**Yes, but start very small.** Capabilities should describe what an entry can *do*, not how it *looks* (that's the renderer's job). Proposed initial set:

| Capability | Type | Default | Meaning |
|---|---|---|---|
| `publishable` | boolean | `true` | Can transition through the publishing workflow |
| `submittable` | boolean | `false` | Accepts external data submission (forms) |
| `routable` | boolean | `true` | Has its own URL path on the frontend |

**Omit for now**:
- `previewable` — this is a frontend/build concern, not a content model concern
- `searchable` — this is a search index concern, better handled by search configuration
- `versionable` — premature; versioning is a much larger feature

Three capabilities is enough to differentiate pages, forms, navigation items, and embeds. Add more when there is a concrete use case.

### 9. Should Entries ever override renderers?

**Almost never.** An Entry overriding its type's renderer is like a database row overriding its table's schema — it creates inconsistency and breaks assumptions. However, there is one legitimate case: **renderer configuration overrides**. An Entry Type might set `rendererConfig: { sandbox: true }`, but a specific trusted embed entry might override `sandbox: false`. This should be modeled as a shallow merge of Entry-level config into Entry Type-level config, not as a renderer replacement.

**Recommendation**: Allow `rendererConfig` overrides on entries (via `metadata_json` or a new field), but never allow `renderer` overrides.

### 10. Is there a cleaner architecture?

The proposed architecture is sound. The main refinement is **keeping renderer metadata purely declarative on the backend** and **keeping all component implementation in frontend packages**. The backend should never know or care what a renderer *does* — it only stores what renderer an entry type *wants*.

One simplification: rather than separate `renderer`, `rendererPackage`, and `rendererVersion` fields, consider a single `rendering` JSON object on the Entry Type:

```json
{
  "rendering": {
    "renderer": "form",
    "package": "@inneropen/marvin-renderers-core",
    "version": "^1.0.0",
    "config": {
      "showLabels": true,
      "submitButton": "Send"
    }
  }
}
```

This groups related concerns, is extensible without schema migrations, and follows the same JSONB pattern as `schema_json`.

---

## Part 3: Proposed Renderer Architecture

### 3.1 Backend: Entry Type Model Additions

Add two JSONB columns to `entry_types`:

```python
class EntryTypes(SqlAlchemyBase, BaseMixins):
    # ... existing fields ...

    rendering_json: Mapped[dict | None] = mapped_column(
        "rendering_json", JSONB, nullable=True
    )
    """Renderer declaration: renderer name, package, version, config."""

    capabilities_json: Mapped[dict | None] = mapped_column(
        "capabilities_json", JSONB, nullable=True
    )
    """Behavioral capabilities: publishable, submittable, routable."""
```

**Why JSONB, not separate columns**: These are structured metadata that will evolve. JSONB avoids migrations when adding new renderer config keys or new capabilities. It follows the established pattern of `schema_json` and `settings_json`.

**Schema definitions** (Pydantic):

```python
class RenderingDefinition(_MarvinModel):
    renderer: str | None = None
    """Renderer identifier (e.g., 'page', 'form', 'external-embed')."""

    package: str | None = None
    """npm package that provides this renderer."""

    version: str | None = None
    """Semver range for the required package version."""

    config: dict | None = None
    """Renderer-specific configuration."""


class CapabilitiesDefinition(_MarvinModel):
    publishable: bool = True
    submittable: bool = False
    routable: bool = True
```

### 3.2 Publishing API Additions

Extend `PublishedEntryRead` and `PublishedEntryListItem` to include entry type metadata:

```python
class PublishedEntryTypeInfo(_MarvinModel):
    slug: str
    name: str
    renderer: str | None = None
    renderer_config: dict | None = None
    capabilities: dict | None = None

class PublishedEntryRead(_MarvinModel):
    # ... existing fields ...
    entry_type: str                      # keep for backwards compatibility
    entry_type_info: PublishedEntryTypeInfo | None = None  # new, richer
```

This is backwards-compatible: `entry_type` remains a string slug. The new `entry_type_info` field provides the renderer and capabilities for frontends that want them.

### 3.3 SDK Additions

The SDK defines a dedicated `PublishedEntryType` interface (separate from the platform `MarvinEntryType`):

```typescript
export interface PublishedEntryType {
  slug: string;
  name: string;
  isRendered: boolean;
  rendering?: {
    renderer?: string;
    package?: string;
    version?: string;
    config?: Record<string, unknown>;
  };
  capabilities?: {
    publishable?: boolean;
    submittable?: boolean;
    routable?: boolean;
  };
}
```

The SDK exposes a dedicated `renderers` module (renamed from the proposed `entryTypes` approach for clarity):

```typescript
const client = createMarvinClient();
const renderers = await client.renderers.list();
// Returns PublishedEntryType[] from GET /api/publish/{workspace}/entry-types

const required = renderers
  .filter(t => t.isRendered)
  .map(t => ({
    renderer: t.rendering?.renderer,
    package: t.rendering?.package,
    version: t.rendering?.version,
  }));
```

### 3.4 Frontend: Renderer Registry

A renderer registry is a simple map from renderer name to component. Each frontend framework has its own registry shape:

**Astro example** (`src/renderers/registry.ts`):

```typescript
import PageRenderer from './page.astro';
import ArticleRenderer from './article.astro';
import FormRenderer from './form.astro';
import ExternalEmbedRenderer from './external-embed.astro';

export const renderers: Record<string, any> = {
  'page': PageRenderer,
  'article': ArticleRenderer,
  'form': FormRenderer,
  'external-embed': ExternalEmbedRenderer,
};

export function getRenderer(name: string) {
  return renderers[name] ?? renderers['page']; // fallback to page
}
```

**Resolution chain**:

```
Entry → entry.entryType → entryType.rendering.renderer → registry[renderer] → Component
```

If no renderer is declared, fall back to a default renderer (e.g., `page` — renders title + markdown body, which covers most content).

### 3.5 Renderer Packages

A renderer package exports framework-specific components and optionally a shared logic layer:

```
@inneropen/marvin-renderers-core/
├── package.json
├── src/
│   ├── logic/           # Framework-agnostic
│   │   ├── form.ts      # Form validation, submission logic
│   │   ├── embed.ts     # Embed URL parsing, sandbox config
│   │   └── index.ts
│   ├── astro/           # Astro components
│   │   ├── PageRenderer.astro
│   │   ├── ArticleRenderer.astro
│   │   ├── FormRenderer.astro
│   │   ├── ExternalEmbedRenderer.astro
│   │   └── index.ts     # Registry helper
│   └── react/           # React components (future)
│       ├── PageRenderer.tsx
│       └── index.ts
```

**Package exports** (`package.json`):

```json
{
  "name": "@inneropen/marvin-renderers-core",
  "exports": {
    "./astro": "./dist/astro/index.js",
    "./react": "./dist/react/index.js",
    "./logic": "./dist/logic/index.js"
  }
}
```

**Usage in an Astro site**:

```typescript
import { coreRenderers } from '@inneropen/marvin-renderers-core/astro';

// Merge package renderers with local overrides
const registry = {
  ...coreRenderers,
  'page': MyCustomPageRenderer, // override the default
};
```

### 3.6 Build-Time Validation

Build-time validation is integrated into `@inneropen/marvin-renderers-core` (not a separate package as originally proposed):

```typescript
// astro.config.mjs
import { marvinIntegration } from '@inneropen/marvin-renderers-core/astro';
import { astroRegistry } from '@inneropen/marvin-renderers-core/astro';

export default defineConfig({
  integrations: [
    marvinIntegration({ registry: astroRegistry }),
  ],
});
```

The integration runs at `astro:config:done`. It reads env vars (`MARVIN_API_URL`, `MARVIN_SITE_CLIENT_TOKEN`, `MARVIN_WORKSPACE_SLUG`), calls `client.renderers.list()`, filters to `isRendered` entry types, and checks each renderer name against the provided registry. Missing renderers produce warnings; set `strict: true` to throw errors.

```
[marvin] Entry type "shopify-product" requires renderer "shopify-product"
         Expected package: @inneropen/marvin-renderer-shopify (^1.0.0)
         No renderer registered. Install the package or add a local renderer.
```

### 3.7 CLI Additions

One subcommand under the `publish` group:

```bash
# List renderers required by the workspace (isRendered types only)
marvin publish renderers
# Output: table with Name, Slug, Renderer, Package, Publishable, Routable

# Include all entry types (even non-rendered)
marvin publish renderers --all
```

The `validate` and `sync` commands proposed originally are deferred — build-time validation in `marvin-renderers-core` covers the primary use case.

---

## Part 4: Advantages and Disadvantages

### Advantages

1. **Preserves the small core model.** No new database tables. Two JSONB columns on an existing table.
2. **Entry Types become the single source of truth** for schema, rendering, and capabilities — no parallel hierarchies.
3. **Backwards-compatible.** The `entry_type` field on published entries remains a string slug. New fields are additive.
4. **Decoupled frontend.** Marvin stores only declarative metadata. All component code lives in frontend packages.
5. **Validates early.** Build-time checks catch missing renderers before production, not after.
6. **Enables the Forms collapse.** Forms can migrate from a separate table to an entry type with `renderer: "form"` and `capabilities: { submittable: true }`.
7. **Framework-independent.** Renderer packages can support multiple frameworks via subpath exports.

### Disadvantages

1. **JSONB columns are less queryable than discrete columns.** If you ever need to query "all entry types with renderer X", JSONB queries are possible but less ergonomic than a column index. (Mitigation: PostgreSQL JSONB indexes work well enough for admin queries.)
2. **Renderer names are strings, not validated.** Typos (`"extrnal-embed"`) will silently fail at build time, not at entry type creation time. (Mitigation: build-time validation catches this.)
3. **Package version management adds complexity.** Semver ranges, version conflicts, and breaking changes in renderer packages are now a concern. (Mitigation: start simple — only `@inneropen/marvin-renderers-core` initially.)
4. **Multiple framework targets multiply maintenance.** Each renderer needs Astro + React + Vue implementations. (Mitigation: start with Astro only, add frameworks on demand.)
5. **Form migration requires care.** Moving Forms from a dedicated table to Entry Types requires changing API routes and submission handling. (Mitigation: Forms is not yet in production use, so this can be done as part of the renderer work without a data migration burden.)

---

## Part 5: Migration Strategy

### From current state to renderer-aware Entry Types

**Phase 1: Backend foundation** ✅ Complete

1. ✅ Added `rendering_json` and `capabilities_json` columns to `entry_types` table
2. ✅ Added `is_rendered` boolean flag to `entry_types` — marks which types have frontend renderers (not in original proposal; added for cleaner filtering)
3. ✅ Added Pydantic schemas: `RenderingDefinition`, `CapabilitiesDefinition`
4. ✅ Added validation in `EntryTypeCreate`/`EntryTypeUpdate`
5. ✅ Exposed new fields in `EntryTypeRead` and `EntryTypeSummary`
6. ✅ Updated system entry types seed data with default renderers:
   - `page` → `renderer: "page"`, `is_rendered: true`
   - `article` → `renderer: "article"`, `is_rendered: true`
   - `faq` → `renderer: "faq"`, `is_rendered: true`
   - `navigation-item` → `renderer: "navigation"`, `is_rendered: true`, `capabilities: { routable: false }`

**Phase 2: Publishing API** ✅ Complete

1. ✅ Added `PublishedEntryTypeRead` schema with `is_rendered`, `rendering`, and `capabilities`
2. ✅ Added dedicated `/api/publish/{workspace}/entry-types` endpoint
3. ✅ Existing entry endpoints unchanged — backwards-compatible

**Phase 3: SDK** ✅ Complete

1. ✅ Added `PublishedEntryType` interface with `isRendered`, `rendering`, and `capabilities`
2. ✅ Added `RenderersModule` with `renderers.list()` method (renamed from `entryTypes` to `renderers`)
3. ✅ Workspace module exposes `workspace.renderers`

**Phase 4: Frontend renderer package** ✅ Complete

1. ✅ Created `@inneropen/marvin-renderers-core` package
2. ✅ Astro renderers for system entry types: page, article, faq, navigation
3. ✅ Registry helper, logic layer, and individual component exports
4. ✅ Build-time validation via `validateRenderers()` (filters to `isRendered` types)

**Phase 5: Build validation** ✅ Complete

1. ✅ Build-time validation integrated into `marvin-renderers-core` (not a separate package)
2. ✅ `marvinIntegration()` Astro integration validates at `astro:config:done`
3. ✅ Uses SDK `createMarvinClient` for authenticated API access

**Phase 6: CLI** ✅ Complete (renamed from proposal)

1. ✅ Added `marvin publish renderers` command (under `publish` group, not top-level)
2. ✅ `--all` flag to include non-rendered entry types (default: `isRendered` only)
3. ✅ Table output with Name, Slug, Renderer, Package, Publishable, Routable columns

**Phase 7: Forms migration** (future — not yet started)

1. Create a `form` entry type with `renderer: "form"`, `capabilities: { submittable: true }`
2. Build form submission handling as a generic capability-driven endpoint
3. Migrate existing form data to entries
4. Remove the `forms` table and dedicated API routes

---

## Part 6: Responsibility Summary

| Layer | Responsibility |
|---|---|
| **Backend (Marvin server)** | Stores `rendering_json` and `capabilities_json` on Entry Types. Validates structure. Exposes via Platform and Publishing APIs. Never interprets renderer values. |
| **Publishing API** | Returns entry type metadata including renderer and capabilities alongside entry data. |
| **SDK** | `RenderersModule` with `renderers.list()`. Passes through `isRendered`, `rendering`, and `capabilities` as TypeScript types. |
| **CLI** | `publish renderers` lists workspace renderers (with `--all` flag). No package management. |
| **Renderer packages** | Provide framework-native components, registry, logic helpers, and build-time validation via Astro integration. |
| **Consumer sites** | Maintain a renderer registry. Map entry types to components. Override or extend package renderers. |

---

## Part 7: Design Decisions (Resolved)

1. **Separate columns.** `rendering_json` and `capabilities_json` are separate JSONB columns on `entry_types`. Clearer semantics and independent evolution outweigh the cost of two migration columns.

2. **Fallback to `null`.** When an entry type has no renderer declared, the frontend picks its own default component. No implicit contract that a `"page"` renderer must exist everywhere.

3. **Flat renderer names.** No namespacing — use plain names like `page`, `form`, `external-embed`. Specialized renderers use descriptive prefixes by convention (`shopify-product`, `youtube-embed`).

4. **Forms migration can happen early.** Forms is not fully implemented or in production use, so it can safely be reworked as part of this architecture rather than requiring a separate migration project.

---

*Phases 1–6 are implemented and shipped. Phase 7 (Forms migration) is planned for a future release.*
