// Smart-collection rules ↔ builder sync (smartRules.ts). Run with `npm test` — plain `node --test`,
// which strips smartRules.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  conditionValueFromText,
  conditionValueText,
  formatRules,
  parseRules,
  rulesFromState,
  stateFromRules,
} from "./smartRules.ts";

describe("rules round trip through the builder", () => {
  test("every entry dimension survives JSON → builder → JSON unchanged", () => {
    const rules = {
      entry_types: ["recipe"],
      statuses: ["published", "approved"],
      published_within_days: 30,
      where: [
        { field: "price", op: "gt", value: 100 },
        { field: "metadata.featured", op: "exists" },
      ],
      tags: ["summer"],
      created_within_days: 7,
      match: "any",
    };
    assert.deepEqual(rulesFromState(stateFromRules(rules), "entry", rules), rules);
  });

  test("keys the builder doesn't show are kept", () => {
    const base = { statuses: ["draft"], asset_types: ["image"], note: "hand-written" };
    const state = { ...stateFromRules(base), statuses: ["published"] };
    assert.deepEqual(rulesFromState(state, "entry", base), {
      statuses: ["published"],
      asset_types: ["image"],
      note: "hand-written",
    });
  });

  test("clearing a control removes its key instead of writing an empty value", () => {
    const base = { statuses: ["draft"], published_within_days: 30, match: "any" };
    const state = { ...stateFromRules(base), statuses: [], publishedWithinDays: null, match: "all" };
    assert.deepEqual(rulesFromState(state, "entry", base), {});
  });

  test("asset and resource targets write their own dimensions", () => {
    const state = { ...stateFromRules({}), assetTypes: ["image"], mimeTypes: ["image/svg+xml"], tags: ["hero"] };
    assert.deepEqual(rulesFromState(state, "asset"), {
      asset_types: ["image"],
      mime_types: ["image/svg+xml"],
      tags: ["hero"],
    });
    const res = { ...stateFromRules({}), resourceTypes: ["fabric"] };
    assert.deepEqual(rulesFromState(res, "resource"), { resource_types: ["fabric"] });
  });

  test("field conditions without a field are dropped, and exists/missing carry no value", () => {
    const state = {
      ...stateFromRules({}),
      where: [
        { field: "  ", op: "eq", value: "x" },
        { field: "sku", op: "missing", value: "ignored" },
      ],
    };
    assert.deepEqual(rulesFromState(state, "entry"), { where: [{ field: "sku", op: "missing" }] });
  });
});

describe("condition values", () => {
  test("typed text becomes a list for `in` and a number for comparisons", () => {
    assert.deepEqual(conditionValueFromText("in", "red, blue ,"), ["red", "blue"]);
    assert.equal(conditionValueFromText("gte", " 12.5 "), 12.5);
    assert.equal(conditionValueFromText("gt", "$1,170"), "$1,170"); // the server reads number-like text
    assert.equal(conditionValueFromText("eq", "42"), "42");
    assert.equal(conditionValueFromText("exists", "x"), undefined);
  });

  test("stored values display as the text that produces them", () => {
    assert.equal(conditionValueText(["red", "blue"]), "red, blue");
    assert.equal(conditionValueText(100), "100");
    assert.equal(conditionValueText(undefined), "");
  });
});

describe("parseRules", () => {
  test("blank is an empty rule set", () => {
    assert.deepEqual(parseRules("  \n"), { ok: true, rules: {} });
  });

  test("invalid JSON and non-objects are errors", () => {
    assert.equal(parseRules('{"statuses": [').ok, false);
    assert.equal(parseRules('["published"]').ok, false);
    assert.equal(parseRules("null").ok, false);
  });

  test("an empty rule set formats as blank so the placeholder shows", () => {
    assert.equal(formatRules({}), "");
    assert.equal(formatRules({ statuses: ["draft"] }), '{\n  "statuses": [\n    "draft"\n  ]\n}');
  });
});
