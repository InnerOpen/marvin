// Where the Marvin bubble rests on screen. It is position: fixed, so a spot is always relative to
// the viewport: the distance from its nearest horizontal edge and its nearest vertical edge. Anchoring
// to the nearest edges (rather than storing left/top) keeps a bubble parked bottom-right in the
// bottom-right when the window or phone rotates, and clamping keeps it reachable on a smaller screen.
// Pure functions so they can be tested without a DOM; Marvin.astro applies the result.

export type BubbleSpot = {
  x: "left" | "right";
  dx: number;
  y: "top" | "bottom";
  dy: number;
};

export type Size = { width: number; height: number };

/** Kept between the bubble and the viewport edge — the admin's standard gutter. */
export const EDGE_GUTTER = 16;

/** Where the bubble sits until someone drags it. */
export const DEFAULT_SPOT: BubbleSpot = { x: "left", dx: EDGE_GUTTER, y: "bottom", dy: EDGE_GUTTER };

const clamp = (n: number, lo: number, hi: number) => Math.min(Math.max(n, lo), Math.max(lo, hi));

/** Pull a spot back inside the viewport so the whole bubble (`box`) stays on screen. */
export function clampSpot(spot: BubbleSpot, box: Size, viewport: Size): BubbleSpot {
  return {
    x: spot.x,
    dx: Math.round(clamp(spot.dx, EDGE_GUTTER, viewport.width - box.width - EDGE_GUTTER)),
    y: spot.y,
    dy: Math.round(clamp(spot.dy, EDGE_GUTTER, viewport.height - box.height - EDGE_GUTTER)),
  };
}

/** The spot for a bubble whose top-left corner is at (left, top), anchored to its nearest edges. */
export function spotFromRect(left: number, top: number, box: Size, viewport: Size): BubbleSpot {
  const right = viewport.width - left - box.width;
  const bottom = viewport.height - top - box.height;
  return clampSpot(
    {
      x: left <= right ? "left" : "right",
      dx: Math.min(left, right),
      y: top <= bottom ? "top" : "bottom",
      dy: Math.min(top, bottom),
    },
    box,
    viewport,
  );
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * Read a stored spot. Accepts the current shape, and the older `{ left, top }` one (viewport
 * coordinates from whatever window it was saved in), re-anchored to the current viewport. Anything
 * unreadable falls back to the default rather than losing the bubble.
 */
export function parseSpot(raw: unknown, box: Size, viewport: Size): BubbleSpot {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    if ((r.x === "left" || r.x === "right") && (r.y === "top" || r.y === "bottom") && isNum(r.dx) && isNum(r.dy)) {
      return clampSpot({ x: r.x, dx: r.dx, y: r.y, dy: r.dy }, box, viewport);
    }
    if (isNum(r.left) && isNum(r.top)) return spotFromRect(r.left, r.top, box, viewport);
  }
  return clampSpot(DEFAULT_SPOT, box, viewport);
}
