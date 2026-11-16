/**
 * Related entries: what points at an entry. Entries have no native relation field, so a child holds its parent's slug in a field of its own
 * (a beat's `story`, a line's `beat`, a take's `line`) and "which beats are in this story" is a lookup the other way. An entry type says
 * which lookups to show on its entries' pages with `children` in its schema: `[{title: "Beats", entry_type: "beat", field: "story"}]`.
 * A lookup may name its order as a guided step does (`sort: {by, direction?, then?}`, wizard.ts sortOf): a story's beats by number, its
 * scenes by `created_at` (as the script met them); without one it lists by title as people count. The pure part; relatedApi.ts asks the
 * entries API.
 */

import { naturalByTitle, type QuerySort, sortOf } from "./wizard.ts";

export interface RelatedSpec {
  title: string;
  entry_type: string;
  field: string;
  sort?: QuerySort;
}

const SLUG = /^[a-z0-9][a-z0-9_-]{0,79}$/;
const FIELD = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;
export const MAX_RELATED = 10;

/** The well-formed `children` of a schema, in order (at most ten): each a title, the child entry type, the field holding the parent's
 *  slug and its own order when it names a well-formed one (a malformed one is left out: by title). */
export function childrenOf(schema: { children?: unknown } | null | undefined): RelatedSpec[] {
  const raw = Array.isArray(schema?.children) ? schema!.children : [];
  return raw
    .flatMap((c): RelatedSpec[] => {
      const x = c as Partial<RelatedSpec> | null;
      return x && typeof x.title === "string" && x.title.trim() && typeof x.entry_type === "string" && SLUG.test(x.entry_type) && typeof x.field === "string" && FIELD.test(x.field)
        ? [{ title: x.title.trim(), entry_type: x.entry_type, field: x.field, ...sortOf(x.sort) }]
        : [];
    })
    .slice(0, MAX_RELATED);
}

export interface RelatedGroup {
  title: string;
  entryType: string;
  total: number;
  rows: { id: string; title: string; status: string | null }[];
}

/** How many of a lookup's entries the page lists. */
export const SHOWN = 30;
/** How many a lookup without its own order asks for before choosing the first ones: the server cannot sort "Beat 9" before "Beat 10" by
 *  title, so the page does, and it needs more than it shows. */
export const FETCHED = 200;

/** The entries query behind a lookup: the child entries holding this one's slug. One with its own order asks the server for it and for
 *  only the rows shown, so every match is ordered before the cut (a story's 300 beats: 1001 first, not whichever 200 came back). */
export function relatedQuery(spec: RelatedSpec, slug: string): { spec: Record<string, unknown>; limit: number } {
  return { spec: { entry_type: spec.entry_type, fields: { [spec.field]: slug }, ...sortOf(spec.sort) }, limit: spec.sort ? SHOWN : FETCHED };
}

/** The first `shown` of a lookup's entries: as the server ordered them when the lookup names its own order, else as people count titles
 *  (Beat 2 before Beat 10), chosen from everything fetched: the list's start, not an arbitrary few. */
export function firstShown<T extends { title?: string | null }>(rows: T[], shown = SHOWN, sort?: QuerySort): T[] {
  return (sort ? rows : naturalByTitle(rows)).slice(0, shown);
}
