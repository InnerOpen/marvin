// The Trash's wording and restore target (trash.ts). Run with `npm test`. The backend rules it mirrors are
// tested in tests/test_trash.py.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { autoEmptyLabel, autoEmptyNote, emptyTrashPrompt, restoresTo, trashedAt } from "./trash.ts";

describe("auto-empty wording", () => {
  test("never vs a number of days", () => {
    assert.equal(autoEmptyLabel(0), "Never");
    assert.equal(autoEmptyLabel(30), "30 days");
    assert.equal(autoEmptyNote(30), "Entries in the Trash are deleted forever after 30 days.");
    assert.equal(autoEmptyNote(0), "Entries in the Trash are kept until you empty the Trash.");
  });

  test("the Empty trash confirmation counts what goes", () => {
    assert.equal(emptyTrashPrompt(1), "Permanently delete 1 entry? This can't be undone.");
    assert.equal(emptyTrashPrompt(12), "Permanently delete 12 entries? This can't be undone.");
  });
});

describe("restoresTo", () => {
  test("goes back to the status it had", () => {
    assert.equal(restoresTo({ trash: { previous_status: "needs_review" } }), "needs_review");
    assert.equal(restoresTo({ trash: { previous_status: "archived" } }), "archived");
  });

  test("a published entry comes back as a draft, and so does one with no record", () => {
    assert.equal(restoresTo({ trash: { previous_status: "published" } }), "draft");
    assert.equal(restoresTo({}), "draft");
    assert.equal(restoresTo(null), "draft");
  });

  test("trashedAt reads the record", () => {
    assert.equal(trashedAt({ trash: { trashed_at: "2026-10-07T10:00:00+00:00" } }), "2026-10-07T10:00:00+00:00");
    assert.equal(trashedAt({}), null);
  });
});
