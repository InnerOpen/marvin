/**
 * The installable app (PWA): its manifest, colours and icons, and the small browser checks the install and
 * push UI make. Pure helpers — the service worker's own logic is src/pwa/sw-logic.js, the browser wiring
 * lib/pwaClient.ts. A non-production instance (backend ENVIRONMENT_LABEL, e.g. "DEV") installs as
 * "Marvin DEV" with its own icons and colour, so it never passes for the real app on a home screen.
 */
import { environmentTone } from "./environmentLabel.ts";

/** Design tokens (styles/global.css): light and dark page background, the brand accent, the DEV badge amber. */
export const COLORS = {
  light: "#fafaf9",
  dark: "#0c0a09",
  accent: "#ea580c",
  dev: "#d97706",
  staging: "#7c3aed",
} as const;

export const ASK_PATH = "/workspace/settings/ai-ask";
export const NEW_ENTRY_PATH = "/workspace/entries/new";
export const REVIEW_QUEUE_PATH = "/workspace/entries?status=needs_review,approved";

/** "Marvin", or "Marvin DEV" on a labelled instance. */
export function appName(label: string | null | undefined): string {
  return label ? `Marvin ${label}` : "Marvin";
}

/** The browser chrome colour: the page background in production (light/dark); the label's badge colour elsewhere. */
export function themeColors(label: string | null | undefined): { light: string; dark: string } {
  if (!label) return { light: COLORS.light, dark: COLORS.dark };
  const tone = environmentTone(label);
  const colour = tone === "staging" ? COLORS.staging : COLORS.dev;
  return { light: colour, dark: colour };
}

/** The icon set: production's, or the dark-and-amber one a labelled instance installs with. */
export function iconPaths(label: string | null | undefined) {
  const s = label ? "-dev" : "";
  return {
    svg: `/icons/marvin${s}.svg`,
    apple: `/icons/apple-touch-icon${s}.png`,
    icon192: `/icons/icon${s}-192.png`,
    icon512: `/icons/icon${s}-512.png`,
    maskable192: `/icons/maskable${s}-192.png`,
    maskable512: `/icons/maskable${s}-512.png`,
  };
}

/** The web app manifest (served at /manifest.webmanifest). */
export function buildManifest(label: string | null | undefined) {
  const name = appName(label);
  const icons = iconPaths(label);
  const theme = themeColors(label);
  return {
    id: "/",
    name,
    short_name: name,
    description: label
      ? `Marvin admin (${label} — not production)`
      : "Marvin: the admin app for your workspaces' content.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "any",
    theme_color: theme.light,
    background_color: COLORS.light,
    icons: [
      { src: icons.icon192, sizes: "192x192", type: "image/png", purpose: "any" },
      { src: icons.icon512, sizes: "512x512", type: "image/png", purpose: "any" },
      { src: icons.maskable192, sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: icons.maskable512, sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      {
        name: "Ask",
        short_name: "Ask",
        description: "Ask Marvin about your workspace",
        url: ASK_PATH,
        icons: [{ src: icons.icon192, sizes: "192x192" }],
      },
      {
        name: "New entry",
        short_name: "New",
        description: "Write a new entry",
        url: NEW_ENTRY_PATH,
        icons: [{ src: icons.icon192, sizes: "192x192" }],
      },
      {
        name: "Review queue",
        short_name: "Review",
        description: "Entries waiting for review",
        url: REVIEW_QUEUE_PATH,
        icons: [{ src: icons.icon192, sizes: "192x192" }],
      },
    ],
  };
}

/** iPhone, iPad and iPod — including iPadOS that reports itself as a Mac but has a touch screen. */
export function isIos(userAgent: string, maxTouchPoints = 0): boolean {
  return /iPad|iPhone|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
}

/**
 * What the Install entry offers: "installed" (already running as the app), "prompt" (the browser handed us
 * an install prompt), "ios" (Safari on iOS: Share → Add to Home Screen) or "menu" (install from the browser's
 * own menu, or not at all).
 */
export function installMode(input: {
  standalone: boolean;
  hasPrompt: boolean;
  userAgent: string;
  maxTouchPoints?: number;
}) {
  if (input.standalone) return "installed" as const;
  if (input.hasPrompt) return "prompt" as const;
  if (isIos(input.userAgent, input.maxTouchPoints)) return "ios" as const;
  return "menu" as const;
}

/**
 * Whether this device can receive push here: "ok", "unsupported" (no Push API), "ios-install" (iOS only
 * delivers push to the app on the Home Screen, from iOS 16.4) or "denied" (blocked in the browser settings).
 */
export function pushSupport(input: {
  hasPushManager: boolean;
  hasServiceWorker: boolean;
  permission: string | null;
  standalone: boolean;
  userAgent: string;
  maxTouchPoints?: number;
}) {
  if (isIos(input.userAgent, input.maxTouchPoints) && !input.standalone) return "ios-install" as const;
  if (!input.hasPushManager || !input.hasServiceWorker) return "unsupported" as const;
  if (input.permission === "denied") return "denied" as const;
  return "ok" as const;
}

/** A base64url VAPID key as the bytes PushManager.subscribe takes for `applicationServerKey`. */
export function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padded = `${base64}${"=".repeat((4 - (base64.length % 4)) % 4)}`.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}
