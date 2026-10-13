/**
 * The public login-page configuration from `/api/app/about/login-info`. The backend serialises it
 * camelCase (oidcEnabled, oidcProviderName, ...); snake_case keys are accepted as a fallback so a
 * differently-configured serialiser can't silently hide the SSO button again. Anything missing or of the
 * wrong type falls back to the password-only defaults.
 */

export interface LoginInfo {
  oidcEnabled: boolean;
  oidcProviderName: string;
  oidcAutoRedirect: boolean;
  isDemo: boolean;
  environmentLabel: string;
}

export const LOGIN_INFO_DEFAULTS: LoginInfo = {
  oidcEnabled: false,
  oidcProviderName: "OAuth",
  oidcAutoRedirect: false,
  isDemo: false,
  environmentLabel: "",
};

function pick(body: Record<string, unknown>, camel: string, snake: string): unknown {
  return body[camel] !== undefined ? body[camel] : body[snake];
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

export function parseLoginInfo(body: unknown): LoginInfo {
  if (!body || typeof body !== "object") return { ...LOGIN_INFO_DEFAULTS };
  const b = body as Record<string, unknown>;
  const d = LOGIN_INFO_DEFAULTS;
  return {
    oidcEnabled: bool(pick(b, "oidcEnabled", "oidc_enabled"), d.oidcEnabled),
    oidcProviderName: str(pick(b, "oidcProviderName", "oidc_provider_name"), d.oidcProviderName) || d.oidcProviderName,
    oidcAutoRedirect: bool(pick(b, "oidcAutoRedirect", "oidc_auto_redirect"), d.oidcAutoRedirect),
    isDemo: bool(pick(b, "isDemo", "is_demo"), d.isDemo),
    environmentLabel: str(pick(b, "environmentLabel", "environment_label"), d.environmentLabel),
  };
}

/** Skip the form and go straight to the provider only when SSO is on, auto-redirect is on, and the user
 * isn't coming back from a failed attempt (?error=...), which would otherwise loop. */
export function shouldAutoRedirectToOidc(info: LoginInfo, error: string | null | undefined): boolean {
  return info.oidcEnabled && info.oidcAutoRedirect && !error;
}
