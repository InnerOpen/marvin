/**
 * Workspace Integrations — SDK wrapper (platform.integrations).
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 */

import type {
  Integration,
  IntegrationActionResult,
  IntegrationCheckResult,
  IntegrationCreate,
  IntegrationEventSubscription,
  IntegrationEventSubscriptionCreate,
  IntegrationPluginInfo,
  IntegrationProviderInfo,
  IntegrationUpdate,
} from "@inneropen/marvin-sdk/platform";
import type { InputOption } from "../integrationOptions";
import type { ErrorOverrides, ErrorPolicyInfo, PolicyHandle } from "../integrationPolicy";
import { createSdkClient } from "../sdk";
import { fetchApi } from "./client";

export type {
  Integration,
  IntegrationActionResult,
  IntegrationCheckResult,
  IntegrationCreate,
  IntegrationEventSubscription,
  IntegrationEventSubscriptionCreate,
  IntegrationPluginInfo,
  IntegrationProviderInfo,
  IntegrationUpdate,
};

/**
 * The published SDK types lag the API. Widen here rather than block on an SDK release, and drop
 * these once the generated types carry them: providers may supply an emoji `icon`, and an action
 * carries capability routing metadata (capability, costHint, requiresApproval) the generated
 * `IntegrationProviderAction` does not yet know about.
 */
export interface ProviderActionInfo {
  key: string;
  label: string;
  description?: string;
  inputSchema?: { properties?: Record<string, unknown> };
  capability?: string | null;
  costHint?: string | null;
  requiresApproval?: boolean;
  /** This action's own error policy (SDK 0.5.0+): code → handling. */
  errorPolicy?: Record<string, PolicyHandle>;
}

export interface ProviderEventInfo {
  key: string;
  label: string;
  description?: string;
}

export type ProviderInfo = Omit<IntegrationProviderInfo, "actions"> & {
  icon?: string;
  /** The provider ships a logo Marvin accepted (see lib/integrationLogo); otherwise show `icon`. */
  hasLogo?: boolean;
  actions: ProviderActionInfo[];
  emits?: ProviderEventInfo[];
  /** How the provider handles its errors (SDK 0.5.0+; null on an older SDK). */
  errorPolicy?: ErrorPolicyInfo | null;
};

/** An open alert on a connection: it needs attention. One per error code, counted. */
export interface IntegrationAttention {
  id: string;
  code: string;
  message?: string | null;
  count: number;
  firstAt?: string | null;
  lastAt?: string | null;
  samples?: Record<string, unknown>[];
}

/** A connection with its health beyond the last check: open alerts and the admin's policy adjustments. */
export type IntegrationWithHealth = Integration & {
  attention?: IntegrationAttention[];
  errorOverrides?: ErrorOverrides;
  credentialSecret?: string | null;
};

export async function listProviders(authToken?: string): Promise<ProviderInfo[]> {
  return createSdkClient(authToken).integrations.listProviders();
}

export async function listIntegrations(authToken?: string): Promise<Integration[]> {
  return createSdkClient(authToken).integrations.list();
}

export async function listPlugins(authToken?: string): Promise<IntegrationPluginInfo[]> {
  return createSdkClient(authToken).integrations.listPlugins();
}

export async function createIntegration(data: IntegrationCreate, authToken?: string): Promise<Integration> {
  return createSdkClient(authToken).integrations.create(data);
}

export async function updateIntegration(id: string, data: IntegrationUpdate, authToken?: string): Promise<Integration> {
  return createSdkClient(authToken).integrations.update(id, data);
}

export async function deleteIntegration(id: string, authToken?: string): Promise<void> {
  return createSdkClient(authToken).integrations.delete(id);
}

export async function checkIntegration(id: string, authToken?: string): Promise<IntegrationCheckResult> {
  return createSdkClient(authToken).integrations.check(id);
}

export async function runIntegrationAction(
  id: string,
  actionKey: string,
  args: Record<string, unknown> = {},
  authToken?: string,
): Promise<IntegrationActionResult> {
  return createSdkClient(authToken).integrations.runAction(id, actionKey, args);
}

export async function listSubscriptions(
  eventType?: string,
  authToken?: string,
): Promise<IntegrationEventSubscription[]> {
  return createSdkClient(authToken).integrations.listSubscriptions(eventType);
}

export async function createSubscription(
  data: IntegrationEventSubscriptionCreate,
  authToken?: string,
): Promise<IntegrationEventSubscription> {
  return createSdkClient(authToken).integrations.createSubscription(data);
}

export async function deleteSubscription(id: string, authToken?: string): Promise<void> {
  return createSdkClient(authToken).integrations.deleteSubscription(id);
}

// Integration error handling — not in the SDK yet, so plain API calls.

/** Mark the connection's open alerts (or just `alertId`) resolved ("I fixed it"); re-arms retries waiting on it. */
export async function resolveAttention(id: string, alertId?: string, authToken?: string): Promise<{ resolved: number }> {
  const query = alertId ? `?alert_id=${encodeURIComponent(alertId)}` : "";
  return fetchApi(`/api/groups/integrations/${encodeURIComponent(id)}/resolve${query}`, { method: "POST" }, authToken);
}

/** Save the connection's review/alert adjustments to its provider's error policy ({} = all defaults). */
export async function setErrorOverrides(
  id: string,
  overrides: ErrorOverrides,
  authToken?: string,
): Promise<IntegrationWithHealth> {
  return fetchApi(
    `/api/groups/integrations/${encodeURIComponent(id)}/error-overrides`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ overrides }) },
    authToken,
  );
}

/**
 * The choices for one action input whose schema carries an `x-marvin-options` hint. Core runs the
 * read action the hint names through this connection; a failure throws with a plain message, and the
 * picker falls back to free text.
 */
export async function listInputOptions(
  id: string,
  actionKey: string,
  input: string,
  authToken?: string,
): Promise<InputOption[]> {
  return fetchApi(
    `/api/groups/integrations/${encodeURIComponent(id)}/options`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actionKey, input }) },
    authToken,
  );
}

// ---- Alerts & health page ----------------------------------------------------------------------

/** One connection at a glance. */
export interface IntegrationHealthRow {
  id: string;
  name: string;
  slug: string;
  provider: string;
  providerName: string;
  enabled: boolean;
  /** The last health check's result: ok | error | unconfigured | unavailable. */
  status: string;
  lastCheckedAt?: string | null;
  lastError?: string | null;
  lastSuccessAt?: string | null;
  /** Failed workflow steps through this connection in the last 7 days. */
  failures7d: number;
  openAlerts: number;
  alertCodes: string[];
  liveRetries: number;
}

/** A connection alert, open or resolved. */
export interface IntegrationAlert {
  id: string;
  integrationId: string;
  integrationName?: string | null;
  integrationSlug: string;
  provider: string;
  providerName: string;
  code: string;
  message?: string | null;
  count: number;
  status: "open" | "resolved";
  firstAt?: string | null;
  lastAt?: string | null;
  notifiedAt?: string | null;
  /** An open alert is announced again on its next failure after this; null while reminders are off. */
  remindAfter?: string | null;
  reminderHours: number;
  resolvedAt?: string | null;
  resolution?: "manual" | "check" | "action" | null;
  resolvedByName?: string | null;
  openSeconds?: number | null;
}

/** A failed workflow step waiting to be retried (or running right now). */
export interface IntegrationRetry {
  id: string;
  status: "pending" | "parked" | "running";
  automationId: string;
  automationName?: string | null;
  automationEnabled: boolean;
  entryId?: string | null;
  entryTitle?: string | null;
  entryExists: boolean;
  integrationId?: string | null;
  integrationName?: string | null;
  integrationSlug: string;
  provider: string;
  providerName: string;
  action: string;
  code: string;
  attempt: number;
  maxAttempts: number;
  nextAttemptAt?: string | null;
  leaseUntil?: string | null;
  lastError?: string | null;
  createdAt?: string | null;
}

/** A failed integration step that the provider's error policy handled. */
export interface HandledFailure {
  id: string;
  executionId: string;
  runStatus: string;
  isRetry: boolean;
  at?: string | null;
  automationId?: string | null;
  automationName?: string | null;
  entryId?: string | null;
  entryTitle?: string | null;
  entryExists: boolean;
  integrationId?: string | null;
  integrationSlug?: string | null;
  provider?: string | null;
  providerName?: string | null;
  action?: string | null;
  code?: string | null;
  error?: string | null;
  outcome: string;
  retryStatus?: string | null;
}

export interface Paged<T> {
  items: T[];
  page: number;
  perPage: number;
  total: number;
}

export async function getIntegrationHealth(authToken?: string): Promise<IntegrationHealthRow[]> {
  return fetchApi("/api/groups/integrations/health", {}, authToken);
}

export async function listIntegrationAlerts(
  status: "open" | "resolved",
  page = 1,
  perPage = 25,
  authToken?: string,
): Promise<Paged<IntegrationAlert>> {
  return fetchApi(`/api/groups/integrations/alerts?status=${status}&page=${page}&per_page=${perPage}`, {}, authToken);
}

export async function listIntegrationRetries(authToken?: string): Promise<IntegrationRetry[]> {
  return fetchApi("/api/groups/integrations/retries", {}, authToken);
}

export async function listHandledFailures(
  page = 1,
  perPage = 25,
  authToken?: string,
): Promise<Paged<HandledFailure> & { since: string }> {
  return fetchApi(`/api/groups/integrations/handled-failures?page=${page}&per_page=${perPage}`, {}, authToken);
}

/** Make a pending or parked retry due now; the retry sweep runs it within about a minute. */
export async function retryNow(id: string, authToken?: string): Promise<IntegrationRetry> {
  return fetchApi(`/api/groups/integrations/retries/${encodeURIComponent(id)}/retry-now`, { method: "POST" }, authToken);
}

/** Stop retrying a failed step. Nothing else happens (no review, no alert). */
export async function giveUpRetry(id: string, authToken?: string): Promise<IntegrationRetry> {
  return fetchApi(`/api/groups/integrations/retries/${encodeURIComponent(id)}/give-up`, { method: "POST" }, authToken);
}
