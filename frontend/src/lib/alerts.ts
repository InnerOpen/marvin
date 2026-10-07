// What every alert settings page shares (Admin → Platform alerts, Settings → Automation → Notifications):
// parsing a recipient list, describing a channel's last delivery, tying a route to its action. Pure, so
// `npm test` covers it (admin/platformAlerts.test.mjs, notifications.test.mjs).

import type { AlertDelivery, AlertTarget } from "./api/alerts";

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
export function deliveryBadge(d: AlertDelivery | null | undefined): {
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
export function missingInputs(target: AlertTarget | undefined, args: Record<string, unknown>): string[] {
  if (!target) return [];
  return target.inputs.filter((i) => i.required && !String(args[i.key] ?? "").trim()).map((i) => i.label);
}

/** A route's arguments as saved: empty ones left out. */
export function cleanArgs(args: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(args).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
  );
}
