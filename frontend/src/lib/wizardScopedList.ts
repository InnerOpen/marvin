/**
 * A `list` step without a parent: the entries of a type that meet the step's `where` (or its `or_where`), as cards a page at a time, with
 * a search, filters and the `columns` editable on each card ("Art price check": every piece for sale, its price, shipping and Sell online,
 * and a "Looks right" button). The pure part: what the step asks the entries API, what a page shows and what a save changes. Whether an
 * entry meets a condition is always the server's answer (the entries query), never worked out here: the page asks once for the list and
 * once per flag, and filters, searches and pages those answers.
 */

import { type Ctx, type Step, FACET_PARAM, FILTER_PARAM, SEARCH_PARAM, substitute } from "./wizard.ts";

export interface Cond {
  field: string;
  op?: string;
  value?: unknown;
}

export interface Flag {
  label: string;
  where: Cond[];
  /** false: the card shows it, but it does not need attention ("Not for sale online"). */
  attention?: boolean;
}

export interface ListRow {
  id: string;
  slug: string;
  title: string;
  dataJson?: Record<string, unknown> | null;
}

/** A list step lists the entries of a type narrowed by `where` instead of those that belong to a parent. */
export function isScopedList(step: Step | null | undefined): boolean {
  return !!step && step.kind === "list" && !step.parent && !step.parent_field;
}

/** The entries queries behind a scoped list, with the choices filled in: its `where`, then its `or_where` (whose entries are listed too). */
export function scopedSpecs(step: Step, ctx: Ctx): Record<string, unknown>[] {
  const base = (where: Cond[] | undefined) => (where?.length ? { entry_type: step.entry_type, where: substitute(where, ctx) } : { entry_type: step.entry_type });
  return [base(step.where), ...(step.or_where?.length ? [base(step.or_where)] : [])];
}

/** The rows of several queries, each once, in the order first met. */
export function unionRows<T extends { id: string }>(lists: T[][]): T[] {
  const seen = new Set<string>();
  return lists.flat().filter((r) => (seen.has(r.id) ? false : (seen.add(r.id), true)));
}

/** The query that says which of these rows meet a flag: the flag's conditions over exactly them. */
export function flagSpec(step: Step, flag: Flag, ids: string[]): Record<string, unknown> {
  return { entry_type: step.entry_type, entries: ids, where: flag.where };
}

/** The filters a scoped list offers, besides one per flag (`flag-0`…): everything, what needs attention, and with a `check`, the
 *  ones not checked yet and the checked ones. */
export const FILTERS = ["all", "attention", "unchecked", "checked"] as const;
/** A scoped list starts at 25 cards a page (25, 50 or 100): every save on a card can start work (a Square listing), so a page is a small batch. */
export const SCOPED_PER = 25;

export interface ListState {
  filter: string;
  facet: string;
  q: string;
}

/** The filters this step offers: FILTERS (the checked ones only with a `check`), then one per flag. */
export function filtersOf(step: Step): string[] {
  const own = FILTERS.filter((f) => step.check || (f !== "unchecked" && f !== "checked"));
  return [...own, ...((step.flags ?? []) as Flag[]).map((_f, n) => `flag-${n}`)];
}

/** The filter, facet value and search the address asks for; anything else is the whole list. */
export function readListState(params: URLSearchParams, step: Step): ListState {
  const asked = (params.get(FILTER_PARAM) ?? "").trim();
  return {
    filter: filtersOf(step).includes(asked) ? asked : "all",
    facet: step.facet ? (params.get(FACET_PARAM) ?? "").trim().slice(0, 80) : "",
    q: (params.get(SEARCH_PARAM) ?? "").replace(/\s+/g, " ").trim().slice(0, 100),
  };
}

/** The address parameters that keep a list's state across a save (empty ones left out). */
export function listParams(state: ListState): Record<string, string> {
  return Object.fromEntries(
    [
      [FILTER_PARAM, state.filter === "all" ? "" : state.filter],
      [FACET_PARAM, state.facet],
      [SEARCH_PARAM, state.q],
    ].filter(([, v]) => v),
  );
}

const isOn = (v: unknown) => v === true || v === "true";

/** A facet value as words: "small-canvases" reads "Small canvases". */
export function facetLabel(value: string): string {
  const words = value.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export interface ListView<T extends ListRow> {
  /** This page's cards. */
  rows: T[];
  /** How many meet the filter, facet and search (what the pages page through). */
  total: number;
  page: number;
  /** How many each filter would show, within the facet value and search. */
  counts: Record<string, number>;
  /** The facet's values with how many cards each has (over the whole list), in the order the field lists its options. */
  facets: { value: string; label: string; count: number }[];
  /** How many of the whole list are checked. */
  checked: number;
  all: number;
}

/**
 * What a page of a scoped list shows. `flagged` holds, per flag, the ids the server said meet it. Search is by name (title or slug,
 * ignoring case); the facet is one value of the facet field; the filter one of FILTERS or a flag. Cards run by name as people count
 * (2 before 10), and a page past the end shows the last one.
 */
export function listView<T extends ListRow>(
  all: T[],
  step: Step,
  flagged: Set<string>[],
  state: ListState,
  paging: { page: number; per: number },
  facetOptions: string[] = [],
): ListView<T> {
  const flags = (step.flags ?? []) as Flag[];
  const check: string | undefined = step.check?.field;
  const attention = (r: T) => flags.some((f, n) => f.attention !== false && flagged[n]?.has(r.id));
  const checked = (r: T) => !!check && isOn(r.dataJson?.[check]);
  const tests: Record<string, (r: T) => boolean> = {
    all: () => true,
    attention,
    unchecked: (r) => !checked(r),
    checked,
    ...Object.fromEntries(flags.map((_f, n) => [`flag-${n}`, (r: T) => !!flagged[n]?.has(r.id)])),
  };
  const facetOf = (r: T) => String(r.dataJson?.[step.facet] ?? "");
  const words = state.q.toLowerCase();
  const sorted = [...all].sort((a, b) => (a.title ?? "").localeCompare(b.title ?? "", undefined, { numeric: true, sensitivity: "base" }));
  const narrowed = sorted.filter((r) => (!state.facet || facetOf(r) === state.facet) && (!words || `${r.title} ${r.slug}`.toLowerCase().includes(words)));
  const counts = Object.fromEntries(filtersOf(step).map((k) => [k, narrowed.filter(tests[k]).length]));
  const shown = narrowed.filter(tests[state.filter] ?? tests.all);
  const last = Math.max(1, Math.ceil(shown.length / paging.per));
  const page = Math.min(Math.max(1, paging.page), last);
  const tally = new Map<string, number>();
  if (step.facet) for (const r of all) if (facetOf(r)) tally.set(facetOf(r), (tally.get(facetOf(r)) ?? 0) + 1);
  const order = (v: string) => (facetOptions.indexOf(v) < 0 ? facetOptions.length : facetOptions.indexOf(v));
  const facets = [...tally.entries()].sort(([a], [b]) => order(a) - order(b) || a.localeCompare(b)).map(([value, count]) => ({ value, label: facetLabel(value), count }));
  return {
    rows: shown.slice((page - 1) * paging.per, page * paging.per),
    total: shown.length,
    page,
    counts,
    facets,
    checked: all.filter(checked).length,
    all: all.length,
  };
}

/** The flags a card shows: the labels of the flags the server said it meets, each with whether it needs attention. */
export function flagsOf(id: string, step: Step, flagged: Set<string>[]): { label: string; attention: boolean }[] {
  return ((step.flags ?? []) as Flag[]).flatMap((f, n) => (flagged[n]?.has(id) ? [{ label: f.label, attention: f.attention !== false }] : []));
}

/** The keys a scoped list may write: exactly its `columns` and its `check` field, nothing the type adds (a required field is not
 *  asked here: the list edits what is there and makes nothing). */
export function editableKeys(step: Step): string[] {
  return [...new Set([...((step.columns ?? []) as string[]), ...(step.check?.field ? [step.check.field] : [])])];
}

/** Which of a card's fields the person changed: the text each box posted against the text the page drew from `was` (a number field
 *  holding "10.00" posts "10.00", which is no change, though it would read as 10). A yes/no field compares as on or off, unset being
 *  off, so a switch left off on a card that never had the field changes nothing. `posted` holds what the form sent per key (null: nothing,
 *  as an unticked box). Only these keys are then read as their types and written. */
export function changedKeys(posted: Record<string, string | null>, was: Record<string, unknown>, booleans: string[]): string[] {
  const text = (v: unknown) => (v === null || v === undefined ? "" : String(v)).replace(/\r\n/g, "\n"); // a box posts its line breaks as \r\n
  return Object.keys(posted).filter((k) => (booleans.includes(k) ? isOn(posted[k]) !== isOn(was[k]) : text(posted[k]) !== text(was[k])));
}
