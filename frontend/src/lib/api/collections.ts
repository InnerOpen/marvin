/**
 * Collections API client - SDK wrapper
 * Migrated to use @inneropen/marvin-sdk
 */

import type {
  PlatformCollection,
  PlatformCollectionCreate,
  PlatformCollectionUpdate,
  PlatformEntry,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";
import { fetchApi } from "./client";
import { getApiUrl } from "./config";

// Re-export SDK types with legacy names for backward compatibility
export type CollectionRead = PlatformCollection;
export type CollectionCreate = PlatformCollectionCreate;
export type CollectionUpdate = PlatformCollectionUpdate;
export type EntryRead = PlatformEntry;

/**
 * List all collections in the current workspace
 */
export async function listCollections(authToken: string): Promise<CollectionRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.list();
}

/**
 * Get a single collection by ID
 */
export async function getCollection(id: string, authToken: string): Promise<CollectionRead> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.get(id);
}

/**
 * Create a new collection
 */
export async function createCollection(data: CollectionCreate, authToken: string): Promise<CollectionRead> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.create(data);
}

/**
 * Update an existing collection
 */
export async function updateCollection(id: string, data: CollectionUpdate, authToken: string): Promise<CollectionRead> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.update(id, data);
}

/**
 * Delete a collection
 */
export async function deleteCollection(id: string, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.delete(id);
}

/**
 * Bulk-reorder collections (sets each one's sortOrder). Works for system collections too.
 */
export async function reorderCollections(
  order: Array<{ id: string; sortOrder: number }>,
  authToken: string,
): Promise<{ updated: number }> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.reorder(order);
}

/**
 * Get entries in a collection
 */
export async function getCollectionEntries(collectionId: string, authToken: string): Promise<EntryRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.getEntries(collectionId);
}

export interface CollectionMember {
  id: string;
  label: string;
  slug: string;
  type: "entry" | "asset" | "resource";
}

/**
 * Get a collection's membership as a lightweight typed list (entries/assets/resources),
 * for uniformly displaying membership of asset/resource smart collections.
 */
export async function getCollectionMembers(collectionId: string, authToken?: string): Promise<CollectionMember[]> {
  const res = await fetch(getApiUrl(`/api/platform/collections/${collectionId}/members`), {
    headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
  });
  if (!res.ok) throw new Error(`get members failed: ${res.status}`);
  return res.json();
}

export interface SmartRulesPreview {
  total: number;
  items: CollectionMember[];
  ignoredKeys: string[];
  note: string | null;
}

/**
 * Evaluate unsaved smart-collection rules — what the collection would contain if saved now.
 * Same matching code as materialization, so the count is the real membership. Saves nothing.
 */
export async function previewSmartRules(
  targetType: CollectionMember["type"],
  smartRules: Record<string, unknown>,
  limit = 10,
  authToken?: string,
): Promise<SmartRulesPreview> {
  return fetchApi<SmartRulesPreview>(
    "/api/platform/collections/preview",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targetType, smartRules, limit }),
    },
    authToken,
  );
}

/**
 * Update junction fields (role, metadata) for an entry in a collection
 */
export async function updateCollectionEntry(
  collectionId: string,
  entryId: string,
  data: { role?: string | null; metadataJson?: Record<string, unknown> | null },
  authToken: string,
): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.collections.updateEntryJunction(collectionId, entryId, data);
}
