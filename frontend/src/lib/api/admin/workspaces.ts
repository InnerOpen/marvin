/**
 * Admin Workspaces API — renaming a workspace (name and slug), removing a member from one, and deleting one safely
 * (a preview of what goes, a backup, the typed name). A changed slug keeps resolving to the workspace (Publishing API URLs,
 * CLI arguments, backups), so renaming doesn't break what already uses the old one.
 */

import { ApiRequestError, fetchApi } from "../client";

export interface AdminWorkspace {
  id: string;
  name: string;
  slug: string | null;
}

/** What deleting a workspace removes, and whether the backup rule is met (`GET /admin/groups/{id}/delete-preview`). */
export interface WorkspaceDeletePreview {
  workspaceId: string;
  workspaceName: string;
  members: number;
  entries: number;
  assets: number;
  assetBytes: number;
  integrations: number;
  scheduledTasks: number;
  smtpProfiles: number;
  /** Users whose home this is: they lose the home and stay, in no workspace. */
  homeUsers: number;
  lastBackupAt: string | null;
  /** A bundle from the last `backupMaxAgeHours` exists: a delete doesn't need the explicit skip. */
  backupIsRecent: boolean;
  backupMaxAgeHours: number;
  /** Its stored files are kept this many days after the delete, then purged (Admin → Storage). */
  storageGraceDays: number;
}

export interface WorkspaceBackup {
  filename: string;
  size: number;
  created_at: string;
  download_url: string;
}

/** Rename a workspace. `slug` blank or omitted: derived from the name. 409 when a name/slug is taken. */
export async function renameWorkspace(
  id: string,
  name: string,
  slug?: string | null,
  authToken?: string,
): Promise<AdminWorkspace> {
  return fetchApi<AdminWorkspace>(
    `/api/admin/groups/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name, slug: slug?.trim() || null }),
    },
    authToken,
  );
}

/** Remove a user from a workspace. 403 for yourself or the workspace's last OWNER, 404 if not a member. */
export async function removeWorkspaceMember(workspaceId: string, userId: string, authToken?: string): Promise<void> {
  await fetchApi(
    `/api/admin/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
    authToken,
  );
}

export async function getWorkspaceDeletePreview(id: string, authToken?: string): Promise<WorkspaceDeletePreview> {
  return fetchApi<WorkspaceDeletePreview>(`/api/admin/groups/${encodeURIComponent(id)}/delete-preview`, {}, authToken);
}

/** Make a backup bundle of the workspace now (the one a delete asks for). */
export async function backUpWorkspace(id: string, authToken?: string): Promise<WorkspaceBackup> {
  return fetchApi<WorkspaceBackup>(`/api/admin/backups/workspaces/${encodeURIComponent(id)}`, { method: "POST" }, authToken);
}

/**
 * Delete a workspace. `confirmName` is its typed name; `skipBackup` deletes without a bundle from the last 24 hours
 * (otherwise 409 `backup_required`). Its content goes with it (`force`: the typed name is the confirmation).
 */
export async function deleteWorkspace(
  id: string,
  options: { confirmName: string; skipBackup: boolean },
  authToken?: string,
): Promise<{ status: string; message: string; storageLocations: number; storagePurgeAfter: string | null }> {
  const query = new URLSearchParams({ confirm_name: options.confirmName, force: "true" });
  if (options.skipBackup) query.set("skip_backup", "true");
  return fetchApi(`/api/admin/groups/${encodeURIComponent(id)}?${query}`, { method: "DELETE" }, authToken);
}

/** The readable message of an admin API error (`detail.message`), else the error's own. */
export function adminErrorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    const detail = (err.body as { detail?: { message?: string } } | undefined)?.detail;
    if (detail && typeof detail === "object" && detail.message) return detail.message;
  }
  return err instanceof Error ? err.message : String(err);
}
