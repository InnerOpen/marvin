/**
 * Admin Platform Alerts API — which platform events (backups, storage, security) reach people outside
 * Marvin, and how: email to super admins (built in) or a message-capable integration action on a
 * connection in the platform workspace. Browser calls go through the same-origin proxy (no token); SSR
 * passes the cookie token.
 */

import type { AlertDelivery, AlertKind, AlertTarget } from "../alerts";
import { fetchApi } from "../client";

export type {
  AlertActionInput as PlatformAlertActionInput,
  AlertDelivery as PlatformAlertDelivery,
  AlertKind as PlatformAlertKind,
  AlertTarget as PlatformAlertTarget,
  DeliveryOutcome,
} from "../alerts";

export interface PlatformAlertEmail {
  enabled: boolean;
  /** null: every super admin with an email address. */
  recipients: string[] | null;
  superAdminEmails: string[];
  smtpReady: boolean;
  lastDelivery: AlertDelivery | null;
}

export interface PlatformAlertPush {
  /** The server has Web Push (VAPID); without it push isn't a channel and the page hides it. */
  configured: boolean;
  enabled: boolean;
  /** Who push reaches right now: super admins with a device and "Platform alerts" on. */
  people: string[];
  lastDelivery: AlertDelivery | null;
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
  lastDelivery: AlertDelivery | null;
}

export interface PlatformAlerts {
  types: AlertKind[];
  email: PlatformAlertEmail;
  push: PlatformAlertPush;
  routes: PlatformAlertRoute[];
  targets: AlertTarget[];
  platformWorkspace: { id: string; name: string; slug: string | null } | null;
  integrationsAvailable: boolean;
}

export interface PlatformAlertsUpdate {
  types: Record<string, boolean>;
  email: { enabled: boolean; recipients: string[] | null };
  /** Left out: push stays as it is. */
  push?: { enabled: boolean };
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
): Promise<{ channel: string; delivery: AlertDelivery }> {
  return fetchApi(
    `${PATH}/test`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel }) },
    authToken,
  );
}
