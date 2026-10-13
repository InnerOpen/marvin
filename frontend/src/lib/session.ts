/**
 * The login session as the frontend sees it: the access token in its cookie.
 *
 * The backend's token expires on its own (TOKEN_TIME, 48 hours by default); a cookie that outlives it sends a dead
 * token with every request, so pages answered "Authentication failed: Unauthorized" until the user found the login
 * page. The cookie now lives exactly as long as its token (cookieMaxAge), and a page request that still carries an
 * expired one goes to the login page and back (middleware.ts: expiredSessionRedirect).
 */

/** How long a cookie lives when its token's expiry can't be read: the old fixed lifetime. */
export const FALLBACK_COOKIE_SECONDS = 60 * 60 * 24 * 7;

/** Pages that work signed out: an expired cookie there is just dropped, never sent to the login page. */
const SIGNED_OUT_PAGES = ["/login", "/forgot", "/register"];
/** Not pages: API routes answer for themselves, and these are fetched by the browser, not visited. */
const NOT_PAGES = ["/api/", "/_astro/", "/healthz", "/version.json", "/manifest.webmanifest", "/share-target"];

/** When `token` (a JWT) expires, in ms since the epoch; null when it isn't a JWT or says nothing. */
export function tokenExpiresAt(token: string | null | undefined): number | null {
  const payload = token?.split(".")[1];
  if (!payload) return null;
  try {
    const json = atob(
      payload
        .replace(/-/g, "+")
        .replace(/_/g, "/")
        .padEnd(Math.ceil(payload.length / 4) * 4, "="),
    );
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp * 1000 : null;
  } catch {
    return null;
  }
}

/** Whether `token` has expired by `now` (ms). A token whose expiry can't be read is left to the backend to judge. */
export function isExpired(token: string | null | undefined, now: number = Date.now()): boolean {
  const expiresAt = tokenExpiresAt(token);
  return expiresAt !== null && expiresAt <= now;
}

/** The cookie's max-age in seconds: until the token expires, so the browser drops them together. */
export function cookieMaxAge(token: string, now: number = Date.now()): number {
  const expiresAt = tokenExpiresAt(token);
  return expiresAt === null ? FALLBACK_COOKIE_SECONDS : Math.max(0, Math.floor((expiresAt - now) / 1000));
}

/**
 * Where a request carrying an expired token should go instead: the login page, coming back to `url` after — or null
 * to go ahead (a signed-out page, an API call, something other than a page view).
 */
export function expiredSessionRedirect(method: string, url: URL): string | null {
  const path = url.pathname;
  if (method !== "GET" && method !== "HEAD") return null;
  if (NOT_PAGES.some((prefix) => path === prefix || path.startsWith(prefix))) return null;
  if (SIGNED_OUT_PAGES.some((page) => path === page || path.startsWith(`${page}/`))) return null;
  const back = `${path}${url.search}`;
  return back === "/" ? "/login" : `/login?return=${encodeURIComponent(back)}`;
}

/**
 * The `return` query value as a path on this site, or "/" — never another origin: `return=https://elsewhere` or
 * `return=//elsewhere` after login would send a user off-site (an open redirect).
 */
export function safeReturnPath(value: string | null | undefined): string {
  if (!value?.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value;
}

/** How long a session the API accepted isn't asked about again (per token, in this server's memory). */
export const SESSION_CHECK_MS = 5 * 60_000;
const SESSION_CHECK_LIMIT = 1000;
const acceptedUntil = new Map<string, number>();

/**
 * Whether the API rejects this unexpired token: a rotated server secret, a deleted or disabled user — the token
 * still looks valid by its own expiry, but every page's API calls would fail with "Unauthorized". `askApi` answers
 * the HTTP status of a cheap authenticated call. Only a 401 counts as rejected: an API that can't be reached says
 * nothing about the session, so it never signs anyone out. An accepted token isn't asked about again for
 * SESSION_CHECK_MS.
 */
export async function sessionRejected(
  token: string,
  askApi: () => Promise<number>,
  now: number = Date.now(),
): Promise<boolean> {
  if ((acceptedUntil.get(token) ?? 0) > now) return false;
  let status: number;
  try {
    status = await askApi();
  } catch {
    return false;
  }
  if (status === 401) {
    acceptedUntil.delete(token);
    return true;
  }
  if (status >= 200 && status < 300) {
    if (acceptedUntil.size >= SESSION_CHECK_LIMIT) acceptedUntil.clear(); // bounded: a full map just starts over
    acceptedUntil.set(token, now + SESSION_CHECK_MS);
  }
  return false;
}
