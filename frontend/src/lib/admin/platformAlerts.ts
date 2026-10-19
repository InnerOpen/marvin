// Admin → Platform alerts: the page's pure helpers (building the save payload; the ones every alert page
// shares are lib/alerts.ts's, re-exported here). Run the tests with `npm test`.

import { cleanArgs, parseRecipients } from "../alerts.ts";
import type { PlatformAlertRoute, PlatformAlertsUpdate, PlatformConnection } from "../api/admin/platformAlerts";

export { deliveryBadge, missingInputs, parseRecipients, type Tone, targetKey } from "../alerts.ts";

/** A route as the page edits it: saved ones have an id, new ones don't yet. */
export interface RouteDraft {
  id?: string;
  integrationId: string;
  action: string;
  args: Record<string, unknown>;
  enabled: boolean;
}

export function draftFrom(route: PlatformAlertRoute): RouteDraft {
  return {
    id: route.id,
    integrationId: route.integrationId,
    action: route.action,
    args: { ...route.args },
    enabled: route.enabled,
  };
}

/** The PUT body. Empty arguments are left out; "every super admin" sends recipients null. */
export function buildUpdate(input: {
  types: Record<string, boolean>;
  emailEnabled: boolean;
  everySuperAdmin: boolean;
  recipientsText: string;
  /** Push on/off; null when the page doesn't show it (no Web Push on the server), which leaves it as it is. */
  pushEnabled?: boolean | null;
  routes: RouteDraft[];
}): PlatformAlertsUpdate {
  return {
    types: { ...input.types },
    email: {
      enabled: input.emailEnabled,
      recipients: input.everySuperAdmin ? null : parseRecipients(input.recipientsText),
    },
    ...(typeof input.pushEnabled === "boolean" ? { push: { enabled: input.pushEnabled } } : {}),
    routes: input.routes.map((r) => ({
      ...(r.id ? { id: r.id } : {}),
      integrationId: r.integrationId,
      action: r.action,
      enabled: r.enabled,
      args: cleanArgs(r.args),
    })),
  };
}

/** What a channel's pill says: its plugin may be gone, or the channel switched off. */
export function connectionPill(c: Pick<PlatformConnection, "available" | "enabled">): {
  label: string;
  tone: "ok" | "warn" | "muted";
} {
  if (!c.available) return { label: "Plugin missing", tone: "warn" };
  return c.enabled ? { label: "On", tone: "ok" } : { label: "Off", tone: "muted" };
}

/** How many URLs an Apprise credential holds (one per line or comma-separated), for "3 URLs" hints. */
export function countUrls(text: string): number {
  return text
    .replace(/,/g, "\n")
    .split("\n")
    .filter((u) => u.trim()).length;
}

/** The routes still pointing at a channel that is gone (its removal took the saved ones; drafts need dropping). */
export function dropRoutesOf(routes: RouteDraft[], connections: Pick<PlatformConnection, "id">[]): RouteDraft[] {
  const alive = new Set(connections.map((c) => c.id));
  return routes.filter((r) => alive.has(r.integrationId));
}
