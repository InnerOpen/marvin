// A view's page without an entry lists the entries to open in it. With `picker` in the view's definition (services/blueprints/views.py) the
// list is a grid of cards: the entry's picture (else the first picture of its strip, else its initials), its title, chips, a line under it,
// a filmstrip of the spine's pictures (a story's beat stills, evenly sampled) and a Play button for a video the entry holds (a story's
// latest render). What a card shows is decided here from rows the page already has; pure, so `npm test` covers it (viewPicker.test.mjs).

import { type Row, type SpineSpec, assetOf } from "./timeline.ts";

/** One part of the line under a card's title: a field key, or the key with a few characters before its value ("Ep "). */
export type SubtitlePart = string | { field: string; before?: string };

/** A view's `picker` key. */
export interface PickerSpec {
  /** An asset field on the entry: the card's picture. */
  picture?: string;
  /** Up to three parts joined with a dot; a field with a `ref` shows the title of the entry it names. */
  subtitle?: SubtitlePart | SubtitlePart[];
  /** Up to three field keys shown as chips (a story's status). */
  badges?: string[];
  /** A filmstrip of the spine's pictures under the card's picture, at most `limit` (default 16). */
  strip?: boolean | { limit?: number };
  /** An asset field on the entry holding a video: a Play button plays it in the card. */
  play?: string;
}

export const STRIP_DEFAULT = 16;
export const STRIP_MAX = 24;
/** The most rows one entries query returns (the API's QUERY_MAX_ROWS), and how many pages of spine items the picker reads at most. */
export const QUERY_MAX_ROWS = 500;
export const STRIP_MAX_PAGES = 4;

/** How many pictures a card's strip shows: 0 when the picker has no strip (or the spine no picture to show). */
export function stripLimit(picker: PickerSpec | null | undefined, spine: Pick<SpineSpec, "picture"> | null | undefined): number {
  const strip = picker?.strip;
  if (!strip || !spine?.picture) return 0;
  const limit = typeof strip === "object" && Number.isInteger(strip.limit) ? Number(strip.limit) : STRIP_DEFAULT;
  return Math.min(STRIP_MAX, Math.max(1, limit));
}

/** `n` of the list, evenly spread from the first to the last, in order; the whole list when it has no more than `n`. */
export function sampleEvenly<T>(list: readonly T[], n: number): T[] {
  if (n <= 0) return [];
  if (list.length <= n) return [...list];
  if (n === 1) return [list[0]];
  return Array.from({ length: n }, (_, i) => list[Math.round((i * (list.length - 1)) / (n - 1))]);
}

/** The one query for the spine items of all the listed entries (a story's beats): by the field that names their entry, in that entry's
 *  order then their own, so a cut at the last page only shortens the last entries'. */
export function stripQuery(spine: Pick<SpineSpec, "entry_type" | "of" | "order">, owners: readonly string[]): Record<string, unknown> {
  return {
    entry_type: spine.entry_type,
    where: [{ field: spine.of, op: "in", value: [...owners] }],
    // biome-ignore lint/suspicious/noThenProperty: the entries query's second sort key is named then
    sort: spine.order ? { by: spine.of, then: spine.order } : { by: spine.of },
  };
}

/** Each listed entry's spine items, in the order the query gave. `complete` false (more matched than were read): the last entry read and the
 *  ones with none may be missing items, so their count is unknown (null); the others' are exact. */
export function stripsByOwner(rows: readonly Row[], of: string, owners: readonly string[], complete: boolean): Map<string, { items: Row[]; count: number | null }> {
  const out = new Map<string, { items: Row[]; count: number | null }>(owners.map((o) => [o, { items: [], count: 0 }]));
  for (const row of rows) out.get(String(row.dataJson?.[of] ?? ""))?.items.push(row);
  const last = rows.length ? String(rows[rows.length - 1].dataJson?.[of] ?? "") : null;
  for (const [owner, strip] of out) strip.count = !complete && (owner === last || strip.items.length === 0) ? null : strip.items.length;
  return out;
}

/** A field's value for display: trimmed text, or a number as written; empty for nothing, a list or an object. */
function text(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return typeof value === "string" ? value.trim() : "";
}

/** The subtitle as a list of `{field, before}`. */
export function subtitleParts(subtitle: PickerSpec["subtitle"]): { field: string; before: string }[] {
  const parts = subtitle === undefined ? [] : Array.isArray(subtitle) ? subtitle : [subtitle];
  return parts.map((p) => (typeof p === "string" ? { field: p, before: "" } : { field: p.field, before: p.before ?? "" })).filter((p) => !!p.field);
}

/** The slugs the subtitle's `ref` fields name, by the type they name: one query each fetches their titles. `refOf` is the field's `ref`. */
export function refsWanted(rows: readonly Row[], picker: PickerSpec, refOf: (field: string) => string | undefined): Map<string, string[]> {
  const out = new Map<string, Set<string>>();
  for (const { field } of subtitleParts(picker.subtitle)) {
    const type = refOf(field);
    if (!type) continue;
    for (const row of rows) {
      const slug = text(row.dataJson?.[field]);
      if (slug) out.set(type, (out.get(type) ?? new Set()).add(slug));
    }
  }
  return new Map([...out].map(([type, slugs]) => [type, [...slugs]]));
}

/** The line under a card's title: its parts that hold something, a `ref` field as the named entry's title (`titles`: field -> slug ->
 *  title; a slug with none found shows as it is), joined with a dot. */
export function subtitleOf(row: Row, picker: PickerSpec, titles: ReadonlyMap<string, ReadonlyMap<string, string>> = new Map()): string {
  return subtitleParts(picker.subtitle)
    .flatMap(({ field, before }) => {
      const value = text(row.dataJson?.[field]);
      return value ? [`${before}${titles.get(field)?.get(value) ?? value}`] : [];
    })
    .join(" · ");
}

/** A chip's words: a select's value as words ("rough-cut" reads "rough cut"). */
export function badgeText(value: unknown): string {
  return text(value).replace(/[-_]+/g, " ").trim();
}

/** A length as a clock: 87.4 → "1:27", 7 → "0:07", an hour and more "1:02:03". Empty for no length. */
export function lengthText(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return "";
  const whole = Math.round(seconds);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = String(whole % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** A type's slug as words for people: "speech-line" → "speech line". */
export const nounOf = (typeSlug: string): string => typeSlug.replace(/[-_]+/g, " ").trim();

/** The card's counts: "24 beats · 1:27"; either part left out when it is not known. */
export function countsLine(count: number | null | undefined, noun: string, seconds: number | null | undefined): string {
  const parts: string[] = [];
  if (typeof count === "number") parts.push(`${count} ${noun}${count === 1 ? "" : "s"}`);
  const length = lengthText(seconds);
  if (length) parts.push(length);
  return parts.join(" · ");
}

/** What stands for a card with no picture: the first letters of the title's first two words ("The Last Onion" → "TL"). */
export function initialsOf(title: string): string {
  const words = title.trim().split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w));
  return (
    words
      .slice(0, 2)
      .map((w) => [...w.replace(/^[^\p{L}\p{N}]+/u, "")][0] ?? "")
      .join("")
      .toUpperCase() || "?"
  );
}

/** The length of a video asset: as measured (`seconds`, a render's), or as an automation or the recorder saved it. */
export function videoSeconds(meta: Record<string, unknown> | null | undefined): number | null {
  const recording = meta?.recording;
  const candidates = [meta?.seconds, meta?.duration_seconds, recording && typeof recording === "object" ? (recording as Record<string, unknown>).duration_seconds : undefined];
  const found = candidates.map(Number).find((n) => Number.isFinite(n) && n > 0);
  return found ?? null;
}

export interface PickerThumb {
  /** Its tooltip: "Beat 07". */
  title: string;
  picture: string | null;
}

export interface PickerCard {
  slug: string;
  title: string;
  href: string;
  /** The entry's picture, else its strip's first; null: the initials stand for it. */
  picture: string | null;
  initials: string;
  subtitle: string;
  badges: string[];
  /** Whether the card has a strip: the picker asks for one and the items were read (an entry with none has an empty one, so the cards line up). */
  strip: boolean;
  /** The strip's pictures. */
  thumbs: PickerThumb[];
  counts: string;
  video: { url: string; seconds: number | null } | null;
}

/** One entry as a card. `strip` is its spine items (in order) and their count, when the picker has a strip. */
export function pickerCard(
  row: Row,
  ctx: {
    picker: PickerSpec;
    spine: Pick<SpineSpec, "entry_type" | "picture" | "order">;
    href: string;
    strip?: { items: Row[]; count: number | null } | null;
    titles?: ReadonlyMap<string, ReadonlyMap<string, string>>;
  },
): PickerCard {
  const { picker, spine } = ctx;
  const limit = stripLimit(picker, spine);
  const noun = nounOf(spine.entry_type);
  const Noun = noun.charAt(0).toUpperCase() + noun.slice(1);
  const pictureOf = (r: Row) => assetOf(r, spine.picture, "image/")?.publicUrl ?? null;
  const items = limit ? (ctx.strip?.items ?? []) : [];
  const thumbs = sampleEvenly(items, limit).map((r) => ({ title: `${Noun} ${text(r.dataJson?.[spine.order ?? ""]) || r.title}`, picture: pictureOf(r) }));
  const firstStill = items.map(pictureOf).find((p) => !!p) ?? null;
  const video = assetOf(row, picker.play, "video/");
  return {
    slug: row.slug,
    title: row.title,
    href: ctx.href,
    picture: assetOf(row, picker.picture, "image/")?.publicUrl ?? firstStill,
    initials: initialsOf(row.title),
    subtitle: subtitleOf(row, picker, ctx.titles),
    badges: (picker.badges ?? []).map((b) => badgeText(row.dataJson?.[b])).filter(Boolean),
    strip: limit > 0 && !!ctx.strip,
    thumbs,
    counts: countsLine(limit ? (ctx.strip?.count ?? null) : null, noun, video ? videoSeconds(video.metadataJson) : null),
    video: video ? { url: video.publicUrl, seconds: videoSeconds(video.metadataJson) } : null,
  };
}
