/**
 * Admin Platform Alerts API — which platform events (backups, storage, security) reach people outside
 * Marvin, and how: email to super admins (built in) or a message-capable integration action on a
 * connection in the platform workspace. Browser calls go through the same-origin proxy (no token); SSR
 * passes the cookie token.
 */

import { fetchApi } from "../client";

export type DeliveryOutcome = "sent" | "failed" | "skipped";

export interface PlatformAlertDelivery {
  at: string;
  outcome: DeliveryOutcome;
  detail: string;
  /** The event that was sent; null for a test. */
  eventType: string | null;
  test: boolean;
}

export interface PlatformAlertKind {
  key: string;
  label: string;
  description: string;
  eventType: string;
  enabled: boolean;
  default: boolean;
}

export interface PlatformAlertEmail {
  enabled: boolean;
  /** null: every super admin with an email address. */
  recipients: string[] | null;
  superAdminEmails: string[];
  smtpReady: boolean;
  lastDelivery: PlatformAlertDelivery | null;
}

export interface PlatformAlertActionInput {
  key: string;
  label: string;
  description: string;
  required: boolean;
}

export interface PlatformAlertTarget {
  integrationId: string;
  integrationName: string;
  provider: string;
  providerName: string;
  connectionEnabled: boolean;
  action: string;
  actionLabel: string;
  inputs: PlatformAlertActionInput[];
}

export interface PlatformAlertRoute {
  id: string;
  integrationId: string;
  action: string;
  args: Record<string, unknown>;
  enabled: boolean;
  label: string;
  /** Why it can't send right now. */
  problem: string | null;
  lastDelivery: PlatformAlertDelivery | null;
}

export interface PlatformAlerts {
  types: PlatformAlertKind[];
  email: PlatformAlertEmail;
  routes: PlatformAlertRoute[];
  targets: PlatformAlertTarget[];
  platformWorkspace: { id: string; name: string; slug: string | null } | null;
  integrationsAvailable: boolean;
}

export interface PlatformAlertsUpdate {
  types: Record<string, boolean>;
  email: { enabled: boolean; recipients: string[] | null };
  routes: { id?: string; integrationId: string; action: string; args: Record<string, unknown>; enabled: boolean }[];
}

const PATH = "/api/admin/alerts";

export async function getPlatformAlerts(authToken?: string): Promise<PlatformAlerts> {
  return fetchApi<PlatformAlerts>(PATH, { method: "GET" }, authToken);
}

export async function updatePlatformAlerts(data: PlatformAlertsUpdate, authToken?: string): Promise<PlatformAlerts> {
  return fetchApi<PlatformAlerts>(
    PATH,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) },
    authToken,
  );
}

/** Send "Test alert from Marvin admin" through one saved channel: `email` or a route id. */
export async function testPlatformAlert(
  channel: string,
  authToken?: string,
): Promise<{ channel: string; delivery: PlatformAlertDelivery }> {
  return fetchApi(
    `${PATH}/test`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel }) },
    authToken,
  );
}
