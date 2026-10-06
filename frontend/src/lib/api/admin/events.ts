/**
 * Admin Events API (/api/admin/events): platform events across workspaces. Super admin only.
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 * Plain fetchApi until the generated SDK types carry these routes.
 */

import type { AdminEventPage, AdminEventSummary, PlatformEventType } from "../../admin/events";
import { fetchApi } from "../client";

const BASE = "/api/admin/events";

export interface AdminEventRead extends AdminEventSummary {
  integrationId: string;
  correlationId: string | null;
  eventData: Record<string, unknown>;
}

/** One page of platform events, newest first. `query` comes from `apiQuery()` in lib/admin/events. */
export async function listAdminEvents(query: string, authToken?: string): Promise<AdminEventPage> {
  return fetchApi(`${BASE}?${query}`, {}, authToken);
}

/** One platform event with its payload. */
export async function getAdminEvent(eventId: string, authToken?: string): Promise<AdminEventRead> {
  return fetchApi(`${BASE}/${encodeURIComponent(eventId)}`, {}, authToken);
}

/** The platform event types, categories in display order, for the type filter. */
export async function listPlatformEventTypes(authToken?: string): Promise<PlatformEventType[]> {
  return fetchApi(`${BASE}/catalog`, {}, authToken);
}
