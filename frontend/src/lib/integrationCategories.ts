// The Integrations page groups its connected list and its catalog by what a provider is for (its
// `category`), in one order. Pure, so `npm test` covers it (integrationCategories.test.mjs).

/** The order the groups appear in: where alerts can go first, then where content goes, then the rest. */
export const CATEGORY_ORDER = ["notify", "destination", "capability", "source"] as const;

export const CATEGORY_LABEL: Record<string, string> = {
  notify: "Notify",
  destination: "Destination",
  capability: "Capability",
  source: "Source",
};

/** A category a provider doesn't declare (or a connection whose plugin isn't installed). */
export const OTHER = "other";

export interface CategoryGroup<T> {
  category: string;
  label: string;
  items: T[];
}

/** `items` in groups by category: the known ones in CATEGORY_ORDER, then any other (alphabetically), then
 * those with none. Empty groups are left out; each group keeps its items' order. With `first`, that group
 * leads (the catalog's focused group). */
export function groupByCategory<T>(
  items: T[],
  categoryOf: (item: T) => string | null | undefined,
  first?: string | null,
): CategoryGroup<T>[] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const category = categoryOf(item) || OTHER;
    groups.set(category, [...(groups.get(category) ?? []), item]);
  }
  const rank = (c: string) => {
    if (c === first) return -1;
    const known = (CATEGORY_ORDER as readonly string[]).indexOf(c);
    return known >= 0 ? known : c === OTHER ? CATEGORY_ORDER.length + 1 : CATEGORY_ORDER.length;
  };
  return [...groups.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((category) => ({ category, label: categoryLabel(category), items: groups.get(category) ?? [] }));
}

export function categoryLabel(category: string): string {
  if (category === OTHER) return "Other";
  return CATEGORY_LABEL[category] ?? category.charAt(0).toUpperCase() + category.slice(1);
}

/** The `?category=` asked for, when it names a group the page can show; else null. */
export function focusedCategory(param: string | null, present: Iterable<string>): string | null {
  const wanted = (param ?? "").trim().toLowerCase();
  return wanted && [...present].includes(wanted) ? wanted : null;
}
