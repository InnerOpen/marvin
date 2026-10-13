/**
 * Webhooks API
 * Migrated to use @inneropen/marvin-sdk
 */

import type { Webhook, WebhookCreate, WebhookUpdate } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type { Webhook, WebhookCreate, WebhookUpdate };

/**
 * List all webhooks in the workspace
 */
export async function listWebhooks(authToken: string): Promise<Webhook[]> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.list();
}

/**
 * Get a webhook by ID
 */
export async function getWebhook(id: string, authToken: string): Promise<Webhook> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.get(id);
}

/**
 * Create a new webhook
 */
export async function createWebhook(data: WebhookCreate, authToken: string): Promise<Webhook> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.create(data);
}

/**
 * Update a webhook
 */
export async function updateWebhook(id: string, data: WebhookUpdate, authToken: string): Promise<Webhook> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.update(id, data);
}

/**
 * Delete a webhook
 */
export async function deleteWebhook(id: string, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.delete(id);
}

/**
 * Test a webhook
 */
export async function testWebhook(
  id: string,
  authToken: string,
): Promise<{ success: boolean; message?: string; statusCode?: number }> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.test(id);
}

/**
 * Rerun failed webhooks
 */
export async function rerunWebhooks(authToken: string): Promise<{ message: string; requeued: number }> {
  const sdk = createSdkClient(authToken);
  return sdk.webhooks.rerun();
}
