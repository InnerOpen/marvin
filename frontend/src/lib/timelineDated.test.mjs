import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_PER_ROWS, layout, perRows } from "./timeline.ts";

const row = (slug, data, title = slug) => ({ id: `id-${slug}`, slug, title, dataJson: data });
const wall = (y, mo, d, h = 0) => Date.UTC(y, mo - 1, d, h);

const calendar = {
  kind: "timeline",
  title: "Team calendar",
  unit: "days",
  entry_type: "cal",
  range: { from: "from", to: "to" },
  spine: { entry_type: "milestone", of: "cal", start: "date", status: "status", seconds: { hold: "days", defaults: { hold: 1 } } },
  lanes: [
    { id: "notes", title: "Notes", entry_type: "note", of: "cal", in: "milestone" },
    { id: "work", title: "Work", entry_type: "task", of: "cal", start: "start", seconds: "days", status: "status", per: "assignee", per_order: "order" },
  ],
};
const kinds = { milestone: { date: "date" }, task: { start: "date" }, cal: { from: "date", to: "date" } };

const calendarRows = (entry = { from: "2026-11-16", to: "2026-12-13" }) => ({
  entry: row("cal", entry),
  spine: [
    row("kickoff", { cal: "cal", date: "2026-11-17", days: 1 }),
    row("design", { cal: "cal", date: "2026-11-18", days: 3 }), // overlaps the review
    row("review", { cal: "cal", date: "2026-11-19", days: 2 }),
    row("launch", { cal: "cal", date: "2026-12-01T00:00:00Z", days: 1 }), // after a gap; a date field saved with a zone
    row("someday", { cal: "cal" }),
  ],
  lanes: {
    notes: [row("n1", { cal: "cal", milestone: "design" })],
    work: [
      row("t1", { cal: "cal", start: "2026-11-16", days: 2, assignee: "ada" }),
      row("t2", { cal: "cal", start: "2026-11-17", days: 3, assignee: "ben" }),
      row("t3", { cal: "cal", start: "2026-11-17", assignee: "ada" }), // no length: one day
      row("t4", { cal: "cal", start: "2026-12-10", days: 2 }), // nobody yet
      row("t5", { cal: "cal", assignee: "ben" }), // no date
    ],
  },
  per: { work: [row("ada", { order: 2 }, "Ada Brooks"), row("ben", { order: 1 }, "Ben Ito")] },
  kinds,
  timeZone: "America/Los_Angeles",
});

test("items placed by date sit at their own day, with empty time between and on top of each other where they overlap", () => {
  const laid = layout(calendar, calendarRows());
  assert.equal(laid.dates.origin, wall(2026, 11, 16), "the range starts at the entry's `from`");
  assert.deepEqual(
    laid.items.map((i) => [i.slug, i.start, i.seconds]),
    [
      ["kickoff", 1, 1],
      ["design", 2, 3],
      ["review", 3, 2],
      ["launch", 15, 1],
    ],
  );
  assert.deepEqual(
    laid.items.map((i) => i.onScreen),
    laid.items.map((i) => ({ start: i.start, seconds: i.seconds })),
    "the pictures are where the items are: nothing is cut between them",
  );
  assert.equal(laid.total, 28, "to the end of the entry's `to` (13 December, a whole day)");
  assert.equal(laid.dates.zoned, false, "a date field is read by its day, even saved with a zone");
});

test("what has no date is listed apart, the items and the lane entries alike, never dropped", () => {
  const laid = layout(calendar, calendarRows());
  assert.deepEqual(laid.dates.undated, [
    { id: "id-someday", slug: "someday", title: "someday", lane: null },
    { id: "id-t5", slug: "t5", title: "t5", lane: "work" },
  ]);
  assert.ok(!laid.items.some((i) => i.slug === "someday"));
});

test("a lane with `start` places its pieces at their own dates, for their own length (a day when none); an `in` lane follows its item", () => {
  const laid = layout(calendar, calendarRows());
  assert.deepEqual(
    laid.dates.lanes.work.map((p) => [p.slug, p.start, p.seconds, p.per]),
    [
      ["t1", 0, 2, "ada"],
      ["t2", 1, 3, "ben"],
      ["t3", 1, 1, "ada"],
      ["t4", 24, 2, ""],
    ],
  );
  const design = laid.items.find((i) => i.slug === "design");
  assert.deepEqual(design.lanes.notes.map((p) => [p.start, p.seconds, p.spans]), [[2, 3, true]]);
});

test("the range is what is drawn when the entry sets none, rounded out to whole days", () => {
  const laid = layout(calendar, calendarRows({}));
  assert.equal(laid.dates.origin, wall(2026, 11, 16), "the first task starts on the 16th");
  assert.equal(laid.total, 26, "the last task ends with the 11th of December");
  const widened = layout(calendar, calendarRows({ from: "2026-11-09", to: "2026-12-20" }));
  assert.equal(widened.dates.origin, wall(2026, 11, 9));
  assert.equal(widened.items[0].start, 8);
  assert.equal(widened.total, 42);
});

test("with nothing dated there is nothing to draw, and everything is in the tray", () => {
  const rows = calendarRows({});
  rows.spine = [row("someday", { cal: "cal" })];
  rows.lanes.work = [row("t5", { cal: "cal" })];
  const laid = layout(calendar, rows);
  assert.equal(laid.items.length, 0);
  assert.equal(laid.total, 0);
  assert.equal(laid.dates.undated.length, 2);
});

test("a lane drawn per a field: one row per value, by the named entry's order, then title, and the pieces with none last", () => {
  const laid = layout(calendar, calendarRows());
  assert.deepEqual(laid.per.work, {
    rows: [
      { key: "ben", title: "Ben Ito", id: "id-ben" },
      { key: "ada", title: "Ada Brooks", id: "id-ada" },
      { key: "", title: "No assignee", id: null },
    ],
    hidden: 0,
  });
  // without per_order, by title; a value that names no entry (a select's value, a person since deleted) is its own title
  const lane = { ...calendar.lanes[1], per_order: undefined };
  const pieces = ["zoe", "ada", "Room 2", "Room 10", "ada"].map((per) => ({ per }));
  assert.deepEqual(
    perRows(lane, pieces, [row("ada", {}, "Ada Brooks")]).rows.map((r) => r.title),
    ["Ada Brooks", "Room 2", "Room 10", "zoe"],
  );
});

test("a lane drawn per a field shows at most MAX_PER_ROWS rows and counts the rest", () => {
  const lane = { id: "work", per: "assignee" };
  const pieces = Array.from({ length: MAX_PER_ROWS + 5 }, (_, i) => ({ per: `p${String(i).padStart(2, "0")}` }));
  const { rows, hidden } = perRows(lane, pieces, []);
  assert.equal(rows.length, MAX_PER_ROWS);
  assert.equal(hidden, 5);
});

const roster = {
  kind: "timeline",
  title: "Shift roster",
  unit: "hours",
  entry_type: "roster",
  spine: { entry_type: "day", of: "roster", start: "date", seconds: { hold: "hours", defaults: { hold: 24 } } },
  lanes: [{ id: "shifts", title: "Shifts", entry_type: "shift", of: "roster", start: "start", seconds: "hours", who: "role", per: "person" }],
};

test("a roster in hours over the night the clocks go forward: days stay one day each; a shift with a zone runs its real hours", () => {
  const rows = {
    entry: row("roster", {}),
    spine: ["2026-03-07", "2026-03-08", "2026-03-09"].map((date, i) => row(`d${i}`, { roster: "roster", date })),
    lanes: {
      shifts: [
        row("night", { roster: "roster", start: "2026-03-08T03:00:00Z", hours: 8, person: "ada" }), // 22:00 EST the 7th
        row("early", { roster: "roster", start: "2026-03-08T06:00", hours: 8, person: "ben" }), // as written on the form
      ],
    },
    kinds: { day: { date: "date" }, shift: { start: "datetime" } },
    timeZone: "America/New_York",
  };
  const laid = layout(roster, rows);
  assert.deepEqual(
    laid.items.map((i) => [i.start, i.seconds]),
    [
      [0, 24],
      [24, 24],
      [48, 24],
    ],
  );
  assert.deepEqual(
    laid.dates.lanes.shifts.map((p) => [p.slug, p.start, p.seconds]),
    [
      ["night", 22, 9], // 22:00 to 07:00: eight hours, one of them skipped by the clocks
      ["early", 30, 8],
    ],
  );
  assert.equal(laid.dates.zoned, true);
  assert.equal(laid.total, 72);
});
