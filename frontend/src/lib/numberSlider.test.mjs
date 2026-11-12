import assert from "node:assert/strict";
import { test } from "node:test";

import { boxText, sliderState, sliderStep, meterState, sliderWanted } from "./numberSlider.ts";

test("the thumb stands where the box says, and a box with nothing in it is not set", () => {
  assert.deepEqual(sliderState("0.25", 0, 1, 0.5), { set: true, position: 0.25 });
  assert.deepEqual(sliderState("0", 0, 1, 0.5), { set: true, position: 0 }, "0 is a value (silence), not empty");
  assert.deepEqual(sliderState("", 0, 1, 0.5), { set: false, position: 0.5 });
  assert.deepEqual(sliderState(null, 0, 1, 0.5), { set: false, position: 0.5 });
  assert.deepEqual(sliderState("abc", 0, 1, 0.5), { set: false, position: 0.5 });
});

test("a value outside the ends puts the thumb at the end, and the rest position is kept inside them", () => {
  assert.deepEqual(sliderState("7", 0, 1, 0.5), { set: true, position: 1 });
  assert.deepEqual(sliderState("-3", 0, 1, 0.5), { set: true, position: 0 });
  assert.deepEqual(sliderState("", 0, 1, 9), { set: false, position: 1 });
});

test("dragging writes a tidy number into the box, to the field's step", () => {
  assert.equal(boxText(0.30000000000000004, 0.01), "0.3");
  assert.equal(boxText(0.123, 0.01), "0.12");
  assert.equal(boxText(0.1234, 0.001), "0.123");
  assert.equal(boxText(7, 1), "7");
  assert.equal(boxText(2.5, 0.5), "2.5");
});

test("the slider moves in the field's step, else a hundredth of its range", () => {
  assert.equal(sliderStep(0.05, 0, 1), 0.05);
  assert.equal(sliderStep(undefined, 0, 1), 0.01);
  assert.equal(sliderStep(null, 0, 30), 0.3);
  assert.equal(sliderStep(0, 0, 10), 0.1);
});

test("a meter fills from the low end to the high end, goes amber near the top and red at it, and is empty when nothing was measured", () => {
  assert.deepEqual(meterState(-30, -60, 0), { has: true, position: 0.5, zone: "ok" });
  assert.equal(meterState(-9, -60, 0).zone, "warn"); // 0.85 of the way
  assert.equal(meterState(-1, -60, 0).zone, "hot");
  assert.equal(meterState(-90, -60, 0).position, 0); // below the floor draws nothing more than the floor
  assert.equal(meterState(6, -60, 0).position, 1); // above the top is the top
  for (const none of [undefined, null, "", "abc"]) assert.equal(meterState(none, -60, 0).has, false);
  assert.equal(meterState(0, -60, 0).has, true); // a measured zero is a reading
  assert.equal(meterState(1, 5, 5).has, false); // no range, no meter
});

test("a number field with both ends gets a slider by itself; one end, none, a read-only value or a meter does not; false opts out and true insists", () => {
  assert.equal(sliderWanted({ min: 0, max: 30 }), true); // not asked for: it can go from 0 to 30, so it can be dragged
  assert.equal(sliderWanted({ min: 0.5, max: 30, slider: null }), true);
  assert.equal(sliderWanted({ min: -60, max: 0 }), true); // a lower end below zero is still a range
  for (const none of [{}, { min: 0 }, { max: 1 }, { min: 1, max: 1 }, { min: 2, max: 1 }, { min: Number.NaN, max: 1 }]) assert.equal(sliderWanted(none), false);
  assert.equal(sliderWanted({ min: 0, max: 1, slider: false }), false); // opted out
  assert.equal(sliderWanted({ min: 0, max: 1, readOnly: true }), false); // nothing to drag
  assert.equal(sliderWanted({ min: -60, max: 0, meter: true, readOnly: true }), false); // the meter is the picture
  assert.equal(sliderWanted({ min: 0, max: 1, readOnly: true, slider: true }), true); // asked for, so shown (dimmed)
  assert.equal(sliderWanted({ slider: true }), false); // asked for but no ends: nothing to draw
});
