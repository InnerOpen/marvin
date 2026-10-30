// The asset / resource fields of a schema form (LinkedItemsField.astro): what the hidden input holds, how a chosen item
// is shown, and the search over the picker's list. Pure, so the page's own picker script and the tests share it.

export interface LinkedItem {
  id: string;
  name: string;
  /** A second line under the name: the mime type of an asset, the slug of a resource. */
  meta?: string | null;
  /** An image asset's public url, shown as a thumbnail; absent for other files and for resources. */
  imageUrl?: string | null;
  alt?: string | null;
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

/** An asset as the picker shows it. */
export function assetItem(a: { id: string; name: string; mimeType?: string | null; publicUrl?: string | null; altText?: string | null }): LinkedItem {
  const image = (a.mimeType ?? "").startsWith("image/") && a.publicUrl ? a.publicUrl : null;
  return { id: a.id, name: a.name, meta: a.mimeType ?? null, imageUrl: image, alt: a.altText ?? null };
}

/** A resource as the picker shows it. */
export function resourceItem(r: { id: string; name: string; slug?: string | null }): LinkedItem {
  return { id: r.id, name: r.name, meta: r.slug ?? null };
}
