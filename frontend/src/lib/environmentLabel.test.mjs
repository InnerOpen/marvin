// Environment label helpers (environmentLabel.ts) behind the non-production badge and the "[DEV] " tab-title
// prefix. Run with `npm test` — plain `node --test`. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

import { environmentTone, getEnvironmentLabel, withEnvironmentPrefix } from "./environmentLabel.ts";

describe("environmentTone", () => {
  test("DEV labels are amber, STAGING labels purple", () => {
    assert.equal(environmentTone("DEV"), "dev");
    assert.equal(environmentTone("DEVELOPMENT"), "dev");
    assert.equal(environmentTone("STAGING"), "staging");
    assert.equal(environmentTone("stage"), "staging");
  });

  test("anything else is neutral", () => {
    for (const label of ["QA", "PR-123", "LOCAL", "PREVIEW"]) assert.equal(environmentTone(label), "neutral");
  });
});

describe("withEnvironmentPrefix", () => {
  test("prefixes the title once with the bracketed label", () => {
    assert.equal(withEnvironmentPrefix("Entries | Marvin", "DEV"), "[DEV] Entries | Marvin");
  });

  test("leaves the title alone without a label (production)", () => {
    for (const label of ["", null, undefined])
      assert.equal(withEnvironmentPrefix("Login | Marvin", label), "Login | Marvin");
  });
});

describe("getEnvironmentLabel", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  test("reads environmentLabel from login-info, then serves it from cache", async () => {
    let calls = 0;
    globalThis.fetch = async (url) => {
      calls++;
      assert.match(String(url), /\/api\/app\/about\/login-info$/);
      return new Response(JSON.stringify({ isDemo: false, environmentLabel: "DEV" }), { status: 200 });
    };
    assert.equal(await getEnvironmentLabel(), "DEV");
    assert.equal(await getEnvironmentLabel(), "DEV");
    assert.equal(calls, 1);
  });
});
