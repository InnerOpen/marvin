/**
 * Entries API client - SDK wrapper
 * Migrated to use @inneropen/marvin-sdk
 */

import type {
  PlatformCollection,
  PlatformEntry,
  PlatformEntryCreate,
  PlatformEntryUpdate,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";
import { getApiUrl } from "./config";

export type EntryRead = PlatformEntry;
export type EntryCreate = PlatformEntryCreate;
export type EntryUpdate = PlatformEntryUpdate;
export type CollectionRead = PlatformCollection;

/**
 * List all entries in the current workspace
 */
export async function listEntries(authToken: string): Promise<EntryRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.entries.list();
}

/**
 * Get a single entry by ID
 */
export async function getEntry(id: string, authToken: string): Promise<EntryRead> {
  const sdk = createSdkClient(authToken);
  return sdk.entries.get(id);
}

/**
 * Create a new entry
 */
export async function createEntry(data: EntryCreate, authToken: string): Promise<EntryRead> {
  const sdk = createSdkClient(authToken);
  return sdk.entries.create(data);
}

/**
 * Update an existing entry
 */
export async function updateEntry(id: string, data: EntryUpdate, authToken: string): Promise<EntryRead> {
  const sdk = createSdkClient(authToken);
  return sdk.entries.update(id, data);
}

/**
 * Apply the entry's staged AI suggestion (suggestion_json) and clear it. Fetches the backend
 * directly (no dedicated SDK method yet).
 */
export async function applyEntrySuggestion(id: string, authToken: string): Promise<EntryRead> {
  const res = await fetch(getApiUrl(`/api/platform/entries/${id}/apply-suggestion`), {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`apply-suggestion failed: ${res.status}`);
  return res.json();
}

/** Discard the entry's staged AI suggestion without applying it. */
export async function rejectEntrySuggestion(id: string, authToken: string): Promise<EntryRead> {
  const res = await fetch(getApiUrl(`/api/platform/entries/${id}/reject-suggestion`), {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`reject-suggestion failed: ${res.status}`);
  return res.json();
}
