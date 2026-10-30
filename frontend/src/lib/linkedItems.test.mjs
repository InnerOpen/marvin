import assert from "node:assert/strict";
import test from "node:test";
import { assetItem, canAdd, chosen, idsOf, matches, resourceItem, serialize } from "./linkedItems.ts";

test("idsOf reads a list, a single id, or an older comma-separated string", () => {
  assert.deepEqual(idsOf(["a", "b"]), ["a", "b"]);
  assert.deepEqual(idsOf("a"), ["a"]);
  assert.deepEqual(idsOf("a, b ,,c"), ["a", "b", "c"]);
  assert.deepEqual(idsOf(null), []);
  assert.deepEqual(idsOf(""), []);
});

test("serialize joins with commas and round-trips through idsOf", () => {
  assert.equal(serialize(["a", "b"]), "a,b");
  assert.deepEqual(idsOf(serialize(["a", "b"])), ["a", "b"]);
});

test("chosen keeps order and leaves a placeholder for an id the list lacks", () => {
  const items = [{ id: "1", name: "One" }, { id: "2", name: "Two" }];
  const out = chosen(["2", "9", "1"], items);
  assert.deepEqual(out.map((i) => i.name), ["Two", "Unknown (9…)", "One"]);
  assert.equal(out[1].id, "9");
});

test("matches searches name, meta and id, case-insensitively", () => {
  const item = { id: "abc-123", name: "Hero shot", meta: "image/jpeg" };
  assert.equal(matches(item, "hero"), true);
  assert.equal(matches(item, "JPEG"), true);
  assert.equal(matches(item, "abc-1"), true);
  assert.equal(matches(item, "pdf"), false);
  assert.equal(matches(item, "  "), true);
});

test("canAdd: a single field takes one, a list respects max", () => {
  assert.equal(canAdd(0, false), true);
  assert.equal(canAdd(1, false), false);
  assert.equal(canAdd(5, true), true);
  assert.equal(canAdd(2, true, 2), false);
  assert.equal(canAdd(1, true, 2), true);
});

test("assetItem shows a thumbnail only for an image with a url", () => {
  assert.equal(assetItem({ id: "1", name: "a", mimeType: "image/png", publicUrl: "/x.png" }).imageUrl, "/x.png");
  assert.equal(assetItem({ id: "1", name: "a", mimeType: "application/pdf", publicUrl: "/x.pdf" }).imageUrl, null);
  assert.equal(assetItem({ id: "1", name: "a", mimeType: "image/png" }).imageUrl, null);
  assert.equal(resourceItem({ id: "r", name: "Thread", slug: "thread" }).meta, "thread");
});
