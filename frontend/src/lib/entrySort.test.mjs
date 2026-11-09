import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_ENTRY_SORT, querySort, readCollectionSort, readEntrySort, sortEntries } from "./entrySort.ts";

const rows = [
  { title: "banana", createdAt: "2026-01-02T00:00:00Z", updatedAt: "2026-01-05T00:00:00Z" },
  { title: "Apple", createdAt: "2026-01-03T00:00:00Z", updatedAt: null },
  { title: "cherry", createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-01-04T00:00:00Z" },
];

test("the address parameter is read with a default", () => {
  assert.equal(readEntrySort("title"), "title");
  assert.equal(readEntrySort("sparkle"), DEFAULT_ENTRY_SORT);
  assert.equal(readEntrySort(null), "newest");
  assert.equal(readCollectionSort(null), "position");
  assert.equal(readCollectionSort("title"), "title");
  assert.deepEqual(querySort("position"), { by: "position", direction: "asc" });
});

test("each order sorts the plain list the same way the query would", () => {
  assert.deepEqual(sortEntries(rows, "newest").map((r) => r.title), ["Apple", "banana", "cherry"]);
  assert.deepEqual(sortEntries(rows, "oldest").map((r) => r.title), ["cherry", "banana", "Apple"]);
  assert.deepEqual(sortEntries(rows, "updated").map((r) => r.title), ["banana", "cherry", "Apple"]); // never updated: its creation counts
  assert.deepEqual(sortEntries(rows, "title").map((r) => r.title), ["Apple", "banana", "cherry"]);
  assert.deepEqual(rows.map((r) => r.title), ["banana", "Apple", "cherry"]); // the input is left alone
  assert.deepEqual(querySort("updated"), { by: "updated_at", direction: "desc" });
  assert.deepEqual(querySort("newest"), { by: "created_at", direction: "desc" });
});
