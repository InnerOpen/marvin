// Settings → Automation → Notifications: the page's pure helpers (a channel's kinds, building the save
// payload; the ones every alert page shares are lib/alerts.ts's). Run the tests with `npm test`.

import { cleanArgs, parseRecipients } from "./alerts.ts";
import type { NotificationRoute, WorkspaceNotificationsUpdate } from "./api/notifications";

/** A route as the page edits it: saved ones have an id, new ones don't yet. */
export interface RouteDraft {
  id?: string;
  integrationId: string;
  action: string;
  args: Record<string, unknown>;
  enabled: boolean;
  kinds: string[] | null;
}

export function draftFrom(route: NotificationRoute): RouteDraft {
  return {
    id: route.id,
    integrationId: route.integrationId,
    action: route.action,
    args: { ...route.args },
    enabled: route.enabled,
    kinds: route.kinds ? [...route.kinds] : null,
  };
}

/** Whether a channel takes `kind` (null takes every kind). */
export function takes(kinds: string[] | null, kind: string): boolean {
  return kinds === null || kinds.includes(kind);
}

/** The ticked kinds as a channel's `kinds`: null when every kind is ticked (so a kind added later is taken
 * too), else the ticked ones in the page's order. */
export function channelKinds(ticked: Iterable<string>, all: string[]): string[] | null {
  const on = new Set(ticked);
  return all.every((k) => on.has(k)) ? null : all.filter((k) => on.has(k));
}

/** What a channel takes, in words: "Every kind", "None", or the labels. */
export function kindsSummary(kinds: string[] | null, labels: Record<string, string>): string {
  if (kinds === null) return "Every kind";
  if (kinds.length === 0) return "None";
  return kinds.map((k) => labels[k] ?? k).join(", ");
}

/** The reminder window typed: a whole number of hours from 0 (never) to 720. */
export function reminderHours(text: string, fallback: number): number {
  const n = Number.parseInt(text, 10);
  return Number.isFinite(n) ? Math.min(720, Math.max(0, n)) : fallback;
}

/** The PUT body. Empty arguments are left out; "every owner and admin" sends recipients null; push is sent
 * only when the page shows it (the server has Web Push), else left as it is. */
export function buildUpdate(input: {
  types: Record<string, boolean>;
  emailEnabled: boolean;
  everyAdmin: boolean;
  recipientsText: string;
  emailKinds: string[] | null;
  push?: { enabled: boolean; kinds: string[] | null } | null;
  routes: RouteDraft[];
  reminderHours: number;
}): WorkspaceNotificationsUpdate {
  return {
    types: { ...input.types },
    email: {
      enabled: input.emailEnabled,
      recipients: input.everyAdmin ? null : parseRecipients(input.recipientsText),
      kinds: input.emailKinds,
    },
    ...(input.push ? { push: { enabled: input.push.enabled, kinds: input.push.kinds } } : {}),
    routes: input.routes.map((r) => ({
      ...(r.id ? { id: r.id } : {}),
      integrationId: r.integrationId,
      action: r.action,
      enabled: r.enabled,
      kinds: r.kinds,
      args: cleanArgs(r.args),
    })),
    integrationReminderHours: input.reminderHours,
  };
}
