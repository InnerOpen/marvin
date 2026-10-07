// Admin → Platform alerts helpers (platformAlerts.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { buildUpdate, deliveryBadge, draftFrom, missingInputs, parseRecipients, targetKey } from "./platformAlerts.ts";

describe("parseRecipients", () => {
  test("one per line or comma-separated, blanks dropped, repeats once", () => {
    assert.deepEqual(parseRecipients("ops@example.test, Ada@example.test\n\nada@example.test;  bob@example.test "), [
      "ops@example.test",
      "Ada@example.test",
      "bob@example.test",
    ]);
    assert.deepEqual(parseRecipients("   "), []);
  });
});

describe("deliveryBadge", () => {
  test("nothing yet", () => {
    assert.deepEqual(deliveryBadge(null), { label: "Nothing sent yet", tone: "muted", detail: "" });
  });
  test("sent, skipped and failed, for an event and a test", () => {
    const base = { at: "2026-10-07T12:00:00Z", detail: "x", eventType: "backup_failed", test: false };
    assert.equal(deliveryBadge({ ...base, outcome: "sent" }).label, "backup_failed: sent");
    assert.equal(deliveryBadge({ ...base, outcome: "skipped" }).tone, "warn");
    assert.deepEqual(deliveryBadge({ ...base, outcome: "failed", eventType: null, test: true }), {
      label: "Test: failed",
      tone: "err",
      detail: "x",
    });
  });
});

describe("routes", () => {
  const target = {
    integrationId: "i1",
    integrationName: "Ops",
    provider: "slack",
    providerName: "Slack",
    connectionEnabled: true,
    action: "post",
    actionLabel: "Post",
    inputs: [
      { key: "channel", label: "Channel", description: "", required: true },
      { key: "emoji", label: "Emoji", description: "", required: false },
    ],
  };

  test("required inputs left empty are named", () => {
    assert.deepEqual(missingInputs(target, { channel: "  " }), ["Channel"]);
    assert.deepEqual(missingInputs(target, { channel: "#ops" }), []);
    assert.deepEqual(missingInputs(undefined, {}), []);
  });

  test("a route keys on its connection and action", () => {
    assert.equal(targetKey(target), "i1:post");
  });

  test("the save payload keeps ids, drops empty arguments and says 'every super admin' as null", () => {
    const saved = draftFrom({
      id: "r1",
      integrationId: "i1",
      action: "post",
      args: { channel: "#ops" },
      enabled: true,
      label: "",
      problem: null,
      lastDelivery: null,
    });
    const update = buildUpdate({
      types: { backup_failed: true, backup_recovered: false },
      emailEnabled: true,
      everySuperAdmin: true,
      recipientsText: "ignored@example.test",
      routes: [
        saved,
        { integrationId: "i2", action: "notify", args: { channel: "", emoji: ":fire:" }, enabled: false },
      ],
    });
    assert.deepEqual(update, {
      types: { backup_failed: true, backup_recovered: false },
      email: { enabled: true, recipients: null },
      routes: [
        { id: "r1", integrationId: "i1", action: "post", enabled: true, args: { channel: "#ops" } },
        { integrationId: "i2", action: "notify", enabled: false, args: { emoji: ":fire:" } },
      ],
    });
    assert.deepEqual(
      buildUpdate({
        types: {},
        emailEnabled: false,
        everySuperAdmin: false,
        recipientsText: "a@example.test",
        routes: [],
      }).email,
      { enabled: false, recipients: ["a@example.test"] },
    );
  });
});
