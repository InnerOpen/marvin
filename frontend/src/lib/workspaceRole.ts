// Who may manage workspace configuration — the admin's mirror of the backend's
// `require_workspace_admin` gate, so pages can hide actions the API would refuse with a 403.

import type { WorkspaceWithMembership } from "@inneropen/marvin-sdk/platform";

interface CallerFlags {
  admin?: boolean | null;
  platformRole?: string | null;
}

/**
 * True when the caller is OWNER/ADMIN of their active workspace, a platform super admin, or a legacy
 * `admin` — the same set the backend lets through.
 *
 * @param memberships - from `listWorkspaces()`; the active entry carries the caller's role
 * @param user - the caller's profile, for the super-admin and legacy-admin bypasses
 */
export function canManageWorkspace(
  memberships: Pick<WorkspaceWithMembership, "role" | "isActive">[],
  user?: CallerFlags | null,
): boolean {
  if (user?.admin === true || user?.platformRole === "SUPER_ADMIN") return true;
  const role = memberships.find((m) => m.isActive)?.role;
  return role === "OWNER" || role === "ADMIN";
}

export const API_CLIENTS_ADMIN_ONLY =
  "Only workspace owners and admins can view or manage API clients. Ask one of them if you need a site token.";

/** What an admin-only settings page shows a member instead of its controls. */
export const ADMINS_ONLY =
  "Only workspace owners and admins can view or change this. Ask one of them if something here needs changing.";

/** Whether a failed API call was the backend refusing the caller (403) — an SDK or fetchApi error. */
export function isForbidden(e: unknown): boolean {
  const err = e as { statusCode?: unknown; status?: unknown } | null;
  return (err?.statusCode ?? err?.status) === 403;
}

/** Await a request the caller may not be allowed to make: null on a 403, any other failure rethrown. */
export async function nullIfForbidden<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (e) {
    if (isForbidden(e)) return null;
    throw e;
  }
}
