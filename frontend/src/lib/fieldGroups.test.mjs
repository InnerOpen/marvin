import test from "node:test";
import assert from "node:assert/strict";
import { groupFields } from "./fieldGroups.ts";

const f = (key, group) => ({ key, group });

test("fields with no group stay single, in order", () => {
  const s = groupFields([f("a"), f("b")]);
  assert.deepEqual(s.map((x) => [x.group, x.fields.map((y) => y.key)]), [[null, ["a"]], [null, ["b"]]]);
});

test("a group gathers its fields where its first field is, even when they are not next to each other", () => {
  const s = groupFields([f("a"), f("m1", "Made"), f("b"), f("m2", "Made")]);
  assert.deepEqual(s.map((x) => [x.group, x.fields.map((y) => y.key)]), [[null, ["a"]], ["Made", ["m1", "m2"]], [null, ["b"]]]);
});

test("a blank or non-text group is no group", () => {
  assert.equal(groupFields([f("a", "  ")])[0].group, null);
  assert.equal(groupFields([{ key: "a", group: 3 }])[0].group, null);
});

test("a group is folded unless a field in it has an error, and counts what is filled", () => {
  const fields = [f("x", "G"), f("y", "G"), f("z", "G")];
  const s = groupFields(fields, { x: "1", y: [], z: null }, {});
  assert.equal(s[0].open, false);
  assert.equal(s[0].filled, 1);
  assert.equal(groupFields(fields, {}, { y: "Required" })[0].open, true);
});
