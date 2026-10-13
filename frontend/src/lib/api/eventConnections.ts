/**
 * Events hub reads: what sends an event type and what reacts to it. Workspace OWNER/ADMIN for the workspace
 * routes, super admin for the admin one. Pass authToken in SSR (from Astro.cookies); omit it in the browser.
 * Plain fetchApi until the SDK release carries these routes.
 */

import type { AdminEventConnections, EventConnectionCounts, EventConnections } from "../eventConnections";
import { fetchApi } from "./client";

/** Every workspace event type: how many senders and reactions it has, and when it last happened. */
export async function getEventConnectionsSummary(authToken?: string): Promise<EventConnectionCounts[]> {
  return fetchApi("/api/platform/event-types/connections", {}, authToken);
}

/** One workspace event type's senders, reactions, newest events and chain. 404 for a platform type. */
export async function getEventConnections(
  eventType: string,
  authToken?: string,
  limit = 10,
): Promise<EventConnections> {
  return fetchApi(
    `/api/platform/event-types/${encodeURIComponent(eventType)}/connections?limit=${limit}`,
    {},
    authToken,
  );
}

/** A platform event type's senders and reactions (built in, then by workspace). Super admin. */
export async function getAdminEventConnections(eventType: string, authToken?: string): Promise<AdminEventConnections> {
  return fetchApi(`/api/admin/event-types/${encodeURIComponent(eventType)}/connections?limit=1`, {}, authToken);
}
