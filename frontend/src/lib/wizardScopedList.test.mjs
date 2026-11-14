import { test } from "node:test";
import assert from "node:assert/strict";
import { readCtx } from "./wizard.ts";
import { editableKeys, facetLabel, filtersOf, flagSpec, flagsOf, isScopedList, listParams, listView, readListState, rowChanges, scopedSpecs, unionRows } from "./wizardScopedList.ts";

// Shaped like Grace's "Art price check": every published piece for sale, plus the sold ones still for sale online.
const STEP = {
  id: "pieces",
  kind: "list",
  title: "Check each piece",
  entry_type: "artwork",
  where: [{ field: "publish_status", op: "eq", value: "published" }, { field: "status", op: "eq", value: "available" }],
  or_where: [{ field: "publish_status", op: "eq", value: "published" }, { field: "status", op: "eq", value: "sold" }, { field: "sellOnline", op: "eq", value: true }],
  columns: ["price", "shippingFee", "sellOnline"],
  check: { field: "priceChecked", label: "Looks right" },
  flags: [
    { label: "No price", where: [{ field: "price", op: "missing" }] },
    { label: "No shipping fee", where: [{ field: "sellOnline", op: "eq", value: true }, { field: "shippingFee", op: "missing" }] },
    { label: "Not for sale online", where: [{ field: "sellOnline", op: "neq", value: true }], attention: false },
  ],
  facet: "group",
};

const row = (n, data = {}) => ({ id: `id-${n}`, slug: `piece-${n}`, title: `Piece ${n}`, dataJson: { group: "ornaments", ...data } });

test("a list is scoped when it has no parent; a parent's list is not", () => {
  assert.equal(isScopedList(STEP), true);
  assert.equal(isScopedList({ id: "cast", kind: "list", title: "Cast", entry_type: "cast-member", parent: "story", parent_field: "story" }), false);
  assert.equal(isScopedList({ ...STEP, kind: "gallery" }), false);
  assert.equal(isScopedList(null), false);
});

test("a scoped list asks for its where, then its or_where, with the choices filled in", () => {
  assert.deepEqual(scopedSpecs(STEP, {}), [
    { entry_type: "artwork", where: STEP.where },
    { entry_type: "artwork", where: STEP.or_where },
  ]);
  const one = { ...STEP, where: [{ field: "series", op: "eq", value: "${series}" }], or_where: undefined };
  assert.deepEqual(scopedSpecs(one, { series: "floral" }), [{ entry_type: "artwork", where: [{ field: "series", op: "eq", value: "floral" }] }]);
  assert.deepEqual(scopedSpecs({ ...STEP, where: undefined, or_where: undefined }, {}), [{ entry_type: "artwork" }]);
});

test("the rows of both queries are listed once each", () => {
  assert.deepEqual(unionRows([[row(1), row(2)], [row(2), row(3)]]).map((r) => r.id), ["id-1", "id-2", "id-3"]);
});

test("a flag is asked of the server over exactly the listed entries", () => {
  assert.deepEqual(flagSpec(STEP, STEP.flags[0], ["a", "b"]), { entry_type: "artwork", entries: ["a", "b"], where: [{ field: "price", op: "missing" }] });
});

test("the filter, facet and search come from the address; anything unknown is the whole list", () => {
  const read = (qs, step = STEP) => readListState(new URLSearchParams(qs), step);
  assert.deepEqual(read(""), { filter: "all", facet: "", q: "" });
  assert.deepEqual(read("filter=unchecked&facet=ornaments&q=  blue   barn "), { filter: "unchecked", facet: "ornaments", q: "blue barn" });
  assert.equal(read("filter=flag-2").filter, "flag-2");
  assert.equal(read("filter=flag-3").filter, "all"); // there are three flags
  assert.equal(read("filter=sparkle").filter, "all");
  assert.equal(read("filter=checked", { ...STEP, check: undefined }).filter, "all"); // no check, no Checked filter
  assert.equal(read("facet=ornaments", { ...STEP, facet: undefined }).facet, "");
  assert.deepEqual(filtersOf(STEP), ["all", "attention", "unchecked", "checked", "flag-0", "flag-1", "flag-2"]);
  assert.deepEqual(listParams({ filter: "all", facet: "", q: "" }), {});
  assert.deepEqual(listParams({ filter: "checked", facet: "ornaments", q: "barn" }), { filter: "checked", facet: "ornaments", q: "barn" });
});

test("the list's own address parameters are never read as choices", () => {
  assert.deepEqual(readCtx(new URLSearchParams("filter=checked&facet=ornaments&q=barn&series=floral")), { series: "floral" });
});

test("a page shows the filter, facet and search over the server's answers, by name as people count, a page at a time", () => {
  const rows = [
    row(10, { price: "$85", priceChecked: true }),
    row(2, { price: "" }),
    row(1, { price: "$40", group: "small-canvases" }),
    row(3, { price: "$60", priceChecked: "true", group: "available" }),
  ];
  const flagged = [new Set(["id-2"]), new Set(["id-10"]), new Set(["id-1"])]; // no price; no shipping fee; not online (no attention)
  const state = { filter: "all", facet: "", q: "" };
  const all = listView(rows, STEP, flagged, state, { page: 1, per: 25 }, ["available", "small-canvases", "ornaments"]);
  assert.deepEqual(all.rows.map((r) => r.title), ["Piece 1", "Piece 2", "Piece 3", "Piece 10"]);
  assert.equal(all.checked, 2);
  assert.equal(all.all, 4);
  assert.deepEqual(all.counts, { all: 4, attention: 2, unchecked: 2, checked: 2, "flag-0": 1, "flag-1": 1, "flag-2": 1 });
  assert.deepEqual(all.facets, [
    { value: "available", label: "Available", count: 1 },
    { value: "small-canvases", label: "Small canvases", count: 1 },
    { value: "ornaments", label: "Ornaments", count: 2 },
  ]);
  // "Needs attention" is any flag that needs it: not "Not for sale online".
  assert.deepEqual(listView(rows, STEP, flagged, { ...state, filter: "attention" }, { page: 1, per: 25 }).rows.map((r) => r.id), ["id-2", "id-10"]);
  assert.deepEqual(listView(rows, STEP, flagged, { ...state, filter: "unchecked" }, { page: 1, per: 25 }).rows.map((r) => r.id), ["id-1", "id-2"]);
  assert.deepEqual(listView(rows, STEP, flagged, { ...state, filter: "flag-2" }, { page: 1, per: 25 }).rows.map((r) => r.id), ["id-1"]);
  // The facet and the search narrow the counts too; the progress is the whole list's.
  const orn = listView(rows, STEP, flagged, { filter: "all", facet: "ornaments", q: "" }, { page: 1, per: 25 });
  assert.deepEqual(orn.rows.map((r) => r.id), ["id-2", "id-10"]);
  assert.equal(orn.counts.checked, 1);
  assert.equal(orn.checked, 2);
  assert.deepEqual(listView(rows, STEP, flagged, { ...state, q: "PIECE 1" }, { page: 1, per: 25 }).rows.map((r) => r.id), ["id-1", "id-10"]);
  assert.deepEqual(listView(rows, STEP, flagged, { ...state, q: "piece-3" }, { page: 1, per: 25 }).rows.map((r) => r.id), ["id-3"]);
});

test("a long list comes a page at a time, and a page past the end shows the last one", () => {
  const rows = Array.from({ length: 104 }, (_v, n) => row(n + 1));
  const none = [new Set(), new Set(), new Set()];
  const state = { filter: "all", facet: "", q: "" };
  const p2 = listView(rows, STEP, none, state, { page: 2, per: 25 });
  assert.equal(p2.total, 104);
  assert.equal(p2.page, 2);
  assert.deepEqual([p2.rows[0].title, p2.rows.at(-1).title], ["Piece 26", "Piece 50"]);
  const past = listView(rows, STEP, none, state, { page: 9, per: 25 });
  assert.equal(past.page, 5);
  assert.equal(past.rows.length, 4);
  assert.equal(listView([], STEP, none, state, { page: 3, per: 25 }).page, 1);
});

test("a card shows the flags the server said it meets", () => {
  const flagged = [new Set(["a"]), new Set(), new Set(["a"])];
  assert.deepEqual(flagsOf("a", STEP, flagged), [{ label: "No price", attention: true }, { label: "Not for sale online", attention: false }]);
  assert.deepEqual(flagsOf("b", STEP, flagged), []);
});

test("a scoped list writes only its columns and its check field", () => {
  assert.deepEqual(editableKeys(STEP), ["price", "shippingFee", "sellOnline", "priceChecked"]);
  assert.deepEqual(editableKeys({ ...STEP, check: undefined, columns: ["price", "price"] }), ["price"]);
});

test("a save changes only what differs from what the page showed; a switch left off on a card without the field changes nothing", () => {
  const booleans = ["sellOnline", "priceChecked"];
  const was = { price: "$85", shippingFee: "10.00", sellOnline: true, priceChecked: null };
  assert.deepEqual(rowChanges({ price: "$85", shippingFee: "10.00", sellOnline: true, priceChecked: false }, was, booleans), {});
  assert.deepEqual(rowChanges({ price: "$95", shippingFee: "10.00", sellOnline: true, priceChecked: true }, was, booleans), { price: "$95", priceChecked: true });
  assert.deepEqual(rowChanges({ price: "$85", shippingFee: null, sellOnline: false, priceChecked: false }, was, booleans), { shippingFee: null, sellOnline: false });
  // An empty box and a field never set are the same: nothing to write.
  assert.deepEqual(rowChanges({ shippingFee: null }, { shippingFee: "" }, booleans), {});
});

test("a facet value reads as words", () => {
  assert.equal(facetLabel("small-canvases"), "Small canvases");
  assert.equal(facetLabel("paper_minis"), "Paper minis");
});
