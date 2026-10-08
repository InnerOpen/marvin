/**
 * Web Push for the signed-in user (/api/self/push): whether the server has push, this user's devices and the
 * kinds of push they take. Browser calls go through the same-origin proxy (no token); SSR passes the cookie
 * token. Everything is the caller's own.
 */
import { fetchApi } from "./client";

export interface PushDevice {
  id: string;
  label: string | null;
  endpoint: string;
  userAgent: string | null;
  createdAt: string | null;
  lastUsedAt: string | null;
  lastSuccessAt: string | null;
  /** Failed sends since the last success. */
  failureCount: number;
}

export interface PushCategory {
  key: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface PushSettings {
  /** The server has Web Push configured (VAPID); without it the UI hides push. */
  enabled: boolean;
  publicKey: string | null;
  categories: PushCategory[];
  devices: PushDevice[];
}

export interface PushSubscriptionBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  userAgent?: string;
  label?: string;
  replaces?: string | null;
}

const PATH = "/api/self/push";
const JSON_HEADERS = { "Content-Type": "application/json" };

export function getPushSettings(authToken?: string): Promise<PushSettings> {
  return fetchApi<PushSettings>(PATH, { method: "GET" }, authToken);
}

export function savePushSubscription(body: PushSubscriptionBody, authToken?: string): Promise<PushDevice> {
  return fetchApi<PushDevice>(
    `${PATH}/subscriptions`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) },
    authToken,
  );
}

export function removePushDevice(id: string, authToken?: string): Promise<void> {
  return fetchApi<void>(`${PATH}/subscriptions/${encodeURIComponent(id)}`, { method: "DELETE" }, authToken);
}

/** Forget this browser's subscription by its endpoint (logout, or turning push off here). */
export function removePushEndpoint(endpoint: string, authToken?: string): Promise<void> {
  return fetchApi<void>(
    `${PATH}/subscriptions?endpoint=${encodeURIComponent(endpoint)}`,
    { method: "DELETE" },
    authToken,
  );
}

export function updatePushPreferences(categories: Record<string, boolean>, authToken?: string): Promise<PushSettings> {
  return fetchApi<PushSettings>(
    `${PATH}/preferences`,
    { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ categories }) },
    authToken,
  );
}

/** Queue a test push to every one of my devices; resolves with how many. */
export function sendTestPush(authToken?: string): Promise<{ devices: number }> {
  return fetchApi<{ devices: number }>(`${PATH}/test`, { method: "POST" }, authToken);
}
