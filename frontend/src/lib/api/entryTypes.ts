/**
 * Entry Types API client - SDK wrapper
 * Migrated to use @inneropen/marvin-sdk
 */

import type { PlatformEntryType } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export interface EntryTypeCreate {
  name: string;
  slug?: string;
  description?: string;
  icon?: string;
  color?: string;
  sortOrder?: number;
  isRendered?: boolean;
  schemaJson?: Record<string, unknown>;
  renderingJson?: Record<string, unknown>;
  capabilitiesJson?: Record<string, unknown>;
  recipeJson?: Record<string, unknown>;
  /** Where the site renders an entry of this type, e.g. "/works/{slug}"; null clears it. */
  pageUrlPattern?: string | null;
}

export interface EntryTypeUpdate {
  name?: string;
  slug?: string;
  description?: string;
  icon?: string;
  color?: string;
  sortOrder?: number;
  isRendered?: boolean;
  schemaJson?: Record<string, unknown>;
  renderingJson?: Record<string, unknown>;
  capabilitiesJson?: Record<string, unknown>;
  recipeJson?: Record<string, unknown>;
  /** Where the site renders an entry of this type, e.g. "/works/{slug}"; null clears it. */
  pageUrlPattern?: string | null;
}

// pageUrlPattern is newer than the published SDK types; drop the intersection once they carry it.
export type EntryTypeRead = PlatformEntryType & { pageUrlPattern?: string | null };

/**
 * List all entry types in the current workspace
 */
export async function listEntryTypes(authToken: string): Promise<EntryTypeRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.entryTypes.list();
}

/**
 * Get a single entry type by ID
 */
export async function getEntryType(id: string, authToken: string): Promise<EntryTypeRead> {
  const sdk = createSdkClient(authToken);
  return sdk.entryTypes.get(id);
}

/**
 * Create a new entry type
 */
export async function createEntryType(data: EntryTypeCreate, authToken: string): Promise<EntryTypeRead> {
  const sdk = createSdkClient(authToken);
  return sdk.entryTypes.create(data);
}

/**
 * Update an entry type
 */
export async function updateEntryType(id: string, data: EntryTypeUpdate, authToken: string): Promise<EntryTypeRead> {
  const sdk = createSdkClient(authToken);
  return sdk.entryTypes.update(id, data);
}

/**
 * Delete an entry type
 */
export async function deleteEntryType(id: string, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.entryTypes.delete(id);
}
