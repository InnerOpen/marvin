/**
 * A `timeline` view, laid out: the entries a package's view definition names (services/blueprints/views.py), as positions in time.
 *
 * The spine (a story's beats) runs end to end; each item lasts as long as the renderer will cut it: an item with timed pieces in its lanes
 * (lines) lasts `lead + Σ piece seconds + gap × (pieces − 1) + tail`, an item with none lasts `hold`. A piece with no recording yet is
 * *estimated* from its text at a reading pace, so the timeline is useful before anything is recorded and firms up as takes land. Pure:
 * nothing here fetches; the page hands in rows and gets back what to draw.
 */

export interface SecondsSpec {
  hold?: string;
  lead?: string;
  gap?: string;
  tail?: string;
  defaults?: Partial<Record<"hold" | "lead" | "gap" | "tail", number>>;
}

export interface SpineSpec {
  entry_type: string;
  of: string;
  order?: string;
  group?: { entry_type: string; field: string; order?: string };
  picture?: string;
  text?: string;
  status?: string;
  title?: string;
  seconds?: SecondsSpec;
}

export interface LaneSpec {
  id: string;
  title: string;
  entry_type: string;
  of: string;
  in?: string;
  placed?: { field: string; ref: string; at: string };
  order?: string;
  text?: string;
  who?: string;
  audio?: string;
  seconds?: string;
  estimate_from?: string;
  status?: string;
}

export interface ActionSpec {
  label: string;
  wizard?: string;
  workflow?: string;
}

export interface TimelineSpec {
  kind: "timeline";
  title: string;
  description?: string;
  entry_type: string;
  spine: SpineSpec;
  lanes?: LaneSpec[];
  actions?: ActionSpec[];
}

/** An entry as the entries query returns it: the fields in dataJson, the attached assets with the field key as their role. */
export interface Row {
  id: string;
  slug: string;
  title: string;
  dataJson?: Record<string, unknown> | null;
  assets?: { role?: string | null; publicUrl?: string | null; mimeType?: string | null }[];
}

export interface Piece {
  id: string;
  slug: string;
  title: string;
  text: string;
  who: string;
  status: string;
  /** Seconds from the start of the whole timeline. */
  start: number;
  seconds: number;
  /** True when `seconds` came from the text, not a recording. */
  estimated: boolean;
  audio: string | null;
  /** For a placed piece: its offset inside the item, as declared. */
  at: number | null;
}

export interface Item {
  id: string;
  slug: string;
  title: string;
  number: number | null;
  text: string;
  picture: string | null;
  status: string;
  start: number;
  seconds: number;
  /** True when any timed piece in it is estimated (so its length may change). */
  estimated: boolean;
  lanes: Record<string, Piece[]>;
}

export interface Group {
  id: string | null;
  slug: string | null;
  title: string;
  start: number;
  seconds: number;
  items: Item[];
}

export interface Layout {
  total: number;
  groups: Group[];
  items: Item[];
}

export const DEFAULT_SECONDS = { hold: 4, lead: 0.3, gap: 0.25, tail: 0.35 };
export const WORDS_PER_MINUTE = 150;
export const MIN_ESTIMATE_SECONDS = 1;
/** The narrowest card: a 0.3 s item is still something to click. */
export const MIN_ITEM_PX = 72;

const num = (v: unknown): number | null => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};
const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
const field = (row: Row, key: string | undefined): unknown => (key ? row.dataJson?.[key] : undefined);

/** How long reading `text` aloud takes, at a steady pace; never under a second, so an unrecorded line still has a width. */
export function estimateSeconds(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(MIN_ESTIMATE_SECONDS, (words / WORDS_PER_MINUTE) * 60);
}

/** The picture an item shows: the asset attached in the picture field's role (a linked asset field syncs its role to its key). */
export function assetUrl(row: Row, key: string | undefined, kind: "image/" | "audio/"): string | null {
  if (!key) return null;
  const hit = (row.assets ?? []).find((a) => a.role === key && a.publicUrl && (a.mimeType ?? "").startsWith(kind));
  return hit?.publicUrl ?? null;
}

/** A lane piece's seconds: the recording's duration when it has one, else an estimate from its text, else nothing (a sound with no file). */
export function pieceSeconds(row: Row, lane: LaneSpec): { seconds: number; estimated: boolean } | null {
  const recorded = num(field(row, lane.seconds));
  if (recorded !== null && recorded > 0) return { seconds: recorded, estimated: false };
  const text = str(field(row, lane.estimate_from));
  if (lane.estimate_from && text.trim()) return { seconds: estimateSeconds(text), estimated: true };
  return null;
}

/** The seconds an item's own fields set, each falling back to the view's default, then to the renderer's. */
export function secondsOf(row: Row, spec: SecondsSpec | undefined): typeof DEFAULT_SECONDS {
  const out = { ...DEFAULT_SECONDS, ...(spec?.defaults ?? {}) };
  for (const key of ["hold", "lead", "gap", "tail"] as const) {
    const own = num(field(row, spec?.[key]));
    if (own !== null && own >= 0) out[key] = own;
  }
  return out;
}

/** The renderer's rule: timed pieces one after another with silences around them; nothing timed, and the item holds. */
export function itemSeconds(row: Row, timed: { seconds: number }[], spec: SecondsSpec | undefined): number {
  const s = secondsOf(row, spec);
  if (timed.length === 0) return s.hold;
  return s.lead + timed.reduce((sum, p) => sum + p.seconds, 0) + s.gap * (timed.length - 1) + s.tail;
}

const byOrder = (key: string | undefined) => (a: Row, b: Row) => {
  const [x, y] = [num(field(a, key)), num(field(b, key))];
  if (x !== null && y !== null && x !== y) return x - y;
  if (x === null && y !== null) return 1;
  if (x !== null && y === null) return -1;
  return a.title.localeCompare(b.title);
};

interface Rows {
  spine: Row[];
  groups?: Row[];
  lanes: Record<string, Row[]>;
}

/**
 * Lay the view out. Spine rows are sorted by the spine's order field and gathered under their group (chapters in their own order; items
 * whose group is unknown come last, under no title). Each `in` lane's rows are the pieces of the item their `in` field names, timed one after
 * another from the item's lead; each `placed` lane's pieces sit where the item's JSON list puts them. Unknown references are ignored.
 */
export function layout(spec: TimelineSpec, rows: Rows): Layout {
  const lanes = spec.lanes ?? [];
  const inLanes = lanes.filter((l) => l.in);
  const placedLanes = lanes.filter((l) => l.placed);
  const laneRows = (lane: LaneSpec) => [...(rows.lanes[lane.id] ?? [])].sort(byOrder(lane.order));
  const bySlug = (lane: LaneSpec) => new Map(laneRows(lane).map((r) => [r.slug, r] as const));

  const items: Item[] = [];
  let clock = 0;
  const groups = groupRows(spec.spine, rows);
  const out: Group[] = [];
  for (const g of groups) {
    const groupStart = clock;
    const made: Item[] = [];
    for (const row of g.rows) {
      const s = secondsOf(row, spec.spine.seconds);
      const item: Item = {
        id: row.id,
        slug: row.slug,
        title: str(field(row, spec.spine.title)) || row.title,
        number: num(field(row, spec.spine.order)),
        text: str(field(row, spec.spine.text)),
        picture: assetUrl(row, spec.spine.picture, "image/"),
        status: str(field(row, spec.spine.status)),
        start: clock,
        seconds: 0,
        estimated: false,
        lanes: {},
      };
      // Timed pieces run across the `in` lanes in declared order, one after another from the lead.
      let cursor = clock + s.lead;
      const timed: Piece[] = [];
      for (const lane of inLanes) {
        const pieces: Piece[] = [];
        for (const r of laneRows(lane).filter((r) => str(field(r, lane.in)) === row.slug)) {
          const length = pieceSeconds(r, lane);
          const piece = pieceOf(r, lane, length?.seconds ?? 0, length?.estimated ?? false, cursor, null);
          if (length) {
            if (timed.length) cursor += s.gap;
            piece.start = cursor;
            cursor += length.seconds;
            timed.push(piece);
          }
          pieces.push(piece);
        }
        item.lanes[lane.id] = pieces;
      }
      item.seconds = itemSeconds(row, timed, spec.spine.seconds);
      item.estimated = timed.some((p) => p.estimated);
      for (const lane of placedLanes) {
        const known = bySlug(lane);
        const placed = field(row, lane.placed!.field);
        const pieces: Piece[] = [];
        for (const ref of Array.isArray(placed) ? placed : []) {
          if (typeof ref !== "object" || ref === null) continue;
          const target = known.get(str((ref as Record<string, unknown>)[lane.placed!.ref]));
          if (!target) continue;
          const at = Math.max(0, num((ref as Record<string, unknown>)[lane.placed!.at]) ?? 0);
          const length = pieceSeconds(target, lane);
          pieces.push(pieceOf(target, lane, length?.seconds ?? 0, length?.estimated ?? false, clock + at, at));
        }
        item.lanes[lane.id] = pieces;
      }
      clock += item.seconds;
      made.push(item);
      items.push(item);
    }
    out.push({ id: g.id, slug: g.slug, title: g.title, start: groupStart, seconds: clock - groupStart, items: made });
  }
  return { total: clock, groups: out, items };
}

function pieceOf(row: Row, lane: LaneSpec, seconds: number, estimated: boolean, start: number, at: number | null): Piece {
  return {
    id: row.id,
    slug: row.slug,
    title: row.title,
    text: str(field(row, lane.text)),
    who: str(field(row, lane.who)),
    status: str(field(row, lane.status)),
    start,
    seconds,
    estimated,
    audio: assetUrl(row, lane.audio, "audio/"),
    at,
  };
}

function groupRows(spine: SpineSpec, rows: Rows): { id: string | null; slug: string | null; title: string; rows: Row[] }[] {
  const sorted = [...rows.spine].sort(byOrder(spine.order));
  if (!spine.group) return [{ id: null, slug: null, title: "", rows: sorted }];
  const groups = [...(rows.groups ?? [])].sort(byOrder(spine.group.order)).map((g) => ({ id: g.id as string | null, slug: g.slug as string | null, title: g.title, rows: [] as Row[] }));
  const known = new Map(groups.map((g) => [g.slug, g]));
  const stray: Row[] = [];
  for (const row of sorted) (known.get(str(field(row, spine.group.field))) ?? { rows: stray }).rows.push(row);
  const out = groups.filter((g) => g.rows.length);
  if (stray.length) out.push({ id: null, slug: null, title: "", rows: stray });
  return out;
}

/** Pixels per second so the whole timeline fills `width`, never so few that an item falls under its minimum card. */
export function scale(items: { seconds: number }[], total: number, width: number): number {
  if (total <= 0 || width <= 0) return 0;
  const fit = width / total;
  const shortest = Math.min(...items.map((i) => i.seconds).filter((s) => s > 0), Infinity);
  return shortest === Infinity ? fit : Math.max(fit, MIN_ITEM_PX / shortest);
}

export const widthOf = (seconds: number, pxPerSecond: number): number => Math.max(MIN_ITEM_PX, Math.round(seconds * pxPerSecond));

const TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

/** Ruler ticks: a step chosen so there are about `want` of them, from the first to just past the end. */
export function ticks(total: number, want = 10): number[] {
  if (total <= 0) return [0];
  const step = TICK_STEPS.find((s) => total / s <= want) ?? TICK_STEPS[TICK_STEPS.length - 1];
  const out: number[] = [];
  for (let t = 0; t <= total + 1e-9; t += step) out.push(Number(t.toFixed(3)));
  return out;
}

export interface Progress {
  label: string;
  done: number;
  total: number;
}

/** What is in place: items with a picture (when the spine has one), each lane's pieces with a recording (when the lane has audio). */
export function progress(spec: TimelineSpec, laid: Layout, noun = { item: "beat", items: "beats" }): Progress[] {
  const out: Progress[] = [];
  if (spec.spine.picture) {
    const total = laid.items.length;
    out.push({ label: `${total === 1 ? noun.item : noun.items} with a picture`, done: laid.items.filter((i) => i.picture).length, total });
  }
  for (const lane of (spec.lanes ?? []).filter((l) => l.audio)) {
    const pieces = laid.items.flatMap((i) => i.lanes[lane.id] ?? []);
    out.push({ label: `${lane.title.toLowerCase()} recorded`, done: pieces.filter((p) => p.audio).length, total: pieces.length });
  }
  return out;
}

export const progressLine = (steps: Progress[]): string => steps.map((p) => `${p.done} of ${p.total} ${p.label}`).join(" · ");

/** What the player walks: each item, then each timed piece in it, in order, with where it starts and what (if anything) plays. */
export interface Cue {
  item: string;
  piece: string | null;
  start: number;
  seconds: number;
  audio: string | null;
}

export function cues(laid: Layout, lanes: LaneSpec[]): Cue[] {
  const timedLanes = lanes.filter((l) => l.in && (l.seconds || l.estimate_from)).map((l) => l.id);
  const out: Cue[] = [];
  for (const item of laid.items) {
    const timed = timedLanes.flatMap((id) => item.lanes[id] ?? []).filter((p) => p.seconds > 0).sort((a, b) => a.start - b.start);
    if (timed.length === 0) {
      out.push({ item: item.id, piece: null, start: item.start, seconds: item.seconds, audio: null });
      continue;
    }
    let at = item.start;
    for (const p of timed) {
      if (p.start > at) out.push({ item: item.id, piece: null, start: at, seconds: p.start - at, audio: null });
      out.push({ item: item.id, piece: p.id, start: p.start, seconds: p.seconds, audio: p.audio });
      at = p.start + p.seconds;
    }
    const end = item.start + item.seconds;
    if (end > at) out.push({ item: item.id, piece: null, start: at, seconds: end - at, audio: null });
  }
  return out;
}
