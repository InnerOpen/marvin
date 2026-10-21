// The Incoming webhooks page's list (incomingWebhookList.ts): needs-attention, the Signed and Received filters, and the
// adapter's grouping through the shared kit. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { organize } from "./organizedList.ts";
import {
  attentionReason,
  incomingWebhookAdapter,
  isSigned,
  needsAttention,
  RECEIVED_OPTIONS,
  receivedState,
  SIGNED_OPTIONS,
} from "./incomingWebhookList.ts";

const NOW = new Date("2026-10-21T12:00:00Z");
const hook = (name, extra = {}) => ({ id: name, name, enabled: true, token: "t", receivedCount: 0, ...extra });
const adapter = incomingWebhookAdapter(() => NOW);
const ids = (result) => result.sections.flatMap((s) => s.items.map((w) => w.name));

describe("needs a look", () => {
  test("on and never received", () => {
    assert.equal(needsAttention(hook("a")), true);
    assert.equal(needsAttention(hook("a", { receivedCount: 3 })), false);
    assert.equal(needsAttention(hook("a", { enabled: false })), false);
  });

  test("the reason says whether a token is missing", () => {
    assert.match(attentionReason(hook("a")), /nothing has arrived/);
    assert.match(attentionReason(hook("a", { token: null })), /no token/);
    assert.equal(attentionReason(hook("a", { receivedCount: 1 })), "");
  });

  test("the Needs attention status filter uses it", () => {
    const items = [hook("silent"), hook("live", { receivedCount: 2 }), hook("off", { enabled: false })];
    const result = organize(items, adapter, {}, { status: "attention" }, {});
    assert.deepEqual(ids(result), ["silent"]);
  });
});

describe("signed", () => {
  test("a webhook with a signing secret is signed", () => {
    assert.equal(isSigned(hook("a", { signingSecretRef: "KEY" })), true);
    assert.equal(isSigned(hook("a", { signingSecretRef: "" })), false);
    assert.equal(isSigned(hook("a")), false);
  });

  test("the Signed filter", () => {
    const items = [hook("s", { signingSecretRef: "K" }), hook("u")];
    assert.deepEqual(ids(organize(items, adapter, {}, { signed: "yes" }, {})), ["s"]);
    assert.deepEqual(ids(organize(items, adapter, {}, { signed: "no" }, {})), ["u"]);
  });
});

describe("received", () => {
  const day = (n) => new Date(NOW.getTime() - n * 86_400_000).toISOString();

  test("recently, older or never", () => {
    assert.equal(receivedState(hook("a", { receivedCount: 2, lastReceivedAt: day(2) }), NOW), "recently");
    assert.equal(receivedState(hook("a", { receivedCount: 2, lastReceivedAt: day(30) }), NOW), "older");
    assert.equal(receivedState(hook("a", { receivedCount: 2, lastReceivedAt: null }), NOW), "older");
    assert.equal(receivedState(hook("a"), NOW), "never");
  });

  test("the Received filter", () => {
    const items = [
      hook("fresh", { receivedCount: 1, lastReceivedAt: day(1) }),
      hook("stale", { receivedCount: 1, lastReceivedAt: day(40) }),
      hook("never"),
    ];
    assert.deepEqual(ids(organize(items, adapter, {}, { received: "recently" }, {})), ["fresh"]);
    assert.deepEqual(ids(organize(items, adapter, {}, { received: "never" }, {})), ["never"]);
  });

  test("the options offered match what the adapter produces", () => {
    assert.deepEqual(SIGNED_OPTIONS.map((o) => o.value), ["yes", "no"]);
    assert.deepEqual(RECEIVED_OPTIONS.map((o) => o.value), ["recently", "never"]);
  });
});

describe("sections", () => {
  test("by source: yours, an integration, a removed integration", () => {
    const integrations = { i1: { name: "Buttondown" } };
    const items = [
      hook("mine"),
      hook("installed", { sourceIntegrationId: "i1", sourceBlueprint: "bd-hook" }),
      hook("orphan", { sourceBlueprint: "old-hook" }),
    ];
    const result = organize(items, adapter, integrations, {}, {});
    assert.deepEqual(result.sections.map((s) => s.key), ["yours", "integration:i1", "removed"]);
  });

  test("search finds the slug and description", () => {
    const items = [hook("A", { slug: "stripe-pay" }), hook("B", { description: "from GitHub" })];
    assert.deepEqual(ids(organize(items, adapter, {}, {}, { query: "stripe" })), ["A"]);
    assert.deepEqual(ids(organize(items, adapter, {}, {}, { query: "github" })), ["B"]);
  });
});
