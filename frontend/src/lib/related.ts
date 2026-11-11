/**
 * Related entries: what points at an entry. Entries have no native relation field, so a child holds its parent's slug in a field of its own
 * (a beat's `story`, a line's `beat`, a take's `line`) and "which beats are in this story" is a lookup the other way. An entry type says
 * which lookups to show on its entries' pages with `children` in its schema: `[{title: "Beats", entry_type: "beat", field: "story"}]`.
 * The pure part; relatedApi.ts asks the entries API.
 */

export interface RelatedSpec {
  title: string;
  entry_type: string;
  field: string;
}

const SLUG = /^[a-z0-9][a-z0-9_-]{0,79}$/;
const FIELD = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;
export const MAX_RELATED = 10;

/** The well-formed `children` of a schema, in order (at most ten): each a title, the child entry type and the field holding the parent's slug. */
export function childrenOf(schema: { children?: unknown } | null | undefined): RelatedSpec[] {
  const raw = Array.isArray(schema?.children) ? schema!.children : [];
  return raw
    .flatMap((c): RelatedSpec[] => {
      const x = c as Partial<RelatedSpec> | null;
      return x && typeof x.title === "string" && x.title.trim() && typeof x.entry_type === "string" && SLUG.test(x.entry_type) && typeof x.field === "string" && FIELD.test(x.field)
        ? [{ title: x.title.trim(), entry_type: x.entry_type, field: x.field }]
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
