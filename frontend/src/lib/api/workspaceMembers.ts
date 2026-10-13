/**
 * Workspace Members API client - SDK wrapper
 * Migrated to use @inneropen/marvin-sdk
 */

import type {
  PlatformWorkspaceMember,
  PlatformWorkspaceMemberCreate,
  PlatformWorkspaceMemberUpdate,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

// Re-export SDK types with legacy names for backward compatibility
export type WorkspaceMemberRead = PlatformWorkspaceMember;
export type WorkspaceMemberCreate = PlatformWorkspaceMemberCreate;
export type WorkspaceMemberUpdate = PlatformWorkspaceMemberUpdate;

/**
 * List all members of a workspace
 * Auth: Workspace member (any role)
 */
export async function listWorkspaceMembers(workspaceId: string, authToken: string): Promise<WorkspaceMemberRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaceMembers.list(workspaceId);
}

/**
 * Get a single workspace member
 * Auth: Workspace member (any role)
 */
export async function getWorkspaceMember(
  workspaceId: string,
  userId: string,
  authToken: string,
): Promise<WorkspaceMemberRead> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaceMembers.get(workspaceId, userId);
}

/**
 * Add a member to a workspace
 * Auth: Workspace ADMIN/OWNER required
 */
export async function addWorkspaceMember(
  workspaceId: string,
  data: WorkspaceMemberCreate,
  authToken: string,
): Promise<WorkspaceMemberRead> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaceMembers.add(workspaceId, data);
}

/**
 * Update a workspace member's role
 * Auth: Workspace ADMIN/OWNER required
 */
export async function updateWorkspaceMemberRole(
  workspaceId: string,
  userId: string,
  data: WorkspaceMemberUpdate,
  authToken: string,
): Promise<WorkspaceMemberRead> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaceMembers.updateRole(workspaceId, userId, data);
}

/**
 * Remove a member from a workspace
 * Auth: Workspace ADMIN/OWNER required
 */
export async function removeWorkspaceMember(workspaceId: string, userId: string, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaceMembers.remove(workspaceId, userId);
}
