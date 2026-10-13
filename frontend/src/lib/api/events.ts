/**
 * Events API
 * Migrated to use @inneropen/marvin-sdk
 */

import type { EventOption } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type { EventOption };

/**
 * Get available event types for webhooks and notifications
 */
export async function getEventOptions(authToken: string): Promise<EventOption[]> {
  const sdk = createSdkClient(authToken);
  return sdk.events.getOptions();
}
