// The service worker's decisions, kept apart from its event wiring (sw.js) so `npm test` can check them.
// Plain JS on purpose: integrations/pwa.mjs inlines this file into dist/client/sw.js at build time (dropping
// the `export` keywords), so it must not import anything and must run in a worker as-is.

export const CACHE_PREFIX = "marvin-";
export const OFFLINE_URL = "/offline.html";

/** The two caches one build owns: the precached app shell and assets fetched later. */
export function cacheNames(version) {
  return { shell: `${CACHE_PREFIX}shell-${version}`, assets: `${CACHE_PREFIX}assets-${version}` };
}

/** Caches to delete on activate: Marvin's from any other build. Other caches on the origin are left alone. */
export function staleCaches(keys, version) {
  const keep = Object.values(cacheNames(version));
  return keys.filter((k) => k.startsWith(CACHE_PREFIX) && !keep.includes(k));
}

/** Static files safe to keep: Astro's content-hashed build output, the icons and the offline page. */
export function isStaticAsset(pathname) {
  return pathname.startsWith("/_astro/") || pathname.startsWith("/icons/") || pathname === OFFLINE_URL;
}

/**
 * How the worker handles a request:
 *   "navigate" — a page load: always the network (pages are signed-in HTML, never cached), the offline
 *                page when there is no network;
 *   "asset"    — a static file: cache first;
 *   "network"  — everything else, API calls above all: not touched, never cached.
 */
export function strategy(request, origin) {
  if (request.method !== "GET") return "network";
  let url;
  try {
    url = new URL(request.url);
  } catch {
    return "network";
  }
  if (url.origin !== origin) return "network";
  if (url.pathname.startsWith("/api/")) return "network";
  if (request.mode === "navigate") return "navigate";
  return isStaticAsset(url.pathname) ? "asset" : "network";
}

/** Whether a fetched response may go in the cache: a whole, same-origin, successful one. */
export function cacheable(response) {
  return Boolean(response) && response.ok && response.status === 200 && response.type === "basic";
}

/** A notification's link, made safe: a path on this origin, else the dashboard. */
export function safeTarget(url, origin) {
  if (typeof url !== "string" || url.trim() === "") return `${origin}/`;
  try {
    const target = new URL(url, origin);
    if (target.origin !== origin || (target.protocol !== "https:" && target.protocol !== "http:")) return `${origin}/`;
    return target.href;
  } catch {
    return `${origin}/`;
  }
}

function text(value, max) {
  return typeof value === "string" ? value.slice(0, max) : "";
}

/** The notification a push payload shows ({title, body, url, tag, badge} from the server; anything else ignored). */
export function notificationFromPush(payload, origin) {
  const data = payload && typeof payload === "object" ? payload : {};
  const tag = text(data.tag, 64);
  const badge = Number.isInteger(data.badge) && data.badge >= 0 ? data.badge : null;
  return {
    title: text(data.title, 120) || "Marvin",
    options: {
      body: text(data.body, 240),
      icon: "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      data: { url: safeTarget(data.url, origin) },
      ...(tag ? { tag, renotify: true } : {}),
    },
    badge,
  };
}

/** A push message's text as JSON, or a plain notification with that text as its body. */
export function parsePush(textValue) {
  if (!textValue) return {};
  try {
    const parsed = JSON.parse(textValue);
    return parsed && typeof parsed === "object" ? parsed : { body: String(parsed) };
  } catch {
    return { body: textValue };
  }
}
