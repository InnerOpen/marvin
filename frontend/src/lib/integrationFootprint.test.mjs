// The integration card's "What it installed" sections (integrationFootprint.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { footprintIsEmpty, footprintSections, footprintSummary, fromHref } from "./integrationFootprint.ts";
import { fromOptions, urlFilters } from "./organizedList.ts";

const item = (name, enabled = true) => ({ id: `id-${name}`, name, enabled });
const empty = {
  integrationId: "b1",
  workflows: [],
  incomingWebhooks: [],
  outgoingWebhooks: [],
  scheduledTasks: [],
  collections: [],
  playbooks: [],
  fieldChanges: [],
  total: 0,
};

describe("footprint sections", () => {
  test("each kind with something gets a counted heading and a link filtered to the integration", () => {
    const sections = footprintSections({
      ...empty,
      workflows: [item("a"), item("b")],
      incomingWebhooks: [item("h")],
      outgoingWebhooks: [item("d")],
      scheduledTasks: [item("t"), item("u"), item("v")],
      collections: [item("c")],
      playbooks: [item("p", false)],
      total: 9,
    });
    assert.deepEqual(
      sections.map((s) => [s.heading, s.href]),
      [
        ["2 workflows", "/automation/workflows?from=integration%3Ab1"],
        ["1 incoming webhook", "/automation/incoming-webhooks?from=integration%3Ab1"],
        ["1 outgoing webhook", "/automation/webhooks?from=integration%3Ab1"],
        ["3 scheduled tasks", "/workspace/scheduled-tasks?from=integration%3Ab1"],
        ["1 collection", "/workspace/collections"],
        ["1 Playbook", "/workspace/settings/ai-playbooks?from=integration%3Ab1"],
      ],
    );
    assert.deepEqual(
      sections[0].items.map((i) => i.name),
      ["a", "b"],
    );
  });

  test("kinds with nothing are left out", () => {
    const sections = footprintSections({ ...empty, scheduledTasks: [item("t")], total: 1 });
    assert.deepEqual(
      sections.map((s) => s.kind),
      ["scheduledTasks"],
    );
    assert.deepEqual(footprintSections(empty), []);
  });

  test("the link's From value is one the list kit accepts and selects", () => {
    const href = fromHref("/automation/workflows", "b1");
    const search = href.slice(href.indexOf("?"));
    const adapter = { id: (i) => i.id, name: (i) => i.name, source: (i) => i.source, enabled: () => true };
    const integrations = { b1: { name: "Buttondown" } };
    const options = fromOptions([{ id: "1", name: "x", source: { integrationId: "b1" } }], adapter, integrations);
    assert.deepEqual(urlFilters(search, { from: options.map((o) => o.value) }), { from: "integration:b1" });
  });
});

describe("empty and summary", () => {
  test("an integration with nothing installed is empty; one with only a field change is not", () => {
    assert.equal(footprintIsEmpty(empty), true);
    assert.equal(footprintSummary(empty), "nothing yet");
    const changed = {
      ...empty,
      fieldChanges: [
        { entryTypeSlug: "n", entryTypeName: "Newsletter Signup", label: "Added fields to Newsletter Signup" },
      ],
    };
    assert.equal(footprintIsEmpty(changed), false);
    assert.equal(footprintSummary(changed), "1 type changed");
  });

  test("the summary counts items and changed types", () => {
    assert.equal(footprintSummary({ ...empty, total: 1 }), "1 item");
    assert.equal(footprintSummary({ ...empty, total: 5, fieldChanges: [{}, {}] }), "5 items, 2 types changed");
  });
});
