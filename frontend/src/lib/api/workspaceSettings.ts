/**
 * Workspace settings API
 * Migrated to use @inneropen/marvin-sdk
 */

import type {
  Workspace,
  WorkspacePreferences,
  WorkspacePreferencesUpdate,
  WorkspaceUpdate,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

// Re-export types for backward compatibility
export type GroupRead = Workspace;
export type GroupAdminUpdate = WorkspaceUpdate;

/**
 * Get workspace settings
 */
export async function getWorkspaceSettings(workspaceId: string, authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.get(workspaceId);
}

/**
 * Update workspace settings
 */
export async function updateWorkspaceSettings(
  workspaceId: string,
  data: WorkspaceUpdate,
  authToken: string,
): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.update(workspaceId, data);
}

/**
 * Get workspace preferences
 */
export async function getWorkspacePreferences(workspaceId: string, authToken: string): Promise<WorkspacePreferences> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.getPreferences(workspaceId);
}

/**
 * Update workspace preferences
 */
export async function updateWorkspacePreferences(
  workspaceId: string,
  data: WorkspacePreferencesUpdate,
  authToken: string,
): Promise<WorkspacePreferences> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.updatePreferences(workspaceId, data);
}
