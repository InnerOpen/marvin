/**
 * The platform admin's Events page (/admin/events): filters from the page's query string, the API query they
 * become, and display helpers. Free of the DOM so it runs under `node --test` (events.test.mjs).
 *
 * Dates are whole days in UTC: the filter form is a plain GET the server renders, so it can't know the viewer's
 * zone. The page says so next to the inputs and shows every time in UTC too.
 */

export interface AdminEventFilters {
  eventType: string;
  workspaceId: string;
  /** YYYY-MM-DD (UTC), inclusive. */
  from: string;
  /** YYYY-MM-DD (UTC), inclusive. */
  to: string;
  page: number;
}

export interface PlatformEventType {
  eventType: string;
  name: string;
  description: string;
  category: string;
}

export interface AdminEventSummary {
  eventId: string;
  eventType: string;
  eventName: string;
  occurredAt: string;
  messageTitle: string;
  messageBody: string | null;
  workspaceId: string | null;
  workspaceName: string | null;
  workspaceSlug: string | null;
  userId: string | null;
  userName: string | null;
  userEmail: string | null;
  entityId: string | null;
  entityType: string | null;
}

/** PaginationBase keeps its own keys in snake_case; the items are camelCase. */
export interface AdminEventPage {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
  items: AdminEventSummary[];
}

export const PER_PAGE = 50;

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EVENT_TYPE = /^[a-z0-9_]+$/;

function isDay(value: string): boolean {
  if (!DAY.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().startsWith(value);
}

/** The page's filters from its query string; anything malformed is dropped rather than sent on. */
export function parseFilters(params: URLSearchParams): AdminEventFilters {
  const get = (key: string) => (params.get(key) ?? "").trim();
  const eventType = get("type");
  const workspaceId = get("workspace");
  const from = get("from");
  const to = get("to");
  const page = Number.parseInt(get("page"), 10);
  return {
    eventType: EVENT_TYPE.test(eventType) ? eventType : "",
    workspaceId: UUID.test(workspaceId) ? workspaceId : "",
    from: isDay(from) ? from : "",
    to: isDay(to) ? to : "",
    page: Number.isFinite(page) && page >= 1 ? page : 1,
  };
}

/** The query string for GET /api/admin/events: the days become a UTC range, `to` inclusive. */
export function apiQuery(filters: AdminEventFilters, perPage: number = PER_PAGE): string {
  const q = new URLSearchParams({ page: String(filters.page), per_page: String(perPage) });
  if (filters.eventType) q.set("event_type", filters.eventType);
  if (filters.workspaceId) q.set("workspace_id", filters.workspaceId);
  if (filters.from) q.set("start_date", `${filters.from}T00:00:00Z`);
  if (filters.to) q.set("end_date", `${filters.to}T23:59:59.999Z`);
  return q.toString();
}

/** A link to this page with the same filters on another page number. */
export function pageHref(filters: AdminEventFilters, page: number): string {
  const q = new URLSearchParams();
  if (filters.eventType) q.set("type", filters.eventType);
  if (filters.workspaceId) q.set("workspace", filters.workspaceId);
  if (filters.from) q.set("from", filters.from);
  if (filters.to) q.set("to", filters.to);
  if (page > 1) q.set("page", String(page));
  const qs = q.toString();
  return qs ? `/admin/events?${qs}` : "/admin/events";
}

export function hasFilters(filters: AdminEventFilters): boolean {
  return Boolean(filters.eventType || filters.workspaceId || filters.from || filters.to);
}

/** "2026-10-05 14:03 UTC"; "—" when missing or unreadable. */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.replace(/(\.\d{3})\d+/, "$1"));
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** Event types grouped by category, in the order the API sent them (categories in display order). */
export function groupTypesByCategory(types: PlatformEventType[]): { category: string; types: PlatformEventType[] }[] {
  const groups = new Map<string, PlatformEventType[]>();
  for (const t of types) {
    const list = groups.get(t.category) ?? [];
    list.push(t);
    groups.set(t.category, list);
  }
  return Array.from(groups, ([category, list]) => ({ category, types: list }));
}

/** "Showing 51–100 of 230"; "No events" when the page is empty. */
export function rangeLabel(page: AdminEventPage): string {
  if (!page.total || page.items.length === 0) return "No events";
  const first = (page.page - 1) * page.per_page + 1;
  const last = first + page.items.length - 1;
  return `Showing ${first}–${last} of ${page.total}`;
}
