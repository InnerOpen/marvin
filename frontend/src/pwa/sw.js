// Marvin's service worker (scope /). Hand-written, no dependencies. integrations/pwa.mjs builds it into
// dist/client/sw.js after `astro build`: it fills in the build's VERSION and PRECACHE list (the hashed
// /_astro/ assets, the icons and the offline page) and inlines src/pwa/sw-logic.js where the marker is.
//
// Privacy: only static files are ever cached. Pages are signed-in HTML and API responses are personal, so
// neither is stored — a shared device keeps nothing of one person for the next, and logout clears the caches.

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

self.addEventListener("fetch", (event) => {
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

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = safeTarget(event.notification.data?.url, self.location.origin);
  event.waitUntil(
    (async () => {
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
    })(),
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
