// Grouping the Integrations page by category (integrationCategories.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { categoryLabel, focusedCategory, groupByCategory } from "./integrationCategories.ts";

const providers = [
  { slug: "rss", category: "source" },
  { slug: "vercel", category: "destination" },
  { slug: "slack", category: "notify" },
  { slug: "openai", category: "capability" },
  { slug: "apprise", category: "notify" },
  { slug: "odd", category: "widget" },
];

const shape = (groups) => groups.map((g) => [g.category, g.items.map((p) => p.slug)]);

describe("groupByCategory", () => {
  test("Notify, Destination, Capability, Source, then anything else; each group in the given order", () => {
    assert.deepEqual(shape(groupByCategory(providers, (p) => p.category)), [
      ["notify", ["slack", "apprise"]],
      ["destination", ["vercel"]],
      ["capability", ["openai"]],
      ["source", ["rss"]],
      ["widget", ["odd"]],
    ]);
  });

  test("empty groups are skipped; no category goes last as Other", () => {
    const groups = groupByCategory([{ slug: "gone" }, { slug: "vercel", category: "destination" }], (p) => p.category);
    assert.deepEqual(shape(groups), [
      ["destination", ["vercel"]],
      ["other", ["gone"]],
    ]);
    assert.equal(groups[1].label, "Other");
  });

  test("a focused group leads", () => {
    assert.deepEqual(
      groupByCategory(providers, (p) => p.category, "source").map((g) => g.category),
      ["source", "notify", "destination", "capability", "widget"],
    );
  });
});

describe("labels and ?category=", () => {
  test("labels", () => {
    assert.equal(categoryLabel("notify"), "Notify");
    assert.equal(categoryLabel("widget"), "Widget");
  });

  test("only a group the page shows can be focused", () => {
    assert.equal(focusedCategory("Notify", ["notify", "source"]), "notify");
    assert.equal(focusedCategory("destination", ["notify"]), null);
    assert.equal(focusedCategory(null, ["notify"]), null);
  });
});
