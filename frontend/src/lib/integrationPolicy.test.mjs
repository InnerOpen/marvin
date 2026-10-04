// "How errors are handled" rows (integrationPolicy.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { overridesFrom, policyRows } from "./integrationPolicy.ts";

const handle = (summary, flags = {}) => ({
  review: false,
  notify: false,
  succeed: false,
  retry: null,
  // biome-ignore lint/suspicious/noThenProperty: the SDK's Handle names its after-retries step "then"
  then: null,
  summary,
  ...flags,
});

const POLICY = {
  provider: {
    "*": handle("send to review", { review: true }),
    auth: handle("notify admins, wait for the connection to recover, then retry once, then fail", { notify: true }),
  },
  actions: {
    create_listing: {
      invalid: handle("send to review", { review: true }),
      auth: handle("notify admins", { notify: true }),
    },
  },
};

describe("policyRows", () => {
  test("one row per code, provider-wide first, the catch-all last", () => {
    const rows = policyRows(POLICY, { create_listing: "Create listing" });

    assert.deepEqual(
      rows.map((r) => r.code),
      ["auth", "invalid", "*"],
    );
    assert.equal(rows[2].label, "Any other error");
    assert.deepEqual(rows[0].declared, [
      { scope: "All actions", summary: POLICY.provider.auth.summary },
      { scope: "Create listing", summary: "notify admins" },
    ]);
  });

  test("applies the connection's overrides and says which rows differ from the default", () => {
    const rows = policyRows(POLICY, {}, { invalid: { review: false, notify: true } });
    const invalid = rows.find((r) => r.code === "invalid");

    assert.deepEqual(invalid.defaults, { review: true, notify: false });
    assert.deepEqual(invalid.effective, { review: false, notify: true });
    assert.equal(invalid.overridden, true);
    assert.equal(rows.find((r) => r.code === "auth").overridden, false);
  });

  test("no policy (an older SDK) is no rows", () => {
    assert.deepEqual(policyRows(null), []);
  });
});

describe("overridesFrom", () => {
  test("keeps only the flags that differ from the provider's default", () => {
    const defaults = { review: true, notify: false };

    assert.deepEqual(
      overridesFrom([
        { code: "invalid", defaults, review: false, notify: false },
        { code: "*", defaults, review: true, notify: false },
      ]),
      { invalid: { review: false } },
    );
  });
});
