/** The related entries of an entry (lib/related.ts), from the entries API, on the server. */

import { fetchApi } from "./api/client";
import { childrenOf, firstShown, type RelatedGroup, relatedQuery, SHOWN } from "./related";

type Row = { id: string; title?: string | null; status?: string | null };

/** For each `children` lookup of the schema: how many entries point at this one and the first few, in its own order or by title as people count. A lookup that fails shows nothing. */
export async function relatedFor(
  schema: { children?: unknown } | null | undefined,
  entry: { slug?: string | null },
  authToken: string | null | undefined,
): Promise<RelatedGroup[]> {
  const specs = childrenOf(schema);
  const slug = entry.slug;
  if (!specs.length || !slug || !authToken) return [];
  const groups = await Promise.all(
    specs.map(async (c) => {
      const found = await fetchApi<{ entries?: Row[]; total?: number }>(
        "/api/platform/entries/query",
        { method: "POST", body: JSON.stringify(relatedQuery(c, slug)) },
        authToken,
      ).catch(() => null);
      const rows = firstShown<Row>(found?.entries ?? [], SHOWN, c.sort).map((e) => ({ id: e.id, title: e.title?.trim() || "(untitled)", status: e.status ?? null }));
      return { title: c.title, entryType: c.entry_type, total: found?.total ?? rows.length, rows } satisfies RelatedGroup;
    }),
  );
  return groups.filter((g) => g.total > 0);
}
