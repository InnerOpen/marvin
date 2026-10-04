// Who may manage workspace configuration (API clients today) — the admin's mirror of the backend's
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

/** Await a request the caller may not be allowed to make: null on a 403, any other failure rethrown. */
export async function nullIfForbidden<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (e) {
    const err = e as { statusCode?: unknown; status?: unknown } | null;
    if ((err?.statusCode ?? err?.status) === 403) return null;
    throw e;
  }
}
