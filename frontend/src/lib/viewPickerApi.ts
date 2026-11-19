/**
 * What a view's picker cards (lib/viewPicker.ts) read, on the server: the spine items of all the listed entries in ONE query (paged by the
 * API's 500 rows, a few pages at most), and the titles the subtitle's `ref` fields name (one query per type). The pictures and the video come
 * with the rows (an entry's attached assets), so nothing is fetched per card. Each part fails soft: a refused query leaves that part off.
 */

import type { RequestScope } from "./requestCache";
import type { Row, TimelineSpec } from "./timeline";
import { QUERY_MAX_ROWS, STRIP_MAX_PAGES, type PickerCard, pickerCard, refsWanted, stripLimit, stripQuery, stripsByOwner } from "./viewPicker";
import { fetchApi } from "./api/client";
import { typeBySlug } from "./wizardApi";

/** One page of an entries query; unlike wizardApi's findEntries a refusal throws, so a part that failed is left off, not shown as none. */
const query = (spec: Record<string, unknown>, authToken: string, offset: number) =>
  fetchApi<{ entries?: Row[]; total?: number }>("/api/platform/entries/query", { method: "POST", body: JSON.stringify({ spec, limit: QUERY_MAX_ROWS, offset }) }, authToken).then((found) => ({
    entries: found.entries ?? [],
    total: found.total ?? found.entries?.length ?? 0,
  }));

/** The spine items of these entries, in their order: as many pages as there are, up to STRIP_MAX_PAGES; `complete` says all were read. */
async function stripRows(spec: TimelineSpec, owners: string[], authToken: string): Promise<{ rows: Row[]; complete: boolean }> {
  const wanted = stripQuery(spec.spine, owners);
  const first = await query(wanted, authToken, 0);
  const pages = Math.min(STRIP_MAX_PAGES, Math.ceil(first.total / QUERY_MAX_ROWS));
  const rest = await Promise.all(Array.from({ length: Math.max(0, pages - 1) }, (_, i) => query(wanted, authToken, (i + 1) * QUERY_MAX_ROWS)));
  const rows = [first, ...rest].flatMap((page) => page.entries);
  return { rows, complete: rows.length >= first.total };
}

/** The titles of the entries the subtitle's `ref` fields name, by field: field -> slug -> title. */
async function refTitles(spec: TimelineSpec, entries: Row[], authToken: string, scope?: RequestScope): Promise<Map<string, Map<string, string>>> {
  const type = await typeBySlug(spec.entry_type, authToken, scope);
  const fields = ((type?.schemaJson ?? {}) as { fields?: { key?: string; ref?: unknown }[] }).fields ?? [];
  const refOf = (key: string) => {
    const ref = fields.find((f) => f.key === key)?.ref;
    return typeof ref === "string" && ref ? ref : undefined;
  };
  const byType = new Map<string, Map<string, string>>();
  await Promise.all(
    [...refsWanted(entries, spec.picker!, refOf)].map(async ([refType, slugs]) => {
      const found = await query({ entry_type: refType, entries: slugs.slice(0, QUERY_MAX_ROWS) }, authToken, 0).catch(() => null);
      if (found) byType.set(refType, new Map(found.entries.map((r: Row) => [r.slug, r.title])));
    }),
  );
  const out = new Map<string, Map<string, string>>();
  for (const f of fields) {
    const titles = f.key ? byType.get(refOf(f.key) ?? "") : undefined;
    if (f.key && titles) out.set(f.key, titles);
  }
  return out;
}

/** The view's entries as cards, each opening the entry in the view (`hrefOf`). */
export async function pickerCards(spec: TimelineSpec, entries: Row[], hrefOf: (slug: string) => string, authToken: string, scope?: RequestScope): Promise<PickerCard[]> {
  const picker = spec.picker;
  if (!picker || !entries.length) return [];
  const owners = entries.map((e) => e.slug);
  const [strips, titles] = await Promise.all([
    stripLimit(picker, spec.spine)
      ? stripRows(spec, owners, authToken)
          .then(({ rows, complete }) => stripsByOwner(rows, spec.spine.of, owners, complete))
          .catch(() => null)
      : null,
    picker.subtitle ? refTitles(spec, entries, authToken, scope).catch(() => new Map<string, Map<string, string>>()) : new Map<string, Map<string, string>>(),
  ]);
  return entries.map((row) => pickerCard(row, { picker, spine: spec.spine, href: hrefOf(row.slug), strip: strips?.get(row.slug) ?? null, titles }));
}
