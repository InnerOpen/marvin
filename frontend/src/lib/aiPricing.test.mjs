// Admin → AI pricing helpers (aiPricing.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import { feedSummary, groupByProvider, priceText, withOverride, withoutOverride } from "./aiPricing.ts";

test("rows group by provider in order", () => {
  const rows = [{ provider: "anthropic", model: "a" }, { provider: "openai", model: "b" }, { provider: "anthropic", model: "c" }];
  assert.deepEqual(groupByProvider(rows).map((g) => [g.provider, g.rows.map((r) => r.model)]), [["anthropic", ["a", "c"]], ["openai", ["b"]]]);
});

test("a price reads in / out, and no price is a dash", () => {
  assert.equal(priceText({ inputPer1m: 4, outputPer1m: 20 }), "$4 / $20");
  assert.equal(priceText({ inputPer1m: 0.15, outputPer1m: 0.6 }), "$0.15 / $0.6");
  assert.equal(priceText({ inputPer1m: null, outputPer1m: null }), "—");
});

test("setting a price replaces that model's override; removing drops only it", () => {
  const list = [{ provider: "openai", model: "x", inputPer1m: 1, outputPer1m: 2 }, { provider: "openai", model: "y", inputPer1m: 3, outputPer1m: 4 }];
  const set = withOverride(list, "openai", "x", 5, 6);
  assert.deepEqual(set.find((o) => o.model === "x"), { provider: "openai", model: "x", inputPer1m: 5, outputPer1m: 6 });
  assert.equal(set.length, 2);
  assert.deepEqual(withoutOverride(list, "openai", "x").map((o) => o.model), ["y"]);
});

test("the feed line says off, not yet, or how many models when", () => {
  assert.equal(feedSummary({ url: "" }), "The price feed is off.");
  assert.match(feedSummary({ url: "https://x", fetchedAt: null }), /^Not fetched yet/);
  assert.match(feedSummary({ url: "https://x", fetchedAt: "2026-10-10T23:00:00+00:00", models: 709 }), /^709 models priced, fetched /);
});
