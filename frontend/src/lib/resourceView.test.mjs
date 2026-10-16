// The Resources page's URL ↔ filters (resourceView.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { filterResources, isFiltered, readResourceView, resourceHref } from "./resourceView.ts";

const view = (qs) => readResourceView(new URLSearchParams(qs));
const items = [
  { name: "Wickett & Craig", resourceType: "supplier", url: "https://wickett.example", tags: ["leather"] },
  { name: "Awl", resourceType: "tool", description: "A stitching awl from Wickett", externalId: "T-1" },
  { name: "Bridle", resourceType: "material", tags: ["leather"] },
];
const names = (rs) => rs.map((r) => r.name);

test("no filters: everything, by name", () => {
  assert.deepEqual(names(filterResources(items, view(""))), ["Awl", "Bridle", "Wickett & Craig"]);
  assert.equal(isFiltered(view("")), false);
  assert.equal(resourceHref(view("")), "/workspace/resources");
});

test("the name search also reads the description", () => {
  assert.deepEqual(names(filterResources(items, view("q=wickett"))), ["Awl", "Wickett & Craig"]);
});

test("type, tag, link and external id each narrow", () => {
  assert.deepEqual(names(filterResources(items, view("type=tool"))), ["Awl"]);
  assert.deepEqual(names(filterResources(items, view("tag=leather&link=no"))), ["Bridle"]);
  assert.deepEqual(names(filterResources(items, view("external=yes"))), ["Awl"]);
});

test("sort by type, then name", () => {
  assert.deepEqual(names(filterResources(items, view("sort=type"))), ["Bridle", "Wickett & Craig", "Awl"]);
});

test("junk in the URL reads as none; a type button toggles", () => {
  const v = view("link=maybe&sort=bogus&status=gone&type=tool");
  assert.equal(v.link, "");
  assert.equal(v.sort, "name");
  assert.equal(v.status, "");
  assert.equal(resourceHref(v, { type: "" }), "/workspace/resources");
  assert.equal(resourceHref(v, { type: "supplier" }), "/workspace/resources?type=supplier");
});
