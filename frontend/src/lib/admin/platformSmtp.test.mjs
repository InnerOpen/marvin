// Admin → Email → Platform SMTP helpers (platformSmtp.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { buildSmtpUpdate, fieldHint, passwordHint, sourceLabel, sourcePill } from "./platformSmtp.ts";

describe("pills and hints", () => {
  test("the overall pill", () => {
    assert.deepEqual(sourcePill({ source: "admin" }), { label: "Admin settings", tone: "ok" });
    assert.deepEqual(sourcePill({ source: "env" }), { label: "Environment", tone: "muted" });
    assert.deepEqual(sourcePill({ source: null }), { label: "Not set", tone: "warn" });
  });

  test("a field says where it comes from and what it overrides", () => {
    assert.equal(fieldHint({ source: "env", envValue: "smtp.env.test" }), "From the environment");
    assert.equal(
      fieldHint({ source: "admin", envValue: "smtp.env.test" }),
      "Overrides the environment's smtp.env.test",
    );
    assert.equal(fieldHint({ source: "admin", envValue: null }), "Set here");
    assert.equal(fieldHint({ source: null, envValue: null }), "Not set");
    assert.equal(sourceLabel("admin"), "Admin");
  });

  test("the password hint", () => {
    const base = { passwordSet: true, passwordSource: "admin", passwordMissing: false, canStorePassword: true };
    assert.match(passwordHint(base), /leave blank to keep/);
    assert.match(passwordHint({ ...base, passwordSource: "env" }), /From the environment/);
    assert.match(
      passwordHint({ ...base, passwordMissing: true, passwordSource: "env" }),
      /missing from the secret store/,
    );
    assert.match(passwordHint({ ...base, canStorePassword: false }), /PLATFORM_SMTP_PASSWORD/);
    assert.equal(passwordHint({ ...base, passwordSet: false, passwordSource: null }), "Not set");
  });
});

describe("buildSmtpUpdate", () => {
  const blank = {
    host: "",
    port: "",
    username: "",
    authStrategy: "",
    fromName: "",
    fromEmail: "",
    password: "",
    clearPassword: false,
  };

  test("blank fields are null (back to the environment) and the password is left out", () => {
    assert.deepEqual(buildSmtpUpdate(blank), {
      host: null,
      port: null,
      username: null,
      authStrategy: null,
      fromName: null,
      fromEmail: null,
    });
  });

  test("values are trimmed, the port a number, a typed password sent", () => {
    assert.deepEqual(
      buildSmtpUpdate({ ...blank, host: " smtp.x.test ", port: "2525", authStrategy: "SSL", password: "pw" }),
      {
        host: "smtp.x.test",
        port: 2525,
        username: null,
        authStrategy: "SSL",
        fromName: null,
        fromEmail: null,
        password: "pw",
      },
    );
  });

  test("clearing the password only counts when none is typed; a bad port is dropped", () => {
    assert.equal(buildSmtpUpdate({ ...blank, clearPassword: true }).clearPassword, true);
    assert.equal("clearPassword" in buildSmtpUpdate({ ...blank, clearPassword: true, password: "new" }), false);
    assert.equal(buildSmtpUpdate({ ...blank, port: "abc" }).port, null);
  });
});
