// Admin → Platform alerts: the page's pure helpers (parsing the recipient list, describing a channel's
// last delivery, building the save payload). Run the tests with `npm test`.

import type {
  PlatformAlertDelivery,
  PlatformAlertRoute,
  PlatformAlertsUpdate,
  PlatformAlertTarget,
} from "../api/admin/platformAlerts";

/** Addresses typed one per line or comma-separated; blanks dropped, repeats (any case) once. */
export function parseRecipients(text: string): string[] {
  const seen = new Map<string, string>();
  for (const raw of text.split(/[\s,;]+/)) {
    const addr = raw.trim();
    if (addr && !seen.has(addr.toLowerCase())) seen.set(addr.toLowerCase(), addr);
  }
  return [...seen.values()];
}

export type Tone = "ok" | "warn" | "err" | "muted";

/** A channel's last delivery for people: a short label, a tone, and the detail line. */
export function deliveryBadge(d: PlatformAlertDelivery | null | undefined): {
  label: string;
  tone: Tone;
  detail: string;
} {
  if (!d) return { label: "Nothing sent yet", tone: "muted", detail: "" };
  const what = d.test ? "Test" : d.eventType ? d.eventType : "Alert";
  switch (d.outcome) {
    case "sent":
      return { label: `${what}: sent`, tone: "ok", detail: d.detail };
    case "skipped":
      return { label: `${what}: not sent`, tone: "warn", detail: d.detail };
    default:
      return { label: `${what}: failed`, tone: "err", detail: d.detail };
  }
}

/** The key that ties a route to the action it runs. */
export function targetKey(t: { integrationId: string; action: string }): string {
  return `${t.integrationId}:${t.action}`;
}

/** Required inputs of the route's action left empty. */
export function missingInputs(target: PlatformAlertTarget | undefined, args: Record<string, unknown>): string[] {
  if (!target) return [];
  return target.inputs.filter((i) => i.required && !String(args[i.key] ?? "").trim()).map((i) => i.label);
}

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
      args: Object.fromEntries(
        Object.entries(r.args).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
      ),
    })),
  };
}
