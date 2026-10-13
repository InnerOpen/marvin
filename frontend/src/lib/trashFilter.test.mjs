// The Statuses filter on Assets and Resources (trashFilter.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import { showsForStatus, TRASHED } from "./trashFilter.ts";

test("All Statuses hides trashed items outside the Trash group", () => {
  assert.equal(showsForStatus("", false, false), true);
  assert.equal(showsForStatus("", true, false), false);
});

test("the Trash group lists its items while nothing is filtered", () => {
  assert.equal(showsForStatus("", true, true), true);
});

test("In the Trash shows only trashed items, in either view", () => {
  assert.equal(showsForStatus(TRASHED, true, false), true);
  assert.equal(showsForStatus(TRASHED, true, true), true);
  assert.equal(showsForStatus(TRASHED, false, false), false);
});
