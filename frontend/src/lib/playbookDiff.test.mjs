import assert from "node:assert/strict";
import test from "node:test";
import { changedFields, diffCounts, diffRows } from "./playbookDiff.ts";

test("an added section shows as added lines with a little context", () => {
  const before = ["# T", "", "a", "b", "c", "d", "e", "f"].join("\n");
  const after = ["# T", "", "a", "b", "c", "d", "e", "f", "", "## New", "- x"].join("\n");
  const rows = diffRows(before, after);
  assert.deepEqual(diffCounts(rows), { added: 3, removed: 0 });
  assert.equal(rows[0].text, "e"); // the untouched top of the text is left out
  assert.equal(rows.at(-1).text, "- x");
});

test("a changed line is one removed and one added", () => {
  const rows = diffRows("one\ntwo\nthree", "one\n2\nthree");
  assert.deepEqual(diffCounts(rows), { added: 1, removed: 1 });
  assert.equal(rows.some((r) => r.kind === "gap"), false);
});

test("identical text has no rows of change", () => {
  assert.deepEqual(diffRows("a\nb", "a\nb"), []);
});

test("changedFields names only the fields that differ", () => {
  assert.deepEqual(changedFields({ description: "x", license: "" }, { description: "y", license: null }), ["Description"]);
  assert.deepEqual(changedFields({ manual_only: false }, { manual_only: true }), ["Manual only"]);
});
