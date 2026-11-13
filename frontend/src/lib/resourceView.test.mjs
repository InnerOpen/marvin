// The Resources page's URL <-> filters <-> the list API's query (resourceView.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { isFiltered, readResourceView, resourceHref, resourceListParams } from "./resourceView.ts";

const view = (qs) => readResourceView(new URLSearchParams(qs));

test("no filters: everything, by name", () => {
  assert.deepEqual(resourceListParams(view("")), { sort: "name" });
  assert.equal(isFiltered(view("")), false);
  assert.equal(resourceHref(view("")), "/workspace/resources");
});

test("the search, type, tag, link and external id become the API's query", () => {
  assert.deepEqual(resourceListParams(view("q=wickett&type=tool&tag=leather&link=no&external=yes")), {
    sort: "name",
    q: "wickett",
    resource_type: "tool",
    tag: "leather",
    has_url: false,
    has_external_id: true,
  });
});

test("sort by type, and the Trash, reach the API", () => {
  assert.deepEqual(resourceListParams(view("sort=type&status=trashed")), { sort: "type", trashed: true });
});

test("junk in the URL reads as none; a type button toggles", () => {
  const v = view("link=maybe&sort=bogus&status=gone&type=tool");
  assert.equal(v.link, "");
  assert.equal(v.sort, "name");
  assert.equal(v.status, "");
  assert.deepEqual(resourceListParams(v), { sort: "name", resource_type: "tool" });
  assert.equal(resourceHref(v, { type: "" }), "/workspace/resources");
  assert.equal(resourceHref(v, { type: "supplier" }), "/workspace/resources?type=supplier");
});
