// Dragging a line on the Timeline: the nudge it writes, and where the lines are drawn while it moves. The render lays them as
// ScreenplayStudio render/storyrender/manifest.py `plan` does; the numbers are worked out by hand from that.
import assert from "node:assert/strict";
import { test } from "node:test";
import { layout, NUDGE_SNAP, nudgeAfterDrag, relaid } from "./timeline.ts";

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);
const allClose = (actual, expected) => {
  assert.equal(actual.length, expected.length);
  for (const [i, a] of actual.entries()) close(a, expected[i]);
};
const S = { lead: 0.3, gap: 0.25, tail: 0.35 };
const line = (seconds, nudge = 0, together = false) => ({ seconds, nudge, together });

test("nudgeAfterDrag: the offset from where the line falls, snapped to 0.05 s", () => {
  assert.equal(NUDGE_SNAP, 0.05);
  assert.equal(nudgeAfterDrag(2.55, 2.97), 0.4);
  assert.equal(nudgeAfterDrag(2.55, 2.12), -0.45);
  assert.equal(nudgeAfterDrag(2.55, 2.56), 0); // back where it falls: no nudge
});

test("nudgeAfterDrag: shift drags it free, to the thousandth", () => {
  assert.equal(nudgeAfterDrag(2.55, 2.9734, true), 0.423);
});

test("nudgeAfterDrag: never before the film starts, never past the render's 10 s", () => {
  assert.equal(nudgeAfterDrag(0.3, -2), -0.3);
  assert.equal(nudgeAfterDrag(20, 5), -10);
  assert.equal(nudgeAfterDrag(1, 40), 10);
});

test("relaid: the dragged line moves and the lines after it follow where it now ends", () => {
  const lines = [line(2), line(1), line(1)];
  allClose(relaid(lines, S, 0, 1, 0.5), [0.3, 3.05, 4.3]);
  allClose(relaid(lines, S, 0, 0, -0.2), [0.1, 2.35, 3.6]);
});

test("relaid: a line simultaneous with the dragged one moves with it", () => {
  allClose(relaid([line(2), line(1, 0, true)], S, 10, 0, 0.5), [10.8, 10.8]);
});

test("relaid: dragging a line back to 0 lays them as if it had never been nudged", () => {
  allClose(relaid([line(2), line(1, 0.5), line(1)], S, 0, 1, 0), [0.3, 2.55, 3.8]);
});

test("layout: each timed piece knows where it would start without its own nudge, and its item the silences it was laid with", () => {
  const spec = {
    kind: "timeline",
    title: "T",
    entry_type: "story",
    spine: { entry_type: "beat", of: "story", order: "number", seconds: { lead: "lead_seconds" } },
    lanes: [
      {
        id: "lines",
        title: "Lines",
        entry_type: "speech-line",
        of: "story",
        in: "beat",
        order: "number",
        seconds: "duration_seconds",
        nudge: "nudge",
      },
    ],
  };
  const row = (slug, data) => ({ id: slug, slug, title: slug, dataJson: { story: "s", ...data } });
  const laid = layout(spec, {
    spine: [row("b1", { number: 1 })],
    lanes: {
      lines: [
        row("l1", { beat: "b1", number: 1, duration_seconds: 2 }),
        row("l2", { beat: "b1", number: 2, duration_seconds: 1, nudge: -0.5 }),
      ],
    },
  });
  const [a, b] = laid.items[0].lanes.lines;
  close(a.natural, 0.3);
  close(b.natural, 2.55);
  close(b.start, 2.05);
  assert.equal(nudgeAfterDrag(b.natural, b.start), -0.5); // dropping it where it is keeps its nudge
  assert.deepEqual(laid.items[0].timing, S);
});
