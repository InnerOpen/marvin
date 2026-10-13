// When an entry save fails, the editor re-renders with what the user submitted instead of the stored
// entry, so nothing they typed is lost. Kept out of the page so it can be tested with plain
// `node --test` (see entryForm.test.mjs).

type Row = { id: string; [key: string]: any };
type Placement = { role?: string | null; metadata?: unknown };

/** Workspace lists to resolve submitted ids against (an attachment added in this edit isn't on the entry yet). */
export type EntryLookups = {
  collections: Row[];
  assets: Row[];
  resources: Row[];
  tags: { id: string; slug: string }[];
};

// Update-payload field → the entry's (camelCase) field, for values shown as submitted.
const SCALARS: [string, string][] = [
  ["title", "title"],
  ["summary", "summary"],
  ["description", "description"],
  ["status", "status"],
  ["metadata_json", "metadataJson"],
  ["publish_at", "publishAt"],
  ["expire_at", "expireAt"],
];

/** Submitted attachments in their submitted order, each the stored row (or the workspace's) plus its placement. */
function placed<P extends Placement>(
  submitted: P[],
  idOf: (p: P) => string,
  current: Row[],
  workspace: Row[],
  orderKey: string,
): Row[] {
  const rows: Row[] = [];
  for (const p of submitted) {
    const id = idOf(p);
    const base = current.find((r) => r.id === id) ?? workspace.find((r) => r.id === id);
    if (!base) continue; // gone since the page loaded
    rows.push({ ...base, role: p.role ?? null, placementMetadata: p.metadata ?? null, [orderKey]: rows.length });
  }
  return rows;
}

/**
 * `entry` with the values from a failed save's update payload (`submitted`, snake_case as sent) laid
 * over it. Fields the payload doesn't carry keep their stored values: a slug left blank (it's derived
 * on save), content when no field was posted, and AI-suggested assets, which the form never posts.
 * A status of "published" that didn't happen isn't shown either.
 */
export function withSubmittedValues<E extends Record<string, any>>(
  entry: E,
  submitted: Record<string, any>,
  lookups: EntryLookups,
): E {
  const out: Record<string, any> = { ...entry };
  for (const [field, key] of SCALARS) {
    if (field in submitted) out[key] = submitted[field];
  }
  // A refused publish left the entry as it was, so its status shows what's stored: Save then keeps
  // the other edits without retrying the publish, and Publish retries it.
  if (submitted.status === "published" && entry.status !== "published") out.status = entry.status;
  if (submitted.slug) out.slug = submitted.slug;
  if (submitted.data_json) out.dataJson = submitted.data_json;

  if (Array.isArray(submitted.tag_ids)) {
    const slugById = new Map(lookups.tags.map((t) => [t.id, t.slug]));
    out.tags = submitted.tag_ids.map((id: string) => slugById.get(id)).filter(Boolean);
  }
  if (Array.isArray(submitted.collection_attachments)) {
    out.collections = placed(
      submitted.collection_attachments,
      (p: any) => p.collection_id,
      entry.collections ?? [],
      lookups.collections,
      "sortOrder",
    );
  }
  if (Array.isArray(submitted.asset_attachments)) {
    const current: Row[] = entry.assets ?? [];
    const suggested = current.filter((a) => a.placementMetadata?.suggested);
    const confirmed = placed(submitted.asset_attachments, (p: any) => p.asset_id, current, lookups.assets, "position");
    out.assets = [...confirmed, ...suggested];
  }
  if (Array.isArray(submitted.resource_attachments)) {
    out.resources = placed(
      submitted.resource_attachments,
      (p: any) => p.resource_id,
      entry.resources ?? [],
      lookups.resources,
      "position",
    );
  }
  return out as E;
}

export const VIEW_ON_SITE_HINT = "Available once published";

/**
 * The Entry Details "View on site" button: none without a page URL (the type has no pattern), a link once the
 * entry is published, and otherwise a disabled button saying why — the URL exists but nothing is live there yet.
 */
export function viewOnSite(
  pageUrl: string | null | undefined,
  status: string | null | undefined,
): { href: string } | { disabled: true; hint: string } | null {
  if (!pageUrl) return null;
  return status === "published" ? { href: pageUrl } : { disabled: true, hint: VIEW_ON_SITE_HINT };
}
