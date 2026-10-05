/**
 * Media embeds — the browser half: provider list and resolve calls (cached per page), DOMPurify-sanitised
 * markdown preview, and player / link-card elements built with DOM APIs from the structured embed
 * (`embed.iframe`), never from server or provider HTML. Pure logic lives in `mediaEmbeds.ts`.
 */

import DOMPurify from "dompurify";
import { ApiRequestError } from "@/lib/api/client";
import { getEmbedProviders, resolveEmbed } from "@/lib/api/mediaEmbeds";
import {
  buildIframeSpec,
  EMBED_SLOT_ATTR,
  type EmbedMode,
  findProvider,
  linkCardText,
  type ProvidersResponse,
  type PublishedEmbed,
  type ResolveResult,
  renderMarkdownPreview,
  safeHref,
} from "@/lib/mediaEmbeds";

let providersPromise: Promise<ProvidersResponse> | null = null;

/** The provider registry, fetched once per page. Resolves to an empty list when it can't be loaded. */
export function loadProviders(): Promise<ProvidersResponse> {
  providersPromise ??= getEmbedProviders().catch((e) => {
    console.warn("[media-embeds] Could not load providers:", e);
    providersPromise = null; // let a later call retry
    return { providers: [], frameSources: [] };
  });
  return providersPromise;
}

const resolved = new Map<string, Promise<ResolveResult>>();

/** Resolve `input` (cached per input + mode for the page). Failures aren't cached so a retry can succeed. */
export function resolveCached(input: string, mode: EmbedMode = "direct"): Promise<ResolveResult> {
  const key = `${mode} ${input.trim()}`;
  let pending = resolved.get(key);
  if (!pending) {
    pending = resolveEmbed(input.trim(), mode);
    resolved.set(key, pending);
    pending.catch(() => resolved.delete(key));
  }
  return pending;
}

/** A human message for a failed resolve call (429 gets its own). */
export function resolveErrorMessage(e: unknown): string {
  if (e instanceof ApiRequestError && e.status === 429) {
    return "Too many links checked in a short time — wait a minute and try again.";
  }
  if (e instanceof ApiRequestError && e.status === 403) {
    return "You don't have permission to embed media in this workspace.";
  }
  return e instanceof Error && e.message ? e.message : "Couldn't check that link. Try again.";
}

function linkElement(href: string, text: string): HTMLAnchorElement {
  const a = document.createElement("a");
  const safe = safeHref(href);
  if (safe) a.href = safe;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = text;
  return a;
}

/**
 * A preview player for `embed`: `<div class="marvin-embed">` around an iframe whose every attribute is set
 * from the host-checked spec — or a link card (`a.marvin-embed-link`) when there is no allowed player.
 */
export function buildEmbedElement(embed: PublishedEmbed, frameSources: readonly string[]): HTMLElement {
  const spec = buildIframeSpec(embed, frameSources);
  if (!spec) {
    const card = linkElement(embed.link?.href || embed.url, linkCardText(embed));
    card.className = "marvin-embed-link";
    card.dataset.provider = embed.provider;
    return card;
  }
  const wrap = document.createElement("div");
  wrap.className = "marvin-embed";
  wrap.dataset.provider = embed.provider;
  wrap.dataset.kind = embed.kind;
  if (spec.aspectRatio) wrap.style.aspectRatio = spec.aspectRatio;
  if (spec.height) wrap.style.height = `${spec.height}px`;
  const iframe = document.createElement("iframe");
  for (const [name, value] of Object.entries(spec.attrs)) iframe.setAttribute(name, value);
  wrap.appendChild(iframe);
  return wrap;
}

/** Sanitise rendered markdown for the preview (placeholder `data-` attributes survive). */
export function sanitizePreview(html: string): string {
  return DOMPurify.sanitize(html);
}

function plainLinkParagraph(url: string): HTMLParagraphElement {
  const p = document.createElement("p");
  p.appendChild(linkElement(url, url));
  return p;
}

/**
 * Render `markdown` into `container` as a sanitised preview. With `autoEmbed`, bare provider URLs on their
 * own paragraph are resolved (mode "direct", cached) and replaced by a player or link card; anything else
 * stays a plain link. Safe to call repeatedly — late resolves for a replaced render are simply dropped.
 */
export function renderPreviewInto(container: HTMLElement, markdown: string, autoEmbed = true): void {
  if (!markdown?.trim()) {
    container.innerHTML = '<div class="preview-empty">Nothing to preview</div>';
    return;
  }
  const { html, slots } = renderMarkdownPreview(markdown, { autoEmbed });
  container.innerHTML = sanitizePreview(html);
  if (slots.length === 0) return;

  const slotEls = new Map<string, Element>();
  for (const el of container.querySelectorAll(`[${EMBED_SLOT_ATTR}]`)) {
    const id = el.getAttribute(EMBED_SLOT_ATTR);
    if (id && !slotEls.has(id)) slotEls.set(id, el);
  }
  // Until the registry answers (or when the host isn't a provider) a slot reads as the plain link it is.
  for (const slot of slots) slotEls.get(slot.id)?.replaceChildren(plainLinkParagraph(slot.url));

  void loadProviders().then(({ providers, frameSources }) => {
    for (const slot of slots) {
      const el = slotEls.get(slot.id);
      if (!el || !findProvider(slot.url, providers)) continue;
      el.classList.add("marvin-embed-pending");
      resolveCached(slot.url, "direct")
        .then((result) => {
          el.classList.remove("marvin-embed-pending");
          if (result.embed) el.replaceChildren(buildEmbedElement(result.embed, frameSources));
        })
        .catch((e) => {
          el.classList.remove("marvin-embed-pending");
          el.setAttribute("title", resolveErrorMessage(e));
        });
    }
  });
}

/** Status line for a resolved embed: "YouTube · Title · player" etc. */
export function describeEmbed(embed: PublishedEmbed): string {
  const status =
    embed.status === "ok"
      ? "plays inline"
      : embed.status === "link"
        ? "shown as a link (no player for this link)"
        : "unavailable — shown as a link";
  return [embed.providerName, embed.title, status].filter(Boolean).join(" · ");
}
