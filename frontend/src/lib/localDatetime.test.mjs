// datetime-local ↔ UTC conversion for the entry editor's schedule fields (localDatetime.ts). Run
// with `npm test` — plain `node --test`, which strips the .ts types itself. Plain JS so
// `astro check` leaves it alone. Each test file runs in its own process, so pinning TZ here
// only affects this file.

process.env.TZ = "America/Chicago";

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { formatLocalDateTime, fromDatetimeLocalValue, toDatetimeLocalValue } from "./localDatetime.ts";

describe("toDatetimeLocalValue", () => {
  test("shows a UTC timestamp as the viewer's wall-clock time", () => {
    // 15:30 UTC on Oct 3 is 10:30 CDT (UTC-5).
    assert.equal(toDatetimeLocalValue("2026-10-03T15:30:00+00:00"), "2026-10-03T10:30");
  });

  test("handles the Z suffix and crossing midnight", () => {
    assert.equal(toDatetimeLocalValue("2026-10-03T02:00:00Z"), "2026-10-02T21:00");
  });

  test("is empty for null, empty and invalid input", () => {
    assert.equal(toDatetimeLocalValue(null), "");
    assert.equal(toDatetimeLocalValue(""), "");
    assert.equal(toDatetimeLocalValue("not a date"), "");
  });
});

describe("fromDatetimeLocalValue", () => {
  test("reads the picker value as the viewer's local time and returns UTC", () => {
    assert.equal(fromDatetimeLocalValue("2026-10-03T10:30"), "2026-10-03T15:30:00.000Z");
  });

  test("uses standard time offsets outside DST", () => {
    // CST is UTC-6.
    assert.equal(fromDatetimeLocalValue("2026-12-01T09:00"), "2026-12-01T15:00:00.000Z");
  });

  test("is empty when the picker is cleared, so the schedule is cleared", () => {
    assert.equal(fromDatetimeLocalValue(""), "");
    assert.equal(fromDatetimeLocalValue(null), "");
  });

  test("round-trips through the picker without drifting", () => {
    const iso = "2026-10-03T15:30:00.000Z";
    assert.equal(fromDatetimeLocalValue(toDatetimeLocalValue(iso)), iso);
  });
});

describe("formatLocalDateTime", () => {
  test("is empty for unset input", () => {
    assert.equal(formatLocalDateTime(null), "");
  });

  test("renders in the viewer's zone", () => {
    assert.match(formatLocalDateTime("2026-10-03T15:30:00Z"), /10:30/);
  });
});
