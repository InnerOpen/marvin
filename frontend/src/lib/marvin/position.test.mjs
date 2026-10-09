// Where the Marvin bubble rests (position.ts). Run with `npm test` — plain `node --test`, which
// strips position.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  clampSpot,
  DEFAULT_SPOT,
  EDGE_GUTTER,
  hiddenAfterScroll,
  parseSpot,
  parseTuck,
  SCROLL_HIDE_PX,
  spotFromRect,
  TUCK_PEEK,
  tuckAt,
  tuckedPosition,
  tuckEdge,
  peekEveryMs,
} from "./position.ts";

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

describe("tucking into an edge", () => {
  const box = { width: 52, height: 52 };
  const view = { width: 400, height: 800 };
  const home = { x: "left", dx: 16, y: "bottom", dy: 16 };

  test("released mostly past a side, it tucks there; mostly on screen, it doesn't", () => {
    assert.equal(tuckEdge(370, 300, box, view), null); // 22 of 52 px past: not enough
    assert.equal(tuckEdge(380, 300, box, view), "right"); // 32 of 52 past
    assert.equal(tuckEdge(-40, 300, box, view), "left");
    assert.equal(tuckEdge(100, -30, box, view), "top");
    assert.equal(tuckEdge(100, 790, box, view), "bottom");
    assert.equal(tuckEdge(-40, 790, box, view), "bottom"); // a corner goes to whichever edge it's further past
  });

  test("a tucked bubble shows only a sliver, where it was dropped along the edge", () => {
    const tuck = tuckAt("right", 390, 374, box, view, home);
    assert.equal(tuck.along, 0.5);
    assert.deepEqual(tuckedPosition(tuck, box, view), { left: 400 - TUCK_PEEK, top: 374 });
    assert.deepEqual(tuckedPosition({ ...tuck, edge: "left" }, box, view), { left: TUCK_PEEK - 52, top: 374 });
    assert.deepEqual(tuckedPosition({ edge: "top", along: 0, restore: home }, box, view), {
      left: 0,
      top: TUCK_PEEK - 52,
    });
    assert.deepEqual(tuckedPosition({ edge: "bottom", along: 1, restore: home }, box, view), {
      left: 348,
      top: 800 - TUCK_PEEK,
    });
  });

  test("peeking shows half of it from the same edge", () => {
    const tuck = tuckAt("right", 390, 374, box, view, home);
    assert.deepEqual(tuckedPosition(tuck, box, view, true), { left: 400 - 26, top: 374 });
    assert.deepEqual(tuckedPosition({ ...tuck, edge: "top" }, box, view, true).top, 26 - 52);
  });

  test("a stored tuck survives a reload and nonsense is ignored", () => {
    const stored = JSON.parse(JSON.stringify(tuckAt("left", -40, 100, box, view, home)));
    assert.equal(parseTuck(stored, box, view).edge, "left");
    assert.deepEqual(parseTuck(stored, box, view).restore, home);
    assert.equal(parseTuck({ edge: "middle", along: 0.5 }, box, view), null);
    assert.equal(parseTuck(null, box, view), null);
  });
});

describe("out of the way while scrolling", () => {
  test("a real scroll down hides it, a scroll up brings it back, jitter changes nothing", () => {
    assert.equal(hiddenAfterScroll(SCROLL_HIDE_PX, false), true);
    assert.equal(hiddenAfterScroll(-SCROLL_HIDE_PX, true), false);
    assert.equal(hiddenAfterScroll(3, false), false);
    assert.equal(hiddenAfterScroll(-3, true), true);
  });
});

describe("peekEveryMs", () => {
  test("uses BUBBLE_PEEK_SECONDS when it is positive, else the default", () => {
    assert.equal(peekEveryMs(60), 60_000);
    assert.equal(peekEveryMs(2.5), 2_500);
    assert.equal(peekEveryMs(undefined), 5_000);
    assert.equal(peekEveryMs(0), 5_000);
  });
});
