import assert from "node:assert/strict";
import { test } from "node:test";
import { childrenOf, firstShown, FETCHED, MAX_RELATED, SHOWN } from "./related.ts";

test("children: the well-formed lookups of a schema, in order, at most ten", () => {
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
  const many = { children: Array.from({ length: 14 }, (_, i) => ({ title: `T${i}`, entry_type: "beat", field: "story" })) };
  assert.equal(childrenOf(many).length, MAX_RELATED);
});

test("shown: the list starts where the entries start as people count them, not at an arbitrary few", () => {
  // 53 beats come back in no order at all; the page shows the first 30 by number, Beat 2 before Beat 10.
  const rows = Array.from({ length: 53 }, (_, i) => ({ id: `id${i + 1}`, title: `Beat ${i + 1}: words` }));
  const scrambled = [...rows].sort((a, b) => ((Number(a.id.slice(2)) * 7919) % 53) - ((Number(b.id.slice(2)) * 7919) % 53));
  const shown = firstShown(scrambled);
  assert.equal(shown.length, SHOWN);
  assert.deepEqual(shown.map((r) => r.title), rows.slice(0, SHOWN).map((r) => r.title));
  assert.equal(shown[1].title, "Beat 2: words");
  assert.equal(shown[9].title, "Beat 10: words");
  assert.ok(FETCHED > SHOWN, "it asks for more than it shows, so it can choose");
  assert.deepEqual(firstShown([{ title: "B" }, { title: "A" }], 5).map((r) => r.title), ["A", "B"]);
});
