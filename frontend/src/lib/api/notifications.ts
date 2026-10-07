/**
 * Workspace notifications API (Settings → Automation → Notifications) — which of the workspace's events
 * reach people outside Marvin, and how: email to its owners and admins (built in) or a message-capable
 * action on one of its connections, each channel taking every kind or only some. Admins and owners only.
 * Browser calls go through the same-origin proxy (no token); SSR passes the cookie token.
 */

import type { AlertDelivery, AlertKind, AlertTarget } from "./alerts";
import { fetchApi } from "./client";

export interface NotificationEmail {
  enabled: boolean;
  /** null: every owner and admin of the workspace with an email address. */
  recipients: string[] | null;
  /** The kinds email takes; null: every kind that is on. */
  kinds: string[] | null;
  adminEmails: string[];
  smtpReady: boolean;
  lastDelivery: AlertDelivery | null;
}

export interface NotificationRoute {
  id: string;
  integrationId: string;
  action: string;
  args: Record<string, unknown>;
  enabled: boolean;
  /** The kinds it takes; null: every kind that is on. */
  kinds: string[] | null;
  label: string;
  /** Why it can't send right now. */
  problem: string | null;
  lastDelivery: AlertDelivery | null;
}

export interface WorkspaceNotifications {
  types: AlertKind[];
  email: NotificationEmail;
  routes: NotificationRoute[];
  targets: AlertTarget[];
  integrationsAvailable: boolean;
  integrationReminderHours: number;
}

export interface WorkspaceNotificationsUpdate {
  types: Record<string, boolean>;
  email: { enabled: boolean; recipients: string[] | null; kinds: string[] | null };
  routes: {
    id?: string;
    integrationId: string;
    action: string;
    args: Record<string, unknown>;
    enabled: boolean;
    kinds: string[] | null;
  }[];
  integrationReminderHours: number;
}

const PATH = "/api/groups/notifications";

export async function getNotifications(authToken?: string): Promise<WorkspaceNotifications> {
  return fetchApi<WorkspaceNotifications>(PATH, { method: "GET" }, authToken);
}

export async function updateNotifications(
  data: WorkspaceNotificationsUpdate,
  authToken?: string,
): Promise<WorkspaceNotifications> {
  return fetchApi<WorkspaceNotifications>(
    PATH,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) },
    authToken,
  );
}

/** Send "Test notification from Marvin" through one saved channel: `email` or a route id. */
export async function testNotification(
  channel: string,
  authToken?: string,
): Promise<{ channel: string; delivery: AlertDelivery }> {
  return fetchApi(
    `${PATH}/test`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel }) },
    authToken,
  );
}
