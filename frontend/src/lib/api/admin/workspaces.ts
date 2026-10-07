/**
 * Admin Workspaces API — renaming a workspace (name and slug), the platform (admin's) workspace included.
 * A changed slug keeps resolving to the workspace (Publishing API URLs, CLI arguments, backups), so
 * renaming doesn't break what already uses the old one.
 */

import { ApiRequestError, fetchApi } from "../client";

export interface AdminWorkspace {
  id: string;
  name: string;
  slug: string | null;
  /** The platform (admin's) workspace: platform alerts and shared services run from it. */
  isPlatform: boolean;
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

/** The readable message of an admin API error (`detail.message`), else the error's own. */
export function adminErrorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    const detail = (err.body as { detail?: { message?: string } } | undefined)?.detail;
    if (detail && typeof detail === "object" && detail.message) return detail.message;
  }
  return err instanceof Error ? err.message : String(err);
}
