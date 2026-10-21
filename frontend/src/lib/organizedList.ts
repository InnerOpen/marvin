// The shared list kit for the Automation pages (Workflows first; incoming webhooks, scheduled tasks, outgoing
// webhooks and custom events adopt it). Pure, so `npm test` covers it (organizedList.test.mjs).
//
// A page describes its items with a `ListAdapter` (how to read a name, searchable text, where the item came from,
// whether it is on, whether it needs attention, and any page-specific facets such as "Starts"), then:
//
//   const result = organize(items, adapter, integrations, filters, { query, linkedId });
//   result.sections   // Yours -> From the Library -> each integration by name -> From a removed integration
//                     // -> Marvin's own; only the ones with something to show
//   fromOptions(...)  // the From filter's choices (only sections that exist)
//   statusOptions({ attention: true })  // On / Off, plus Needs attention for pages that compute flags
//   loadFilters / saveFilters           // remembered per browser, in localStorage (never throws)
//
// Rendering lives in organizedListHtml.ts (section headings, cards' ⋯ menu) and organizedListView.ts (the DOM wiring).

export type SectionKind = "yours" | "library" | "integration" | "removed" | "system" | "group";

/** Where an item came from. All read-only, as the server records them. */
export interface ItemSource {
  /** A Workflow Library recipe id (workflows only). */
  recipe?: string | null;
  /** The integration (connection) that installed it. */
  integrationId?: string | null;
  /** Marvin's own (a platform scheduled task). */
  system?: boolean;
}

export interface ListAdapter<T> {
  id(item: T): string;
  name(item: T): string;
  /** Extra searchable text (a trigger summary, a URL host…). The name is always searched. */
  search?(item: T): string[];
  source(item: T): ItemSource | undefined;
  enabled(item: T): boolean;
  /** Needs attention (a failed last run, a plugin item that is off…). Pages without flags omit it. */
  attention?(item: T): boolean;
  /** Page-specific filters: facet id (the filter's key in `filters`) -> the item's value for it. */
  facets?: Record<string, (item: T) => string>;
  /** For pages whose sections are not "where it came from" (custom events: what sends them): the sections' keys and
   * titles, in order, and which one an item is in. The From filter then offers these. */
  groups?: { choices: Choice[]; of(item: T): string };
}

export interface IntegrationInfo {
  name: string;
  /** The provider slug, icon and logo flag, for the heading's mark (lib/integrationLogo.ts). */
  slug?: string;
  icon?: string;
  hasLogo?: boolean;
}

/** The workspace's integrations by id. A source integration missing from it has been removed. */
export type Integrations = Record<string, IntegrationInfo>;

/** What the filter bar holds: `from` (a section key), `status` ("on" | "off" | "attention") and each facet. Blank: all. */
export type ListFilters = Record<string, string | undefined>;

export interface Section<T> {
  /** "yours" | "library" | "integration:<id>" | "removed" | "system": also the From filter's values. */
  key: string;
  kind: SectionKind;
  title: string;
  integrationId?: string;
  /** What is shown: enabled first, then by name. */
  items: T[];
  count: number;
  on: number;
}

export interface Organized<T> {
  sections: Section<T>[];
  shown: number;
  /** The linked item is among those shown. */
  linkedShown: boolean;
}

export interface Choice {
  value: string;
  label: string;
}

export const SECTION_TITLE: Record<Exclude<SectionKind, "integration" | "group">, string> = {
  yours: "Yours",
  library: "From the Library",
  removed: "From a removed integration",
  system: "Marvin's own",
};

/** The empty-filter message (the Library's wording). */
export const emptyMessage = (noun: string) => `No ${noun} matches. Try another search, or show all.`;

/** Which section an item's source puts it in. */
export function sectionKey(source: ItemSource | undefined, integrations: Integrations): string {
  if (source?.system) return "system";
  if (source?.integrationId)
    return source.integrationId in integrations ? `integration:${source.integrationId}` : "removed";
  if (source?.recipe) return "library";
  return "yours";
}

const kindOf = (key: string): SectionKind => (key.startsWith("integration:") ? "integration" : (key as SectionKind));

/** The section an item is in: the page's own grouping if it has one, else by source. */
function keyOf<T>(item: T, adapter: ListAdapter<T>, integrations: Integrations): string {
  return adapter.groups ? adapter.groups.of(item) : sectionKey(adapter.source(item), integrations);
}

function titleFor<T>(key: string, adapter: ListAdapter<T>, integrations: Integrations): string {
  return adapter.groups
    ? (adapter.groups.choices.find((c) => c.value === key)?.label ?? key)
    : titleOf(key, integrations);
}

function compareFor<T>(adapter: ListAdapter<T>, integrations: Integrations) {
  const order = adapter.groups?.choices.map((c) => c.value);
  return (a: string, b: string) => (order ? order.indexOf(a) - order.indexOf(b) : compareKeys(a, b, integrations));
}

const ORDER: SectionKind[] = ["yours", "library", "integration", "removed", "system"];

function titleOf(key: string, integrations: Integrations): string {
  const kind = kindOf(key);
  if (kind !== "integration") return SECTION_TITLE[kind];
  return integrations[key.slice("integration:".length)]?.name ?? "an integration";
}

function compareKeys(a: string, b: string, integrations: Integrations): number {
  const [ka, kb] = [ORDER.indexOf(kindOf(a)), ORDER.indexOf(kindOf(b))];
  if (ka !== kb) return ka - kb;
  return titleOf(a, integrations).localeCompare(titleOf(b, integrations));
}

function matchesFilters<T>(
  item: T,
  adapter: ListAdapter<T>,
  integrations: Integrations,
  filters: ListFilters,
  query: string,
): boolean {
  if (filters.from && keyOf(item, adapter, integrations) !== filters.from) return false;
  const status = filters.status;
  if (status === "on" && !adapter.enabled(item)) return false;
  if (status === "off" && adapter.enabled(item)) return false;
  if (status === "attention" && !adapter.attention?.(item)) return false;
  for (const [id, read] of Object.entries(adapter.facets ?? {})) {
    if (filters[id] && read(item) !== filters[id]) return false;
  }
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = [adapter.name(item), ...(adapter.search?.(item) ?? [])].join(" ").toLowerCase();
  return words.every((word) => haystack.includes(word));
}

/** Group, filter and order a page's items. The linked item (`?workflow=<id>`) is shown whatever the filters say. */
export function organize<T>(
  items: T[],
  adapter: ListAdapter<T>,
  integrations: Integrations,
  filters: ListFilters = {},
  options: { query?: string; linkedId?: string | null } = {},
): Organized<T> {
  const { query = "", linkedId = null } = options;
  const groups = new Map<string, T[]>();
  let shown = 0;
  let linkedShown = false;
  for (const item of items) {
    const linked = linkedId !== null && adapter.id(item) === linkedId;
    if (!linked && !matchesFilters(item, adapter, integrations, filters, query)) continue;
    const key = keyOf(item, adapter, integrations);
    groups.set(key, [...(groups.get(key) ?? []), item]);
    shown += 1;
    linkedShown ||= linked;
  }
  const sections = [...groups.keys()].sort(compareFor(adapter, integrations)).map((key): Section<T> => {
    const sorted = [...(groups.get(key) ?? [])].sort(
      (a, b) =>
        Number(adapter.enabled(b)) - Number(adapter.enabled(a)) || adapter.name(a).localeCompare(adapter.name(b)),
    );
    return {
      key,
      kind: adapter.groups ? "group" : kindOf(key),
      title: titleFor(key, adapter, integrations),
      ...(key.startsWith("integration:") ? { integrationId: key.slice("integration:".length) } : {}),
      items: sorted,
      count: sorted.length,
      on: sorted.filter((i) => adapter.enabled(i)).length,
    };
  });
  return { sections, shown, linkedShown };
}

/** "5 workflows, 4 on" for a section heading. */
export function countsText(
  section: Pick<Section<unknown>, "count" | "on">,
  noun: string,
  options: { onOff?: boolean } = {},
): string {
  const count = `${section.count} ${noun}${section.count === 1 ? "" : "s"}`;
  return options.onOff === false ? count : `${count}, ${section.on} on`;
}

/** The From filter's choices: the sections that exist for these items, in section order. */
export function fromOptions<T>(items: T[], adapter: ListAdapter<T>, integrations: Integrations): Choice[] {
  const keys = new Set(items.map((item) => keyOf(item, adapter, integrations)));
  return [...keys]
    .sort(compareFor(adapter, integrations))
    .map((key) => ({ value: key, label: titleFor(key, adapter, integrations) }));
}

export const STATUS_OPTIONS: Choice[] = [
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
];

/** The Status filter's choices. Pages that compute attention flags pass `{ attention: true }` for Needs attention. */
export function statusOptions(options: { attention?: boolean } = {}): Choice[] {
  return options.attention ? [{ value: "attention", label: "Needs attention" }, ...STATUS_OPTIONS] : STATUS_OPTIONS;
}

// ── Remembered filters (per browser, per page) ──────────────────────────────

export type KeyValueStore = Pick<Storage, "getItem" | "setItem">;

/** localStorage, or null where it is blocked (private mode, site data off). */
export function browserStore(): KeyValueStore | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The remembered filters. `allowed` lists each filter's valid values: one no longer offered (an integration since
 * removed) falls back to All. Never throws. */
export function loadFilters(
  store: KeyValueStore | null,
  key: string,
  allowed: Record<string, string[]>,
): Record<string, string> {
  let saved: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(store?.getItem(key) ?? "{}");
    if (parsed && typeof parsed === "object") saved = parsed;
  } catch {
    // unreadable: start from All
  }
  return Object.fromEntries(
    Object.entries(allowed).map(([id, values]) => [
      id,
      typeof saved[id] === "string" && values.includes(saved[id] as string) ? (saved[id] as string) : "",
    ]),
  );
}

/** Filters named by the page's URL (`?from=integration:<id>&status=off`): the way another page links here already filtered.
 * Only values the page offers count; the rest are dropped. A filter that is not in the result is left to what was remembered. */
export function urlFilters(search: string, allowed: Record<string, string[]>): Record<string, string> {
  const params = new URLSearchParams(search);
  const found: Record<string, string> = {};
  for (const [id, values] of Object.entries(allowed)) {
    const value = params.get(id);
    if (value && values.includes(value)) found[id] = value;
  }
  return found;
}

export function saveFilters(store: KeyValueStore | null, key: string, filters: ListFilters): void {
  try {
    store?.setItem(key, JSON.stringify(filters));
  } catch {
    // blocked or full: just don't remember
  }
}
