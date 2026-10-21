// The Custom events page's list (customEventList.ts): grouping by what sends each event, search, and the card.
// Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { customEventAdapter, customEventCardHtml, SENDER_GROUPS, senderGroup } from "./customEventList.ts";
import { fromOptions, organize } from "./organizedList.ts";

const ev = (name, extra = {}) => ({
  name,
  eventType: `custom.${name}`,
  title: null,
  description: null,
  fields: [],
  usedBy: [],
  ...extra,
});

describe("what sends an event", () => {
  test("a webhook beats a workflow, a workflow beats nothing", () => {
    assert.equal(senderGroup(["incoming_webhook", "workflow"]), "webhook");
    assert.equal(senderGroup(["workflow"]), "workflow");
    assert.equal(senderGroup([]), "none");
    assert.equal(senderGroup(undefined), "none");
  });

  test("Marvin's own and scheduled senders don't count for a custom event", () => {
    assert.equal(senderGroup(["marvin", "scheduled_task"]), "none");
  });
});

describe("the adapter", () => {
  const kinds = { "custom.hooked": ["incoming_webhook", "workflow"], "custom.flowed": ["workflow"] };
  const adapter = customEventAdapter(kinds);
  const events = [
    ev("idle"),
    ev("flowed", { title: "Kit shipped", description: "Sent when a kit leaves" }),
    ev("hooked"),
    ev("zzz_idle"),
  ];

  test("sections: workflow, webhook, nothing yet; empty ones left out", () => {
    const result = organize(events, adapter, {});
    assert.deepEqual(
      result.sections.map((s) => [s.key, s.title, s.items.map((e) => e.name)]),
      [
        ["workflow", "Sent by a workflow", ["flowed"]],
        ["webhook", "Sent by a webhook", ["hooked"]],
        ["none", "Nothing sends it yet", ["idle", "zzz_idle"]],
      ],
    );
    assert.deepEqual(fromOptions(events.filter((e) => e.name === "hooked"), adapter, {}).map((c) => c.value), ["webhook"]);
    assert.equal(SENDER_GROUPS.length, 3);
  });

  test("search covers the name, title, description and event type", () => {
    const hit = (query) => organize(events, adapter, {}, {}, { query }).sections.flatMap((s) => s.items.map((e) => e.name));
    assert.deepEqual(hit("kit shipped"), ["flowed"]);
    assert.deepEqual(hit("leaves"), ["flowed"]);
    assert.deepEqual(hit("custom.hooked"), ["hooked"]);
    assert.deepEqual(hit("nothing-like-this"), []);
  });

  test("an event the counts don't know (still loading, or the call failed) reads as nothing sends it", () => {
    const sections = organize(events, customEventAdapter({}), {}).sections;
    assert.deepEqual(sections.map((s) => s.key), ["none"]);
  });
});

describe("the card", () => {
  test("title, slug, description, fields, who uses it, and the existing actions", () => {
    const html = customEventCardHtml(
      ev("kit_shipped", {
        title: "Kit <shipped>",
        description: "When it leaves",
        fields: [{ key: "sku", type: "string", description: "which" }],
        usedBy: ["Notify"],
      }),
    );
    assert.match(html, /data-name="kit_shipped"/);
    assert.match(html, /Kit &lt;shipped&gt;/);
    assert.match(html, /custom\.kit_shipped/);
    assert.match(html, /When it leaves/);
    assert.match(html, /sku/);
    assert.match(html, /Used by Notify/);
    assert.match(html, /href="\/automation\/events\/custom\.kit_shipped"/);
    assert.match(html, /js-edit/);
    assert.match(html, /js-delete/);
  });

  test("no fields and no users say so", () => {
    const html = customEventCardHtml(ev("quiet"));
    assert.match(html, /No fields: the event just happens\./);
    assert.match(html, /No workflow uses it yet\./);
  });
});
