import type { APIRoute } from "astro";

/**
 * The manifest's share target (lib/pwa.ts). The service worker answers the share POST itself and keeps the
 * files on the device (src/pwa/sw.js), so this only runs when no worker did — the app opened without one, or
 * it was cleared: say so on the Share page instead of losing the share in a 404. Nothing is read or stored.
 */
const toSharePage: APIRoute = ({ redirect }) => redirect("/share?error=no-worker", 303);

export const POST = toSharePage;
export const GET = toSharePage;
