/**
 * Submission protection — platform defaults (admin) and the per-workspace view.
 *
 * Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 */

import { fetchApi } from "./client";

export type SubmissionProtectionMode = "off" | "review" | "reject";

export interface SubmissionProtectionSettings {
  mode: SubmissionProtectionMode;
  blockedDomains: string[];
  allowedDomains: string[];
  blockDisposableDomains: boolean;
  blockPersonalDomains: boolean;
  captureClientInfo: boolean;
  exemptIps: string[];
  surgeThreshold: number | null;
  surgeWindowMinutes: number;
}

/** Workspace override: every field optional, null = inherit the platform default. */
export type SubmissionProtectionOverride = { [K in keyof SubmissionProtectionSettings]: SubmissionProtectionSettings[K] | null };

export interface SubmissionProtectionStatus {
  platformDefaults: SubmissionProtectionSettings;
  workspaceOverride: SubmissionProtectionOverride;
  effective: SubmissionProtectionSettings;
}

export interface EmailDomainPresets {
  disposable: string[];
  personal: string[];
}

const ADMIN_PATH = "/api/admin/submission-protection";

export async function getPlatformSubmissionProtection(authToken?: string): Promise<SubmissionProtectionSettings> {
  return fetchApi<SubmissionProtectionSettings>(ADMIN_PATH, { method: "GET" }, authToken);
}

export async function updatePlatformSubmissionProtection(
  data: SubmissionProtectionSettings,
  authToken?: string,
): Promise<SubmissionProtectionSettings> {
  return fetchApi<SubmissionProtectionSettings>(
    ADMIN_PATH,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) },
    authToken,
  );
}

export async function getEmailDomainPresets(authToken?: string): Promise<EmailDomainPresets> {
  return fetchApi<EmailDomainPresets>(`${ADMIN_PATH}/presets`, { method: "GET" }, authToken);
}

export async function getWorkspaceSubmissionProtection(
  workspaceId: string,
  authToken?: string,
): Promise<SubmissionProtectionStatus> {
  return fetchApi<SubmissionProtectionStatus>(
    `/api/groups/${workspaceId}/preferences/submission-protection`,
    { method: "GET" },
    authToken,
  );
}
