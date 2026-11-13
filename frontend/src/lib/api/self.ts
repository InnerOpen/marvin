/**
 * Who is signed in, their workspaces and the current one: what nearly every page, its layout and the middleware ask
 * the API, read once per page request when `scope` is the request's `Astro.locals` (lib/requestCache.ts). Without it
 * (the browser, a form POST) each call reads straight from the API. Errors reach the caller unchanged, so each keeps
 * its own fallback (a 401 still signs out, a 403 is still a 403).
 */

import type { UserProfile, Workspace, WorkspaceWithMembership } from "@inneropen/marvin-sdk/platform";
import { type RequestScope, readOnce } from "../requestCache";
import { createSdkClient } from "../sdk";

/** GET /api/self: the signed-in user. */
export const readProfile = (authToken: string | undefined, scope?: RequestScope): Promise<UserProfile> =>
  readOnce(scope, "/api/self", authToken, () => createSdkClient(authToken).user.getProfile());

/** GET /api/self/workspaces: the workspaces the user may use, with their role in each. */
export const readWorkspaces = (authToken: string | undefined, scope?: RequestScope): Promise<WorkspaceWithMembership[]> =>
  readOnce(scope, "/api/self/workspaces", authToken, () => createSdkClient(authToken).workspaces.list());

/** GET /api/self/workspaces/current, as the API answered it: null when the user is in no workspace. */
export const readCurrentWorkspace = (authToken: string | undefined, scope?: RequestScope): Promise<Workspace | null | undefined> =>
  readOnce(scope, "/api/self/workspaces/current", authToken, () => createSdkClient(authToken).workspaces.getCurrent());
