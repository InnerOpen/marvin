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
import { createSdkClient } from "../sdk";

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
 * The published SDK types lag the API. A provider may supply an optional emoji `icon`; widen here
 * rather than block on an SDK release, and drop this once the generated types carry it.
 */
export type ProviderInfo = IntegrationProviderInfo & { icon?: string };

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
