/**
 * Platform API methods - Assets and API Clients (Site Clients)
 * Migrated to use @inneropen/marvin-sdk
 */

import type { PlatformAPIClient, PlatformAsset } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";
import { fetchApi, fetchApiPage } from "./client";

// Re-export SDK types with legacy names for backward compatibility
export type MarvinAsset = PlatformAsset;
export type APIClientRead = PlatformAPIClient;

// Preview returns the same structure

/**
 * Get all assets in the current workspace
 */
/** The library's filters (GET /api/platform/assets): see lib/assetLibraryView.ts. */
export type AssetListParams = Record<string, string | number | boolean | string[]>;

export async function getAssets(authToken: string, params?: AssetListParams): Promise<MarvinAsset[]> {
  if (!params) return createSdkClient(authToken).assets.list();
  // The filters are newer than the SDK release the frontend pins, so the route is called directly.
  return fetchApi<MarvinAsset[]>(`/api/platform/assets?${assetQuery(params)}`, {}, authToken);
}

/** One page of the library (`limit`/`offset` among the params) and how many match in all (`X-Total-Count`). */
export async function getAssetsPage(authToken: string, params: AssetListParams): Promise<{ items: MarvinAsset[]; total: number }> {
  return fetchApiPage<MarvinAsset>(`/api/platform/assets?${assetQuery(params)}`, authToken);
}

function assetQuery(params: AssetListParams): URLSearchParams {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const v of Array.isArray(value) ? value : [value]) qs.append(key, String(v));
  }
  return qs;
}

// ===== API Client Management (Admin Operations) =====

/**
 * Get all API clients for the current workspace
 * Auth: Normal Marvin user session, workspace-scoped
 */
export async function getSiteClients(authToken: string): Promise<APIClientRead[]> {
  const sdk = createSdkClient(authToken);
  return sdk.apiClients.list();
}
