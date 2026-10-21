// The Incoming webhooks page's list: what counts as "needs a look", the Signed and Received filters, and the adapter that
// feeds the shared list kit (organizedList.ts). Pure, so `npm test` covers it (incomingWebhookList.test.mjs).

import type { Choice, ListAdapter } from "./organizedList.ts";

/** An incoming webhook as the list API returns it (camelCase), as far as the list needs. */
export interface IncomingWebhookRow {
  id: string;
  name: string;
  slug?: string;
  description?: string | null;
  enabled: boolean;
  token?: string | null;
  signingSecretRef?: string | null;
  receivedCount?: number;
  lastReceivedAt?: string | null;
  sourceIntegrationId?: string | null;
  sourceBlueprint?: string | null;
}

/** "Received recently" means within this many days. */
export const RECENT_DAYS = 7;

export const SIGNED_OPTIONS: Choice[] = [
  { value: "yes", label: "Signed" },
  { value: "no", label: "Not signed" },
];

export const RECEIVED_OPTIONS: Choice[] = [
  { value: "recently", label: `Received in the last ${RECENT_DAYS} days` },
  { value: "never", label: "Never received" },
];

/** Whether requests to it must carry a valid signature. */
export const isSigned = (w: IncomingWebhookRow): boolean => !!w.signingSecretRef;

export const neverReceived = (w: IncomingWebhookRow): boolean => !w.receivedCount;

/**
 * Needs a look: on, and nothing has ever arrived. Marvin does not record rejected deliveries (a bad token or signature
 * only reaches the server log), so "recent calls were all rejected" cannot be told here; this is the same single rule as
 * the server's count (services/automation/attention.py).
 */
export const needsAttention = (w: IncomingWebhookRow): boolean => w.enabled && neverReceived(w);

/** Why a flagged webhook needs a look, in words ("" when it doesn't). */
export function attentionReason(w: IncomingWebhookRow): string {
  if (!needsAttention(w)) return "";
  return w.token ? "On, but nothing has arrived yet" : "On, but has no token yet, so nothing can arrive";
}

/** "recently" (a call in the last RECENT_DAYS), "older" (calls, but not lately) or "never". */
export function receivedState(w: IncomingWebhookRow, now: Date = new Date()): "recently" | "older" | "never" {
  if (neverReceived(w)) return "never";
  const at = w.lastReceivedAt ? new Date(w.lastReceivedAt).getTime() : Number.NaN;
  return Number.isNaN(at) || now.getTime() - at > RECENT_DAYS * 86_400_000 ? "older" : "recently";
}

/** The adapter for the shared list kit; the page passes `statusOptions({ attention: true })` to the filter bar. */
export function incomingWebhookAdapter(now: () => Date = () => new Date()): ListAdapter<IncomingWebhookRow> {
  return {
    id: (w) => w.id,
    name: (w) => w.name,
    search: (w) => [w.slug ?? "", w.description ?? ""],
    source: (w) => ({ integrationId: w.sourceIntegrationId ?? null, blueprint: w.sourceBlueprint ?? null }),
    enabled: (w) => w.enabled,
    attention: needsAttention,
    facets: {
      signed: (w) => (isSigned(w) ? "yes" : "no"),
      received: (w) => receivedState(w, now()),
    },
  };
}
