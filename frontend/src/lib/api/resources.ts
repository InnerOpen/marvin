/**
 * Resources API client - SDK wrapper
 * Migrated to use @inneropen/marvin-sdk
 */

import type {
  PlatformEntry,
  PlatformResource,
  PlatformResourceCreate,
  PlatformResourceUpdate,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";
import { getApiUrl } from "./config";

// Re-export SDK types with legacy names for backward compatibility
export type ResourceRead = PlatformResource;
export type ResourceCreate = PlatformResourceCreate;
export type ResourceUpdate = PlatformResourceUpdate;
export type EntryRead = PlatformEntry;

/**
 * List all resources in the current workspace
 */
export async function listResources(authToken: string): Promise<ResourceRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.resources.list();
}

/**
 * Get a single resource by ID
 */
export async function getResource(id: string, authToken: string): Promise<ResourceRead> {
  const sdk = createSdkClient(authToken);
  return sdk.resources.get(id);
}

/**
 * Create a new resource
 */
export async function createResource(data: ResourceCreate, authToken: string): Promise<ResourceRead> {
  const sdk = createSdkClient(authToken);
  return sdk.resources.create(data);
}

/**
 * Update an existing resource
 */
export async function updateResource(id: string, data: ResourceUpdate, authToken: string): Promise<ResourceRead> {
  const sdk = createSdkClient(authToken);
  return sdk.resources.update(id, data);
}

/**
 * Delete a resource
 */
export async function deleteResource(id: string, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.resources.delete(id);
}

/**
 * Get entries that reference this resource
 */
export async function getResourceEntries(resourceId: string, authToken: string): Promise<EntryRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.resources.getEntries(resourceId);
}

/** Apply the resource's staged AI suggestion (suggestion_json) and clear it. */
export async function applyResourceSuggestion(id: string, authToken: string): Promise<ResourceRead> {
  const res = await fetch(getApiUrl(`/api/platform/resources/${id}/apply-suggestion`), {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`apply-suggestion failed: ${res.status}`);
  return res.json();
}

/** Discard the resource's staged AI suggestion without applying it. */
export async function rejectResourceSuggestion(id: string, authToken: string): Promise<ResourceRead> {
  const res = await fetch(getApiUrl(`/api/platform/resources/${id}/reject-suggestion`), {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`reject-suggestion failed: ${res.status}`);
  return res.json();
}
