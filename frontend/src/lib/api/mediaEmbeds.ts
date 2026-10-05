/**
 * Media embeds — /api/platform/media-embeds (not in the SDK yet). Listing providers is open to every
 * workspace member; resolving is AUTHOR+ and rate-limited (429). Pass authToken in SSR; omit it in the browser.
 */

import type { EmbedMode, ProvidersResponse, ResolveResult } from "@/lib/mediaEmbeds";
import { fetchApi } from "./client";

const BASE = "/api/platform/media-embeds";

/** The provider allow-list and the origins a player iframe may load from. */
export function getEmbedProviders(authToken?: string): Promise<ProvidersResponse> {
  return fetchApi<ProvidersResponse>(`${BASE}/providers`, {}, authToken);
}

/** Resolve a pasted link or provider embed code to the URL to store and its embed (or an error message). */
export function resolveEmbed(input: string, mode: EmbedMode = "direct", authToken?: string): Promise<ResolveResult> {
  return fetchApi<ResolveResult>(
    `${BASE}/resolve`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ input, mode }) },
    authToken,
  );
}
