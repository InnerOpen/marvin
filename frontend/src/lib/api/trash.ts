/**
 * The Trash — deleted entries, assets and resources, waiting to be restored or emptied (backend:
 * services/entries/trash.py for entries, services/trash.py for assets, resources and the whole Trash).
 *
 * Delete moves an item to the Trash; Restore brings it back (an entry to the status it had, a published one
 * as a draft); Delete forever / Empty trash remove items for good — an asset's file too (emptying is
 * ADMIN/OWNER only, and empties all three).
 * Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 */

import type { AssetRead } from "./assets";
import type { EntryRead } from "./entries";
import type { ResourceRead } from "./resources";
import { fetchApi } from "./client";

const ENTRIES = "/api/platform/entries";
const TRASH = "/api/platform/trash";

/** What else can be in the Trash, and where its routes live. */
export type TrashKind = "asset" | "resource";
const ITEMS: Record<TrashKind, string> = { asset: "/api/platform/assets", resource: "/api/platform/resources" };

/** How long the Trash keeps entries, in days (0 = until someone empties it). */
export interface TrashAutoEmpty {
  platform_default_days: number;
  /** The workspace's own choice; null inherits the platform default. */
  workspace_override_days: number | null;
  effective_days: number;
}

export interface TrashSummary extends TrashAutoEmpty {
  count: number;
}

/** The whole Trash: how many of each kind, and their total. */
export interface TrashCounts extends TrashAutoEmpty {
  entries: number;
  assets: number;
  resources: number;
  total: number;
}

export async function getTrashSummary(authToken?: string): Promise<TrashSummary> {
  return fetchApi<TrashSummary>(`${ENTRIES}/trash`, { method: "GET" }, authToken);
}

/** Move an entry to the Trash (what Delete does). */
export async function moveToTrash(id: string, authToken?: string): Promise<void> {
  await fetchApi(`${ENTRIES}/${id}`, { method: "DELETE" }, authToken);
}

/** Take an entry out of the Trash, back to the status it had. */
export async function restoreFromTrash(id: string, authToken?: string): Promise<EntryRead> {
  return fetchApi<EntryRead>(`${ENTRIES}/${id}/restore`, { method: "POST" }, authToken);
}

/** Delete one entry that is in the Trash forever. */
export async function deleteForever(id: string, authToken?: string): Promise<void> {
  await fetchApi(`${ENTRIES}/${id}?permanent=true`, { method: "DELETE" }, authToken);
}

/** Delete everything in the Trash forever — entries, assets (files too) and resources (workspace ADMIN/OWNER).
 * Returns how many were deleted. */
export async function emptyTrash(authToken?: string): Promise<number> {
  const res = await fetchApi<{ deleted: number }>(`${TRASH}/empty`, { method: "POST" }, authToken);
  return res.deleted;
}

export async function getTrashCounts(authToken?: string): Promise<TrashCounts> {
  return fetchApi<TrashCounts>(TRASH, { method: "GET" }, authToken);
}

export async function listTrashedAssets(authToken?: string): Promise<AssetRead[]> {
  return fetchApi<AssetRead[]>(`${TRASH}/assets`, { method: "GET" }, authToken);
}

export async function listTrashedResources(authToken?: string): Promise<ResourceRead[]> {
  return fetchApi<ResourceRead[]>(`${TRASH}/resources`, { method: "GET" }, authToken);
}

/** Move an asset or resource to the Trash (what Delete does); its file stays in storage meanwhile. */
export async function moveItemToTrash(kind: TrashKind, id: string, authToken?: string): Promise<void> {
  await fetchApi(`${ITEMS[kind]}/${id}`, { method: "DELETE" }, authToken);
}

/** Take an asset or resource out of the Trash. */
export async function restoreItemFromTrash(kind: TrashKind, id: string, authToken?: string): Promise<void> {
  await fetchApi(`${ITEMS[kind]}/${id}/restore`, { method: "POST" }, authToken);
}

/** Delete one asset (its file too) or resource that is in the Trash forever. */
export async function deleteItemForever(kind: TrashKind, id: string, authToken?: string): Promise<void> {
  await fetchApi(`${ITEMS[kind]}/${id}?permanent=true`, { method: "DELETE" }, authToken);
}

export async function getWorkspaceTrashSettings(workspaceId: string, authToken?: string): Promise<TrashAutoEmpty> {
  return fetchApi<TrashAutoEmpty>(`/api/groups/${workspaceId}/preferences/trash`, { method: "GET" }, authToken);
}

const ADMIN_PATH = "/api/admin/trash";

export async function getPlatformTrashSettings(authToken?: string): Promise<{ auto_empty_days: number }> {
  return fetchApi<{ auto_empty_days: number }>(ADMIN_PATH, { method: "GET" }, authToken);
}

export async function updatePlatformTrashSettings(
  days: number,
  authToken?: string,
): Promise<{ auto_empty_days: number }> {
  return fetchApi<{ auto_empty_days: number }>(
    ADMIN_PATH,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ auto_empty_days: days }) },
    authToken,
  );
}
