import assert from "node:assert/strict";
import { test } from "node:test";
import { timecode } from "./audioTimeline.ts";
import { PLAIN_DEFAULTS, TICK_STEPS, clockText, layout, minorTickLevels, parseClock, tickLevels, ticks, unitOf } from "./timeline.ts";
import { UNIT_STEPS, lengthText, parseLength, positionText, timeWords } from "./timelineUnits.ts";

const SWEEP = [0, 0.004, 0.05, 0.3, 1, 4, 12.345, 59.95, 60, 83.456, 599.99, 3600, 3723.5, 7261.25];

test("a view that names no unit is in seconds, and so is one with a unit this page does not know", () => {
  assert.equal(unitOf({}), "seconds");
  assert.equal(unitOf(null), "seconds");
  assert.equal(unitOf({ unit: "fortnights" }), "seconds");
  assert.equal(unitOf({ unit: "days" }), "days");
});

test("seconds writes time exactly as the Timeline always has: the same functions, the same text, the same ruler", () => {
  const w = timeWords("seconds");
  assert.equal(w.position, timecode);
  assert.equal(w.total, timecode);
  assert.equal(w.clock, clockText);
  assert.equal(w.parse, parseClock);
  assert.equal(w.steps, TICK_STEPS);
  assert.deepEqual(w.nudge, [0.1, 1]);
  for (const t of SWEEP) {
    assert.equal(w.length(t), `${t.toFixed(1)} s`);
    assert.equal(w.short(t), `${t.toFixed(1)}s`);
    assert.equal(w.offset(t), `${t.toFixed(3)} s`);
    for (const want of [3, 10, 37]) {
      assert.deepEqual(tickLevels(t, want, w.steps), tickLevels(t, want));
      assert.deepEqual(minorTickLevels(t, want, w.steps), minorTickLevels(t, want));
      assert.deepEqual(ticks(t, want, w.steps), ticks(t, want));
    }
  }
});

test("a length in minutes or hours: at most two parts, never one skipped between them", () => {
  assert.equal(lengthText(45, "minutes"), "45 min");
  assert.equal(lengthText(90, "minutes"), "1 h 30 min");
  assert.equal(lengthText(120, "minutes"), "2 h");
  assert.equal(lengthText(0.5, "minutes"), "30 s");
  assert.equal(lengthText(1445, "minutes"), "1 d", "a day and five minutes is not 1 d 5 min");
  assert.equal(lengthText(0, "minutes"), "0 min");
  assert.equal(lengthText(-15, "minutes"), "−15 min");
  assert.equal(lengthText(3, "hours"), "3 h");
  assert.equal(lengthText(28, "hours"), "1 d 4 h");
  assert.equal(lengthText(1.5, "hours"), "1 h 30 min");
  assert.equal(lengthText(0, "hours"), "0 h");
});

test("a length in days says days, and weeks once it is long", () => {
  assert.equal(lengthText(1, "days"), "1 day");
  assert.equal(lengthText(3, "days"), "3 days");
  assert.equal(lengthText(1.25, "days"), "1 day 6 h");
  assert.equal(lengthText(7, "days"), "1 week");
  assert.equal(lengthText(14, "days"), "2 weeks");
  assert.equal(lengthText(17, "days"), "2 weeks 3 days");
  assert.equal(lengthText(0, "days"), "0 days");
});

test("a position: the time from the start, or in days the day it falls on, the first being Day 1", () => {
  assert.equal(positionText(0, "minutes"), "0 min");
  assert.equal(positionText(150, "minutes"), "2 h 30 min");
  assert.equal(positionText(26, "hours"), "1 d 2 h");
  assert.equal(positionText(0, "days"), "Day 1");
  assert.equal(positionText(2, "days"), "Day 3");
  assert.equal(positionText(2.25, "days"), "Day 3, 6 h");
  assert.equal(positionText(2.99999, "days"), "Day 4", "rounding carries into the next day");
});

test("what is typed into the clock of a plan, read in its unit", () => {
  assert.equal(parseLength("90", "minutes"), 90);
  assert.equal(parseLength("1 h 30 min", "minutes"), 90);
  assert.equal(parseLength("1:30", "minutes"), 90);
  assert.equal(parseLength("1:30", "hours"), 1.5);
  assert.equal(parseLength("45m", "minutes"), 45);
  assert.equal(parseLength("2,5 h", "minutes"), 150);
  assert.equal(parseLength("Day 3", "days"), 2);
  assert.equal(parseLength("day 3, 6 h", "days"), 2.25);
  assert.equal(parseLength("2 weeks 3 days", "days"), 17);
  assert.equal(parseLength("1 d 4 h", "hours"), 28);
  assert.equal(parseLength("", "minutes"), null);
  assert.equal(parseLength("soon", "minutes"), null);
  assert.equal(parseLength("1h30", "minutes"), null);
  assert.equal(parseLength("Day 0", "days"), null);
  assert.equal(parseLength("1:30", "days"), null);
  const w = timeWords("days");
  assert.equal(w.parse(w.clock(9)), 9, "the clock reads back what it shows");
});

test("the ruler of a plan steps in round numbers of its unit", () => {
  assert.deepEqual(ticks(480, 10, UNIT_STEPS.minutes), [0, 60, 120, 180, 240, 300, 360, 420, 480]);
  assert.deepEqual(ticks(14, 10, UNIT_STEPS.days), [0, 2, 4, 6, 8, 10, 12, 14]);
  assert.deepEqual(ticks(84, 10, UNIT_STEPS.days), [0, 14, 28, 42, 56, 70, 84]);
  assert.deepEqual(ticks(40, 10, UNIT_STEPS.hours), [0, 6, 12, 18, 24, 30, 36]);
  const levels = tickLevels(14, 10, UNIT_STEPS.days);
  assert.deepEqual(levels.find((x) => x.t === 1).levels, [2, 4, 8], "every day once zoomed in");
  const minor = minorTickLevels(14, 10, UNIT_STEPS.days);
  assert.deepEqual(minor.find((x) => x.t === 1).levels, [1], "a mark on each day between the numbered ones");
  const w = timeWords("days");
  assert.deepEqual(ticks(14, 10, w.steps).map(w.position), ["Day 1", "Day 3", "Day 5", "Day 7", "Day 9", "Day 11", "Day 13", "Day 15"]);
});

const row = (slug, data) => ({ id: `id-${slug}`, slug, title: slug, dataJson: data });
const plan = (unit) => ({
  kind: "timeline",
  title: "Plan",
  unit,
  entry_type: "plan",
  spine: { entry_type: "day", of: "plan", order: "number", seconds: { hold: "days" } },
  lanes: [{ id: "posts", title: "Posts", entry_type: "post", of: "plan", in: "day", who: "channel", seconds: "length" }],
});
const rows = {
  entry: row("p", {}),
  spine: [row("d1", { plan: "p", number: 1 }), row("d2", { plan: "p", number: 2, days: 2 })],
  lanes: { posts: [row("a", { plan: "p", day: "d1" }), row("b", { plan: "p", day: "d1" }), row("c", { plan: "p", day: "d2", length: 0.5 })] },
};

test("a plan holds one unit by default, with none of the render's pauses around its pieces", () => {
  const laid = layout(plan("days"), rows);
  assert.deepEqual(PLAIN_DEFAULTS, { hold: 1, lead: 0, gap: 0, tail: 0 });
  assert.deepEqual(
    laid.items.map((i) => [i.slug, i.start, i.seconds]),
    [
      ["d1", 0, 1],
      ["d2", 1, 2],
    ],
  );
  const timed = laid.items[1].lanes.posts[0];
  assert.deepEqual([timed.start, timed.seconds], [1, 0.5], "a piece with a length starts with its item: no lead");
});

test("in a plan, a piece with no length of its own spans its item; in seconds it stays a sliver at the item's start", () => {
  const days = layout(plan("days"), rows).items[0].lanes.posts;
  assert.deepEqual(
    days.map((p) => [p.slug, p.start, p.seconds]),
    [
      ["a", 0, 1],
      ["b", 0, 1],
    ],
  );
  assert.ok(days.every((p) => p.spans), "marked, so the page draws it as wide as its card");
  const seconds = layout(plan(undefined), rows);
  assert.equal(seconds.items[0].seconds, 4, "the render's default hold");
  assert.deepEqual(
    seconds.items[0].lanes.posts.map((p) => [p.start, p.seconds]),
    [
      [0.3, 0],
      [0.3, 0],
    ],
  );
  assert.ok(seconds.items[0].lanes.posts.every((p) => !p.spans));
});
