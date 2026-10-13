// Event subject links (eventEntity.ts). Run with `npm test` — plain `node --test`, which strips the
// module's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { entityHref, entityLink, entityTypeLabel } from "./eventEntity.ts";

describe("entityHref", () => {
  test("links an entry to its page", () => {
    assert.equal(entityHref("entry", "e-1"), "/workspace/entries/e-1");
  });

  test("links a workflow to the workflows page with it picked", () => {
    assert.equal(entityHref("automation", "w-1"), "/automation/workflows?workflow=w-1");
  });

  test("links a scheduled task and an outgoing webhook to their detail pages", () => {
    assert.equal(entityHref("scheduled_task", "t-1"), "/workspace/scheduled-tasks/t-1");
    assert.equal(entityHref("webhook", "h-1"), "/automation/webhooks/h-1");
  });

  test("links kinds without a detail page to their list page", () => {
    assert.equal(entityHref("incoming_webhook", "i-1"), "/automation/incoming-webhooks");
    assert.equal(entityHref("integration", "n-1"), "/workspace/settings/integrations");
  });

  test("encodes the id", () => {
    assert.equal(entityHref("asset", "a/b"), "/workspace/assets/a%2Fb");
  });

  test("returns null for an unknown type, a type with no page, or a missing id", () => {
    assert.equal(entityHref("ai_thread", "x"), null);
    assert.equal(entityHref("user", "u-1"), null);
    assert.equal(entityHref("toString", "x"), null);
    assert.equal(entityHref("entry", null), null);
    assert.equal(entityHref(null, "x"), null);
  });
});

describe("entityTypeLabel", () => {
  test("names a workflow a workflow, not an automation", () => {
    assert.equal(entityTypeLabel("automation"), "Workflow");
  });

  test("humanizes other types", () => {
    assert.equal(entityTypeLabel("scheduled_task"), "Scheduled task");
    assert.equal(entityTypeLabel("entry"), "Entry");
  });
});

describe("entityLink", () => {
  test("carries the name, the link and a short id", () => {
    assert.deepEqual(entityLink("entry", "0123456789abcdef", "Summer menu"), {
      label: "Entry 'Summer menu'",
      href: "/workspace/entries/0123456789abcdef",
      shortId: "01234567",
    });
  });

  test("renders an unknown type as plain text", () => {
    assert.deepEqual(entityLink("ai_thread", "0123456789"), { label: "Ai thread", href: null, shortId: "01234567" });
  });

  test("is null without a type", () => {
    assert.equal(entityLink(null, "x"), null);
  });
});
