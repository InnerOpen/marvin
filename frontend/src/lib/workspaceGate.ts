/**
 * Pages that work inside a workspace, and where a user with none goes instead.
 *
 * A user may have no workspace (no home, no membership): an Admin-created, OIDC or LDAP sign-up waiting for an invite,
 * or a super admin on a fresh install. Every workspace-scoped API answers them 409 `no_workspace`, so their pages
 * can't render — the middleware (middleware.ts) sends a page view for one of these to `noWorkspaceLanding` first.
 */

/** Page prefixes whose content belongs to a workspace ("/" is the workspace dashboard). */
const WORKSPACE_PAGES = [
  "/workspace",
  "/workspaces",
  "/automation",
  "/publishing",
  "/site-clients",
  "/share",
  "/platform",
  "/user/api-tokens",
  "/user/cli-and-mcp",
];

/** Whether the page at `path` shows a workspace's content (so it needs the user to have one). */
export function needsWorkspace(path: string): boolean {
  return path === "/" || WORKSPACE_PAGES.some((page) => path === page || path.startsWith(`${page}/`));
}

/** The page for a user with no workspace: Admin for a super admin (it works with none), else the waiting page. */
export function noWorkspaceLanding(platformRole: string | null | undefined): string {
  return platformRole === "SUPER_ADMIN" ? "/admin" : "/no-workspace";
}

/** The API's 409 for a workspace-scoped call from a user with no workspace (`detail.code`). */
export const NO_WORKSPACE = "no_workspace";

/** Whether a response body is the API's "no workspace" error. */
export function isNoWorkspaceError(body: unknown): boolean {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "object" && detail !== null && (detail as { code?: unknown }).code === NO_WORKSPACE;
}
