// The Workflows page's list (workflowList.ts): how a workflow starts, its one-line summary, and the adapter that
// feeds the shared list kit. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { organize } from "./organizedList.ts";
import {
  humanInterval,
  STARTS_OPTIONS,
  triggerKind,
  triggerSummary,
  workflowAdapter,
  workflowCardHtml,
} from "./workflowList.ts";

const wf = (trigger, extra = {}) => ({ id: "x", name: "X", enabled: true, definition: { trigger }, ...extra });
const names = {
  webhookName: (ref) => (ref === "hook" ? "Deploy hook" : ref),
  automationName: (ref) => (ref === "a" ? "Nightly" : ref),
};

describe("how a workflow starts", () => {
  test("kinds: events, schedule, webhook, by hand", () => {
    assert.equal(triggerKind(wf({ type: "event", event: "entry_published" })), "event");
    assert.equal(triggerKind(wf({ type: "chained", automation: "a" })), "event");
    assert.equal(triggerKind(wf({ type: "on_error" })), "event");
    assert.equal(triggerKind(wf({ type: "schedule" })), "schedule");
    assert.equal(triggerKind(wf({ type: "incoming_webhook" })), "webhook");
    assert.equal(triggerKind(wf({ type: "manual" })), "manual");
    assert.equal(triggerKind(wf({ type: "mcp" })), "manual");
  });

  test("a workflow with no trigger counts as an event workflow", () => {
    assert.equal(triggerKind({ id: "x", name: "X", enabled: true }), "event");
  });

  test("the Starts filter offers the four ways", () => {
    assert.deepEqual(
      STARTS_OPTIONS.map((o) => o.value),
      ["event", "schedule", "webhook", "manual"],
    );
  });

  test("summaries read like the cards always did", () => {
    assert.equal(triggerSummary(wf({ type: "manual" }), names), "run manually");
    assert.equal(triggerSummary(wf({ type: "mcp" }), names), "MCP tool");
    assert.equal(triggerSummary(wf({ type: "event", event: "entry_published" }), names), "entry published");
    assert.equal(
      triggerSummary(wf({ type: "schedule", schedule_config: { interval_seconds: 86400 } }), names),
      "every 1 day",
    );
    assert.equal(triggerSummary(wf({ type: "chained", automation: "a" }), names), "after Nightly");
    assert.equal(triggerSummary(wf({ type: "on_error", automation: "a" }), names), "if Nightly fails");
    assert.equal(triggerSummary(wf({ type: "incoming_webhook", webhook: "hook" }), names), "Deploy hook received");
  });

  test("intervals", () => {
    assert.equal(humanInterval(120), "2 minutes");
    assert.equal(humanInterval(3600), "1 hour");
    assert.equal(humanInterval(0), "—");
  });
});

describe("the workflow adapter", () => {
  const adapter = workflowAdapter(names);
  const items = [
    wf({ type: "event", event: "bench_note_published" }, { id: "1", name: "Tell Slack" }),
    wf(
      { type: "schedule", schedule_config: { interval_seconds: 3600 } },
      { id: "2", name: "Hourly", sourceIntegrationId: "b1" },
    ),
    wf({ type: "manual" }, { id: "3", name: "Mine", sourceRecipe: "r", enabled: false }),
  ];

  test("reads camelCase source fields from the API", () => {
    assert.deepEqual(adapter.source(items[1]), { integrationId: "b1", recipe: null });
    assert.deepEqual(adapter.source(items[2]), { integrationId: null, recipe: "r" });
  });

  test("search finds a workflow by what starts it", () => {
    const hit = organize(items, adapter, {}, {}, { query: "bench note published" });
    assert.deepEqual(
      hit.sections.flatMap((s) => s.items.map((i) => i.id)),
      ["1"],
    );
  });

  test("the Starts filter uses the trigger kind", () => {
    const hit = organize(items, adapter, { b1: { name: "B" } }, { starts: "schedule" });
    assert.deepEqual(
      hit.sections.flatMap((s) => s.items.map((i) => i.id)),
      ["2"],
    );
  });

  test("no attention flags yet (a later ticket adds them)", () => {
    assert.equal(adapter.attention, undefined);
  });
});

describe("the card", () => {
  const card = (extra = {}) =>
    workflowCardHtml(wf({ type: "manual" }, { id: "7", name: 'A "b" <c>', ...extra }), {
      summary: "run manually",
      details: "<p>flow</p>",
      linked: false,
    });

  test("Run and Edit are on the card; the rest sit in the ⋯ menu", () => {
    const html = card();
    const [outside, menu] = html.split('<div class="org-menu"');
    assert.match(outside, /js-run/);
    assert.match(outside, /js-edit/);
    for (const cls of ["js-dryrun", "js-history", "js-copy", "js-delete"]) assert.match(menu, new RegExp(cls));
  });

  test("escapes the name; carries the id, the trigger and the steps", () => {
    const html = card();
    assert.match(html, /data-id="7"/);
    assert.match(html, /A &quot;b&quot; &lt;c&gt;/);
    assert.match(html, /run manually/);
    assert.match(html, /<p>flow<\/p>/);
  });

  test("an off workflow is dimmed, says Off, and can't be run", () => {
    const html = card({ enabled: false });
    assert.match(html, /class="org-card wf-card off"/);
    assert.match(html, /Off · run manually/);
    assert.match(html, /js-run" disabled/);
  });

  test("the linked workflow is marked", () => {
    assert.match(
      workflowCardHtml(wf({ type: "manual" }), { summary: "", details: "", linked: true }),
      /wf-card linked/,
    );
  });
});
