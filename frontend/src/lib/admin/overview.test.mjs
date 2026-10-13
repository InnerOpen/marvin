// Admin overview summaries (overview.ts). Run with `npm test` — plain `node --test`, which strips
// overview.ts's types itself. Plain JS so `astro check` (which has no Node typings here) leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { BACKUP_STALE_DAYS, formatAge, summarizeBackups, summarizeTasks } from "./overview.ts";

const NOW = Date.parse("2026-10-03T12:00:00Z");
const DAY_MS = 86_400_000;
const daysAgo = (n) => new Date(NOW - n * DAY_MS).toISOString();

function task(overrides) {
  return { id: "t", name: "Task", enabled: true, lastStatus: "success", lastRunAt: null, ...overrides };
}

describe("summarizeBackups", () => {
  test("test_summarize_backups_with_none_returns_none", () => {
    assert.deepEqual(summarizeBackups([], NOW), { state: "none", latestAt: null });
  });

  test("test_summarize_backups_picks_the_newest_regardless_of_order", () => {
    const summary = summarizeBackups([{ created_at: daysAgo(3) }, { created_at: daysAgo(1) }], NOW);
    assert.deepEqual(summary, { state: "fresh", latestAt: daysAgo(1) });
  });

  test("test_summarize_backups_older_than_threshold_returns_stale", () => {
    const summary = summarizeBackups([{ created_at: daysAgo(BACKUP_STALE_DAYS + 1) }], NOW);
    assert.equal(summary.state, "stale");
  });
});

describe("summarizeTasks", () => {
  test("test_summarize_tasks_lists_enabled_failures_only", () => {
    const summary = summarizeTasks([
      task({ id: "a", name: "Backup", lastStatus: "failed" }),
      task({ id: "b", name: "Poll", lastStatus: "timeout" }),
      task({ id: "c", name: "Old", lastStatus: "failed", enabled: false }),
      task({ id: "d", name: "Fine" }),
    ]);
    assert.deepEqual(summary.failing, [
      { id: "a", name: "Backup" },
      { id: "b", name: "Poll" },
    ]);
  });

  test("test_summarize_tasks_reports_most_recent_run", () => {
    const summary = summarizeTasks([task({ lastRunAt: daysAgo(2) }), task({ lastRunAt: daysAgo(1) }), task({})]);
    assert.equal(summary.lastRunAt, daysAgo(1));
  });
});

describe("formatAge", () => {
  test("test_format_age_scales_units", () => {
    assert.deepEqual(
      [formatAge(new Date(NOW - 30_000).toISOString(), NOW), formatAge(new Date(NOW - 5 * 60_000).toISOString(), NOW), formatAge(daysAgo(0.5), NOW), formatAge(daysAgo(12), NOW)],
      ["just now", "5m ago", "12h ago", "12d ago"],
    );
  });
});
