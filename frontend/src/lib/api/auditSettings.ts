/**
 * Event Log audit settings (/api/groups/audit-settings).
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 * Plain fetchApi until the generated SDK types carry these routes.
 */

import type { AuditEventSetting, AuditExcludedEvent, AuditOverrides } from "../auditSettings";
import { fetchApi } from "./client";

const BASE = "/api/groups/audit-settings";

/** Every catalog event type with its audit setting. ADMIN/OWNER (403 otherwise). */
export async function getAuditSettings(authToken?: string): Promise<AuditEventSetting[]> {
  return fetchApi(BASE, {}, authToken);
}

/** The event types this workspace's Event Log leaves out. Any member. */
export async function getExcludedEventTypes(authToken?: string): Promise<AuditExcludedEvent[]> {
  return fetchApi(`${BASE}/excluded`, {}, authToken);
}

/** Merge overrides (null = back to the default); returns every type's setting afterwards. ADMIN/OWNER. */
export async function updateAuditSettings(overrides: AuditOverrides, authToken?: string): Promise<AuditEventSetting[]> {
  return fetchApi(
    BASE,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ overrides }) },
    authToken,
  );
}
