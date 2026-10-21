// The shared list kit (organizedList.ts): sections by source, search, filters, counts, the linked item and
// remembered filters. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  countsText,
  fromOptions,
  loadFilters,
  organize,
  STATUS_OPTIONS,
  saveFilters,
  sectionKey,
  statusOptions,
} from "./organizedList.ts";

const adapter = {
  id: (i) => i.id,
  name: (i) => i.name,
  search: (i) => [i.trigger ?? ""],
  source: (i) => i.source ?? {},
  enabled: (i) => i.on !== false,
  attention: (i) => Boolean(i.broken),
  facets: { starts: (i) => i.starts ?? "event" },
};

const integrations = { b1: { name: "Buttondown" }, c1: { name: "Cloudflare Pages" } };

const items = [
  { id: "w1", name: "Zeta mine", trigger: "run manually", starts: "manual" },
  { id: "w2", name: "Alpha mine", on: false },
  { id: "w3", name: "Recipe made", source: { recipe: "notify-on-publish" } },
  { id: "w4", name: "Send email", source: { integrationId: "b1" } },
  { id: "w5", name: "Rebuild", source: { integrationId: "c1" }, broken: true },
  { id: "w6", name: "Archive", source: { integrationId: "b1" }, on: false },
  { id: "w7", name: "Orphan", source: { integrationId: "gone" } },
  { id: "w8", name: "Platform job", source: { system: true } },
];

const keys = (result) => result.sections.map((s) => s.key);
const ids = (section) => section.items.map((i) => i.id);

describe("sections", () => {
  test("fixed order: yours, library, integrations by name, removed, marvin's own", () => {
    assert.deepEqual(keys(organize(items, adapter, integrations)), [
      "yours",
      "library",
      "integration:b1",
      "integration:c1",
      "removed",
      "system",
    ]);
  });

  test("within a section: enabled first, then by name", () => {
    const [yours, , buttondown] = organize(items, adapter, integrations).sections;
    assert.deepEqual(ids(yours), ["w1", "w2"]);
    assert.deepEqual(ids(buttondown), ["w4", "w6"]);
  });

  test("a source integration that no longer exists is From a removed integration", () => {
    const removed = organize(items, adapter, integrations).sections.find((s) => s.kind === "removed");
    assert.deepEqual(ids(removed), ["w7"]);
    assert.equal(removed.title, "From a removed integration");
  });

  test("an integration wins over a recipe; an item with neither is yours", () => {
    const both = { id: "x", name: "x", source: { recipe: "r", integrationId: "b1" } };
    assert.equal(sectionKey(both.source, integrations), "integration:b1");
    assert.equal(sectionKey({}, integrations), "yours");
    assert.equal(sectionKey(undefined, integrations), "yours");
  });

  test("titles and counts: integrations carry their name, counts are shown items and how many are on", () => {
    const buttondown = organize(items, adapter, integrations).sections.find((s) => s.key === "integration:b1");
    assert.equal(buttondown.title, "Buttondown");
    assert.equal(buttondown.integrationId, "b1");
    assert.deepEqual([buttondown.count, buttondown.on], [2, 1]);
    assert.equal(countsText(buttondown, "workflow"), "2 workflows, 1 on");
    assert.equal(countsText({ count: 1, on: 1 }, "workflow"), "1 workflow, 1 on");
  });

  test("a section with nothing to show is left out", () => {
    const only = organize([items[0]], adapter, integrations);
    assert.deepEqual(keys(only), ["yours"]);
  });
});

describe("search and filters", () => {
  test("search reads the name and the adapter's text; every word must match", () => {
    assert.deepEqual(
      organize(items, adapter, integrations, {}, { query: "manually" }).sections[0].items.map((i) => i.id),
      ["w1"],
    );
    assert.equal(organize(items, adapter, integrations, {}, { query: "zeta manually" }).shown, 1);
    assert.equal(organize(items, adapter, integrations, {}, { query: "zeta nothing" }).shown, 0);
  });

  test("From filters to one section", () => {
    assert.deepEqual(keys(organize(items, adapter, integrations, { from: "integration:c1" })), ["integration:c1"]);
    assert.deepEqual(keys(organize(items, adapter, integrations, { from: "library" })), ["library"]);
  });

  test("Status: on, off and needs attention", () => {
    assert.equal(organize(items, adapter, integrations, { status: "off" }).shown, 2);
    assert.equal(organize(items, adapter, integrations, { status: "on" }).shown, 6);
    const attention = organize(items, adapter, integrations, { status: "attention" });
    assert.deepEqual(attention.sections.flatMap(ids), ["w5"]);
  });

  test("an adapter without attention flags never matches Needs attention", () => {
    const plain = { ...adapter, attention: undefined };
    assert.equal(organize(items, plain, integrations, { status: "attention" }).shown, 0);
  });

  test("page-specific facets filter by the adapter's value; a blank filter means all", () => {
    assert.deepEqual(organize(items, adapter, integrations, { starts: "manual" }).sections.flatMap(ids), ["w1"]);
    assert.equal(organize(items, adapter, integrations, { starts: "" }).shown, items.length);
  });

  test("filters combine", () => {
    const result = organize(items, adapter, integrations, { from: "integration:b1", status: "off" });
    assert.deepEqual(result.sections.flatMap(ids), ["w6"]);
  });

  test("an empty result has no sections and shown 0", () => {
    const result = organize(items, adapter, integrations, {}, { query: "zzz" });
    assert.deepEqual([result.sections.length, result.shown], [0, 0]);
  });
});

describe("the linked item", () => {
  test("is shown whatever the filters and search say, in its own section", () => {
    const result = organize(
      items,
      adapter,
      integrations,
      { from: "yours", status: "on" },
      { query: "send", linkedId: "w6" },
    );
    assert.deepEqual(keys(result), ["integration:b1"]);
    assert.deepEqual(ids(result.sections[0]), ["w6"]);
    assert.ok(result.linkedShown);
  });

  test("an id that matches nothing changes nothing", () => {
    const result = organize(items, adapter, integrations, { status: "off" }, { linkedId: "nope" });
    assert.equal(result.shown, 2);
    assert.equal(result.linkedShown, false);
  });
});

describe("filter options", () => {
  test("From lists only the sections that exist, in order, integrations by name", () => {
    assert.deepEqual(fromOptions(items, adapter, integrations), [
      { value: "yours", label: "Yours" },
      { value: "library", label: "From the Library" },
      { value: "integration:b1", label: "Buttondown" },
      { value: "integration:c1", label: "Cloudflare Pages" },
      { value: "removed", label: "From a removed integration" },
      { value: "system", label: "Marvin's own" },
    ]);
    assert.deepEqual(fromOptions([items[0]], adapter, integrations), [{ value: "yours", label: "Yours" }]);
  });

  test("Status: On and Off, and Needs attention when a page has flags", () => {
    assert.deepEqual(
      STATUS_OPTIONS.map((o) => o.value),
      ["on", "off"],
    );
    assert.deepEqual(
      statusOptions({ attention: true }).map((o) => o.value),
      ["attention", "on", "off"],
    );
    assert.deepEqual(
      statusOptions().map((o) => o.value),
      ["on", "off"],
    );
  });
});

describe("remembered filters", () => {
  const memory = () => {
    const data = new Map();
    return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
  };
  const allowed = { from: ["yours", "integration:b1"], status: ["on", "off"], starts: ["event", "manual"] };

  test("round-trips what was chosen", () => {
    const store = memory();
    saveFilters(store, "k", { from: "yours", status: "off", starts: "" });
    assert.deepEqual(loadFilters(store, "k", allowed), { from: "yours", status: "off", starts: "" });
  });

  test("a value that is no longer offered falls back to All", () => {
    const store = memory();
    saveFilters(store, "k", { from: "integration:gone", status: "attention", starts: "manual" });
    assert.deepEqual(loadFilters(store, "k", allowed), { from: "", status: "", starts: "manual" });
  });

  test("nothing stored, bad JSON and blocked storage all give the defaults", () => {
    assert.deepEqual(loadFilters(memory(), "k", allowed), { from: "", status: "", starts: "" });
    const bad = { getItem: () => "{nope", setItem() {} };
    assert.deepEqual(loadFilters(bad, "k", allowed), { from: "", status: "", starts: "" });
    assert.deepEqual(loadFilters(null, "k", allowed), { from: "", status: "", starts: "" });
    const blocked = {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("blocked");
      },
    };
    assert.deepEqual(loadFilters(blocked, "k", allowed), { from: "", status: "", starts: "" });
    assert.doesNotThrow(() => saveFilters(blocked, "k", { from: "yours" }));
    assert.doesNotThrow(() => saveFilters(null, "k", { from: "yours" }));
  });
});

describe("pages that group by something other than the source", () => {
  const grouped = {
    ...adapter,
    groups: {
      choices: [
        { value: "workflow", label: "Sent by a workflow" },
        { value: "webhook", label: "Sent by a webhook" },
        { value: "none", label: "Nothing sends it yet" },
      ],
      of: (i) => i.sender ?? "none",
    },
  };
  const rows = [
    { id: "a", name: "Zed", sender: "webhook" },
    { id: "b", name: "Bee" },
    { id: "c", name: "Ant", sender: "workflow" },
    { id: "d", name: "Bat", sender: "workflow" },
  ];

  test("sections follow the page's own order and titles, not the source", () => {
    const result = organize(rows, grouped, {});
    assert.deepEqual(keys(result), ["workflow", "webhook", "none"]);
    assert.deepEqual(result.sections.map((s) => s.title), ["Sent by a workflow", "Sent by a webhook", "Nothing sends it yet"]);
    assert.deepEqual(ids(result.sections[0]), ["c", "d"]);
  });

  test("From offers only the groups that exist, and filters on them", () => {
    assert.deepEqual(fromOptions(rows.slice(1), grouped, {}).map((c) => c.value), ["workflow", "none"]);
    assert.deepEqual(keys(organize(rows, grouped, {}, { from: "none" })), ["none"]);
  });

  test("search still reads the name and the extra text", () => {
    assert.deepEqual(keys(organize(rows, grouped, {}, {}, { query: "ant" })), ["workflow"]);
  });

  test("counts can leave out the on/off tally", () => {
    assert.equal(countsText({ count: 2, on: 2 }, "event", { onOff: false }), "2 events");
    assert.equal(countsText({ count: 1, on: 1 }, "event", { onOff: false }), "1 event");
  });
});
