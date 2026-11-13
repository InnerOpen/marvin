import assert from "node:assert/strict";
import { test } from "node:test";
import { lastPage, pager, pageHref, pastEndHref, rangeText, readPage } from "./pagination.ts";

const at = (path) => new URL(path, "http://marvin.test");

test("the page and size come from the address, with page 1 of 50 when they are missing or wrong", () => {
  assert.deepEqual(readPage(at("/workspace/entries").searchParams), { page: 1, per: 50, offset: 0 });
  assert.deepEqual(readPage(at("/x?page=3&per=25").searchParams), { page: 3, per: 25, offset: 50 });
  assert.deepEqual(readPage(at("/x?page=0&per=7").searchParams), { page: 1, per: 50, offset: 0 });
  assert.deepEqual(readPage(at("/x?page=abc").searchParams), { page: 1, per: 50, offset: 0 });
});

test("the range counts with thousands separators", () => {
  assert.equal(rangeText(2, 50, 1255), "51–100 of 1,255");
  assert.equal(rangeText(1, 50, 0), "");
});

test("the last page is partial", () => {
  assert.equal(lastPage(1255, 50), 26);
  assert.equal(rangeText(26, 50, 1255), "1,251–1,255 of 1,255");
  const p = pager(at("/workspace/entries?page=26"), 1255);
  assert.equal(p.next, null);
  assert.equal(p.prev, "/workspace/entries?page=25");
});

test("page 1 has no Previous, and a single page has neither", () => {
  const first = pager(at("/workspace/entries"), 120);
  assert.equal(first.prev, null);
  assert.equal(first.next, "/workspace/entries?page=2");
  const only = pager(at("/workspace/entries"), 10);
  assert.equal(only.prev, null);
  assert.equal(only.next, null);
});

test("a page past the end goes to the last page, or page 1 when there is nothing", () => {
  assert.equal(pastEndHref(at("/workspace/entries?page=40&sort=title"), 1255), "/workspace/entries?page=26&sort=title");
  assert.equal(pastEndHref(at("/workspace/entries?page=3"), 0), "/workspace/entries");
  assert.equal(pastEndHref(at("/workspace/entries?page=26"), 1255), null);
  assert.equal(pastEndHref(at("/workspace/entries"), 0), null);
});

test("paging keeps the filters and the order", () => {
  const c = encodeURIComponent(JSON.stringify([{ dim: "status", op: "is", value: ["draft"] }]));
  const url = at(`/workspace/entries?c=${c}&sort=title&per=25&page=2`);
  const next = new URL(pager(url, 200).next, "http://marvin.test");
  assert.equal(next.searchParams.get("c"), JSON.stringify([{ dim: "status", op: "is", value: ["draft"] }]));
  assert.equal(next.searchParams.get("sort"), "title");
  assert.equal(next.searchParams.get("per"), "25");
  assert.equal(next.searchParams.get("page"), "3");
});

test("a new page size starts again at page 1 and keeps the filters", () => {
  const url = at("/workspace/entries?sort=updated&page=4");
  assert.equal(pageHref(url, { per: 100 }), "/workspace/entries?sort=updated&per=100");
  assert.equal(pageHref(at("/workspace/entries?per=100&page=2"), { per: 50 }), "/workspace/entries");
  const sizes = pager(url, 500).sizes;
  assert.deepEqual(sizes.map((s) => [s.per, s.current]), [[25, false], [50, true], [100, false]]);
});

test("the one-shot trashed parameter is not carried to another page", () => {
  const url = at("/workspace/entries?trashed=abc&sort=title");
  assert.equal(pageHref(url, { page: 2 }), "/workspace/entries?sort=title&page=2");
  assert.equal(pageHref(url, { per: 25 }), "/workspace/entries?sort=title&per=25");
});
