/**
 * The environment label (backend ENVIRONMENT_LABEL, e.g. "DEV", "STAGING") that marks a non-production
 * instance: the layouts and the login page badge it and prefix the tab title with it. Empty in production,
 * where nothing renders. The backend normalises it; this module only reads it and decides how it looks.
 */
import { getServerApiBaseUrl } from "./api/config.ts";

export type EnvironmentTone = "dev" | "staging" | "neutral";

const CACHE_MS = 60_000;
let cache: { at: number; value: string } | null = null;

/** Badge colour family: DEV/DEVELOPMENT → amber, STAGING/STAGE → purple, anything else → neutral. */
export function environmentTone(label: string): EnvironmentTone {
  const l = label.trim().toUpperCase();
  if (l.startsWith("DEV")) return "dev";
  if (l.startsWith("STAG")) return "staging";
  return "neutral";
}

/** "[DEV] Entries | Marvin" — the title unchanged when there is no label. */
export function withEnvironmentPrefix(title: string, label: string | null | undefined): string {
  return label ? `[${label}] ${title}` : title;
}

/**
 * The label, from the public login-info endpoint (the same read the login page makes), cached briefly
 * so layouts can call it on every render. Fails closed: an unreachable backend means no badge.
 */
export async function getEnvironmentLabel(): Promise<string> {
  const now = Date.now();
  if (cache && now - cache.at < CACHE_MS) return cache.value;
  let value = "";
  try {
    const res = await fetch(`${getServerApiBaseUrl()}/api/app/about/login-info`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      const body = (await res.json()) as { environmentLabel?: unknown };
      if (typeof body?.environmentLabel === "string") value = body.environmentLabel;
    }
  } catch {
    // Backend unreachable — no badge.
  }
  cache = { at: now, value };
  return value;
}
