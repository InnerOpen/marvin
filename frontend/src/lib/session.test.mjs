// The login session (session.ts): the cookie lives as long as its token, an expired one sends a page view to the
// login page and back, and the way back never leaves the site. Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  cookieMaxAge,
  expiredSessionRedirect,
  FALLBACK_COOKIE_SECONDS,
  isExpired,
  SESSION_CHECK_MS,
  safeReturnPath,
  sessionRejected,
  tokenExpiresAt,
} from "./session.ts";

/** A JWT-shaped token (unsigned: only the payload matters here). */
const jwt = (payload) => `eyJhbGciOiJIUzI1NiJ9.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.sig`;
const NOW = Date.UTC(2026, 9, 9, 22, 0, 0);
const inSeconds = (s) => Math.floor(NOW / 1000) + s;

describe("token expiry", () => {
  test("reads exp from the token's payload", () => {
    assert.equal(tokenExpiresAt(jwt({ sub: "u", exp: inSeconds(60) })), NOW + 60_000);
  });

  test("a token whose expiry can't be read is not treated as expired", () => {
    for (const token of ["not-a-jwt", jwt({ sub: "u" }), "a.%%%.b", "", null, undefined]) {
      assert.equal(isExpired(token, NOW), false, String(token));
    }
  });

  test("expired once exp has passed", () => {
    assert.equal(isExpired(jwt({ exp: inSeconds(-1) }), NOW), true);
    assert.equal(isExpired(jwt({ exp: inSeconds(3600) }), NOW), false);
  });
});

describe("cookieMaxAge", () => {
  test("lasts exactly as long as the token", () => {
    assert.equal(cookieMaxAge(jwt({ exp: inSeconds(48 * 3600) }), NOW), 48 * 3600);
  });

  test("an unreadable token keeps the old 7-day cookie; an expired one gets none", () => {
    assert.equal(cookieMaxAge("opaque", NOW), FALLBACK_COOKIE_SECONDS);
    assert.equal(cookieMaxAge(jwt({ exp: inSeconds(-10) }), NOW), 0);
  });
});

describe("expiredSessionRedirect", () => {
  const at = (path) => new URL(`https://marvin.example${path}`);

  test("a page view goes to login and comes back to the same page, query included", () => {
    assert.equal(
      expiredSessionRedirect("GET", at("/workspace/settings/ai-workflow?tab=persona")),
      "/login?return=%2Fworkspace%2Fsettings%2Fai-workflow%3Ftab%3Dpersona",
    );
    assert.equal(expiredSessionRedirect("GET", at("/")), "/login");
  });

  test("signed-out pages, API calls and non-GET requests go ahead", () => {
    for (const path of [
      "/login",
      "/login?error=invalid",
      "/forgot",
      "/register",
      "/api/groups/ai-settings",
      "/healthz",
      "/version.json",
      "/manifest.webmanifest",
      "/_astro/x.js",
    ]) {
      assert.equal(expiredSessionRedirect("GET", at(path)), null, path);
    }
    assert.equal(expiredSessionRedirect("POST", at("/workspace/entries/new")), null);
    assert.equal(expiredSessionRedirect("POST", at("/share-target")), null);
  });
});

describe("safeReturnPath", () => {
  test("keeps a path on this site", () => {
    assert.equal(safeReturnPath("/workspace/settings?tab=persona"), "/workspace/settings?tab=persona");
  });

  test("anything that could leave the site becomes /", () => {
    for (const value of [
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "javascript:alert(1)",
      "",
      null,
      undefined,
    ]) {
      assert.equal(safeReturnPath(value), "/", String(value));
    }
  });
});

describe("sessionRejected", () => {
  const asked = (status) => {
    const calls = { n: 0 };
    const ask = async () => {
      calls.n += 1;
      if (status instanceof Error) throw status;
      return status;
    };
    return { calls, ask };
  };

  test("a 401 from the API means the session is dead", async () => {
    assert.equal(await sessionRejected("t-401", asked(401).ask, NOW), true);
  });

  test("an accepted session isn't asked about again for a while", async () => {
    const { calls, ask } = asked(200);
    assert.equal(await sessionRejected("t-ok", ask, NOW), false);
    assert.equal(await sessionRejected("t-ok", ask, NOW + SESSION_CHECK_MS - 1), false);
    assert.equal(calls.n, 1);
    await sessionRejected("t-ok", ask, NOW + SESSION_CHECK_MS + 1);
    assert.equal(calls.n, 2);
  });

  test("an unreachable or failing API never signs anyone out, and is asked again next time", async () => {
    const down = asked(new Error("ECONNREFUSED"));
    assert.equal(await sessionRejected("t-down", down.ask, NOW), false);
    const broken = asked(500);
    assert.equal(await sessionRejected("t-500", broken.ask, NOW), false);
    await sessionRejected("t-500", broken.ask, NOW + 1);
    assert.equal(broken.calls.n, 2);
  });
});
