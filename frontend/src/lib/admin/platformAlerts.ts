// Admin → Platform alerts: the page's pure helpers (building the save payload; the ones every alert page
// shares are lib/alerts.ts's, re-exported here). Run the tests with `npm test`.

import { cleanArgs, parseRecipients } from "../alerts.ts";
import type { PlatformAlertRoute, PlatformAlertsUpdate } from "../api/admin/platformAlerts";

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
  routes: RouteDraft[];
}): PlatformAlertsUpdate {
  return {
    types: { ...input.types },
    email: {
      enabled: input.emailEnabled,
      recipients: input.everySuperAdmin ? null : parseRecipients(input.recipientsText),
    },
    routes: input.routes.map((r) => ({
      ...(r.id ? { id: r.id } : {}),
      integrationId: r.integrationId,
      action: r.action,
      enabled: r.enabled,
      args: cleanArgs(r.args),
    })),
  };
}
