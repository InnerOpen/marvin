import assert from "node:assert/strict";
import { describe, test } from "node:test";
import {
  formatBytes,
  formatDuration,
  formatInterval,
  formatRetention,
  formatSchedule,
  relativeTime,
  stateBadge,
} from "./backupHealth.ts";

describe("stateBadge", () => {
  test("states and statuses get a label and a tone", () => {
    assert.deepEqual(stateBadge("ok"), { label: "OK", tone: "ok" });
    assert.deepEqual(stateBadge("overdue"), { label: "Overdue", tone: "err" });
    assert.deepEqual(stateBadge("partial"), { label: "Partial", tone: "warn" });
    assert.deepEqual(stateBadge("missed"), { label: "Missed", tone: "err" });
    assert.deepEqual(stateBadge("unknown"), { label: "No schedule", tone: "muted" });
  });
  test("an unknown value is shown as is", () => {
    assert.deepEqual(stateBadge("weird"), { label: "weird", tone: "muted" });
  });
});

describe("formatting", () => {
  test("bytes", () => {
    assert.equal(formatBytes(null), "—");
    assert.equal(formatBytes(512), "512 B");
    assert.equal(formatBytes(7_400_000), "7.4 MB");
    assert.equal(formatBytes(2_500_000_000), "2.50 GB");
  });
  test("durations", () => {
    assert.equal(formatDuration(8.73), "8.7 s");
    assert.equal(formatDuration(245), "4 min 05 s");
    assert.equal(formatDuration(3720), "1 h 02 min");
    assert.equal(formatDuration(null), "—");
  });
  test("intervals", () => {
    assert.equal(formatInterval(3600), "every hour");
    assert.equal(formatInterval(86400), "every 24 h");
    assert.equal(formatInterval(900), "every 15 min");
    assert.equal(formatInterval(null), "—");
  });
  test("relative times", () => {
    const now = "2026-10-07T16:05:00Z";
    assert.equal(relativeTime("2026-10-07T16:04:30Z", now), "just now");
    assert.equal(relativeTime("2026-10-07T15:05:00Z", now), "1 h ago");
    assert.equal(relativeTime("2026-10-07T15:35:00Z", now), "30 min ago");
    assert.equal(relativeTime("2026-10-07T13:05:00Z", now), "3 h ago");
    assert.equal(relativeTime("2026-10-07T17:00:00Z", now), "in 55 min");
    assert.equal(relativeTime("2026-10-04T16:05:00Z", now), "3 days ago");
    assert.equal(relativeTime(null, now), "—");
  });
  test("retention leaves out what is off", () => {
    assert.equal(formatRetention({ keepHourly: 48, keepDaily: 30, keepWeekly: 8 }), "48 hourly · 30 daily · 8 weekly");
    assert.equal(formatRetention({ keepHourly: 0, keepDaily: 30, keepWeekly: 8 }), "30 daily · 8 weekly");
    assert.equal(formatRetention({ keepHourly: null, keepDaily: null, keepWeekly: null }), "—");
  });
  test("schedule names its zone", () => {
    assert.equal(formatSchedule("0 * * * *", "America/New_York"), "0 * * * * (America/New_York)");
    assert.equal(formatSchedule("30 2 * * *", null), "30 2 * * * (UTC)");
    assert.equal(formatSchedule(null, null), "—");
  });
});
