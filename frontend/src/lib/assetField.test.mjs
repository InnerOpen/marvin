// Making an attached asset the entry's asset field (assetField.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { assetFieldOf, offerableAssets } from "./assetField.ts";

describe("assetFieldOf", () => {
  test("the first single-asset field, with its label", () => {
    const schema = { fields: [{ key: "text", type: "textarea" }, { key: "audio", label: "Audio", type: "asset" }, { key: "more", type: "asset-list" }] };
    assert.deepEqual(assetFieldOf(schema), { key: "audio", label: "Audio" });
  });
  test("the key stands in for a missing label", () => {
    assert.deepEqual(assetFieldOf({ fields: [{ key: "hero", type: "asset" }] }), { key: "hero", label: "hero" });
  });
  test("null when the type has no single-asset field", () => {
    assert.equal(assetFieldOf({ fields: [{ key: "gallery", type: "asset-list" }] }), null);
    assert.equal(assetFieldOf(null), null);
  });
});

describe("offerableAssets", () => {
  const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
  test("every attached asset but the one in use, when there is a choice", () => {
    assert.deepEqual(offerableAssets(items, "b").map((x) => x.id), ["a", "c"]);
    assert.deepEqual(offerableAssets(items, null).map((x) => x.id), ["a", "b", "c"]);
  });
  test("nothing to offer when only one is attached", () => {
    assert.deepEqual(offerableAssets([{ id: "a" }], null), []);
  });
});
