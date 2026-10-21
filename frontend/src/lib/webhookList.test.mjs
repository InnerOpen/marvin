// The outgoing Webhooks page's list (webhookList.ts): mode, host-only display, the adapter for the list kit. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { organize, statusOptions } from "./organizedList.ts";
import { attentionReason, hostOf, MODE_OPTIONS, modeKind, webhookAdapter, webhookCardHtml, webhookSummary } from "./webhookList.ts";

const hook = (extra = {}) => ({ id: "1", name: "Hook", url: "https://hooks.example.com/services/T0/B0/SECRET?token=abc", enabled: true, ...extra });

describe("mode", () => {
  test("event-driven, scheduled (generic, user, entries) and workflow-called", () => {
    assert.equal(modeKind(hook({ webhookType: "event_driven" })), "event");
    for (const t of ["generic", "user", "entries", undefined]) assert.equal(modeKind(hook({ webhookType: t })), "schedule");
    assert.equal(modeKind(hook({ webhookType: "workflow" })), "manual");
  });
  test("offers the three modes", () => {
    assert.deepEqual(MODE_OPTIONS.map((o) => o.value), ["event", "schedule", "manual"]);
  });
});

describe("what the card shows of the URL", () => {
  test("the host and port only", () => {
    assert.equal(hostOf("https://hooks.example.com/services/T0/B0/SECRET?token=abc"), "hooks.example.com");
    assert.equal(hostOf("http://localhost:8083/hook"), "localhost:8083");
    assert.equal(hostOf("https://user:pw@example.com/x"), "example.com");
    assert.equal(hostOf("not a url"), "");
  });
  test("no path, query or credentials reach the card's markup", () => {
    const html = webhookCardHtml(hook({ url: "https://user:pw@hooks.example.com/services/SECRET?token=abc" }), { linked: false });
    for (const secret of ["SECRET", "token", "abc", "user:pw", "/services"]) assert.ok(!html.includes(secret), secret);
    assert.match(html, /hooks\.example\.com/);
  });
  test("search finds the host, not the path", () => {
    const a = webhookAdapter();
    assert.deepEqual(a.search(hook()), ["hooks.example.com"]);
  });
});

describe("summary", () => {
  test("method, host and how it fires", () => {
    assert.equal(webhookSummary(hook({ method: "GET", webhookType: "event_driven" })), "GET · hooks.example.com · when something happens");
    assert.equal(webhookSummary(hook({ webhookType: "workflow" })), "POST · hooks.example.com · called by a workflow");
    assert.equal(webhookSummary(hook({ scheduledTime: "2026-10-21T12:00:00Z" }), () => "today"), "POST · hooks.example.com · scheduled today");
    assert.match(webhookSummary(hook()), /not scheduled/);
  });
});

describe("the card", () => {
  test("Test and Edit are on the card, Delete sits in the ⋯ menu, the switch toggles", () => {
    const [outside, menu] = webhookCardHtml(hook(), { linked: false }).split('<div class="org-menu"');
    assert.match(outside, /js-toggle/);
    assert.match(outside, /js-test/);
    assert.match(outside, /href="\/automation\/webhooks\/1"/);
    assert.match(menu, /js-delete/);
  });
  test("an off webhook is dimmed, says Off and can't be tested", () => {
    const html = webhookCardHtml(hook({ enabled: false }), { linked: false });
    assert.match(html, /class="org-card wh-card off"/);
    assert.match(html, /Off · POST/);
    assert.match(html, /js-test" disabled/);
  });
  test("escapes the name; a flagged webhook says why", () => {
    const html = webhookCardHtml(hook({ name: "<b>x</b>", attention: "unreachable_address" }), { linked: false });
    assert.ok(!html.includes("<b>x</b>"));
    assert.match(html, /Needs a look/);
    assert.match(attentionReason(hook({ attention: "unreachable_address" })), /local or private/);
    assert.equal(attentionReason(hook()), "");
  });
});

describe("through the list kit", () => {
  const items = [
    hook({ id: "a", name: "Mine" }),
    hook({ id: "b", name: "Localhost", url: "http://localhost:8083/h", attention: "unreachable_address" }),
    hook({ id: "c", name: "Plugin", sourceIntegrationId: "i1", sourceBlueprint: "acme" }),
    hook({ id: "d", name: "Orphan", sourceBlueprint: "gone" }),
    hook({ id: "e", name: "Timed", webhookType: "user", enabled: false }),
  ];
  const integrations = { i1: { name: "Acme" } };
  const keys = (filters = {}) => organize(items, webhookAdapter(), integrations, filters, { query: "" }).sections.map((s) => s.key);

  test("sections: Yours, the integration, a removed integration", () => {
    assert.deepEqual(keys(), ["yours", "integration:i1", "removed"]);
  });
  test("Needs attention shows the flagged ones; the Mode filter narrows", () => {
    const names = (f) => organize(items, webhookAdapter(), integrations, f, { query: "" }).sections.flatMap((s) => s.items.map((i) => i.name));
    assert.deepEqual(names({ status: "attention" }), ["Localhost"]);
    assert.deepEqual(names({ mode: "schedule" }).sort(), ["Localhost", "Mine", "Orphan", "Plugin", "Timed"].sort());
    assert.deepEqual(names({ mode: "event" }), []);
  });
  test("the status filter offers Needs attention", () => {
    assert.equal(statusOptions({ attention: true })[0].value, "attention");
  });
});
