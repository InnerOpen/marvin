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

export interface AlertRoutingTarget {
  integrationId: string;
  name: string;
  provider: string;
  action: string;
  enabled: boolean;
}

/** Where integration alerts go besides the bell (which always gets them). */
export interface AlertRouting {
  emailAdmins: boolean;
  targets: AlertRoutingTarget[];
  reminderHours: number;
}

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

/** Mark the connection's open alerts resolved ("I fixed it"); re-arms retries waiting on it. */
export async function resolveAttention(id: string, authToken?: string): Promise<{ resolved: number }> {
  return fetchApi(`/api/groups/integrations/${encodeURIComponent(id)}/resolve`, { method: "POST" }, authToken);
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

export async function getAlertRouting(authToken?: string): Promise<AlertRouting> {
  return fetchApi("/api/groups/integrations/alert-routing", {}, authToken);
}

export async function setAlertRouting(
  data: { emailAdmins: boolean; integrationIds: string[]; reminderHours: number },
  authToken?: string,
): Promise<AlertRouting> {
  return fetchApi(
    "/api/groups/integrations/alert-routing",
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) },
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
