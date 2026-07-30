/**
 * API base URL resolution — resolved at runtime, never baked in at build.
 *
 * The frontend ships as one image that any deployment configures with its own backend address.
 * Reading `import.meta.env` here would let Vite inline the value at build time, pinning the image
 * to whatever URL it was built against — so this module reads the *live* environment instead:
 *
 * - On the server (SSR): `process.env`, read fresh, so the running container's configuration wins.
 * - In the browser: a value the SSR server injects into the page at request time (see
 *   `RuntimeConfig.astro`). The browser has no `process.env`, so the server hands it the URL.
 *
 * The two can legitimately differ. A split deployment reaches the backend over an internal service
 * address from the SSR server (`MARVIN_API_URL`, e.g. http://marvin-api:8080) while the browser
 * must use a publicly reachable one (`PUBLIC_MARVIN_API_URL`, e.g. https://cms.example.com). For a
 * single combined container, set one and both use it.
 */

const DEFAULT_API_BASE_URL = "http://localhost:8080";

/** The shape the SSR server injects onto `window` for browser code to read. */
export interface MarvinRuntimeConfig {
  apiBaseUrl: string;
  /** When true, browser API calls go same-origin through the frontend proxy (see getApiBaseUrl). */
  browserApiProxy?: boolean;
}

declare global {
  interface Window {
    __MARVIN_RUNTIME__?: MarvinRuntimeConfig;
  }
}

function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

function serverEnv(name: string): string | undefined {
  // Guarded because this module is also bundled for the browser, where `process` is undefined.
  return typeof process !== "undefined" ? process.env[name] : undefined;
}

/**
 * The URL the SSR server uses to reach the backend. Prefers the internal address so a split
 * deployment can keep backend traffic on the cluster network; falls back to the public one, then
 * the local default.
 */
export function getServerApiBaseUrl(): string {
  const url = serverEnv("MARVIN_API_URL") || serverEnv("PUBLIC_MARVIN_API_URL") || DEFAULT_API_BASE_URL;
  return stripTrailingSlash(url);
}

/**
 * The URL the browser uses to reach the backend. Prefers the public address (it must be reachable
 * from the user's machine, not just the cluster). This is what `RuntimeConfig.astro` injects.
 */
export function getBrowserApiBaseUrl(): string {
  const url = serverEnv("PUBLIC_MARVIN_API_URL") || serverEnv("MARVIN_API_URL") || DEFAULT_API_BASE_URL;
  return stripTrailingSlash(url);
}

/**
 * The API base URL for the current execution context. Call it at request time — do not cache the
 * result at module scope, or a browser bundle would freeze whatever value happened to load first.
 */
export function getApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    // Proxy mode (default): route every browser API call same-origin through the frontend's
    // catch-all proxy (pages/api/[...path].ts), which reads the httpOnly session cookie server-side
    // and forwards a Bearer token to the backend. Being same-origin, it is immune to the split
    // UI/API problem where the host-only session cookie never reaches a separate API host (OCP).
    if (window.__MARVIN_RUNTIME__?.browserApiProxy) {
      return stripTrailingSlash(window.location.origin);
    }
    const injected = window.__MARVIN_RUNTIME__?.apiBaseUrl;
    return stripTrailingSlash(injected || DEFAULT_API_BASE_URL);
  }
  return getServerApiBaseUrl();
}

/**
 * Whether auth cookies should carry the `Secure` flag. Browsers only store `Secure` cookies over
 * HTTPS, so a deploy served over plain HTTP (e.g. a homelab NodePort) MUST set this false or the
 * session cookie is silently dropped and login never sticks — even though backend auth succeeded.
 *
 * Resolved at runtime (never baked in), so one image serves both HTTP and HTTPS deployments:
 *   1. Explicit `MARVIN_COOKIE_SECURE` ("true"/"false"/"1"/"0") wins.
 *   2. Otherwise derive from the public URL scheme — https ⇒ secure, http ⇒ not.
 *   3. Fall back to build mode (production ⇒ secure) when nothing else is known.
 */
export function getCookieSecure(): boolean {
  const explicit = serverEnv("MARVIN_COOKIE_SECURE");
  if (explicit != null && explicit.trim() !== "") {
    return /^(1|true|yes|on)$/i.test(explicit.trim());
  }
  const publicUrl = serverEnv("PUBLIC_MARVIN_API_URL") || serverEnv("MARVIN_API_URL");
  if (publicUrl) return publicUrl.trim().startsWith("https:");
  return import.meta.env.PROD;
}

/**
 * The auth cookie name. MUST match the backend's `AUTH_COOKIE_NAME` — the backend reads
 * `request.cookies[settings.AUTH_COOKIE_NAME]` (dependencies.py), so the frontend has to write and
 * read the same name or auth silently breaks. Set the one `AUTH_COOKIE_NAME` env on both (shared in
 * a combined container). Defaults to "marvin.access_token", matching the backend default.
 */
export function getCookieName(): string {
  return serverEnv("AUTH_COOKIE_NAME") || "marvin.access_token";
}

/**
 * Whether browser API calls should route same-origin through the frontend proxy instead of calling
 * the backend directly. On (default) standardizes the whole UI on the proxy pattern — origin-
 * independent, so it works for split UI/API deployments and removes the browser's dependency on
 * backend CORS. Set `MARVIN_BROWSER_API_PROXY=false` to fall back to direct browser→API calls.
 * Read at runtime and injected into the page by RuntimeConfig.astro.
 */
export function getBrowserApiProxyEnabled(): boolean {
  const explicit = serverEnv("MARVIN_BROWSER_API_PROXY");
  if (explicit != null && explicit.trim() !== "") {
    return /^(1|true|yes|on)$/i.test(explicit.trim());
  }
  return true;
}

/**
 * Site-client read token for unauthenticated public API access. Server-only: it is a credential
 * and must never be injected into the page. Read at runtime so the image is not pinned to a token
 * baked in at build.
 */
export function getSiteClientToken(): string {
  return serverEnv("MARVIN_SITE_CLIENT_TOKEN") ?? "";
}

/** Whether an API backend is resolvable in the current context. */
export function hasApiBackend(): boolean {
  return getApiBaseUrl().length > 0;
}

/** Construct a full API URL from a path, against the current context's base. */
export function getApiUrl(path: string): URL {
  const base = getApiBaseUrl();
  if (!base) {
    throw new Error("MARVIN_API_URL is not configured.");
  }
  return new URL(path.replace(/^\//, ""), `${base}/`);
}
