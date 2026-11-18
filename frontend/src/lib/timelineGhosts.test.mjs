// Where a nudged line came from (its ghost) and where two lines play at once (the overlap bracket). The lines are laid by layout() as the
// render lays them (lead 0.3, gap 0.25, tail 0.35); the numbers are worked out by hand from that.
import assert from "node:assert/strict";
import { test } from "node:test";
import { layout, nudgeGhosts, overlapsIn, stackRows } from "./timeline.ts";

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);
const spec = {
  kind: "timeline",
  title: "T",
  entry_type: "story",
  spine: { entry_type: "beat", of: "story", order: "number" },
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
      simultaneous: "simultaneous",
    },
  ],
};
let n = 0;
const line = (seconds, data = {}) => {
  n += 1;
  return {
    id: `l${n}`,
    slug: `l${n}`,
    title: `l${n}`,
    dataJson: { story: "s", beat: "b1", number: n, duration_seconds: seconds, ...data },
  };
};
/** The lane's pieces and their rows, as the page draws them. */
const laneOf = (lines) => {
  const laid = layout(spec, {
    spine: [{ id: "b1", slug: "b1", title: "b1", dataJson: { story: "s", number: 1 } }],
    lanes: { lines },
  });
  const pieces = laid.items.flatMap((i) => i.lanes.lines);
  return { pieces, rows: stackRows(pieces) };
};

test("ghost: a line nudged over the one before leaves its outline where it would have played, on the row it left empty", () => {
  // A 0.3-3.3; B would start at 3.55 (after the gap) and is nudged -1.65 to 1.9, so it drops to row 1
  const { pieces, rows } = laneOf([line(3), line(2, { nudge: -1.65 })]);
  assert.deepEqual(rows, [0, 1]);
  const [ghost] = nudgeGhosts(pieces, rows);
  close(ghost.start, 3.55);
  close(ghost.seconds, 2);
  close(ghost.to, 1.9);
  assert.equal(ghost.nudge, -1.65);
  assert.deepEqual([ghost.row, ghost.toRow, ghost.free], [0, 1, true]);
});

test("ghost: when every row is taken at its slot it is still drawn, behind, on row 0", () => {
  // C follows B where B now ends (3.9 + 0.25 = 4.15) on row 0, inside B's natural slot 3.55-5.55; row 1 holds B itself until 3.9
  const { pieces, rows } = laneOf([line(3), line(2, { nudge: -1.65 }), line(1)]);
  assert.deepEqual(rows, [0, 1, 0]);
  const [ghost] = nudgeGhosts(pieces, rows);
  assert.deepEqual([ghost.row, ghost.free], [0, false]);
});

test("ghost: none for a line with no nudge or one spoken together with the line before", () => {
  const { pieces, rows } = laneOf([line(2), line(1, { simultaneous: true }), line(1)]);
  assert.deepEqual(nudgeGhosts(pieces, rows), []);
  const later = laneOf([line(2), line(1, { nudge: 0.5 })]);
  const [ghost] = nudgeGhosts(later.pieces, later.rows);
  close(ghost.start, 2.55);
  close(ghost.to, 3.05); // moved later: the arrow points right
});

test("overlap: from the later line's start to where the earlier one ends, across both rows", () => {
  const { pieces, rows } = laneOf([line(3), line(2, { nudge: -1.65 })]);
  const [o] = overlapsIn(pieces, rows);
  close(o.start, 1.9);
  close(o.seconds, 1.4);
  assert.deepEqual([o.earlier, o.later, o.rows], [pieces[0].id, pieces[1].id, [0, 1]]);
});

test("overlap: a line laid wholly inside another overlaps for its own length", () => {
  const { pieces, rows } = laneOf([line(3), line(0.5, { nudge: -2.5 })]); // 0.3 + 3 + 0.25 - 2.5 = 1.05, ends 1.55
  const [o] = overlapsIn(pieces, rows);
  close(o.start, 1.05);
  close(o.seconds, 0.5);
});

test("overlap: two lines spoken together overlap for the shorter one's length", () => {
  const { pieces, rows } = laneOf([line(2), line(1, { simultaneous: true })]);
  const [o] = overlapsIn(pieces, rows);
  close(o.start, 0.3);
  close(o.seconds, 1);
});

test("overlap: each pair that plays at once has its own; lines that only touch have none", () => {
  // B nudged -1.0 starts 1.55 under A (0.3-2.3) and ends 3.55; C nudged -0.5 starts 3.55 + 0.25 - 0.5 = 3.3, under B
  const { pieces, rows } = laneOf([line(2), line(2, { nudge: -1 }), line(1, { nudge: -0.5 })]);
  const found = overlapsIn(pieces, rows);
  assert.equal(found.length, 2);
  close(found[0].start, 1.55);
  close(found[0].seconds, 0.75);
  close(found[1].start, 3.3);
  close(found[1].seconds, 0.25);
  // a gap nudged to exactly 0: B starts where A ends
  assert.deepEqual(overlapsIn(...Object.values(laneOf([line(2), line(1, { nudge: -0.25 })]))), []);
});
