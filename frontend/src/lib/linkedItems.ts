// The asset / resource fields of a schema form (LinkedItemsField.astro): what the hidden input holds, how a chosen item
// is shown, and the search over the picker's list. Pure, so the page's own picker script and the tests share it.

import { isVideoAsset, videoPosterOf } from "./videoAsset.ts";

export interface LinkedItem {
  id: string;
  name: string;
  /** A second line under the name: the mime type of an asset, the slug of a resource. */
  meta?: string | null;
  /** An image asset's public url, shown as a thumbnail; absent for other files and for resources. */
  imageUrl?: string | null;
  /** An audio asset's public url, played from its card (an actor's voice sample). */
  audioUrl?: string | null;
  /** A video asset's public url, played small on its card (InlineVideo.astro), and the still it shows before it plays. */
  videoUrl?: string | null;
  posterUrl?: string | null;
  alt?: string | null;
  /** An asset's file type, for a field that takes only some kinds (lib/assetAccept.ts). */
  mimeType?: string | null;
}

/** The ids a stored value names: one id, a list, or the comma-separated string an older form saved. */
export function idsOf(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((v) => String(v ?? "").trim()).filter(Boolean);
  if (typeof value === "string") return value.split(",").map((s) => s.trim()).filter(Boolean);
  return [];
}

/** What the hidden input posts: ids joined by commas (coerceDataJsonValue splits a list field back into an array). */
export function serialize(ids: string[]): string {
  return ids.join(",");
}

/** The items for a list of ids, in that order; an id the list no longer has keeps a placeholder so it is not lost on save. */
export function chosen(ids: string[], items: LinkedItem[]): LinkedItem[] {
  const byId = new Map(items.map((i) => [i.id, i]));
  return ids.map((id) => byId.get(id) ?? { id, name: `Unknown (${id.slice(0, 8)}…)`, meta: "not in this workspace's list" });
}

/** Case-insensitive match on the name, meta and id; an empty query keeps everything. */
export function matches(item: LinkedItem, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [item.name, item.meta ?? "", item.id].some((s) => s.toLowerCase().includes(q));
}

/** Whether another item may be added: a single field holds one, a list field respects `max`. */
export function canAdd(count: number, multiple: boolean, max?: number | null): boolean {
  if (!multiple) return count === 0;
  return max == null || count < max;
}

type PickedAsset = { id: string; slug?: string | null; name: string; mimeType?: string | null; publicUrl?: string | null; altText?: string | null; metadataJson?: Record<string, unknown> | null };

/** An asset as the picker shows it. A video's poster named by id is found among `siblings` (assetItems passes the whole list). One argument
 *  as far as `.map(assetItem)` is concerned: the index it would pass is not a list. */
export function assetItem(a: PickedAsset, siblings?: unknown): LinkedItem {
  const image = (a.mimeType ?? "").startsWith("image/") && a.publicUrl ? a.publicUrl : null;
  const video = isVideoAsset(a) ? (a.publicUrl as string) : null;
  const audio = !video && (a.mimeType ?? "").startsWith("audio/") && a.publicUrl ? a.publicUrl : null;
  const poster = video ? videoPosterOf(a, Array.isArray(siblings) ? siblings : []) : null;
  return { id: a.id, name: a.name, meta: a.mimeType ?? null, imageUrl: image, audioUrl: audio, videoUrl: video, posterUrl: poster, alt: a.altText ?? null, mimeType: a.mimeType ?? null };
}

/** A list of assets as the picker shows them, each video's poster looked up among the others. */
export function assetItems(list: readonly PickedAsset[]): LinkedItem[] {
  return list.map((a) => assetItem(a, list));
}

/** A resource as the picker shows it. */
export function resourceItem(r: { id: string; name: string; slug?: string | null }): LinkedItem {
  return { id: r.id, name: r.name, meta: r.slug ?? null };
}

/** A slug for an asset uploaded from a field: the name, lowercased with dashes, capped; a short stamp keeps a second "Untitled" apart. */
export function uploadSlug(name: string, stamp: string = Date.now().toString(36)): string {
  const base = name
    .toLowerCase()
    .replace(/\.[a-z0-9]{1,5}$/, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return stamp ? `${base || "asset"}-${stamp}` : base || "asset";
}

/** The name an upload starts with: the file's name without its extension, underscores and dashes as spaces. */
export function nameFromFile(filename: string): string {
  return filename.replace(/\.[a-z0-9]{1,5}$/i, "").replace(/[_-]+/g, " ").trim() || filename;
}

