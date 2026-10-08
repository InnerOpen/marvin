// The Trash's wording and restore target (trash.ts). Run with `npm test`. The backend rules it mirrors are
// tested in tests/test_trash.py.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  autoEmptyLabel,
  autoEmptyNote,
  deleteForeverPrompt,
  emptyTrashPrompt,
  restoreFailedMessage,
  restoresTo,
  trashedAt,
} from "./trash.ts";

describe("auto-empty wording", () => {
  test("never vs a number of days", () => {
    assert.equal(autoEmptyLabel(0), "Never");
    assert.equal(autoEmptyLabel(30), "30 days");
    assert.equal(autoEmptyNote(30), "Items in the Trash are deleted forever after 30 days.");
    assert.equal(autoEmptyNote(0), "Items in the Trash are kept until you empty the Trash.");
  });

  test("the Empty trash confirmation counts everything that goes and says files go too", () => {
    assert.equal(
      emptyTrashPrompt({ entries: 25, assets: 3, resources: 1 }),
      "Empty the Trash? This permanently deletes everything in it — on every tab, not just this one: 25 entries, 3 assets " +
        "and 1 resource. The assets' files are removed from storage. This can't be undone.",
    );
    assert.equal(
      emptyTrashPrompt({ entries: 1, assets: 0, resources: 0 }),
      "Empty the Trash? This permanently deletes everything in it — on every tab, not just this one: 1 entry. This can't be undone.",
    );
    assert.equal(
      emptyTrashPrompt({ entries: 2, assets: 0, resources: 4 }),
      "Empty the Trash? This permanently deletes everything in it — on every tab, not just this one: 2 entries and 4 resources. " +
        "This can't be undone.",
    );
  });

  test("delete forever says an asset's file goes", () => {
    assert.equal(deleteForeverPrompt("entry"), "Delete this entry forever? This can't be undone.");
    assert.equal(deleteForeverPrompt("resource"), "Delete this resource forever? This can't be undone.");
    assert.match(deleteForeverPrompt("asset"), /file is removed from storage/);
  });

  test("bulk restore failures name the tab", () => {
    assert.equal(restoreFailedMessage(2, 5, "assets"), "2 of 5 assets could not be restored.");
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
