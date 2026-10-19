/**
 * Admin Platform Alerts API — which platform events (backups, storage, security) reach people outside
 * Marvin, and how: email to super admins (built in), push, or a message-capable integration action on one
 * of the platform's own channels (Apprise first). Browser calls go through the same-origin proxy (no
 * token); SSR passes the cookie token.
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

interface PlatformAlertEmail {
  enabled: boolean;
  /** null: every super admin with an email address. */
  recipients: string[] | null;
  superAdminEmails: string[];
  smtpReady: boolean;
  lastDelivery: AlertDelivery | null;
}

interface PlatformAlertPush {
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

/** A platform channel. The credential (Apprise URLs…) is never returned, only whether there is one. */
export interface PlatformConnection {
  id: string;
  provider: string;
  providerName: string;
  name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  hasCredential: boolean;
  /** Its plugin is installed and still sends messages. */
  available: boolean;
  /** Every message action of it needs more than the message (a channel…): test it through a route. */
  needsRouteInputs: boolean;
  /** How many alert routes use it. */
  routes: number;
}

/** An installed plugin that can carry a message: what a new channel can be (Apprise first). */
export interface PlatformConnectionProvider {
  slug: string;
  name: string;
  description: string;
  credentialLabel: string | null;
  credentialHelp: string;
  credentialRequired: boolean;
  configFields: { key: string; label: string; required: boolean; description: string }[];
}

export interface PlatformAlerts {
  types: AlertKind[];
  email: PlatformAlertEmail;
  push: PlatformAlertPush;
  routes: PlatformAlertRoute[];
  targets: AlertTarget[];
  connections: PlatformConnection[];
  providers: PlatformConnectionProvider[];
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

const json = { "Content-Type": "application/json" };

/** Add a platform channel; `credential` is write-only (Apprise: the notification URLs, one per line). */
export async function createPlatformConnection(
  data: { provider: string; name: string; config?: Record<string, string>; credential?: string },
  authToken?: string,
): Promise<PlatformAlerts> {
  return fetchApi<PlatformAlerts>(
    `${PATH}/connections`,
    { method: "POST", headers: json, body: JSON.stringify(data) },
    authToken,
  );
}

/** Rename, turn on or off, or rotate the credential of a channel (blank credential keeps the saved one). */
export async function updatePlatformConnection(
  id: string,
  data: { name?: string; enabled?: boolean; config?: Record<string, string>; credential?: string },
  authToken?: string,
): Promise<PlatformAlerts> {
  return fetchApi<PlatformAlerts>(
    `${PATH}/connections/${id}`,
    { method: "PUT", headers: json, body: JSON.stringify(data) },
    authToken,
  );
}

/** Remove a channel, its credential and the routes that used it. */
export async function deletePlatformConnection(id: string, authToken?: string): Promise<PlatformAlerts> {
  return fetchApi<PlatformAlerts>(`${PATH}/connections/${id}`, { method: "DELETE" }, authToken);
}

/** Send "Test alert from Marvin admin" through a channel (one whose action needs no extra input). */
export async function testPlatformConnection(
  id: string,
  authToken?: string,
): Promise<{ channel: string; delivery: AlertDelivery }> {
  return fetchApi(`${PATH}/connections/${id}/test`, { method: "POST" }, authToken);
}
