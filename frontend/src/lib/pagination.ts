/**
 * Server-side paging for a long list (Entries, a collection's edit page): `?page=N` (1-based) and `?per=25|50|100` in the
 * address. Links keep every other parameter (the search's `c`, `sort`, …) so paging never drops a filter, and leave out
 * the one-shot ones (`trashed`: the Undo notice is for the page the entry was trashed from, not every page after it).
 * No imports: node's test runner loads this file as it is.
 */

export const PAGE_SIZES = [25, 50, 100] as const;
export const DEFAULT_PER = 50;
const ONE_SHOT = ["trashed"];

export interface PageState {
  page: number;
  per: number;
  offset: number;
}

export function readPage(params: URLSearchParams): PageState {
  const n = Number.parseInt(params.get("page") ?? "", 10);
  const page = Number.isFinite(n) && n >= 1 ? n : 1;
  const p = Number.parseInt(params.get("per") ?? "", 10);
  const per = (PAGE_SIZES as readonly number[]).includes(p) ? p : DEFAULT_PER;
  return { page, per, offset: (page - 1) * per };
}

/** The last page there is (1 when there is nothing, so an empty list is page 1). */
export function lastPage(total: number, per: number): number {
  return Math.max(1, Math.ceil(total / per));
}

const fmt = new Intl.NumberFormat("en-US");

/** "51–100 of 1,255"; empty when there is nothing to count. */
export function rangeText(page: number, per: number, total: number): string {
  if (total <= 0) return "";
  const first = (page - 1) * per + 1;
  const last = Math.min(page * per, total);
  return `${fmt.format(first)}–${fmt.format(last)} of ${fmt.format(total)}`;
}

/** This address with another page or page size (a new size starts again at page 1). Page 1 and the default size are
 *  left out of the address. */
export function pageHref(url: URL, change: { page?: number; per?: number }): string {
  const params = new URLSearchParams(url.search);
  for (const key of ONE_SHOT) params.delete(key);
  if (change.per !== undefined) {
    if (change.per === DEFAULT_PER) params.delete("per");
    else params.set("per", String(change.per));
    params.delete("page");
  }
  if (change.page !== undefined) {
    if (change.page <= 1) params.delete("page");
    else params.set("page", String(change.page));
  }
  const search = params.toString();
  return search ? `${url.pathname}?${search}` : url.pathname;
}

/** Where to send a page past the end (the last page; page 1 when there is nothing), or null when the page exists. */
export function pastEndHref(url: URL, total: number): string | null {
  const { page, per } = readPage(url.searchParams);
  const last = lastPage(total, per);
  return page > last ? pageHref(url, { page: last }) : null;
}

export interface Pager extends PageState {
  total: number;
  range: string;
  prev: string | null;
  next: string | null;
  sizes: { per: number; href: string; current: boolean }[];
}

/** Everything the pagination bar shows for this address and total. */
export function pager(url: URL, total: number): Pager {
  const state = readPage(url.searchParams);
  const { page, per } = state;
  return {
    ...state,
    total,
    range: rangeText(page, per, total),
    prev: page > 1 ? pageHref(url, { page: page - 1 }) : null,
    next: page < lastPage(total, per) ? pageHref(url, { page: page + 1 }) : null,
    sizes: PAGE_SIZES.map((n) => ({ per: n, href: pageHref(url, { per: n }), current: n === per })),
  };
}
