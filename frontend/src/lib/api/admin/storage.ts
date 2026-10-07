/**
 * Admin Storage API - where new asset uploads go (a platform admin's choice; STORAGE_PROVIDER is the
 * default), and how many files live on each provider. Existing files never move when the choice
 * changes: `python -m marvin.scripts.storage_migrate` moves them.
 */

import { fetchApi } from "../client";

export interface StorageProviderOption {
  slug: string;
  name: string;
  /** "builtin", "core" (core's temporary s3), the plugin that adds it, or "" when not installed. */
  source: string;
  /** Installed and configured: it can take new uploads. */
  available: boolean;
  error: string | null;
  assets: number;
  bytes: number;
  libraryFiles: number;
}

export interface StorageWorkspaceUsage {
  workspaceId: string;
  workspace: string;
  provider: string;
  assets: number;
  bytes: number;
}

export interface StorageSettings {
  /** STORAGE_PROVIDER: where uploads go until an admin chooses. */
  envDefault: string;
  /** The admin's choice; null follows STORAGE_PROVIDER. */
  uploadProvider: string | null;
  /** Where new uploads go now. */
  effectiveProvider: string;
  /** Set when the choice is unavailable and uploads fall back to STORAGE_PROVIDER. */
  warning: string | null;
  providers: StorageProviderOption[];
  workspaces: StorageWorkspaceUsage[];
}

const PATH = "/api/admin/storage";

export async function getStorageSettings(authToken?: string): Promise<StorageSettings> {
  return fetchApi<StorageSettings>(PATH, { method: "GET" }, authToken);
}

export async function updateStorageSettings(
  uploadProvider: string | null,
  authToken?: string,
): Promise<StorageSettings> {
  return fetchApi<StorageSettings>(
    PATH,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ uploadProvider }) },
    authToken,
  );
}
