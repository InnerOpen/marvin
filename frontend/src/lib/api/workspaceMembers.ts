/**
 * Workspace Members API client - SDK wrapper
 * Migrated to use @inneropen/marvin-sdk
 */

import type { PlatformWorkspaceMember } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

// Re-export SDK types with legacy names for backward compatibility
export type WorkspaceMemberRead = PlatformWorkspaceMember;

/**
 * List all members of a workspace
 * Auth: Workspace member (any role)
 */
export async function listWorkspaceMembers(workspaceId: string, authToken: string): Promise<WorkspaceMemberRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaceMembers.list(workspaceId);
}
