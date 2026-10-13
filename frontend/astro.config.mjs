import node from "@astrojs/node";
import { defineConfig } from "astro/config";
import pwa from "./integrations/pwa.mjs";

// Keep the dev server on the port the backend advertises. FRONTEND_URL is the single knob —
// AppSettings derives FRONTEND_PORT from it, and docker/start.sh binds the built server to the
// same value — so `npm run dev` reads the same environment rather than hardcoding a second
// opinion. Falls back to 4322, the FRONTEND_URL default.
function frontendPort() {
  const explicit = Number.parseInt(process.env.FRONTEND_PORT ?? "", 10);
  if (Number.isInteger(explicit) && explicit > 0) return explicit;

  try {
    const parsed = new URL(process.env.FRONTEND_URL ?? "");
    if (parsed.port) return Number.parseInt(parsed.port, 10);
    if (parsed.protocol === "https:") return 443;
    if (parsed.protocol === "http:") return 80;
  } catch {
    // No FRONTEND_URL, or not a URL — fall through to the default.
  }

  return 4322;
}

export default defineConfig({
  output: "server",
  adapter: node({
    mode: "standalone",
  }),
  // The service worker (sw.js) is written after the build, from src/pwa/ — see integrations/pwa.mjs.
  integrations: [pwa()],
  server: {
    host: "localhost",
    port: frontendPort(),
  },
});
