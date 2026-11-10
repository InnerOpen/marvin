import assert from "node:assert/strict";
import { test } from "node:test";
import { childrenOf, MAX_RELATED } from "./related.ts";

test("children: the well-formed lookups of a schema, in order, at most six", () => {
  const schema = {
    children: [
      { title: " Beats ", entry_type: "beat", field: "story" },
      { title: "", entry_type: "chapter", field: "story" },
      { title: "Lines", entry_type: "Speech Line", field: "story" },
      { title: "Takes", entry_type: "take", field: "bad field" },
      { entry_type: "scene", field: "story" },
      { title: "Chapters", entry_type: "chapter", field: "story" },
    ],
  };
  assert.deepEqual(childrenOf(schema), [
    { title: "Beats", entry_type: "beat", field: "story" },
    { title: "Chapters", entry_type: "chapter", field: "story" },
  ]);
  assert.deepEqual(childrenOf({}), []);
  assert.deepEqual(childrenOf(null), []);
  assert.deepEqual(childrenOf({ children: "beats" }), []);
  const many = { children: Array.from({ length: 9 }, (_, i) => ({ title: `T${i}`, entry_type: "beat", field: "story" })) };
  assert.equal(childrenOf(many).length, MAX_RELATED);
});
