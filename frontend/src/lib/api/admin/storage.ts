/**
 * Admin Storage API - where new asset uploads go (a platform admin's choice; STORAGE_PROVIDER is the
 * default), and how many files live on each provider. Existing files never move when the choice
 * changes: `python -m marvin.scripts.storage_migrate` moves them.
 */

import { fetchApi } from "../client";

/** One setting as it is in effect (read-only: from the environment). Secrets read `****`, key ids `…ab12`. */
export interface StorageSettingValue {
  env: string;
  label: string;
  /** The effective value (the default when unset), masked when secret; null when unset with no default. */
  value: string | null;
  /** Set in the environment (false: the default, or nothing). */
  isSet: boolean;
  secret: boolean;
  help: string;
}

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
  /** Its effective settings as the backend reads them. */
  settings: StorageSettingValue[];
}

/** A backup target as its latest run recorded it (the backend has no CronJob env): never a key. */
export interface StorageBackupTarget {
  name: string;
  type: string;
  location: string | null;
  settings: StorageSettingValue[];
  /** ok, partial, failed, overdue or unknown — details on Admin → Backup health. */
  state: string;
  lastRunAt: string | null;
}

export interface StorageCheckStep {
  /** list, put, get, delete (or settings, when the provider can't be built). */
  name: string;
  ok: boolean;
  ms: number;
  /** What went wrong, in plain words. */
  error: string | null;
  /** The service's error code (InvalidAccessKeyId, AccessDenied, NoSuchBucket…). */
  code: string | null;
}

export interface StorageCheckResult {
  provider: string;
  ok: boolean;
  key: string;
  location: string | null;
  checkedAt: string;
  steps: StorageCheckStep[];
}

export interface StorageWorkspaceUsage {
  workspaceId: string;
  workspace: string;
  provider: string;
  assets: number;
  bytes: number;
}

/** A workspace's storage settings: the opaque key prefix its files get, and its own public domain. */
export interface StorageWorkspaceSettings {
  workspaceId: string;
  workspace: string;
  /** The first segment of the workspace's storage keys (and file URLs). */
  storageCode: string | null;
  /** Its own public domain for files on a remote provider; null uses remotePublicBaseUrl. */
  assetPublicBaseUrl: string | null;
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
  workspaceSettings: StorageWorkspaceSettings[];
  /** STORAGE_REMOTE_PUBLIC_URL: the domain remote files use when their workspace has none of its own. */
  remotePublicBaseUrl: string | null;
  /** Backup targets that have recorded a run. */
  backupTargets: StorageBackupTarget[];
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

/** Serve a workspace's remote-stored files from its own domain (null: the platform default). */
export async function updateWorkspaceStorage(
  workspaceId: string,
  assetPublicBaseUrl: string | null,
  authToken?: string,
): Promise<StorageSettings> {
  return fetchApi<StorageSettings>(
    `${PATH}/workspaces/${encodeURIComponent(workspaceId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assetPublicBaseUrl }),
    },
    authToken,
  );
}

/** Test connection (super admin): list, put, get and delete a tiny object through the provider. */
export async function testStorageProvider(slug: string, authToken?: string): Promise<StorageCheckResult> {
  return fetchApi<StorageCheckResult>(
    `${PATH}/providers/${encodeURIComponent(slug)}/test`,
    { method: "POST" },
    authToken,
  );
}
