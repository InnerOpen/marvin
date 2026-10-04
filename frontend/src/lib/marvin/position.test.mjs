// Where the Marvin bubble rests (position.ts). Run with `npm test` — plain `node --test`, which
// strips position.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { clampSpot, DEFAULT_SPOT, EDGE_GUTTER, parseSpot, spotFromRect } from "./position.ts";

const BOX = { width: 52, height: 52 };
const PHONE = { width: 375, height: 812 };
const DESKTOP = { width: 1280, height: 800 };

describe("parseSpot", () => {
  test("test_parse_spot_with_nothing_stored_returns_bottom_left_default", () => {
    assert.deepEqual(parseSpot(null, BOX, PHONE), DEFAULT_SPOT);
  });

  test("test_parse_spot_with_garbage_returns_default", () => {
    assert.deepEqual(parseSpot({ x: "middle", dx: "far" }, BOX, PHONE), DEFAULT_SPOT);
  });

  test("test_parse_spot_with_current_shape_keeps_it", () => {
    const spot = { x: "right", dx: 40, y: "top", dy: 120 };
    assert.deepEqual(parseSpot(spot, BOX, PHONE), spot);
  });

  test("test_parse_spot_with_legacy_off_screen_left_top_pulls_it_into_the_nearest_corner", () => {
    // Saved on a big monitor (or as page coordinates): far outside a phone's viewport.
    assert.deepEqual(parseSpot({ left: 1500, top: 2400 }, BOX, PHONE), {
      x: "right",
      dx: EDGE_GUTTER,
      y: "bottom",
      dy: EDGE_GUTTER,
    });
  });

  test("test_parse_spot_with_legacy_on_screen_left_top_anchors_to_nearest_edges", () => {
    // 100px from the left and 600px down a 800px window: nearer the left and the bottom.
    assert.deepEqual(parseSpot({ left: 100, top: 600 }, BOX, DESKTOP), { x: "left", dx: 100, y: "bottom", dy: 148 });
  });
});

describe("spotFromRect", () => {
  test("test_spot_from_rect_near_top_right_anchors_right_and_top", () => {
    assert.deepEqual(spotFromRect(1180, 40, BOX, DESKTOP), { x: "right", dx: 48, y: "top", dy: 40 });
  });

  test("test_spot_from_rect_past_the_edge_clamps_to_the_gutter", () => {
    assert.deepEqual(spotFromRect(-30, 790, BOX, PHONE), { x: "left", dx: EDGE_GUTTER, y: "bottom", dy: EDGE_GUTTER });
  });
});

describe("clampSpot", () => {
  test("test_clamp_spot_on_a_smaller_viewport_keeps_the_bubble_on_screen", () => {
    const clamped = clampSpot({ x: "right", dx: 900, y: "top", dy: 700 }, BOX, PHONE);
    assert.deepEqual(clamped, { x: "right", dx: PHONE.width - BOX.width - EDGE_GUTTER, y: "top", dy: 700 });
  });

  test("test_clamp_spot_with_viewport_smaller_than_bubble_falls_back_to_the_gutter", () => {
    assert.deepEqual(clampSpot(DEFAULT_SPOT, BOX, { width: 60, height: 60 }), DEFAULT_SPOT);
  });
});
