// The Entries page's structured search: chips ↔ URL ↔ query spec (entryQuery.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { addCond, condLabel, condsHref, fieldKind, fieldsFor, legacyConds, opsFor, readConds, toggleValue, toSpec, withoutCond } from "./entryQuery.ts";

const bench = { slug: "bench-note", schemaJson: { fields: [{ key: "readTime", label: "Read time", type: "text" }, { key: "noteNumber", type: "number" }, { key: "hero", type: "asset" }] } };
const project = { slug: "project", schemaJson: { fields: [{ key: "readTime", label: "Read time", type: "text" }, { key: "price", type: "number" }] } };

test("three conditions, one at a time, become one spec", () => {
  let conds = addCond([], { dim: "type", op: "is", value: ["bench-note"] });
  conds = addCond(conds, { dim: "status", op: "is", value: ["published"] });
  conds = addCond(conds, { dim: "field:readTime", op: "contains", value: "2 min" });
  assert.deepEqual(toSpec(conds), {
    sort: { by: "updated_at", direction: "desc" },
    entry_types: ["bench-note"],
    status: ["published"],
    where: [{ field: "readTime", op: "contains", value: "2 min" }],
  });
  assert.deepEqual(toSpec(withoutCond(conds, 1)).status, undefined);
});

test("a second chip on a list dimension joins the first as another value", () => {
  const conds = addCond(addCond([], { dim: "tag", op: "is", value: ["denim"] }), { dim: "tag", op: "is", value: ["repair"] });
  assert.equal(conds.length, 1);
  assert.deepEqual(toSpec(conds).tags, ["denim", "repair"]);
  assert.equal(condLabel(conds[0], { tags: { denim: "Denim" } }), "Tag is Denim or repair");
});

test("dates take a day, a before / after, or 'in the last N days'", () => {
  assert.equal(toSpec([{ dim: "published", op: "within", value: 30 }]).published_after, "-30d");
  assert.equal(toSpec([{ dim: "created", op: "before", value: "2026-10-01" }]).created_before, "2026-10-01");
  assert.equal(condLabel({ dim: "published", op: "within", value: 30 }), "Published in the last 30 days");
});

test("is set / is empty carry no value; is one of carries a list", () => {
  assert.deepEqual(toSpec([{ dim: "field:price", op: "missing" }]).where, [{ field: "price", op: "missing" }]);
  assert.deepEqual(toSpec([{ dim: "field:size", op: "in", value: ["S", "M"] }]).where, [{ field: "size", op: "in", value: ["S", "M"] }]);
  assert.equal(condLabel({ dim: "field:price", op: "exists" }, { fields: { price: "Price" } }), "Price is set");
});

test("the chips survive the URL, and junk in it reads as none", () => {
  const conds = [{ dim: "type", op: "is", value: ["bench-note"] }, { dim: "title", op: "contains", value: "denim & seams" }];
  const href = condsHref(conds);
  assert.deepEqual(readConds(new URL(href, "https://x.test").searchParams), conds);
  assert.equal(condsHref([]), "/workspace/entries");
  assert.deepEqual(readConds(new URLSearchParams("c=not-json")), []);
  assert.deepEqual(readConds(new URLSearchParams("c=%5B%7B%22op%22%3A1%7D%5D")), []);
});

test("fields offered are the comparable ones the chosen types share", () => {
  assert.deepEqual(fieldsFor([bench, project], ["bench-note"]).map((f) => f.key), ["readTime", "noteNumber"]);
  assert.deepEqual(fieldsFor([bench, project], ["bench-note", "project"]).map((f) => f.key), ["readTime"]);
  assert.deepEqual(fieldsFor([bench, project], []), []);
  assert.equal(fieldKind("asset"), null);
  assert.deepEqual(opsFor("field:noteNumber", { key: "noteNumber", label: "n", kind: "number" }).slice(0, 3), ["eq", "neq", "gt"]);
  assert.deepEqual(opsFor("published"), ["after", "before", "within"]);
});

test("the sidebar's old ?status= and ?tag= links open as chips", () => {
  assert.deepEqual(legacyConds(new URLSearchParams("status=inbox,needs_review,bogus&tag=leather")), [
    { dim: "status", op: "is", value: ["inbox", "needs_review"] },
    { dim: "tag", op: "is", value: ["leather"] },
  ]);
  assert.deepEqual(legacyConds(new URLSearchParams("trashed=x")), []);
});

test("a status button turns its status on and off", () => {
  let conds = toggleValue([], "status", "inbox");
  conds = toggleValue(conds, "status", "draft");
  assert.deepEqual(conds, [{ dim: "status", op: "is", value: ["inbox", "draft"] }]);
  conds = toggleValue(toggleValue(conds, "status", "inbox"), "status", "draft");
  assert.deepEqual(conds, []);
});

test("the images chip can ask for entries with no images", () => {
  assert.deepEqual(opsFor("images"), ["yes", "no"]);
  assert.equal(toSpec([{ dim: "images", op: "no" }]).has_images, false);
  assert.equal(toSpec([{ dim: "images", op: "yes" }]).has_images, true);
  assert.equal(condLabel({ dim: "images", op: "no" }), "Has no images");
});
