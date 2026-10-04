/**
 * Workspace management API client (migrated to SDK)
 */

import type {
  Workspace,
  WorkspaceCreate,
  WorkspaceUpdate,
  WorkspaceWithMembership,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";
import { canManageWorkspace } from "../workspaceRole";

/**
 * Get the user's currently active workspace
 */
export async function getCurrentWorkspace(authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.getCurrent();
}

/**
 * List all workspaces accessible to the current user
 * For SUPER_ADMIN: Returns all workspaces
 * For regular users: Returns only workspaces they're members of
 */
export async function listWorkspaces(authToken: string): Promise<WorkspaceWithMembership[]> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.list();
}

/**
 * Whether the caller may manage the active workspace's configuration (OWNER/ADMIN, super admin,
 * legacy admin) — the same gate the backend applies to API clients, webhooks and the like.
 */
export async function canManageCurrentWorkspace(authToken: string): Promise<boolean> {
  const sdk = createSdkClient(authToken);
  const [memberships, user] = await Promise.all([sdk.workspaces.list(), sdk.user.getProfile()]);
  return canManageWorkspace(memberships, user);
}

/**
 * Activate a workspace (make it the current active workspace)
 * Accepts workspace ID or slug
 */
export async function activateWorkspace(workspaceIdOrSlug: string, authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.setActive(workspaceIdOrSlug);
}

/**
 * Create a new workspace (requires SUPER_ADMIN)
 */
export async function createWorkspace(data: WorkspaceCreate, authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.create(data);
}

/**
 * Update workspace settings (requires ADMIN or OWNER)
 */
export async function updateWorkspace(id: string, data: WorkspaceUpdate, authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.update(id, data);
}

/**
 * Delete a workspace (requires SUPER_ADMIN)
 */
export async function deleteWorkspace(id: string, authToken: string, force: boolean = false): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.delete(id, force);
}

/**
 * Get a single workspace by ID
 */
export async function getWorkspace(id: string, authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.get(id);
}

/**
 * Set the active workspace by slug
 */
export async function setActiveWorkspace(slug: string, authToken: string): Promise<Workspace> {
  const sdk = createSdkClient(authToken);
  return sdk.workspaces.setActive(slug);
}

// Type re-exports for backward compatibility
export type WorkspaceRead = Workspace;
export type { WorkspaceCreate, WorkspaceUpdate };
