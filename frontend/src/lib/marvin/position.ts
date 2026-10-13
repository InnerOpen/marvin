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

// ── Tucked into an edge ──────────────────────────────────────────────────────────────────────────
// Dragged mostly off a side and let go, the bubble tucks into that edge: only a sliver (TUCK_PEEK) shows, at
// the point along the edge where it was dropped. A tap (or a drag) brings it back to where it last rested.

export type Edge = "left" | "right" | "top" | "bottom";

export type Tuck = {
  edge: Edge;
  /** Where along the edge its centre sits, as a fraction of the edge's length (0 = top/left). */
  along: number;
  /** Where it comes back to. */
  restore: BubbleSpot;
};

/** How much of a tucked bubble stays on screen. */
export const TUCK_PEEK = 14;
/** Share of the bubble that must be past an edge, on release, for it to tuck there. */
export const TUCK_PAST = 0.5;

/** The edge a bubble released with its top-left at (left, top) tucks into, or null to rest normally. */
export function tuckEdge(left: number, top: number, box: Size, viewport: Size): Edge | null {
  const past: [Edge, number][] = [
    ["left", -left / box.width],
    ["right", (left + box.width - viewport.width) / box.width],
    ["top", -top / box.height],
    ["bottom", (top + box.height - viewport.height) / box.height],
  ];
  const [edge, share] = past.reduce((a, b) => (b[1] > a[1] ? b : a));
  return share >= TUCK_PAST ? edge : null;
}

/** The tuck for a bubble released at (left, top) past `edge`, coming back to `restore`. */
export function tuckAt(edge: Edge, left: number, top: number, box: Size, viewport: Size, restore: BubbleSpot): Tuck {
  const vertical = edge === "left" || edge === "right";
  const centre = vertical ? top + box.height / 2 : left + box.width / 2;
  const length = vertical ? viewport.height : viewport.width;
  return { edge, along: clamp(length ? centre / length : 0.5, 0, 1), restore };
}

/** How much of a tucked bubble shows while it peeks out: all of it — at half, a character drawn in the middle of its
 * frame played its peek behind the screen edge. */
export const PEEK_SHARE = 1;
/** Seconds between peeks unless BUBBLE_PEEK_SECONDS says otherwise (it was a random 45–75 s until 2026-10-09). */
export const PEEK_EVERY_DEFAULT_S = 5;

/** The wait before the next peek, in ms: the configured seconds when positive, else the default. */
export function peekEveryMs(configuredSeconds?: number | null): number {
  const seconds = configuredSeconds != null && configuredSeconds > 0 ? configuredSeconds : PEEK_EVERY_DEFAULT_S;
  return seconds * 1000;
}
/** How long a peek stays out: it starts back in (a 0.35 s slide) before the character's peek ends (PEEK_MS, 2 s in
 * character.ts), so the idle frame never shows outside. */
export const PEEK_OUT_MS = 1_650;

/** The empty frame around a character image's drawing on each side, as shares of the frame (measured by the server
 * at upload: AI settings' `characterInsets`). */
export type Inset = Partial<Record<Edge, number>>;
/** A peek never hides more of its frame than this, whatever an inset says: something always comes out. */
const MAX_PEEK_INSET = 0.9;

/** Top-left of a tucked bubble: TUCK_PEEK on screen (`peeking`: PEEK_SHARE of it), kept within the edge's length.
 * Peeking, the empty frame on the edge's side (`inset`) stays off screen, so the drawing — a peek's drawn ledge —
 * meets the edge instead of floating off it. */
export function tuckedPosition(tuck: Tuck, box: Size, viewport: Size, peeking = false, inset?: Inset | null): { left: number; top: number } {
  const across = tuck.edge === "left" || tuck.edge === "right" ? box.width : box.height;
  const margin = clamp(inset?.[tuck.edge] ?? 0, 0, MAX_PEEK_INSET);
  const shown = peeking ? Math.round(across * (PEEK_SHARE - margin)) : TUCK_PEEK;
  const alongEdge = (length: number, size: number) =>
    Math.round(clamp(tuck.along * length - size / 2, 0, length - size));
  switch (tuck.edge) {
    case "left":
      return { left: shown - box.width, top: alongEdge(viewport.height, box.height) };
    case "right":
      return { left: viewport.width - shown, top: alongEdge(viewport.height, box.height) };
    case "top":
      return { left: alongEdge(viewport.width, box.width), top: shown - box.height };
    default:
      return { left: alongEdge(viewport.width, box.width), top: viewport.height - shown };
  }
}

/** Read a stored tuck; null for nothing stored or anything unreadable (the bubble then rests normally). */
export function parseTuck(raw: unknown, box: Size, viewport: Size): Tuck | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!["left", "right", "top", "bottom"].includes(r.edge as string) || !isNum(r.along)) return null;
  return { edge: r.edge as Edge, along: clamp(r.along, 0, 1), restore: parseSpot(r.restore, box, viewport) };
}

// ── Out of the way while scrolling (phones) ─────────────────────────────────────────────────────

/** Scrolled this far down in one go: the bubble steps aside. */
export const SCROLL_HIDE_PX = 24;
/** No scrolling for this long: it comes back. */
export const SCROLL_IDLE_MS = 1800;

/** After scrolling by `delta` px (positive = down), should the bubble be out of the way? `current` is whether it is. */
export function hiddenAfterScroll(delta: number, current: boolean): boolean {
  if (delta >= SCROLL_HIDE_PX) return true;
  if (delta <= -SCROLL_HIDE_PX / 2) return false;
  return current;
}
