/**
 * Incoming webhooks (ingress) — SDK wrapper (platform.incomingWebhooks).
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 */

import type { IncomingWebhook, IncomingWebhookCreate, IncomingWebhookUpdate } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type { IncomingWebhook, IncomingWebhookCreate, IncomingWebhookUpdate };

export async function listIncomingWebhooks(authToken?: string): Promise<IncomingWebhook[]> {
  return createSdkClient(authToken).incomingWebhooks.list();
}

export async function createIncomingWebhook(data: IncomingWebhookCreate, authToken?: string): Promise<IncomingWebhook> {
  return createSdkClient(authToken).incomingWebhooks.create(data);
}

export async function updateIncomingWebhook(
  id: string,
  data: IncomingWebhookUpdate,
  authToken?: string,
): Promise<IncomingWebhook> {
  return createSdkClient(authToken).incomingWebhooks.update(id, data);
}

export async function deleteIncomingWebhook(id: string, authToken?: string): Promise<void> {
  return createSdkClient(authToken).incomingWebhooks.delete(id);
}

export async function mintIncomingWebhookToken(id: string, authToken?: string): Promise<IncomingWebhook> {
  return createSdkClient(authToken).incomingWebhooks.mintToken(id);
}

export async function revokeIncomingWebhookToken(id: string, authToken?: string): Promise<IncomingWebhook> {
  return createSdkClient(authToken).incomingWebhooks.revokeToken(id);
}
