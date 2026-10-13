// Who may do what in the active workspace — the admin's mirror of the backend's role gates
// (`require_workspace_admin`, `require_workspace_editor`, `require_can_edit_entry` in
// marvin.routes._base.checks), so pages can hide actions the API would refuse with a 403.

import type { WorkspaceWithMembership } from "@inneropen/marvin-sdk/platform";

interface CallerFlags {
  admin?: boolean | null;
  platformRole?: string | null;
}

type Memberships = Pick<WorkspaceWithMembership, "role" | "isActive">[];

export type WorkspaceRoleName = "VIEWER" | "AUTHOR" | "EDITOR" | "ADMIN" | "OWNER";

const RANK: Record<WorkspaceRoleName, number> = { VIEWER: 1, AUTHOR: 2, EDITOR: 3, ADMIN: 4, OWNER: 5 };

/**
 * True when the caller holds `minimum` or a higher role in their active workspace, or is a platform
 * super admin or legacy `admin` (who pass every workspace gate) — the same set the backend lets through.
 *
 * @param memberships - from `listWorkspaces()`; the active entry carries the caller's role
 * @param user - the caller's profile, for the super-admin and legacy-admin bypasses
 */
export function hasWorkspaceRole(memberships: Memberships, user: CallerFlags | null | undefined, minimum: WorkspaceRoleName): boolean {
  if (user?.admin === true || user?.platformRole === "SUPER_ADMIN") return true;
  const role = memberships.find((m) => m.isActive)?.role as WorkspaceRoleName | undefined;
  return role !== undefined && (RANK[role] ?? 0) >= RANK[minimum];
}

/** OWNER/ADMIN: workspace settings and structure (entry types, forms). */
export function canManageWorkspace(memberships: Memberships, user?: CallerFlags | null): boolean {
  return hasWorkspaceRole(memberships, user, "ADMIN");
}

/** EDITOR and above: change any content (entries, collections, assets, resources, tags). */
export function canEditContent(memberships: Memberships, user?: CallerFlags | null): boolean {
  return hasWorkspaceRole(memberships, user, "EDITOR");
}

/** AUTHOR and above: create entries, upload assets, add tags. VIEWERs only read. */
export function canAuthorContent(memberships: Memberships, user?: CallerFlags | null): boolean {
  return hasWorkspaceRole(memberships, user, "AUTHOR");
}

/** Statuses only an EDITOR or above may set, or edit an entry in (backend `AUTHOR_LOCKED_STATUSES`). */
export const AUTHOR_LOCKED_STATUSES: readonly string[] = ["approved", "published"];

/**
 * Whether the caller may change (or delete) this entry: EDITOR and above any entry; an AUTHOR only
 * one they created while it is not approved or published.
 */
export function canEditEntry(
  memberships: Memberships,
  user: (CallerFlags & { id?: string | null }) | null | undefined,
  entry: { createdBy?: string | null; status?: string | null },
): boolean {
  if (canEditContent(memberships, user)) return true;
  if (!canAuthorContent(memberships, user)) return false;
  return !!user?.id && entry.createdBy === user.id && !AUTHOR_LOCKED_STATUSES.includes(entry.status ?? "");
}

export const API_CLIENTS_ADMIN_ONLY =
  "Only workspace owners and admins can view or manage API clients. Ask one of them if you need a site token.";

/** What an admin-only settings page shows a member instead of its controls. */
export const ADMINS_ONLY =
  "Only workspace owners and admins can view or change this. Ask one of them if something here needs changing.";

/** What a content page shows a member below EDITOR instead of its change controls. */
export const EDITORS_ONLY =
  "Only workspace editors, admins and owners can change this. Ask one of them if something here needs changing.";

/** What a create page shows a VIEWER, who can read the workspace's content but not add to it. */
export const AUTHORS_ONLY =
  "Viewers can read this workspace's content but not add to it. Ask a workspace admin for an author or editor role.";

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
