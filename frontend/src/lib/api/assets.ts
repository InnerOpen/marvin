/**
 * Assets API client — suggestion write-back wrappers.
 *
 * Assets are otherwise managed through the SDK directly (createSdkClient().assets); these two
 * helpers hit the apply/reject-suggestion endpoints the SDK doesn't wrap yet, mirroring entries.
 */

import type { PlatformAsset } from "@inneropen/marvin-sdk/platform";
import { getApiUrl } from "./config";

export type AssetRead = PlatformAsset;

/** Apply the asset's staged AI suggestion (suggestion_json) and clear it. */
export async function applyAssetSuggestion(id: string, authToken: string): Promise<AssetRead> {
  const res = await fetch(getApiUrl(`/api/platform/assets/${id}/apply-suggestion`), {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`apply-suggestion failed: ${res.status}`);
  return res.json();
}

/** Discard the asset's staged AI suggestion without applying it. */
export async function rejectAssetSuggestion(id: string, authToken: string): Promise<AssetRead> {
  const res = await fetch(getApiUrl(`/api/platform/assets/${id}/reject-suggestion`), {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`reject-suggestion failed: ${res.status}`);
  return res.json();
}
