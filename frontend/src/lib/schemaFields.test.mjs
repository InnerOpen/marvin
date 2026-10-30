import assert from "node:assert/strict";
import test from "node:test";
import { coerceDataJsonValue } from "./schemaFields.ts";

test("a list field's comma-joined ids become an array, and an empty one an empty array", () => {
  assert.deepEqual(coerceDataJsonValue("asset-list", "a,b"), ["a", "b"]);
  assert.deepEqual(coerceDataJsonValue("resource-list", " a , b "), ["a", "b"]);
  assert.deepEqual(coerceDataJsonValue("asset-list", ""), []);
});

test("a single asset or resource field stays a string, blank is null", () => {
  assert.equal(coerceDataJsonValue("asset", "a"), "a");
  assert.equal(coerceDataJsonValue("resource", ""), null);
});

test("numbers and booleans coerce as before", () => {
  assert.equal(coerceDataJsonValue("number", "3"), 3);
  assert.equal(coerceDataJsonValue("number", "x"), null);
  assert.equal(coerceDataJsonValue("boolean", "true"), true);
  assert.equal(coerceDataJsonValue(undefined, "false"), false);
  assert.equal(coerceDataJsonValue("text", "hi"), "hi");
});
