// The service worker's decisions, kept apart from its event wiring (sw.js) so `npm test` can check them.
// Plain JS on purpose: integrations/pwa.mjs inlines this file into dist/client/sw.js at build time (dropping
// the `export` keywords), so it must not import anything and must run in a worker as-is.

export const CACHE_PREFIX = "marvin-";
export const OFFLINE_URL = "/offline.html";
/** Files shared to the app, until the Share page has used them (or an hour has passed). */
export const SHARE_CACHE = `${CACHE_PREFIX}share`;

/** The two caches one build owns: the precached app shell and assets fetched later. */
export function cacheNames(version) {
  return { shell: `${CACHE_PREFIX}shell-${version}`, assets: `${CACHE_PREFIX}assets-${version}` };
}

/** Caches to delete on activate: Marvin's from any other build (a share in progress outlives an update). Other
 * caches on the origin are left alone. */
export function staleCaches(keys, version) {
  const keep = [...Object.values(cacheNames(version)), SHARE_CACHE];
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

/** A push's `workspace` (the group id it is about) when it is well-formed, else null: open where the app is. */
export function workspaceOf(value) {
  return typeof value === "string" && UUID.test(value) ? value : null;
}

/**
 * The request that makes `workspace` the active one before a notification's page opens, or null when there is
 * nothing to switch (no workspace, or it is already `current`). The active workspace is the person's (server-side),
 * so this switches it everywhere, as the workspace switcher does.
 */
export function switchRequest(workspace, current) {
  const target = workspaceOf(workspace);
  if (!target || (typeof current === "string" && current.toLowerCase() === target.toLowerCase())) return null;
  return {
    url: "/api/self/workspaces/current",
    init: {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: target }),
    },
  };
}

/** A push's `approval` ({id, token}) when it is well-formed, else null: no buttons. */
export function approvalOf(value) {
  if (!value || typeof value !== "object") return null;
  const { id, token } = value;
  return typeof id === "string" && UUID.test(id) && typeof token === "string" && TOKEN.test(token)
    ? { id, token }
    : null;
}

/** The notification a push payload shows ({title, body, url, tag, badge, approval, workspace} from the server; anything else ignored). */
export function notificationFromPush(payload, origin) {
  const data = payload && typeof payload === "object" ? payload : {};
  const tag = text(data.tag, 64);
  const badge = Number.isInteger(data.badge) && data.badge >= 0 ? data.badge : null;
  const approval = approvalOf(data.approval);
  const workspace = workspaceOf(data.workspace);
  return {
    title: text(data.title, 120) || "Marvin",
    options: {
      body: text(data.body, 240),
      icon: "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      data: { url: safeTarget(data.url, origin), ...(approval ? { approval } : {}), ...(workspace ? { workspace } : {}) },
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
export function approvalOutcome(action, ok, body, fallbackUrl, origin, tag = "", fallbackWorkspace = null) {
  const answer = body && typeof body === "object" ? body : {};
  const url = safeTarget(typeof answer.url === "string" ? answer.url : fallbackUrl, origin);
  const workspace = workspaceOf(answer.workspace) ?? workspaceOf(fallbackWorkspace);
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
      data: { url, ...(workspace ? { workspace } : {}) },
      ...(tag ? { tag: text(tag, 64) } : {}),
    },
    badge,
    open: !ok,
    url,
    workspace,
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

// ── Share to Marvin (Web Share Target: Chromium on Android and desktop) ──────────────────────────────────

export const SHARE_TARGET = "/share-target";
export const SHARE_PAGE = "/share";
export const SHARE_TTL_MS = 60 * 60 * 1000;
export const SHARE_MAX_FILES = 10;
/** What the manifest's share_target accepts; anything else shared along is dropped (and counted). */
export const SHARE_ACCEPT = ["image/*", "video/*", "application/pdf"];

/** The share POST the manifest points at (the worker answers it; the network never sees it). */
export function isShareTarget(request, origin) {
  if (request.method !== "POST") return false;
  try {
    const url = new URL(request.url);
    return url.origin === origin && url.pathname === SHARE_TARGET;
  } catch {
    return false;
  }
}

export function acceptedType(type) {
  const t = typeof type === "string" ? type.toLowerCase() : "";
  return t.startsWith("image/") || t.startsWith("video/") || t === "application/pdf";
}

/** An http(s) URL, or null — never javascript:, data: or anything else a share might carry. */
export function httpUrl(value) {
  if (typeof value !== "string" || value.trim() === "") return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** The shared link: the `url` field, or the first http(s) URL in the text (Android often sends it there). */
export function sharedLink(url, textValue) {
  const direct = httpUrl(url);
  if (direct) return direct;
  const found = typeof textValue === "string" ? textValue.match(/https?:\/\/[^\s<>"]+/) : null;
  return found ? httpUrl(found[0].replace(/[.,;:!?)\]]+$/, "")) : null;
}

/**
 * What a share keeps: title, text and link (bounded, the link validated) and the files of accepted types, at
 * most SHARE_MAX_FILES; `dropped` counts the rest. `files` are {name, type, size} (File-like).
 */
export function shareFrom({ title, text: body, url, files }, now = Date.now()) {
  const list = Array.isArray(files) ? files.filter((f) => f && typeof f === "object") : [];
  const accepted = list.filter((f) => acceptedType(f.type)).slice(0, SHARE_MAX_FILES);
  return {
    title: text(title, 300).trim(),
    text: text(body, 5000).trim(),
    url: sharedLink(url, body),
    files: accepted.map((f) => ({
      name: text(f.name, 255) || "shared-file",
      type: text(f.type, 100),
      size: Number(f.size) || 0,
    })),
    dropped: list.length - accepted.length,
    createdAt: now,
  };
}

const SHARE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isShareId(id) {
  return typeof id === "string" && SHARE_ID.test(id);
}

/** Where a share's parts live in SHARE_CACHE: its record and each file, as same-origin URLs. */
export function shareKeys(id, origin) {
  return { meta: `${origin}/__share/${id}/meta.json`, file: (i) => `${origin}/__share/${id}/file-${i}` };
}

/** The share id a cache key belongs to, or null. */
export function shareIdOf(key) {
  const match = /\/__share\/([^/]+)\//.exec(typeof key === "string" ? key : "");
  return match && isShareId(match[1]) ? match[1] : null;
}

/** Whether a share's record is past its hour (or unreadable): its parts can go. */
export function shareExpired(meta, now = Date.now()) {
  const created = Number(meta?.createdAt);
  return !Number.isFinite(created) || now - created > SHARE_TTL_MS || created > now + 60_000;
}

/** Where the worker sends the browser after a share: the Share page for it, or with why it couldn't keep it. */
export function sharePageUrl(origin, id, error = "") {
  return error ? `${origin}${SHARE_PAGE}?error=${encodeURIComponent(error)}` : `${origin}${SHARE_PAGE}?id=${id}`;
}
