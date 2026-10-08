// Builds the service worker after `astro build` (no PWA plugin: the worker is hand-written in src/pwa/sw.js).
// Only the build knows the hashed names of the app's assets, so this hook lists them as the precache, stamps
// a version made from their names (a new build → a new worker → the "new version" prompt), inlines
// src/pwa/sw-logic.js and writes dist/client/sw.js. `astro dev` has no worker; the page only registers one
// in a production build.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const PWA_DIR = fileURLToPath(new URL("../src/pwa/", import.meta.url));
// Precache what a page needs to start: styles, scripts and the icons. Fonts and images under /_astro/ are
// fetched on first use (cache first), so installing the worker stays light.
const PRECACHE_EXT = /\.(css|js|mjs)$/;

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

/** The worker's source with the build's version, precache list and logic filled in. */
export function buildServiceWorker(clientDir) {
  const urlOf = (path) => `/${relative(clientDir, path).split(sep).join("/")}`;
  const assets = walk(join(clientDir, "_astro"))
    .filter((p) => PRECACHE_EXT.test(p))
    .map(urlOf);
  const icons = walk(join(clientDir, "icons")).map(urlOf);
  const precache = ["/offline.html", ...icons, ...assets].sort();
  const version = createHash("sha256").update(precache.join("\n")).digest("hex").slice(0, 12);
  const logic = readFileSync(join(PWA_DIR, "sw-logic.js"), "utf8").replace(/^export /gm, "");
  return readFileSync(join(PWA_DIR, "sw.js"), "utf8")
    .replace("__MARVIN_SW_VERSION__", version)
    .replace("__MARVIN_SW_PRECACHE__", JSON.stringify(precache, null, 2))
    .replace("/* __MARVIN_SW_LOGIC__ */", logic);
}

export default function pwa() {
  return {
    name: "marvin-pwa",
    hooks: {
      "astro:build:done": ({ dir, logger }) => {
        // `dir` is the client output (dist/client/) in server mode; fall back to its sibling if an adapter differs.
        const candidates = [fileURLToPath(dir), fileURLToPath(new URL("../client/", dir))];
        const target = candidates.find((d) => statSync(join(d, "_astro"), { throwIfNoEntry: false })) ?? candidates[0];
        const source = buildServiceWorker(target);
        writeFileSync(join(target, "sw.js"), source);
        logger.info(`sw.js written (${source.length} bytes)`);
      },
    },
  };
}
