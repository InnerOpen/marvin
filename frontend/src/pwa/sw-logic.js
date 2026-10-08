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

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

/** The buttons an AI approval one tap may decide gets (Chromium shows them; iOS ignores them and opens it). */
export const APPROVAL_ACTIONS = [
  { action: "approve", title: "Approve" },
  { action: "deny", title: "Deny" },
];

/** A push's `approval` ({id, token}) when it is well-formed, else null: no buttons. */
export function approvalOf(value) {
  if (!value || typeof value !== "object") return null;
  const { id, token } = value;
  return typeof id === "string" && UUID.test(id) && typeof token === "string" && TOKEN.test(token)
    ? { id, token }
    : null;
}

/** The notification a push payload shows ({title, body, url, tag, badge, approval} from the server; anything else ignored). */
export function notificationFromPush(payload, origin) {
  const data = payload && typeof payload === "object" ? payload : {};
  const tag = text(data.tag, 64);
  const badge = Number.isInteger(data.badge) && data.badge >= 0 ? data.badge : null;
  const approval = approvalOf(data.approval);
  return {
    title: text(data.title, 120) || "Marvin",
    options: {
      body: text(data.body, 240),
      icon: "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      data: { url: safeTarget(data.url, origin), ...(approval ? { approval } : {}) },
      ...(tag ? { tag, renotify: true } : {}),
      ...(approval ? { actions: APPROVAL_ACTIONS } : {}),
    },
    badge,
  };
}

/**
 * What a notification button does: POST the approval's token to Marvin — no cookie, the token is the
 * authority — or null for anything else (a plain tap, an unknown button, a notification without an approval),
 * which opens the notification's page as usual.
 */
export function approvalRequest(action, data, origin) {
  const approval = approvalOf(data?.approval);
  if (!approval || !APPROVAL_ACTIONS.some((a) => a.action === action)) return null;
  return {
    url: `${origin}/api/self/push/approvals/${approval.id}/${action}`,
    init: {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: approval.token }),
    },
  };
}

/**
 * The confirmation a button leaves behind, from Marvin's answer (`ok`, and its JSON `body`): what was done, or
 * why not — then (`open`) the conversation, so the person can decide there. Replaces the approval's
 * notification (same tag); tapping it opens the conversation.
 */
export function approvalOutcome(action, ok, body, fallbackUrl, origin, tag = "") {
  const answer = body && typeof body === "object" ? body : {};
  const url = safeTarget(typeof answer.url === "string" ? answer.url : fallbackUrl, origin);
  const verb = action === "deny" ? "deny" : "approve";
  const title = ok
    ? text(answer.message, 120) || (verb === "deny" ? "Denied" : "Approved")
    : `Couldn't ${verb}: ${text(typeof answer.detail === "string" ? answer.detail : "", 100) || "Marvin didn't answer."}`;
  const badge = ok && Number.isInteger(answer.badge) && answer.badge >= 0 ? answer.badge : null;
  return {
    title,
    options: {
      body: ok ? "The results are in the conversation." : "Opening the conversation to decide there.",
      icon: "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      data: { url },
      ...(tag ? { tag: text(tag, 64) } : {}),
    },
    badge,
    open: !ok,
    url,
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
