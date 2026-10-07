/**
 * The Trash — deleted entries, waiting to be restored or emptied (backend: services/entries/trash.py).
 *
 * Delete moves an entry to the Trash; Restore brings it back to the status it had (a published entry as
 * a draft); Delete forever / Empty trash remove entries for good (emptying is ADMIN/OWNER only).
 * Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 */

import type { EntryRead } from "./entries";
import { fetchApi } from "./client";

const ENTRIES = "/api/platform/entries";

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

/** Delete everything in the Trash forever (workspace ADMIN/OWNER). Returns how many were deleted. */
export async function emptyTrash(authToken?: string): Promise<number> {
  const res = await fetchApi<{ deleted: number }>(`${ENTRIES}/trash/empty`, { method: "POST" }, authToken);
  return res.deleted;
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
