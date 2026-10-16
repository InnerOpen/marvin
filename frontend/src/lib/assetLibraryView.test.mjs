// The Assets library's URL ↔ filters (assetLibraryView.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { isFiltered, isUnsearchableImage, listParams, readLibraryView, viewHref } from "./assetLibraryView.ts";

const view = (qs) => readLibraryView(new URLSearchParams(qs));

test("the default view folds versions and sorts by name", () => {
  assert.deepEqual(listParams(view("")), { sort: "name", versions: false });
  assert.equal(isFiltered(view("")), false);
});

test("filters become the API's query; unknown values are ignored", () => {
  const v = view("q=harbour&type=image&origin=generated&tag=brand&collection=featured&attached=no&sort=newest&type2=x");
  assert.deepEqual(listParams(v), {
    sort: "newest",
    q: "harbour",
    asset_type: ["image"],
    origin: ["generated"],
    tag: ["brand"],
    collection: "featured",
    unattached: true,
    versions: false,
  });
  assert.deepEqual(listParams(view("type=nonsense&sort=random&attached=maybe")), { sort: "name", versions: false });
});

test("versions show when asked, when filtering to derived ones, and for one original's versions", () => {
  assert.equal("versions" in listParams(view("versions=show")), false);
  assert.equal("versions" in listParams(view("origin=derived")), false);
  assert.deepEqual(listParams(view("source=abc")), { sort: "name", source: "abc" });
});

test("links keep the view and change only what they say", () => {
  const v = view("tag=brand&sort=newest");
  assert.equal(viewHref(v, { source: "abc" }), "/workspace/assets?tag=brand&source=abc&sort=newest");
  assert.equal(viewHref(v, { tag: "", sort: "name" }), "/workspace/assets");
  assert.equal(viewHref(view("versions=show")), "/workspace/assets?versions=show");
});

test("the decision filter (what an approval said about a picture) reaches the API and the links", () => {
  const v = view("decision=denied");
  assert.equal(listParams(v).decision, "denied");
  assert.equal(isFiltered(v), true);
  assert.match(viewHref(v), /decision=denied/);
  assert.equal("decision" in listParams(view("decision=maybe")), false);
});


test("'not searchable yet' filters on the page, not in the API query, and survives links", () => {
  const v = view("searchable=no&type=image");
  assert.equal(v.searchable, "no");
  assert.equal(isFiltered(v), true);
  assert.equal("searchable" in listParams(v), false);
  assert.equal(viewHref(v, { sort: "newest" }), "/workspace/assets?type=image&searchable=no&sort=newest");
  assert.equal(view("searchable=maybe").searchable, "");
});

test("a picture with no alt text or description is not searchable; anything else is left alone", () => {
  assert.equal(isUnsearchableImage({ mimeType: "image/jpeg", altText: "", description: "  " }), true);
  assert.equal(isUnsearchableImage({ mimeType: "image/jpeg", altText: "Hands at a sewing machine" }), false);
  assert.equal(isUnsearchableImage({ mimeType: "image/png", description: "A worn knee" }), false);
  assert.equal(isUnsearchableImage({ mimeType: "application/pdf" }), false);
});
