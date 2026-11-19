import assert from "node:assert/strict";
import { test } from "node:test";
import { ZOOM_LEVELS, stackRows } from "./timeline.ts";
import { dateRange, dateTicks, dayLabelPx, edgesOf, localeOf, momentOf, monthSpans, nowMark, placeOf, rangeEnd, wallEnd, wallIn } from "./timelineDates.ts";
import { dateWords } from "./timelineUnits.ts";

const wall = (y, mo, d, h = 0, mi = 0) => Date.UTC(y, mo - 1, d, h, mi);

test("a plain date is that day in every zone: no zone moves it to the day before or after", () => {
  for (const zone of ["UTC", "America/Los_Angeles", "Pacific/Auckland", "Asia/Kolkata"]) {
    assert.deepEqual(momentOf("2026-11-19", "date", zone), { wall: wall(2026, 11, 19), day: true, zoned: false });
    assert.deepEqual(momentOf("2026-11-19", undefined, zone), { wall: wall(2026, 11, 19), day: true, zoned: false });
  }
});

test("a date field saved with a time and a zone is still read by its day: midnight UTC is not the evening before in Los Angeles", () => {
  assert.equal(momentOf("2026-11-19T00:00:00Z", "date", "America/Los_Angeles").wall, wall(2026, 11, 19));
  assert.equal(momentOf("2026-11-19T23:30:00-08:00", "date", "Pacific/Auckland").wall, wall(2026, 11, 19));
  // a datetime field holding the same text is a real moment, shown in the viewer's zone
  const evening = momentOf("2026-11-19T02:00:00Z", "datetime", "America/Los_Angeles");
  assert.equal(evening.wall, wall(2026, 11, 18, 18));
  assert.equal(evening.zoned, true);
  assert.equal(momentOf("2026-11-19T02:00:00Z", "datetime", "Pacific/Auckland").wall, wall(2026, 11, 19, 15));
  assert.equal(momentOf("2026-11-19T09:00+05:30", undefined, "UTC").wall, wall(2026, 11, 19, 3, 30));
});

test("a datetime without a zone (what the entry form saves) is that time on the wall, wherever it is looked at", () => {
  for (const zone of ["UTC", "America/New_York", "Pacific/Auckland"]) {
    assert.deepEqual(momentOf("2026-11-19T14:00", "datetime", zone), { wall: wall(2026, 11, 19, 14), day: false, zoned: false });
    assert.equal(momentOf("2026-11-19 14:00:30.5", "datetime", zone).wall, wall(2026, 11, 19, 14) + 30_500);
  }
});

test("what is not a date is no place: it goes to the tray", () => {
  for (const v of ["", "soon", "2026-02-30", "2026-11-19T25:00", "19/11/2026", 20261119, null, undefined, { at: "2026-11-19" }]) {
    assert.equal(momentOf(v, undefined, "UTC"), null, String(v));
  }
});

test("a zone the runtime does not know reads as UTC instead of failing", () => {
  assert.equal(wallIn(wall(2026, 11, 19, 12), "Mars/Olympus"), wall(2026, 11, 19, 12));
});

test("the night the clocks go forward: a zoned shift runs its real hours and ends when the clock says; a day on the calendar stays one day", () => {
  const ny = "America/New_York"; // 8 March 2026, 2:00 → 3:00
  const zoned = momentOf("2026-03-08T05:00:00Z", "datetime", ny); // midnight, EST
  assert.equal(zoned.wall, wall(2026, 3, 8, 0));
  assert.equal(wallEnd(zoned, 8, "hours", ny), wall(2026, 3, 8, 9), "8 real hours from midnight end at 09:00 EDT");
  const written = momentOf("2026-03-08T00:00", "datetime", ny);
  assert.equal(wallEnd(written, 8, "hours", ny), wall(2026, 3, 8, 8), "a time as written runs on the wall");
  const day = momentOf("2026-03-08", "date", ny);
  assert.equal(wallEnd(day, 24, "hours", ny), wall(2026, 3, 9), "a roster day of 24 hours is that one day: no overlap with the next");
  assert.equal(wallEnd(day, 1, "days", ny), wall(2026, 3, 9));
  assert.equal(wallEnd(zoned, 1, "days", ny), wall(2026, 3, 9), "days are counted on the calendar");
});

test("the night the clocks go back: a zoned shift of 8 hours from midnight ends at 07:00", () => {
  const ny = "America/New_York"; // 1 November 2026, 2:00 → 1:00
  const zoned = momentOf("2026-11-01T04:00:00Z", "datetime", ny);
  assert.equal(zoned.wall, wall(2026, 11, 1, 0));
  assert.equal(wallEnd(zoned, 8, "hours", ny), wall(2026, 11, 1, 7));
});

test("the range runs from the first start to the last end, rounded out, and widened by the entry's own from and to", () => {
  const spans = [
    { start: wall(2026, 11, 18, 9), end: wall(2026, 11, 19, 9) },
    { start: wall(2026, 11, 23), end: wall(2026, 11, 25) },
  ];
  assert.deepEqual(dateRange(spans, "days"), { origin: wall(2026, 11, 18), end: wall(2026, 11, 25) });
  assert.deepEqual(dateRange(spans, "hours"), { origin: wall(2026, 11, 18, 9), end: wall(2026, 11, 25) });
  assert.deepEqual(dateRange([{ start: wall(2026, 11, 18, 9, 5), end: wall(2026, 11, 18, 17, 20) }], "minutes"), { origin: wall(2026, 11, 18, 9), end: wall(2026, 11, 18, 17, 30) });
  // an empty week still shows: the entry's from and to (a plain date `to` is that whole day)
  const to = rangeEnd(momentOf("2026-11-29", "date", "UTC"));
  assert.deepEqual(dateRange(spans, "days", { from: wall(2026, 11, 16), to }), { origin: wall(2026, 11, 16), end: wall(2026, 11, 30) });
  assert.deepEqual(dateRange([], "days", { from: wall(2026, 11, 16), to }), { origin: wall(2026, 11, 16), end: wall(2026, 11, 30) });
  assert.deepEqual(dateRange([], "days", { from: wall(2026, 11, 16) }), { origin: wall(2026, 11, 16), end: wall(2026, 11, 17) }, "at least one unit");
  assert.equal(dateRange([], "days"), null);
  assert.equal(placeOf(wall(2026, 11, 23), wall(2026, 11, 16), "days"), 7);
  assert.equal(placeOf(wall(2026, 11, 16, 13, 30), wall(2026, 11, 16), "hours"), 13.5);
});

test("things that overlap stack on the fewest rows; a gap is room for the next on the same row", () => {
  const origin = wall(2026, 11, 16);
  const at = (d, days) => ({ start: placeOf(wall(2026, 11, d), origin, "days"), seconds: days });
  // 16-18, 17-19 (overlaps), 23-24 (after a gap), 23-26 (overlaps the last), 25 (fits under the third)
  const rows = stackRows([at(16, 3), at(17, 3), at(23, 1), at(23, 4), at(25, 1)], 0);
  assert.deepEqual(rows, [0, 1, 1, 0, 1]);
  assert.equal(Math.max(...rows) + 1, 2);
});

test("a ruler in days: a mark for each day when there is room, the Mondays when not; month and week starts are marked", () => {
  const range = { origin: wall(2026, 11, 16), end: wall(2026, 12, 14) }; // four weeks from a Monday
  const { major, minor } = dateTicks(range, "days", 10, ZOOM_LEVELS, "en-GB");
  const at = (level) => major.filter((m) => m.levels.includes(level));
  assert.deepEqual(at(1).map((m) => m.label), ["Mon 16 Nov", "Mon 23 Nov", "Mon 30 Nov", "Mon 7 Dec"]);
  assert.equal(at(4).length, 28, "a day each at 4×");
  assert.deepEqual(at(4).slice(0, 3).map((m) => [m.t, m.label]), [[0, "Mon 16 Nov"], [1, "Tue 17 Nov"], [2, "Wed 18 Nov"]]);
  assert.equal(major.find((m) => m.label === "Tue 1 Dec").edge, "month");
  assert.equal(major.find((m) => m.label === "Mon 23 Nov").edge, "week");
  assert.equal(major.find((m) => m.label === "Wed 18 Nov").edge, null);
  assert.ok(minor.some((m) => m.t === 1 && m.levels.includes(1)), "the days between the Mondays, unnumbered");
  assert.ok(!minor.some((m) => m.levels.includes(4) && at(4).some((x) => x.t === m.t)), "never a minor mark under a numbered one");
});

test("the right day under a date across a change of the clocks: every mark of a day ruler is a whole day", () => {
  const range = { origin: wall(2026, 3, 2), end: wall(2026, 3, 16) };
  const days = dateTicks(range, "days", 10, [8], "en-GB").major;
  assert.deepEqual(days.map((m) => m.t), [...Array(14).keys()]);
  assert.equal(days[6].label, "Sun 8 Mar");
});

test("a ruler in hours: a midnight reads its day, the marks between their time", () => {
  const range = { origin: wall(2026, 11, 16), end: wall(2026, 11, 23) }; // a week
  const { major } = dateTicks(range, "hours", 10, ZOOM_LEVELS, "en-GB");
  const at = (level) => major.filter((m) => m.levels.includes(level));
  assert.deepEqual(at(1).map((m) => m.label).slice(0, 3), ["Mon 16 Nov", "Tue 17 Nov", "Wed 18 Nov"]);
  assert.equal(at(1)[1].t, 24);
  assert.equal(at(1)[1].edge, "day");
  assert.deepEqual(at(4).slice(0, 3).map((m) => m.label), ["Mon 16 Nov", "06:00", "12:00"]);
  const us = dateTicks(range, "hours", 10, [4], "en-US").major;
  assert.equal(us[0].label, "Mon, Nov 16", "in the viewer's locale");
  assert.equal(us[1].label, "06:00 AM");
});

test("the months a day view runs over, named", () => {
  const range = { origin: wall(2026, 11, 16), end: wall(2026, 12, 14) };
  assert.deepEqual(monthSpans(range, "days", "en-GB"), [
    { start: 0, seconds: 15, label: "November 2026" },
    { start: 15, seconds: 13, label: "December 2026" },
  ]);
});

test("today is its whole day in a day view and the moment in an hour view; outside the range there is none", () => {
  const range = { origin: wall(2026, 11, 16), end: wall(2026, 11, 23) };
  assert.deepEqual(nowMark(range, "days", wall(2026, 11, 19, 15, 30)), { start: 3, seconds: 1 });
  assert.deepEqual(nowMark(range, "hours", wall(2026, 11, 19, 15, 30)), { start: 3 * 24 + 15.5, seconds: 0 });
  assert.equal(nowMark(range, "days", wall(2026, 11, 23)), null);
  assert.equal(nowMark(range, "days", wall(2026, 11, 15, 23)), null);
});

test("a place reads as its date (and time), an end in days as the last day it covers", () => {
  const days = dateWords("days", wall(2026, 11, 16), "en-GB");
  assert.equal(days.position(0), "Mon 16 Nov");
  assert.equal(days.position(2.5), "Wed 18 Nov, 12:00");
  assert.equal(days.until(3), "Wed 18 Nov", "three days from Monday end with Wednesday");
  assert.equal(days.length(3), "3 days");
  assert.equal(days.range(28), "16 Nov 2026 – 13 Dec 2026");
  assert.equal(days.parse("2026-11-19"), 3);
  assert.equal(days.parse("Day 3"), 2, "a place counted from the start still works");
  const hours = dateWords("hours", wall(2026, 11, 16), "en-GB");
  assert.equal(hours.position(24 + 6), "Tue 17 Nov, 06:00");
  assert.equal(hours.until(30), "Tue 17 Nov, 06:00");
  assert.equal(hours.range(168), "16 Nov 2026 – 22 Nov 2026");
  assert.equal(hours.parse("2026-11-17 06:00"), 30);
  assert.equal(hours.length(7.5), "7 h 30 min");
});

test("the lines down the view: a month's and a Monday's start in days, every midnight in hours", () => {
  const range = { origin: wall(2026, 11, 16), end: wall(2026, 12, 14) };
  assert.deepEqual(edgesOf(range, "days"), [
    { t: 7, edge: "week" },
    { t: 14, edge: "week" },
    { t: 15, edge: "month" },
    { t: 21, edge: "week" },
  ]);
  assert.deepEqual(edgesOf({ origin: wall(2026, 11, 16), end: wall(2026, 11, 18) }, "hours"), [{ t: 24, edge: "day" }]);
  assert.deepEqual(edgesOf({ origin: wall(2026, 11, 16, 9), end: wall(2026, 11, 16, 17) }, "minutes"), []);
});

test("a day's label takes the room its locale writes it in", () => {
  const november = { origin: wall(2026, 11, 16), end: wall(2026, 12, 14) };
  assert.equal(dayLabelPx(november, "en-GB"), Math.ceil("Sat 28 Nov".length * 6.2 + 10), "72 px: a day of the narrowest strip has its label");
  assert.equal(dayLabelPx(november, "en-US"), Math.ceil("Sat, Nov 28".length * 6.2 + 10));
  assert.equal(dayLabelPx({ origin: wall(2026, 9, 1), end: wall(2026, 9, 30) }, "en-GB"), Math.ceil("Mon 28 Sept".length * 6.2 + 10), "British English writes Sept");
});

test("the viewer's language from Accept-Language: the first tag when it is one, else the runtime's own (never an error)", () => {
  assert.equal(localeOf("en-GB,en;q=0.9"), "en-GB");
  assert.equal(localeOf("de-DE;q=0.8"), "de-DE");
  for (const header of ["*", "en_US", "", null, undefined, ";q=1", "!!"]) assert.equal(localeOf(header), undefined, String(header));
});

test("a ruler in minutes: the hours, finer as it is zoomed, and the day at midnight", () => {
  const range = { origin: wall(2026, 11, 19, 21), end: wall(2026, 11, 20, 3) }; // six hours over midnight
  const { major } = dateTicks(range, "minutes", 10, ZOOM_LEVELS, "en-GB");
  const at = (level) => major.filter((m) => m.levels.includes(level));
  assert.deepEqual(at(1).map((m) => m.label), ["21:00", "22:00", "23:00", "Fri 20 Nov", "01:00", "02:00"]);
  assert.deepEqual(at(1).map((m) => m.t), [0, 60, 120, 180, 240, 300]);
  assert.equal(at(1)[3].edge, "day");
  assert.equal(at(1)[3].day, true);
  assert.equal(at(4)[1].label, "21:10", "every ten minutes at 4×");
});
