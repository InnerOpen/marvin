// Login-page configuration parsing (loginInfo.ts). Run with `npm test` — plain `node --test`.
// Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { LOGIN_INFO_DEFAULTS, parseLoginInfo, shouldAutoRedirectToOidc } from "./loginInfo.ts";

describe("parseLoginInfo", () => {
  test("reads the camelCase keys the backend actually sends", () => {
    const info = parseLoginInfo({
      oidcEnabled: true,
      oidcProviderName: "Authentik",
      oidcAutoRedirect: true,
      allowSignup: false,
      isDemo: true,
      environmentLabel: "DEV",
    });
    assert.deepEqual(info, {
      oidcEnabled: true,
      oidcProviderName: "Authentik",
      oidcAutoRedirect: true,
      isDemo: true,
      environmentLabel: "DEV",
    });
  });

  test("production payload (everything off) equals the password-only defaults", () => {
    const info = parseLoginInfo({
      oidcEnabled: false,
      oidcProviderName: "OAuth",
      oidcAutoRedirect: false,
      allowSignup: false,
      isDemo: false,
      environmentLabel: "",
    });
    assert.deepEqual(info, LOGIN_INFO_DEFAULTS);
  });

  test("tolerates snake_case keys", () => {
    const info = parseLoginInfo({
      oidc_enabled: true,
      oidc_provider_name: "Keycloak",
      oidc_auto_redirect: false,
      is_demo: true,
      environment_label: "STAGING",
    });
    assert.deepEqual(info, {
      oidcEnabled: true,
      oidcProviderName: "Keycloak",
      oidcAutoRedirect: false,
      isDemo: true,
      environmentLabel: "STAGING",
    });
  });

  test("camelCase wins when both spellings are present", () => {
    assert.equal(parseLoginInfo({ oidcEnabled: false, oidc_enabled: true }).oidcEnabled, false);
  });

  test("missing, empty or mistyped values fall back to the defaults", () => {
    for (const body of [null, undefined, "nope", 42, {}]) assert.deepEqual(parseLoginInfo(body), LOGIN_INFO_DEFAULTS);
    const info = parseLoginInfo({ oidcEnabled: "true", oidcProviderName: "", isDemo: 1, environmentLabel: null });
    assert.deepEqual(info, LOGIN_INFO_DEFAULTS);
  });
});

describe("shouldAutoRedirectToOidc", () => {
  const info = (oidcEnabled, oidcAutoRedirect) => ({ ...LOGIN_INFO_DEFAULTS, oidcEnabled, oidcAutoRedirect });

  test("only when SSO and auto-redirect are both on", () => {
    assert.equal(shouldAutoRedirectToOidc(info(true, true), null), true);
    assert.equal(shouldAutoRedirectToOidc(info(true, false), null), false);
    assert.equal(shouldAutoRedirectToOidc(info(false, true), null), false);
    assert.equal(shouldAutoRedirectToOidc(info(false, false), null), false);
  });

  test("never when returning from a failed attempt", () => {
    assert.equal(shouldAutoRedirectToOidc(info(true, true), "oidc"), false);
  });
});
