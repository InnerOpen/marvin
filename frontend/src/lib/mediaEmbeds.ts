/**
 * Media embeds ("paste a link, get a player") — the pure half: provider host matching, finding the
 * bare provider URLs in markdown that become players, the iframe attribute builder and the markdown
 * preview renderer. No DOM and no `@/` imports, so `node --test` can import this file directly; the
 * browser half (DOMPurify, fetch, DOM building) is `mediaEmbedsBrowser.ts`.
 *
 * The bare-URL rule must match the site side (MarvinAstro `renderMarkdown`, marked + GFM): a
 * top-level paragraph that is exactly one autolinked URL whose text is its href. `<url>`,
 * `[text](url)`, a URL with trailing punctuation, or one inside a sentence/list/blockquote/code
 * stays an ordinary link.
 */

import type { Token, Tokens } from "marked";
import { Marked } from "marked";

export type EmbedKind = "video" | "audio" | "podcast" | "playlist";
export type EmbedStatus = "ok" | "link" | "unavailable";
export type EmbedMode = "direct" | "click_to_load";

export interface EmbedProvider {
  key: string;
  name: string;
  kinds: EmbedKind[];
  /** Exact hostnames; an entry starting with "*." matches any subdomain of the rest. */
  hosts: string[];
  examples: string[];
  /** The provider only ever renders a link card from a plain URL. */
  linkOnly: boolean;
}

export interface ProvidersResponse {
  providers: EmbedProvider[];
  /** Origins a player iframe may load from (e.g. "https://www.youtube-nocookie.com"). */
  frameSources: string[];
}

export interface EmbedIframe {
  src: string;
  title: string;
  allow: string;
  sandbox: string;
  referrerpolicy: string;
  aspectRatio?: string;
  height?: number;
}

export interface PublishedEmbed {
  url: string;
  canonicalUrl: string;
  provider: string;
  providerName: string;
  kind: EmbedKind;
  status: EmbedStatus;
  title?: string;
  authorName?: string;
  thumbnailUrl?: string;
  /** Present only when status is "ok". */
  iframe?: EmbedIframe;
  link: { href: string; title: string; providerName: string };
  html: string;
}

export interface ResolveResult {
  input: string;
  /** The URL to store/insert, or null when the input isn't a supported provider. */
  url: string | null;
  embed: PublishedEmbed | null;
  error: string | null;
}

/** Default consent line for click-to-load facades; `{provider}` becomes the provider name. */
export const DEFAULT_CONSENT_TEXT = "Loading this player connects to {provider}, which may set cookies.";

/** The lower-cased hostname of an http(s) URL, or null for anything else. */
export function httpHost(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  return parsed.hostname.toLowerCase().replace(/\.$/, "") || null;
}

/** Whether `host` matches one registry host entry: exact, or any subdomain for "*.example.com". */
export function hostMatches(host: string, pattern: string): boolean {
  const h = host.toLowerCase().replace(/\.$/, "");
  const p = pattern.toLowerCase().trim();
  if (p.startsWith("*.")) {
    const base = p.slice(2);
    return base.length > 0 && h.length > base.length + 1 && h.endsWith(`.${base}`);
  }
  return h === p;
}

/** The provider whose hosts cover this URL, or null (not http(s), unparsable or not allow-listed). */
export function findProvider(url: string, providers: readonly EmbedProvider[]): EmbedProvider | null {
  const host = httpHost(url);
  if (!host) return null;
  return providers.find((p) => p.hosts.some((pattern) => hostMatches(host, pattern))) ?? null;
}

/** The bare URL a top-level paragraph token consists of, or null when it is anything else. */
export function bareUrlOfParagraph(token: Token): string | null {
  if (token.type !== "paragraph") return null;
  const inline = (token as Tokens.Paragraph).tokens ?? [];
  if (inline.length !== 1 || inline[0].type !== "link") return null;
  const link = inline[0] as Tokens.Link;
  if (link.text !== link.href || link.raw !== link.href) return null;
  return httpHost(link.href) ? link.href : null;
}

function lexer(): Marked {
  return new Marked({ gfm: true });
}

/**
 * The bare URLs (as written) standing alone in a top-level paragraph of `markdown`, in order. These are
 * embed candidates; only those whose host is in a provider's `hosts` become players.
 */
export function findEmbedCandidates(markdown: string): string[] {
  const urls: string[] = [];
  for (const token of lexer().lexer(markdown ?? "")) {
    const url = bareUrlOfParagraph(token);
    if (url) urls.push(url);
  }
  return urls;
}

/** Schemes a rendered markdown link or image may point at (relative URLs and #anchors pass too). */
const SAFE_URL = /^(?:https?:|mailto:|tel:|[/#?.]|[^:/?#]*(?:[/?#]|$))/i;

/** `href` when it is safe to render, otherwise "" — drops `javascript:`, `data:`, `vbscript:` and the like. */
export function safeHref(href: string | null | undefined): string {
  // Browsers ignore ASCII whitespace/control characters inside a scheme, so judge the URL without them.
  // biome-ignore lint/suspicious/noControlCharactersInRegex: stripping control characters is the point
  const compact = String(href ?? "").replace(/[\u0000- \u007f]+/g, "");
  return SAFE_URL.test(compact) ? String(href ?? "").trim() : "";
}

export interface PreviewSlot {
  /** Matches the `data-marvin-embed-slot` attribute of the placeholder in `html`. */
  id: string;
  /** The URL as written in the markdown. */
  url: string;
}

export interface PreviewRender {
  /** Unsanitised HTML — run it through DOMPurify before it touches the DOM. */
  html: string;
  /** Bare-URL paragraphs replaced by an empty placeholder div, for the caller to fill with a player. */
  slots: PreviewSlot[];
}

export const EMBED_SLOT_ATTR = "data-marvin-embed-slot";

/**
 * Render markdown for the editor preview with marked (GFM, like the sites). Unsafe link/image URLs are
 * blanked here as well as by DOMPurify later. With `autoEmbed`, every bare-URL paragraph becomes a
 * placeholder `<div data-marvin-embed-slot="…">`; the slot ids carry a per-render nonce so raw HTML in
 * the markdown can't forge one.
 */
export function renderMarkdownPreview(
  markdown: string,
  options: { autoEmbed?: boolean; nonce?: string } = {},
): PreviewRender {
  const md = lexer();
  const nonce = options.nonce ?? Math.random().toString(36).slice(2, 10);
  const slots: PreviewSlot[] = [];
  const tokens = md.lexer(markdown ?? "");

  if (options.autoEmbed !== false) {
    tokens.forEach((token, index) => {
      const url = bareUrlOfParagraph(token);
      if (!url) return;
      const id = `${nonce}-${slots.length}`;
      slots.push({ id, url });
      const placeholder: Tokens.HTML = {
        type: "html",
        raw: token.raw,
        text: `<div ${EMBED_SLOT_ATTR}="${id}"></div>\n`,
        block: true,
        pre: false,
      };
      tokens[index] = placeholder;
    });
  }

  md.walkTokens(tokens, (token) => {
    if (token.type === "link" || token.type === "image") {
      const t = token as Tokens.Link | Tokens.Image;
      t.href = safeHref(t.href);
    }
  });

  return { html: md.parser(tokens), slots };
}

export interface IframeSpec {
  attrs: Record<string, string>;
  /** CSS aspect-ratio for the wrapper (e.g. "16/9"), when the provider has one. */
  aspectRatio?: string;
  /** Fixed player height in px (audio/podcast players). */
  height?: number;
}

function originOf(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/**
 * The attributes for a player iframe, rebuilt from `embed.iframe` — never from provider HTML. Refused
 * (null) unless the embed is "ok" and its https `src` is on one of the allowed `frameSources` origins.
 */
export function buildIframeSpec(embed: PublishedEmbed, frameSources: readonly string[]): IframeSpec | null {
  const frame = embed.iframe;
  if (embed.status !== "ok" || !frame?.src) return null;
  let src: URL;
  try {
    src = new URL(frame.src);
  } catch {
    return null;
  }
  if (src.protocol !== "https:") return null;
  const allowed = new Set(frameSources.map(originOf).filter((o): o is string => !!o));
  if (!allowed.has(src.origin)) return null;

  const attrs: Record<string, string> = {
    src: src.href,
    title: frame.title || embed.title || `${embed.providerName} player`,
    loading: "lazy",
    referrerpolicy: frame.referrerpolicy || "strict-origin-when-cross-origin",
  };
  if (frame.allow) attrs.allow = frame.allow;
  // An empty sandbox attribute would block everything (scripts included), so only set a real token list.
  if (frame.sandbox?.trim()) attrs.sandbox = frame.sandbox.trim();
  if (embed.kind === "video" || embed.kind === "playlist") attrs.allowfullscreen = "";

  const spec: IframeSpec = { attrs };
  if (frame.aspectRatio && /^\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?$/.test(frame.aspectRatio)) {
    spec.aspectRatio = frame.aspectRatio.replace(/\s+/g, "");
  }
  if (typeof frame.height === "number" && Number.isInteger(frame.height) && frame.height > 0 && frame.height <= 2000) {
    spec.height = frame.height;
  }
  return spec;
}

/** The link-card text for an embed that has no player: "Title · on Provider". */
export function linkCardText(embed: PublishedEmbed): string {
  const provider = embed.link?.providerName || embed.providerName;
  const title = embed.link?.title || embed.title || embed.url;
  return `${title} · on ${provider}`;
}

/**
 * Insert `url` into `value` as its own paragraph (blank line before and after) in place of the
 * selection `start..end`. Returns the new value and the caret position just after the URL.
 */
export function insertEmbedParagraph(
  value: string,
  start: number,
  end: number,
  url: string,
): { value: string; caret: number } {
  const before = value.slice(0, start).replace(/[ \t]+$/, "");
  const after = value.slice(end).replace(/^[ \t]+/, "");
  const lead = before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const trail = after === "" || after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n";
  const head = `${before}${lead}${url}`;
  return { value: `${head}${trail}${after}`, caret: head.length };
}

/** Whether `providerKey` is allowed by an `embed` field's optional `providers` filter (empty = all). */
export function providerAllowed(providerKey: string, allowed: readonly string[] | null | undefined): boolean {
  return !allowed || allowed.length === 0 || allowed.includes(providerKey);
}
