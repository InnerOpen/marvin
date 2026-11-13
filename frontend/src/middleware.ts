import { defineMiddleware } from "astro:middleware";

import { getCookieName, getServerApiBaseUrl } from "@/lib/api/config";
import { readCurrentWorkspace, readProfile, readWorkspaces } from "@/lib/api/self";
import { createRequestCache, type RequestScope } from "@/lib/requestCache";
import { expiredSessionRedirect, isExpired, sessionRejected } from "@/lib/session";
import { needsWorkspace, noWorkspaceLanding } from "@/lib/workspaceGate";

/** How long the session check may take before the page renders anyway (the API being slow isn't a sign-out). */
const SESSION_CHECK_TIMEOUT_MS = 3000;

async function profileStatus(token: string): Promise<number> {
  const response = await fetch(`${getServerApiBaseUrl()}/api/self`, {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(SESSION_CHECK_TIMEOUT_MS),
  });
  return response.status;
}

/**
 * `read`, or a failure once SESSION_CHECK_TIMEOUT_MS has passed. Only this check stops waiting: the read itself goes on
 * and is shared with the page (lib/requestCache.ts), so a slow API never leaves a failed read behind for the page.
 */
async function within<T>(read: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("The API took too long to answer.")), SESSION_CHECK_TIMEOUT_MS);
  });
  try {
    return await Promise.race([read, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Where a page view that needs a workspace goes when the user has none (lib/workspaceGate.ts): Admin for a super
 * admin, else the waiting-for-an-invite page — or null to render the page as asked. Asked only for pages that show a
 * workspace's content; an API that can't answer never redirects anyone. The reads are the
 * request's own (`locals`), so the page and its layout reuse them instead of asking again.
 */
async function noWorkspaceRedirect(method: string, url: URL, token: string, locals: RequestScope): Promise<string | null> {
  if ((method !== "GET" && method !== "HEAD") || !needsWorkspace(url.pathname)) return null;
  // These pages draw AppLayout, which reads the user and their workspaces as well: all three go out at once, and the
  // page finds them waiting rather than asking one after another. Not awaited here, so not a wait for this check.
  for (const read of [readProfile(token, locals), readWorkspaces(token, locals)]) read.catch(() => null);
  try {
    if ((await within(readCurrentWorkspace(token, locals))) !== null) return null;
    // An error answer leaves the role unknown (the landing for anyone but a super admin); no answer renders the page.
    const profile = await within(readProfile(token, locals)).catch((error: { statusCode?: unknown }) => {
      if (typeof error?.statusCode === "number") return null;
      throw error;
    });
    return noWorkspaceLanding(profile?.platformRole);
  } catch {
    return null;
  }
}

/**
 * Turn a Response thrown during page rendering into that Response.
 *
 * The auth helpers signal "stop rendering, go here instead" by throwing the result of
 * Astro.redirect (see requireAuth in lib/auth.ts). Astro only unwraps a thrown Response in
 * endpoints and actions — thrown out of .astro frontmatter it is just an unhandled error, so
 * every protected page answered 500 instead of redirecting to /login. Catching it here keeps
 * the throw-to-redirect idiom working at all ~25 call sites.
 *
 * Before that, a request carrying an expired or rejected login token is sent to the login page (see below), and a
 * GET or HEAD request gets its own cache of API reads (`locals.apiCache`, lib/requestCache.ts), so the page, its layout
 * and their components read the signed-in user, their workspaces and the like once. A POST writes and then renders,
 * so it gets none and reads fresh.
 */
export const onRequest = defineMiddleware(async (context, next) => {
  const method = context.request.method;
  if (method === "GET" || method === "HEAD") context.locals.apiCache = createRequestCache();
  // A page view with an expired login (lib/session.ts) goes to the login page and back, instead of every API call on
  // the page failing with "Authentication failed: Unauthorized". The dead cookie goes either way.
  // The same for a token the API rejects though it hasn't expired (a rotated secret, a removed user), asked once
  // per token every few minutes.
  const token = context.cookies.get(getCookieName())?.value;
  if (token) {
    const login = expiredSessionRedirect(context.request.method, context.url);
    const dead = isExpired(token) || (login !== null && (await sessionRejected(token, () => profileStatus(token))));
    if (dead) {
      context.cookies.delete(getCookieName(), { path: "/" });
      if (login) return context.redirect(login, 302);
    } else {
      const landing = await noWorkspaceRedirect(method, context.url, token, context.locals);
      if (landing) return context.redirect(landing, 302);
    }
  }
  try {
    return await next();
  } catch (error) {
    if (error instanceof Response) {
      return error;
    }
    throw error;
  }
});
