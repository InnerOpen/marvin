// Event Log audit coverage helpers (auditSettings.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  excludedSummary,
  groupByCategory,
  isOverridden,
  matchesFilter,
  overrideFor,
  searchText,
} from "./auditSettings.ts";

const row = (eventType, category, audited, defaultAudited = true, locked = false) => ({
  eventType,
  name: eventType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
  category,
  audited,
  defaultAudited,
  locked,
});

describe("isOverridden", () => {
  test("differs from the default", () => {
    assert.equal(isOverridden(row("entry_updated", "Content", false)), true);
    assert.equal(isOverridden(row("scheduled_task_started", "Automation", true, false)), true);
  });
  test("matches the default", () => {
    assert.equal(isOverridden(row("entry_updated", "Content", true)), false);
    assert.equal(isOverridden(row("scheduled_task_started", "Automation", false, false)), false);
  });
  test("a locked type is never overridden", () => {
    assert.equal(isOverridden(row("member_added", "Members", false, true, true)), false);
  });
});

describe("groupByCategory", () => {
  test("keeps the API's order of categories and rows", () => {
    const groups = groupByCategory([
      row("member_added", "Members", true),
      row("entry_created", "Content", true),
      row("member_removed", "Members", true),
      row("entry_updated", "Content", false),
    ]);
    assert.deepEqual(
      groups.map((g) => [g.category, g.rows.map((r) => r.eventType)]),
      [
        ["Members", ["member_added", "member_removed"]],
        ["Content", ["entry_created", "entry_updated"]],
      ],
    );
  });
  test("empty", () => assert.deepEqual(groupByCategory([]), []));
});

describe("filter", () => {
  const text = searchText(row("entry_updated", "Content", true));
  test("matches name, machine name and category, any case and word order", () => {
    assert.equal(matchesFilter(text, "Entry Updated"), true);
    assert.equal(matchesFilter(text, "entry_updated"), true);
    assert.equal(matchesFilter(text, "updated entry"), true);
    assert.equal(matchesFilter(text, "content"), true);
  });
  test("an empty box matches everything", () => assert.equal(matchesFilter(text, "  "), true));
  test("a word that isn't there fails", () => assert.equal(matchesFilter(text, "entry deleted"), false));
});

describe("excludedSummary", () => {
  test("counts", () => {
    assert.equal(excludedSummary(0), "every event type recorded");
    assert.equal(excludedSummary(1), "1 event type excluded from this log");
    assert.equal(excludedSummary(3), "3 event types excluded from this log");
  });
});

describe("overrideFor", () => {
  test("null when the switch lands on the default", () => {
    assert.equal(overrideFor({ defaultAudited: true }, true), null);
    assert.equal(overrideFor({ defaultAudited: false }, false), null);
  });
  test("the value otherwise", () => {
    assert.equal(overrideFor({ defaultAudited: true }, false), false);
    assert.equal(overrideFor({ defaultAudited: false }, true), true);
  });
});
