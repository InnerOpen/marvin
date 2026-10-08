// Marvin's service worker (scope /). Hand-written, no dependencies. integrations/pwa.mjs builds it into
// dist/client/sw.js after `astro build`: it fills in the build's VERSION and PRECACHE list (the hashed
// /_astro/ assets, the icons and the offline page) and inlines src/pwa/sw-logic.js where the marker is.
//
// Privacy: only static files are ever cached. Pages are signed-in HTML and API responses are personal, so
// neither is stored — a shared device keeps nothing of one person for the next, and logout clears the caches.
// The one exception is what someone shares to the app: kept in its own cache until the Share page has used it
// (or for an hour), and cleared on logout with the rest.

const VERSION = "__MARVIN_SW_VERSION__";
const PRECACHE = __MARVIN_SW_PRECACHE__;

/* __MARVIN_SW_LOGIC__ */

const CACHES = cacheNames(VERSION);

self.addEventListener("install", (event) => {
  // Precache the shell; the new worker then waits until the page offers "Reload" (SKIP_WAITING).
  event.waitUntil(caches.open(CACHES.shell).then((cache) => cache.addAll(PRECACHE)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(staleCaches(keys, VERSION).map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  const type = event.data?.type;
  if (type === "SKIP_WAITING") self.skipWaiting();
  if (type === "CLEAR_CACHES") {
    event.waitUntil(
      caches
        .keys()
        .then((keys) => Promise.all(keys.filter((k) => k.startsWith(CACHE_PREFIX)).map((k) => caches.delete(k)))),
    );
  }
});

async function fromNetworkOrOffline(event) {
  try {
    return await fetch(event.request);
  } catch {
    return (await caches.match(OFFLINE_URL)) ?? Response.error();
  }
}

async function fromCacheFirst(request) {
  const hit = await caches.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (cacheable(response)) {
    const copy = response.clone();
    caches
      .open(CACHES.assets)
      .then((cache) => cache.put(request, copy))
      .catch(() => {});
  }
  return response;
}

async function dropStaleShares(cache) {
  const keys = await cache.keys();
  const ids = [...new Set(keys.map((r) => shareIdOf(r.url)).filter(Boolean))];
  const origin = self.location.origin;
  for (const id of ids) {
    const meta = await cache
      .match(shareKeys(id, origin).meta)
      .then((r) => r?.json())
      .catch(() => null);
    if (!shareExpired(meta)) continue;
    await Promise.all(keys.filter((r) => shareIdOf(r.url) === id).map((r) => cache.delete(r)));
  }
}

// A share from another app (Android's share sheet, desktop Chrome's Share): keep its files here for the
// Share page — never on the network until the person chooses what to make of them, signed in.
async function receiveShare(request) {
  const origin = self.location.origin;
  try {
    const form = await request.formData();
    const files = form.getAll("files").filter((f) => typeof f !== "string");
    const share = shareFrom({ title: form.get("title"), text: form.get("text"), url: form.get("url"), files });
    const kept = files.filter((f) => acceptedType(f.type)).slice(0, SHARE_MAX_FILES);
    const id = self.crypto.randomUUID();
    const keys = shareKeys(id, origin);
    const cache = await caches.open(SHARE_CACHE);
    await dropStaleShares(cache).catch(() => {});
    await Promise.all(
      kept.map((f, i) =>
        cache.put(keys.file(i), new Response(f, { headers: { "Content-Type": f.type || "application/octet-stream" } })),
      ),
    );
    await cache.put(
      keys.meta,
      new Response(JSON.stringify(share), { headers: { "Content-Type": "application/json" } }),
    );
    return Response.redirect(sharePageUrl(origin, id), 303);
  } catch {
    return Response.redirect(sharePageUrl(origin, "", "unreadable"), 303);
  }
}

self.addEventListener("fetch", (event) => {
  if (isShareTarget(event.request, self.location.origin)) {
    event.respondWith(receiveShare(event.request));
    return;
  }
  const kind = strategy(event.request, self.location.origin);
  if (kind === "navigate") event.respondWith(fromNetworkOrOffline(event));
  else if (kind === "asset") event.respondWith(fromCacheFirst(event.request));
  // "network": left to the browser — never cached.
});

self.addEventListener("push", (event) => {
  const note = notificationFromPush(parsePush(event.data ? event.data.text() : ""), self.location.origin);
  const work = [self.registration.showNotification(note.title, note.options)];
  if (note.badge !== null && "setAppBadge" in self.navigator) {
    work.push(self.navigator.setAppBadge(note.badge).catch(() => {}));
  }
  event.waitUntil(Promise.all(work));
});

async function openOrFocus(target) {
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
  if (!open) return self.clients.openWindow(target);
  await open.focus();
  if (open.url === target) return undefined;
  try {
    return await open.navigate(target);
  } catch {
    return self.clients.openWindow(target); // an uncontrolled window can't be navigated from here
  }
}

// A notification about another workspace opens there: switch first (the active workspace is the person's, kept
// server-side), then open. A failed switch still opens the page, which then says what it can't find.
async function openIn(workspace, target) {
  if (workspace) {
    try {
      const current = await fetch("/api/self/workspaces/current", { credentials: "same-origin" });
      const request = switchRequest(workspace, current.ok ? (await current.json())?.id : null);
      if (request) await fetch(request.url, request.init);
    } catch {
      /* offline or signed out: open as is */
    }
  }
  return openOrFocus(target);
}

// Approve / Deny on an AI approval (Chromium): the token in the notification decides it, then a confirmation
// replaces the notification; when it can't (expired, decided already…), the conversation opens instead.
async function decide(action, request, target, tag, workspace) {
  let ok = false;
  let body = null;
  try {
    const response = await fetch(request.url, request.init);
    ok = response.ok;
    body = await response.json().catch(() => null);
  } catch {
    body = { detail: "No connection to Marvin." };
  }
  const outcome = approvalOutcome(action, ok, body, target, self.location.origin, tag, workspace);
  const work = [self.registration.showNotification(outcome.title, outcome.options)];
  if (outcome.badge !== null && "setAppBadge" in self.navigator) {
    work.push(self.navigator.setAppBadge(outcome.badge).catch(() => {}));
  }
  if (outcome.open) work.push(openIn(outcome.workspace, outcome.url));
  await Promise.all(work);
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data ?? {};
  const target = safeTarget(data.url, self.location.origin);
  const request = approvalRequest(event.action, data, self.location.origin);
  const workspace = workspaceOf(data.workspace);
  event.waitUntil(
    request ? decide(event.action, request, target, event.notification.tag, workspace) : openIn(workspace, target),
  );
});

self.addEventListener("pushsubscriptionchange", (event) => {
  // The push service rotated this device's subscription: subscribe again with the same key and tell Marvin,
  // replacing the old endpoint. Same-origin through the frontend's API proxy, so the session cookie signs it.
  event.waitUntil(
    (async () => {
      const old = event.oldSubscription;
      const key = old?.options?.applicationServerKey;
      const fresh =
        event.newSubscription ??
        (key
          ? await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
          : null);
      if (!fresh) return;
      await fetch("/api/self/push/subscriptions", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...fresh.toJSON(), replaces: old?.endpoint ?? null }),
      });
    })(),
  );
});
