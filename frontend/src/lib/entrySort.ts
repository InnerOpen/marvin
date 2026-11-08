/**
 * How the Entries list is ordered: a `sort` address parameter the page reads, applied to the plain list here and handed to the entries
 * query (its own `sort` key) when there are conditions, so both show the same order.
 */

export const ENTRY_SORTS = {
  newest: "Newest first",
  oldest: "Oldest first",
  updated: "Recently updated",
  title: "Title A–Z",
} as const;

export type EntrySort = keyof typeof ENTRY_SORTS;
export const DEFAULT_ENTRY_SORT: EntrySort = "newest";

export function readEntrySort(value: string | null | undefined): EntrySort {
  return value && value in ENTRY_SORTS ? (value as EntrySort) : DEFAULT_ENTRY_SORT;
}

/** The query spec's `sort` for this order (services/entries/query.py: `{by, direction}`). */
export function querySort(sort: EntrySort): { by: string; direction: "asc" | "desc" } {
  switch (sort) {
    case "oldest":
      return { by: "created_at", direction: "asc" };
    case "updated":
      return { by: "updated_at", direction: "desc" };
    case "title":
      return { by: "title", direction: "asc" };
    default:
      return { by: "created_at", direction: "desc" };
  }
}

interface Sortable {
  title?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

const when = (v: string | null | undefined): number => (v ? Date.parse(v) || 0 : 0);

/** The plain list in this order (a new array; ties keep their place). */
export function sortEntries<T extends Sortable>(entries: readonly T[], sort: EntrySort): T[] {
  const out = [...entries];
  const by: (a: T, b: T) => number =
    sort === "title"
      ? (a, b) => (a.title ?? "").localeCompare(b.title ?? "", undefined, { sensitivity: "base" })
      : sort === "oldest"
        ? (a, b) => when(a.createdAt) - when(b.createdAt)
        : sort === "updated"
          ? (a, b) => when(b.updatedAt ?? b.createdAt) - when(a.updatedAt ?? a.createdAt)
          : (a, b) => when(b.createdAt) - when(a.createdAt);
  return out.sort(by);
}
