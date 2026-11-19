// Times in an Ask answer as links to the moment in the recording they belong to. An answer that cites a timestamped recording (an
// asset source with a `startSeconds`, from search_content; `start_seconds` in /ask's retrieved_sources) and says `[0:00:10]`,
// `0:00:10` or `1:05` gets each such time as a link to the recording's page opened there (assetHref). Decided here, from the sources
// the reply already shows, never from the model's wording: with one timed recording cited every time is its; with several, a time
// is linked only when the nearest title before it on its line is one of theirs. A time in code or in a link, or inside a cited
// title ("Recording Nov 18, 2026, 5:46:18 PM"), stays text. The stored message is untouched. Pure (marked only), so `npm test` covers
// it (askTimeLinks.test.mjs); capabilities.ts renderMarkdown sanitizes the HTML it returns.

import { type Token, type Tokens, marked } from "marked";

import { formatLength } from "./assetRecording.ts";
import { assetHref } from "./mediaTime.ts";

/** A reply's source as the Ask page and the agent bubble get it (`sources`), or as /ask's `retrieved_sources` has it. */
export interface CitedSource {
  entityType?: string | null;
  entityId?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  title?: string | null;
  startSeconds?: number | null;
  start_seconds?: number | null;
}

/** A time in a line of text that belongs to a cited recording: where it is (`start`..`end`), its seconds and the asset. */
export interface TimeLink {
  start: number;
  end: number;
  seconds: number;
  assetId: string;
}

interface Timed {
  id: string;
  title: string;
}

/** `[h:mm:ss]`, `h:mm:ss`, `[m:ss]` or `m:ss`, standing alone: not part of a longer number, a date-time (`T17:46:18Z`), a decimal or
 * SRT time (`0:10.5`, `0:10,500`), a path, or a time of day (`5:46 PM`). */
const TIME = /(?<![\w:./])(\[?)(?:(\d{1,2}):(\d{2}):(\d{2})|(\d{1,3}):(\d{2}))(\]?)(?![\w:/]|[.,]\d|\s*[ap]\.?m\b)/gi;

/** A title this short is not looked for in the text (it would match by chance). */
const MIN_TITLE = 3;

const sourceId = (s: CitedSource) => String(s.entityId ?? s.entity_id ?? "");
const sourceType = (s: CitedSource) => s.entityType ?? s.entity_type ?? "";
const sourceStart = (s: CitedSource) => s.startSeconds ?? s.start_seconds;

/** The cited recordings: asset sources that say where in their recording they start (0 counts), once each. */
function timedAssets(sources: readonly CitedSource[]): Timed[] {
  const byId = new Map<string, Timed>();
  for (const s of sources) {
    const id = sourceId(s);
    if (sourceType(s) !== "asset" || !id || typeof sourceStart(s) !== "number" || byId.has(id)) continue;
    byId.set(id, { id, title: String(s.title ?? "").trim() });
  }
  return [...byId.values()];
}

/** Where `needle` occurs in `hay`, ignoring case: [start, end) pairs. */
function occurrences(hay: string, needle: string): [number, number][] {
  const out: [number, number][] = [];
  if (needle.length < MIN_TITLE) return out;
  const h = hay.toLowerCase();
  const n = needle.toLowerCase();
  for (let at = h.indexOf(n); at !== -1; at = h.indexOf(n, at + 1)) out.push([at, at + n.length]);
  return out;
}

/** The seconds a matched time stands for, or null when it isn't one (minutes or seconds of 60 or more after a colon: `99:99`). */
function matchSeconds(m: RegExpMatchArray): number | null {
  const [h, mm, ss] = m[2] !== undefined ? [Number(m[2]), Number(m[3]), Number(m[4])] : [0, Number(m[5]), Number(m[6])];
  if (ss >= 60 || (m[2] !== undefined && mm >= 60)) return null;
  return h * 3600 + mm * 60 + ss;
}

/** The recording a time at `at` in `line` belongs to when several are cited: the one whose title is mentioned nearest before it
 * (the longer title when two end there). Null when none is, or when that mention names two recordings (the same title). */
function namedBefore(line: string, at: number, timed: Timed[]): string | null {
  let best: { end: number; len: number; ids: Set<string> } | null = null;
  for (const t of timed) {
    for (const [s, e] of occurrences(line, t.title)) {
      if (e > at) continue;
      const len = e - s;
      if (!best || e > best.end || (e === best.end && len > best.len)) best = { end: e, len, ids: new Set([t.id]) };
      else if (e === best.end && len === best.len) best.ids.add(t.id);
    }
  }
  return best && best.ids.size === 1 ? [...best.ids][0] : null;
}

/** The times in `text` that belong to a cited recording, in order. Each line (`\n`) is looked at on its own. With one timed recording
 * among `sources` every time is its; with several, only a time whose line names one of them before it (see namedBefore). A time
 * inside a cited title is never one. */
export function timeLinksIn(text: string, sources: readonly CitedSource[] | null | undefined): TimeLink[] {
  const timed = timedAssets(sources ?? []);
  if (!timed.length) return [];
  const titles = [...new Set((sources ?? []).map((s) => String(s.title ?? "").trim()))];
  const out: TimeLink[] = [];
  let offset = 0;
  for (const line of text.split("\n")) {
    const inTitle = titles.flatMap((t) => occurrences(line, t));
    for (const m of line.matchAll(TIME)) {
      const seconds = matchSeconds(m);
      if (seconds === null) continue;
      // A lone bracket stays outside the link: `[0:10` links `0:10`.
      const start = (m.index ?? 0) + (m[1] && !m[7] ? 1 : 0);
      const end = (m.index ?? 0) + m[0].length - (m[7] && !m[1] ? 1 : 0);
      if (inTitle.some(([s, e]) => start < e && end > s)) continue;
      const assetId = timed.length === 1 ? timed[0].id : namedBefore(line, start, timed);
      if (assetId) out.push({ start: offset + start, end: offset + end, seconds, assetId });
    }
    offset += line.length + 1;
  }
  return out;
}

/** A plain text leaf of an inline run, and where its text sits in the run's flattened text. */
interface Leaf {
  token: Tokens.Text;
  owner: Token[];
  start: number;
  end: number;
}

const isLeafText = (t: Token): t is Tokens.Text => t.type === "text" && !("tokens" in t && t.tokens?.length);

/** Adjacent plain text tokens as one (marked may cut `[0:00:10]` at its bracket), so a time is never split between two. */
function mergeText(tokens: Token[]): void {
  for (let i = tokens.length - 1; i > 0; i--) {
    const [a, b] = [tokens[i - 1], tokens[i]];
    if (isLeafText(a) && isLeafText(b) && !a.escaped && !b.escaped) {
      a.raw += b.raw;
      a.text += b.text;
      tokens.splice(i, 1);
    }
  }
}

/** Raw HTML the model wrote that opens or closes a link or code, whose text stays as it is. */
const RAW_OPEN = /^<(a|code|pre|kbd|samp)\b/i;
const RAW_CLOSE = /^<\/(a|code|pre|kbd|samp)\s*>/i;

/** An inline run's text as one string (`br` as a line break) and the text leaves a link may go in: not in a link, an image, code or
 * raw HTML's `<a>`/`<code>`. Everything counts for where a title is mentioned. */
function flatten(tokens: Token[], linkable: boolean, acc: { text: string; leaves: Leaf[]; rawOpen: number }): void {
  mergeText(tokens);
  for (const t of tokens) {
    if (isLeafText(t)) {
      const start = acc.text.length;
      acc.text += t.text;
      if (linkable && !t.escaped && !acc.rawOpen)
        acc.leaves.push({ token: t, owner: tokens, start, end: acc.text.length });
    } else if (t.type === "html") {
      if (RAW_OPEN.test(t.text)) acc.rawOpen++;
      else if (RAW_CLOSE.test(t.text)) acc.rawOpen = Math.max(0, acc.rawOpen - 1);
    } else if (t.type === "br") acc.text += "\n";
    else if ("tokens" in t && Array.isArray(t.tokens))
      flatten(t.tokens, linkable && t.type !== "link" && t.type !== "image", acc);
    else if ("text" in t && typeof t.text === "string") acc.text += t.text;
  }
}

function textToken(text: string): Tokens.Text {
  return { type: "text", raw: text, text, escaped: false };
}

function linkToken(text: string, link: TimeLink, title: string): Tokens.Link {
  const where = formatLength(link.seconds);
  return {
    type: "link",
    raw: text,
    href: assetHref(link.assetId, link.seconds),
    title: title ? `Play ${title} from ${where}` : `Play from ${where}`,
    text,
    tokens: [textToken(text)],
  };
}

/** One inline run (a paragraph, list item, heading or table cell) with its times made links, in place. */
function linkRun(tokens: Token[], sources: readonly CitedSource[], titles: Map<string, string>): void {
  const acc = { text: "", leaves: [] as Leaf[], rawOpen: 0 };
  flatten(tokens, true, acc);
  const inLeaf = (s: number, e: number) => acc.leaves.some((f) => s >= f.start && e <= f.end);
  const links = timeLinksIn(acc.text, sources).map((l) => {
    if (inLeaf(l.start, l.end)) return l;
    // An escaped bracket (`\[0:00:10\]`) is a token of its own: the link is the time inside it.
    const start = acc.text[l.start] === "[" ? l.start + 1 : l.start;
    const end = acc.text[l.end - 1] === "]" ? l.end - 1 : l.end;
    return { ...l, start, end };
  });
  if (!links.length) return;
  for (const leaf of acc.leaves) {
    const inside = links.filter((l) => l.start >= leaf.start && l.end <= leaf.end); // a time across two leaves stays text
    if (!inside.length) continue;
    const parts: Token[] = [];
    let at = 0;
    const text = leaf.token.text;
    for (const l of inside) {
      const [s, e] = [l.start - leaf.start, l.end - leaf.start];
      if (s > at) parts.push(textToken(text.slice(at, s)));
      parts.push(linkToken(text.slice(s, e), l, titles.get(l.assetId) ?? ""));
      at = e;
    }
    if (at < text.length) parts.push(textToken(text.slice(at)));
    leaf.owner.splice(leaf.owner.indexOf(leaf.token), 1, ...parts);
  }
}

/** Every inline run of a block token list, through lists, quotes and tables; code blocks and raw HTML are left alone. */
function linkBlocks(tokens: Token[], sources: readonly CitedSource[], titles: Map<string, string>): void {
  for (const t of tokens) {
    if ((t.type === "paragraph" || t.type === "heading" || t.type === "text") && "tokens" in t && t.tokens)
      linkRun(t.tokens, sources, titles);
    else if (t.type === "list") for (const item of (t as Tokens.List).items) linkBlocks(item.tokens, sources, titles);
    else if (t.type === "blockquote") linkBlocks((t as Tokens.Blockquote).tokens, sources, titles);
    else if (t.type === "table") {
      const table = t as Tokens.Table;
      for (const cell of [...table.header, ...table.rows.flat()]) linkRun(cell.tokens, sources, titles);
    }
  }
}

/** An answer's markdown as HTML (marked, not yet sanitized) with the times that belong to a cited recording as links to that moment.
 * No sources, or none of them a timed recording: exactly what marked makes of it. */
export function answerMarkdownHtml(markdown: string, sources?: readonly CitedSource[] | null): string {
  const tokens = marked.lexer(markdown);
  const timed = timedAssets(sources ?? []);
  if (timed.length) linkBlocks(tokens, sources ?? [], new Map(timed.map((t) => [t.id, t.title])));
  return marked.parser(tokens);
}
