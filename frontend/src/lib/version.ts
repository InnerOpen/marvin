/**
 * What version of Marvin this page was rendered by — the frontend build and the backend it talks
 * to. The layout stamps it into the page; /version.json reports the live value; the browser
 * compares the two and offers a reload when they drift (a deploy landed while the tab was open).
 */
import { getServerApiBaseUrl } from "@/lib/api/config";

export type AppVersion = { frontend: string; backend: string };

const BACKEND_CACHE_MS = 30_000;
let backendCache: { at: number; value: string } | null = null;

/** The image's git commit (set at build: Dockerfile ARG COMMIT → ENV GIT_COMMIT_HASH), short form. */
export function getFrontendVersion(): string {
  const sha = typeof process !== "undefined" ? process.env.GIT_COMMIT_HASH : undefined;
  return sha ? sha.slice(0, 12) : "dev";
}

/** The backend's reported version (public /api/app/about/version), cached briefly so page renders stay cheap. */
export async function getBackendVersion(): Promise<string> {
  const now = Date.now();
  if (backendCache && now - backendCache.at < BACKEND_CACHE_MS) return backendCache.value;
  let value = "unknown";
  try {
    const res = await fetch(`${getServerApiBaseUrl()}/api/app/about/version`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      const body = (await res.json()) as { version?: string };
      if (body?.version) value = String(body.version);
    }
  } catch {
    // Backend unreachable — leave "unknown"; the banner never fires on unknowns.
  }
  backendCache = { at: now, value };
  return value;
}

export async function getAppVersion(): Promise<AppVersion> {
  return { frontend: getFrontendVersion(), backend: await getBackendVersion() };
}
