/**
 * The installable app in the browser: registers the service worker (production builds only — `astro dev`
 * has none), announces a waiting update to the update banner, remembers the install prompt for Profile, keeps
 * the browser chrome colour on the chosen theme, shows the inbox count on the app icon, and cleans up on
 * logout (this device's push subscription and the caches). Pure decisions live in lib/pwa.ts.
 */
import { removePushEndpoint, savePushSubscription } from "./api/push";
import { urlBase64ToUint8Array } from "./pwa";

/** Fired on window when a new service worker is installed and waiting (detail: the worker). */
export const SW_UPDATE_EVENT = "marvin:sw-update";
/** Fired on window when the browser offers to install the app (the prompt is in installPrompt()). */
export const INSTALLABLE_EVENT = "marvin:installable";

type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

declare global {
  interface Window {
    __MARVIN_SW_WAITING__?: ServiceWorker | null;
    __MARVIN_INSTALL_PROMPT__?: InstallPrompt | null;
  }
}

const LOGOUT_TIMEOUT_MS = 3000;

export function isStandalone(): boolean {
  return window.matchMedia?.("(display-mode: standalone)").matches || (navigator as any).standalone === true;
}

export function installPrompt(): InstallPrompt | null {
  return window.__MARVIN_INSTALL_PROMPT__ ?? null;
}

function announceWaiting(worker: ServiceWorker | null) {
  if (!worker || !navigator.serviceWorker.controller) return; // first install: nothing to update from
  window.__MARVIN_SW_WAITING__ = worker;
  window.dispatchEvent(new CustomEvent(SW_UPDATE_EVENT, { detail: worker }));
}

/** Register /sw.js and watch for updates. */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    announceWaiting(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const worker = reg.installing;
      worker?.addEventListener("statechange", () => {
        if (worker.state === "installed") announceWaiting(worker);
      });
    });
    return reg;
  } catch (e) {
    console.warn("[pwa] service worker registration failed", e);
    return null;
  }
}

/** Let the waiting worker take over, then reload once it controls the page. False when none is waiting. */
export function activateWaitingWorker(): boolean {
  const worker = window.__MARVIN_SW_WAITING__;
  if (!worker || !("serviceWorker" in navigator)) return false;
  navigator.serviceWorker.addEventListener("controllerchange", () => location.reload(), { once: true });
  worker.postMessage({ type: "SKIP_WAITING" });
  setTimeout(() => location.reload(), 4000); // in case the switch never comes
  return true;
}

/** Ask the browser to look for a newer worker now (a deploy was detected). */
export function checkForUpdate(): void {
  navigator.serviceWorker
    ?.getRegistration()
    .then((reg) => reg?.update())
    .catch(() => {});
}

/** Keep the install prompt for Profile's "Install app" (the browser fires it once, early). */
export function captureInstallPrompt(): void {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    window.__MARVIN_INSTALL_PROMPT__ = event as InstallPrompt;
    window.dispatchEvent(new Event(INSTALLABLE_EVENT));
  });
  window.addEventListener("appinstalled", () => {
    window.__MARVIN_INSTALL_PROMPT__ = null;
    window.dispatchEvent(new Event(INSTALLABLE_EVENT));
  });
}

/** The browser chrome colour follows the theme the person chose (ThemeSwitcher), not only the system's. */
export function syncThemeColor(): void {
  const metas = [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"][data-light]')];
  if (!metas.length) return;
  const apply = () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    for (const meta of metas) meta.content = (dark ? meta.dataset.dark : meta.dataset.light) ?? meta.content;
  };
  apply();
  new MutationObserver(apply).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

/** The inbox count on the installed app's icon (where the browser supports badges). */
export function setBadge(count: number): void {
  const nav = navigator as any;
  if (!nav.setAppBadge) return;
  (count > 0 ? nav.setAppBadge(count) : nav.clearAppBadge()).catch(() => {});
}

/** This browser's push subscription, if any. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return (await reg?.pushManager.getSubscription()) ?? null;
}

function sameKey(current: ArrayBuffer | null, wanted: Uint8Array): boolean {
  if (!current) return true; // the browser doesn't say: assume it's ours
  const bytes = new Uint8Array(current);
  return bytes.length === wanted.length && bytes.every((b, i) => b === wanted[i]);
}

/** Turn push on here: ask for permission (only ever from a click), subscribe, and register the device. */
export async function enablePush(publicKey: string): Promise<PushSubscription> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted")
    throw new Error(permission === "denied" ? "Notifications are blocked for this site." : "Permission wasn't given.");
  const reg = await navigator.serviceWorker.ready;
  const key = urlBase64ToUint8Array(publicKey);
  let existing = await reg.pushManager.getSubscription();
  if (existing && !sameKey(existing.options.applicationServerKey, key)) {
    await existing.unsubscribe(); // subscribed under an older server key: it would never deliver
    existing = null;
  }
  const subscription =
    existing ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key as BufferSource }));
  const json = subscription.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  await savePushSubscription({ endpoint: json.endpoint, keys: json.keys, userAgent: navigator.userAgent });
  return subscription;
}

/** Turn push off here: forget the device in Marvin and unsubscribe the browser. */
export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  try {
    await removePushEndpoint(subscription.endpoint);
  } finally {
    await subscription.unsubscribe().catch(() => false);
  }
}

async function clearCaches(): Promise<void> {
  if (!("caches" in window)) return;
  const keys = await caches.keys();
  await Promise.all(keys.filter((k) => k.startsWith("marvin-")).map((k) => caches.delete(k)));
}

/**
 * Logging out on a shared device leaves nothing behind: this browser stops getting the person's pushes and
 * the app's caches are emptied (they only ever hold static files, but a clean slate is the rule). Capped so
 * a slow network never holds up the logout.
 */
export function guardLogout(): void {
  document.addEventListener("submit", (event) => {
    const form = event.target as HTMLFormElement | null;
    if (
      !form ||
      form.dataset.pwaCleaned === "1" ||
      !new URL(form.action, location.href).pathname.endsWith("/api/auth/logout")
    )
      return;
    event.preventDefault();
    const cleanup = Promise.allSettled([disablePush(), clearCaches(), Promise.resolve(setBadge(0))]);
    const timeout = new Promise((resolve) => setTimeout(resolve, LOGOUT_TIMEOUT_MS));
    Promise.race([cleanup, timeout]).finally(() => {
      form.dataset.pwaCleaned = "1";
      form.submit();
    });
  });
}
