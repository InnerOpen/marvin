# Direction: capability-routed enrichment (integrations → vision model → local)

**Audience:** the agent building workspace integrations / MCP servers.
**From:** the entry-type recipe + media-pipeline work.
**Status:** direction / request-for-contract. Phase-1 local media ops already shipped; this is how integrations plug into the same seam.

---

## TL;DR

Enrichment ops (alt-text, image grade/crop, "find a matching image", "restyle to look
rustic", "generate similar") should not hardcode a backend. Each op declares a **capability
it needs**, and a **resolver** picks the best available backend in this order:

1. **A connected integration / MCP server** that advertises the capability. *(preferred)*
2. **The workspace's configured model, if it satisfies the capability** — for vision-in
   work (describe / analyze / ground), a `vision`-capable model is the **default path**.
3. **Local, deterministic code** (Pillow) — for pure-pixel transforms only.

So: **check integrations/MCP first; fall back to the vision model; local for pixel ops.**
Generation/restyle has *no* model or local fallback today — it is integration-only until a
dedicated image-output provider exists.

The **ask** for the integrations agent is at the bottom: a small **capability-advertisement +
uniform-invocation contract** so the resolver can discover and call any connected integration
the same way.

---

## Why this shape

The recipe is already the declaration layer. An entry type's `recipe_json` carries:
- `assets.roles[].derive` — per-role tokens (`thumbnail`, `palette`, `alt_text`, and now
  `grade:*` / `crop:*`).
- `enrichment` — a permissive dict (`extra="allow"`, no migration to add keys).

`AuthoringService.compose` runs enrichment steps after the draft is written — today
`_run_alt_text_enrichment(...)` and (new) `_run_media_enrichment(...)` in
`src/marvin/services/ai/authoring.py` (~L243, helpers ~L483+). Each step is **best-effort**
and **self-contained**. That is exactly where capability-routed steps belong: the recipe says
*what* to do; the resolver decides *who* does it.

Ops themselves already carry capability metadata: an `AIOperation`
(`src/marvin/services/ai/operations/base.py`) declares `requires_vision`, `entity_types`,
`writeback`, etc., and execution is gated by `_validate_model_capabilities` +
`approval_mode` write-back in `src/marvin/routes/ai/operations_controller.py`
(`execute_operation` / `_write_back`). Providers advertise `supports_vision`,
`structured_output`, `embeddings`, `tool_calls` in `src/marvin/services/ai/base.py`. There is
**no image-output capability today** — every provider is image-*in* only (`ImagePart`).

## Capability classes and their resolution order

Route by *class of capability*, not by op name:

| Capability class | Examples | Resolution order |
|---|---|---|
| **Pixel transform** (deterministic, local) | crop-to-aspect, color-grade, filter, thumbnail, palette | **Local (Pillow)** — no model, no integration, no cost. Already shipped. |
| **Vision-in** (image → text/data) | describe image, generate alt-text, detect subject bbox for a smart crop, classify | **Integration/MCP → else the workspace `vision` model (default) → else skip** |
| **Image-out** (image/prompt → image) | restyle ("make it rustic"), generate-similar, inpaint, upscale-generative | **Integration/MCP → else a configured image-output provider → else skip.** No model/local fallback today. |
| **External match/fetch** (find media/data) | find a matching stock/DAM image, pull supplier/product imagery, reverse-image lookup | **Integration/MCP only** |

Key point the user called out: **the workspace model with `vision` is the *default* for
vision-in work, but only after checking integrations** — and it does **not** cover image-out.
So "check for those integration/MCP types first, then default to the vision model" applies to
vision-in; image-out and external-match are integration-first with no model default.

## The resolver (proposed)

A single seam every enrichment op calls:

```
resolve_capability(kind, *, group_id) -> CapabilityHandler | None
    kind ∈ { "image.describe", "image.generate", "image.edit", "image.search", ... }

    1. integrations/MCP: any connected server in this workspace advertising `kind`
       (highest-priority / most-specific wins; group-scoped).
    2. model default: if kind is vision-in and the workspace model.supports_vision → the model.
       if kind is image-out and an image-output provider is configured → that provider.
    3. local: if kind is a pixel transform → the local handler.
    else None  → op logs "no backend for <kind>", skips (best-effort, never fails compose).
```

`CapabilityHandler` is a thin uniform interface — `invoke(inputs) -> outputs` — so an op does
not care whether it's talking to an MCP tool, the vision model, or Pillow. Persisting a
produced image already exists: `AssetStorageService.create_derivative(...)` (writes bytes as a
new asset with provenance `metadata_json.derived_from` / `.derivation`) and `read_bytes(...)`
in `src/marvin/services/assets/asset_storage_service.py`; link via `EntryAssets` with a derived
role. Gate model/integration-produced assets through the existing `approval_mode`
(suggest-only default for anything generative/irreversible).

## What we need FROM integrations/MCP (the ask)

For the resolver to discover and call a connected integration uniformly, each integration /
MCP server should expose:

1. **Capability advertisement.** A machine-readable list of capabilities it provides, using a
   shared vocabulary (`image.describe`, `image.generate`, `image.edit`, `image.search`,
   `image.upscale`, …). This can be a manifest field on the workspace MCP-server record, or
   derived from tool tags/names. The resolver queries: *"who in this workspace can do
   `image.generate`?"*
2. **Uniform invocation contract per capability.** Predictable inputs/outputs so one handler
   fits all providers:
   - `image.describe` — in: image (asset ref or bytes) + optional prompt; out: text/JSON.
   - `image.generate` — in: prompt (+ optional reference image, count); out: image bytes[].
   - `image.edit` / restyle — in: image + prompt (+ strength/mask); out: image bytes.
   - `image.search` — in: query (text or image) + filters; out: candidate refs/URLs + metadata.
   - Bytes over URLs where possible (we persist via `create_derivative`); if URLs, we fetch
     and store, recording source/provenance.
3. **Selection metadata** so the resolver can rank when several match: priority/precedence,
   cost hint, and whether it needs approval (maps to `approval_mode`). Most-specific / highest
   priority wins; ties fall back to config order.
4. **Group scoping + auth** handled by the integration layer — the resolver only asks "for
   this `group_id`, who provides `kind`?" and gets back callable handlers already authorized.
   (Headless/cron note: interactively-authed servers may be absent — the resolver must treat
   "not available" as skip, not error.)

If integrations advertise capabilities this way, generation/restyle/find-image become ordinary
enrichment steps — the recipe declares the step, the resolver finds the connected provider, and
nothing in the op is provider-specific.

## Example flows

- **Rustic hero, no integration connected.** Recipe `derive: ["grade:rustic-warm"]` → pixel
  class → **local** grade. (Shipped.) If a `image.edit` integration *is* connected and the
  recipe uses `enrichment.media: [{op: restyle-image, prompt: "rustic workshop…"}]` → image-out
  class → **integration**, suggest-only.
- **Alt-text / describe.** Vision-in class → integration if one advertises `image.describe`,
  else the workspace **vision model** (today's path), else skip.
- **Smart crop to subject.** `crop:subject` → needs a subject bbox (vision-in): integration →
  else vision model returns a box → Pillow performs the deterministic cut (pixel class).
- **Find a matching image for an entry with none.** `enrichment.media: [{op: find-image,
  query_from: title+summary}]` → external-match class → **integration only**; attach the chosen
  result as an asset (approval-gated).

## What exists today vs. what this needs

- **Exists:** recipe `derive`/`enrichment` hooks; the ops framework + `requires_vision` +
  `approval_mode` write-back; provider `supports_vision`; `ImagePart` (image-in);
  `AssetStorageService.create_derivative`/`read_bytes`; Phase-1 local grade/crop
  (`services/ai/media/`), wired into compose.
- **Needs building (roughly in order):**
  1. `resolve_capability(kind, group_id)` + `CapabilityHandler` interface.
  2. Integration capability-advertisement + uniform invocation (the ask above) — **integrations agent**.
  3. Vision-model handler adapter (wrap the existing `describe-image` plumbing behind the resolver).
  4. Image-out ops (`restyle-image`, `generate-similar-image`) that call the resolver, persist
     via `create_derivative`, default to suggest-only.
  5. `supports_image_output` flag on the model/provider row (mirror `supports_vision`) for the
     rare case a model itself can output images — one nullable boolean, autogenerate-clean.

## Open questions for the integrations agent

1. Where does capability advertisement live — on the workspace MCP-server record
   (`mcp_servers` / `ai-mcp-servers`), a manifest, or tool-name/tag convention?
2. Is there already a per-group registry of connected servers the resolver can query, and does
   it expose a "list tools/capabilities" call we can filter by capability kind?
3. Preferred shape for passing an image to an MCP tool — base64 bytes inline, a signed URL, or
   an asset reference the server can fetch? (We can produce any; bytes-back is easiest to store.)
4. How should precedence/selection be expressed when multiple servers advertise the same
   capability — explicit priority field, or workspace ordering?
