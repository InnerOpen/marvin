import { defineMiddleware } from "astro:middleware";

import { getCookieName } from "@/lib/api/config";
import { expiredSessionRedirect, isExpired } from "@/lib/session";

/**
 * Turn a Response thrown during page rendering into that Response.
 *
 * The auth helpers signal "stop rendering, go here instead" by throwing the result of
 * Astro.redirect (see requireAuth in lib/auth.ts). Astro only unwraps a thrown Response in
 * endpoints and actions — thrown out of .astro frontmatter it is just an unhandled error, so
 * every protected page answered 500 instead of redirecting to /login. Catching it here keeps
 * the throw-to-redirect idiom working at all ~25 call sites.
 *
 * Before that, a request carrying an expired login token is sent to the login page (see below).
 */
export const onRequest = defineMiddleware(async (context, next) => {
  // A page view with an expired login (lib/session.ts) goes to the login page and back, instead of every API call on
  // the page failing with "Authentication failed: Unauthorized". The dead cookie goes either way.
  const token = context.cookies.get(getCookieName())?.value;
  if (token && isExpired(token)) {
    context.cookies.delete(getCookieName(), { path: "/" });
    const login = expiredSessionRedirect(context.request.method, context.url);
    if (login) return context.redirect(login, 302);
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
