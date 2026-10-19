/**
 * Admin → Email → Platform SMTP: the server platform mail goes through. The environment's SMTP_* settings with an
 * admin's per-field overrides on top; the password is write-only (only `passwordSet` comes back). Browser calls go
 * through the same-origin proxy (no token); SSR passes the cookie token.
 */

import { fetchApi } from "../client";

/** Where a value comes from: an admin set it, or the environment has it; null = set nowhere. */
export type SmtpSource = "admin" | "env" | null;

export interface PlatformSmtpField {
  /** What's in force (the port as text); null when set nowhere. */
  value: string | null;
  /** What the environment says, whether or not an admin overrode it. */
  envValue: string | null;
  source: SmtpSource;
}

export interface PlatformSmtp {
  ready: boolean;
  /** When it isn't ready, why. */
  problem: string | null;
  /** `admin` when any field is an admin's, `env` when the environment alone is complete, else null. */
  source: SmtpSource;
  host: PlatformSmtpField;
  port: PlatformSmtpField;
  username: PlatformSmtpField;
  authStrategy: PlatformSmtpField;
  fromName: PlatformSmtpField;
  fromEmail: PlatformSmtpField;
  passwordSet: boolean;
  passwordSource: SmtpSource;
  /** The admin's saved password can't be read from the secret store: enter it again. */
  passwordMissing: boolean;
  /** False with SECRET_BACKEND=env: the operator sets PLATFORM_SMTP_PASSWORD in the environment instead. */
  canStorePassword: boolean;
  envAvailable: boolean;
  envSummary: string | null;
}

export interface PlatformSmtpUpdate {
  host: string | null;
  port: number | null;
  username: string | null;
  authStrategy: string | null;
  fromName: string | null;
  fromEmail: string | null;
  /** Write-only; left out keeps the saved one. */
  password?: string;
  clearPassword?: boolean;
}

const PATH = "/api/admin/email/platform-smtp";
const json = { "Content-Type": "application/json" };

export async function getPlatformSmtp(authToken?: string): Promise<PlatformSmtp> {
  return fetchApi<PlatformSmtp>(PATH, { method: "GET" }, authToken);
}

/** Replace the admin's fields: a blank (null) one goes back to the environment's. */
export async function savePlatformSmtp(data: PlatformSmtpUpdate, authToken?: string): Promise<PlatformSmtp> {
  return fetchApi<PlatformSmtp>(PATH, { method: "PUT", headers: json, body: JSON.stringify(data) }, authToken);
}

/** "Use environment settings": clear every admin field and the admin password. */
export async function useEnvironmentSmtp(authToken?: string): Promise<PlatformSmtp> {
  return fetchApi<PlatformSmtp>(PATH, { method: "DELETE" }, authToken);
}

/** Send a test email to the signed-in admin through the saved settings. */
export async function testPlatformSmtp(authToken?: string): Promise<{ success: boolean; error: string | null }> {
  return fetchApi(`${PATH}/test`, { method: "POST" }, authToken);
}
