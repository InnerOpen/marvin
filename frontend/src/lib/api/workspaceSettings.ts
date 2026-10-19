/**
 * Workspace settings API
 * Migrated to use @inneropen/marvin-sdk
 */

import type { WorkspacePreferences } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

/**
 * Get workspace preferences
 */
export async function getWorkspacePreferences(workspaceId: string, authToken: string): Promise<WorkspacePreferences> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.getPreferences(workspaceId);
}
