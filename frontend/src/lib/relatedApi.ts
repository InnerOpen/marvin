/** The related entries of an entry (lib/related.ts), from the entries API, on the server. */

import { fetchApi } from "./api/client";
import { type RelatedGroup, childrenOf } from "./related";
import { naturalByTitle } from "./wizard";

const SHOWN = 30;

/** For each `children` lookup of the schema: how many entries point at this one and the first few, by title as people count. A lookup that fails shows nothing. */
export async function relatedFor(
  schema: { children?: unknown } | null | undefined,
  entry: { slug?: string | null },
  authToken: string | null | undefined,
): Promise<RelatedGroup[]> {
  const specs = childrenOf(schema);
  if (!specs.length || !entry.slug || !authToken) return [];
  const groups = await Promise.all(
    specs.map(async (c) => {
      const found = await fetchApi<{ entries?: { id: string; title?: string | null; status?: string | null }[]; total?: number }>(
        "/api/platform/entries/query",
        { method: "POST", body: JSON.stringify({ spec: { entry_type: c.entry_type, fields: { [c.field]: entry.slug } }, limit: SHOWN }) },
        authToken,
      ).catch(() => null);
      const rows = naturalByTitle(found?.entries ?? []).map((e) => ({ id: e.id, title: e.title?.trim() || "(untitled)", status: e.status ?? null }));
      return { title: c.title, entryType: c.entry_type, total: found?.total ?? rows.length, rows } satisfies RelatedGroup;
    }),
  );
  return groups.filter((g) => g.total > 0);
}
