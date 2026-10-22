/**
 * The Site links setup check — what keeps an entry's link (`entry.url`, "View on site") from working: no site address,
 * or a publishable entry type without a page URL pattern (backend: services/site_links.py).
 * `getSiteLinks` reads settings only; `probeSiteLinks` fetches one published entry per type, so it runs on a click.
 * Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 */

import { fetchApi } from "./client";

export interface SiteLinkProblem {
  kind: "no_site_address" | "no_page_pattern" | "probe_failed";
  message: string;
  /** Where to fix it: a label for the link and an app path. */
  fix: { label: string; path: string };
  entryType?: string | null;
  url?: string | null;
}

export interface SiteLinksStatus {
  ok: boolean;
  problems: SiteLinkProblem[];
}

export async function getSiteLinks(workspaceId: string, authToken?: string): Promise<SiteLinksStatus> {
  return fetchApi<SiteLinksStatus>(`/api/groups/${workspaceId}/preferences/site-links`, { method: "GET" }, authToken);
}

/** The problems a live fetch of one published entry per type found (empty `problems`: every link answered 200). */
export async function probeSiteLinks(workspaceId: string, authToken?: string): Promise<SiteLinksStatus> {
  return fetchApi<SiteLinksStatus>(`/api/groups/${workspaceId}/preferences/site-links/probe`, { method: "POST" }, authToken);
}
