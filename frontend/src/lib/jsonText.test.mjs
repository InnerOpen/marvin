import assert from "node:assert/strict";
import { test } from "node:test";
import { jsonText } from "./jsonText.ts";

const words = [
  { word: "Hi", start: 0.1, end: 0.4 },
  { word: "there", start: 0.45, end: 0.9 },
];

test("jsonText: a read-only list of flat rows is one row to a line, and the same JSON", () => {
  const text = jsonText(words, true);
  assert.equal(text, '[\n  {"word":"Hi","start":0.1,"end":0.4},\n  {"word":"there","start":0.45,"end":0.9}\n]');
  assert.deepEqual(JSON.parse(text), words);
});

test("jsonText: an editable value, a nested one or an empty one is as it always was", () => {
  assert.equal(jsonText(words), JSON.stringify(words, null, 2));
  const nested = [{ word: "Hi", tags: ["a"] }];
  assert.equal(jsonText(nested, true), JSON.stringify(nested, null, 2));
  assert.equal(jsonText({ a: 1 }, true), JSON.stringify({ a: 1 }, null, 2));
  assert.equal(jsonText([], true), "[]");
  for (const empty of [null, undefined, ""]) assert.equal(jsonText(empty, true), "");
});
