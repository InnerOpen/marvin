// Admin → Email → Platform SMTP: the block's pure helpers (the save payload, what each pill and hint says).
// Run the tests with `npm test`.

import type { PlatformSmtp, PlatformSmtpField, PlatformSmtpUpdate, SmtpSource } from "../api/admin/platformSmtp";

export type Tone = "ok" | "warn" | "muted";

/** The overall pill: any admin field makes it Admin; a complete environment alone is Environment. */
export function sourcePill(smtp: Pick<PlatformSmtp, "source">): { label: string; tone: Tone } {
  if (smtp.source === "admin") return { label: "Admin settings", tone: "ok" };
  if (smtp.source === "env") return { label: "Environment", tone: "muted" };
  return { label: "Not set", tone: "warn" };
}

/** One field's hint: where its value comes from, and what an admin value overrides. */
export function fieldHint(field: Pick<PlatformSmtpField, "source" | "envValue">): string {
  if (field.source === "admin") return field.envValue ? `Overrides the environment's ${field.envValue}` : "Set here";
  if (field.source === "env") return "From the environment";
  return "Not set";
}

/** The password's hint. */
export function passwordHint(
  smtp: Pick<PlatformSmtp, "passwordSet" | "passwordSource" | "passwordMissing" | "canStorePassword">,
): string {
  if (smtp.passwordMissing) return "The saved password is missing from the secret store: enter it again.";
  if (!smtp.canStorePassword)
    return "This install's secret backend is read-only: set PLATFORM_SMTP_PASSWORD in the server's environment.";
  if (smtp.passwordSource === "admin") return "Set here: leave blank to keep it";
  if (smtp.passwordSource === "env") return "From the environment: type one to override it";
  return "Not set";
}

export function sourceLabel(source: SmtpSource): string {
  return source === "admin" ? "Admin" : source === "env" ? "Environment" : "Not set";
}

/** The PUT body. A blank field is null (back to the environment's); the port a number; the password only when typed. */
export function buildSmtpUpdate(input: {
  host: string;
  port: string;
  username: string;
  authStrategy: string;
  fromName: string;
  fromEmail: string;
  password: string;
  clearPassword: boolean;
}): PlatformSmtpUpdate {
  const text = (v: string) => (v.trim() === "" ? null : v.trim());
  const port = input.port.trim() === "" ? null : Number(input.port.trim());
  return {
    host: text(input.host),
    port: port !== null && Number.isFinite(port) ? Math.trunc(port) : null,
    username: text(input.username),
    authStrategy: text(input.authStrategy),
    fromName: text(input.fromName),
    fromEmail: text(input.fromEmail),
    ...(input.password !== "" ? { password: input.password } : {}),
    ...(input.clearPassword && input.password === "" ? { clearPassword: true } : {}),
  };
}
