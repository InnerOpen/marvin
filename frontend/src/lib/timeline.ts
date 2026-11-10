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

export interface BedSpec {
  /** The field naming the lane entry's slug: on the view's entry (default), on each spine item (`on: "spine"`), or on the entry a spine
   * item's `via` field names (`via` + `entry_type`: a beat's scene names its ambience). */
  field: string;
  on?: "entry" | "spine";
  via?: string;
  entry_type?: string;
  /** The level (0 to 1) on the entry that names the bed, and an override on the spine item. On a bed that runs under the whole story (no
   * `via`) the override *replaces* the level while that item plays (a beat's music_volume, 0 = silence) and shows as steps in the block. */
  volume?: string;
  item_volume?: string;
  muffled?: string;
  /** The level when neither the item, the entry that names the bed nor the sound itself sets one: what the render falls back to (0.12 for
   * music, 0.5 for ambience). Without it, 1. */
  default_volume?: number;
  /** The sound's own fade fields (seconds), what the render uses when they are empty (`default_fade_*`: ambience crossfades over 0.6, music
   * fades out over 2), and the field on the view's entry that sets how long every bed fades out at the end of the film (it wins there). */
  fade_in?: string;
  fade_out?: string;
  default_fade_in?: number;
  default_fade_out?: number;
  end_fade?: string;
  /** A field on the view's entry holding `none`, `light` or `strong`: how far the bed goes down under each spoken line (Play follows it). */
  duck?: string;
}

/** A video laid over each spine item's picture. The item's own field wins, then the entry `via` names (a beat's scene), then the view's entry
 * itself (the story); a blend of `none` at any of them switches the overlay off from there up. */
export interface CoverSpec {
  /** The asset field (its attached asset carries the field key as its role). */
  field: string;
  blend?: string;
  opacity?: string;
  via?: string;
  entry_type?: string;
}

export interface LaneSpec {
  id: string;
  title: string;
  entry_type: string;
  /** The field on a lane entry that holds the view's entry's slug; required for `in` lanes, optional otherwise. */
  of?: string;
  in?: string;
  placed?: { field: string; ref: string; at: string };
  bed?: BedSpec;
  cover?: CoverSpec;
  order?: string;
  text?: string;
  who?: string;
  audio?: string;
  seconds?: string;
  /** The lane entry's own level (0 to 1) and whether it repeats. */
  volume?: string;
  loop?: string;
  estimate_from?: string;
  status?: string;
  /** A guided setup (of the same package) a piece of this lane opens on, with the piece chosen, instead of its own page: a line opens its takes. */
  open?: { wizard: string };
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
  /** True when there is a take but its length was never stored (an upload), so `seconds` is still the text's estimate. */
  unmeasured: boolean;
  audio: string | null;
  /** The entry's own level, 0 to 1, when it declares one. */
  volume: number | null;
  /** For a placed piece: its offset inside the item, as declared. */
  at: number | null;
}

/** A sound running under a stretch of the timeline: a scene's ambience across its beats, a story's music under everything. */
export interface Bed {
  id: string;
  slug: string;
  title: string;
  start: number;
  seconds: number;
  audio: string | null;
  /** The effective level: the sound's own × the level where it is named (× the spine item's override). */
  volume: number;
  loop: boolean;
  muffled: boolean;
  /** The spine items it runs under. */
  items: string[];
  /** When items set a level of their own: the whole block as runs at one level each (an item's level replaces the block's). Else empty. */
  steps: BedStep[];
  /** Seconds the block rises from silence at its start and falls to it at its end, as the render fades it (0 for none). */
  fadeIn: number;
  fadeOut: number;
  /** How far the bed goes down under speech, as a share of its level (0.12: down to an eighth), or null for none. */
  duck: number | null;
}

export interface BedStep {
  start: number;
  seconds: number;
  volume: number;
}

/** A video over a stretch of pictures, merged across consecutive items that get the same one. */
export interface Cover {
  /** The video's address, which tells two overlays apart. */
  url: string;
  /** Its file name, for the label. */
  name: string;
  /** The entry type it was set on: the spine's, the `via`'s or the view's own. */
  from: string;
  blend: string;
  /** 0 to 1; 1 when none is set. */
  opacity: number;
  start: number;
  seconds: number;
  items: string[];
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
  /** Per bed lane, its blocks in time order. */
  beds: Record<string, Bed[]>;
  /** Per cover lane, its blocks in time order. */
  covers: Record<string, Cover[]>;
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
export function assetUrl(row: Row, key: string | undefined, kind: "image/" | "audio/" | "video/"): string | null {
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
  return a.slug.localeCompare(b.slug); // the renderer's own fallback: slugs are numbered (story-line-007)
};

interface Rows {
  /** The view's entry itself (a bed lane may name its sound on it). */
  entry?: Row;
  spine: Row[];
  groups?: Row[];
  /** Per lane id, its entries: the children of an `in` lane, the referenced entries of a `placed` or `bed` lane. */
  lanes: Record<string, Row[]>;
  /** Per bed lane with `via`, the entries the spine items name (the scenes). */
  via?: Record<string, Row[]>;
}

const level = (v: unknown): number | null => {
  const n = num(v);
  return n === null ? null : Math.max(0, Math.min(1, n));
};

/**
 * Lay the view out. Spine rows are sorted by the spine's order field and gathered under their group (chapters in their own order; items
 * whose group is unknown come last, under no title). Each `in` lane's rows are the pieces of the item their `in` field names, timed one after
 * another from the item's lead; each `placed` lane's pieces sit where the item's JSON list puts them. Unknown references are ignored.
 */
export function layout(spec: TimelineSpec, rows: Rows): Layout {
  const lanes = spec.lanes ?? [];
  const inLanes = lanes.filter((l) => l.in);
  const placedLanes = lanes.filter((l) => l.placed);
  const bedLanes = lanes.filter((l) => l.bed);
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
  const beds: Record<string, Bed[]> = {};
  for (const lane of bedLanes) beds[lane.id] = bedsOf(lane, items, rows, clock, bySlug(lane));
  const covers: Record<string, Cover[]> = {};
  for (const lane of lanes.filter((l) => l.cover)) covers[lane.id] = coversOf(lane.cover!, spec, items, rows, lane.id);
  return { total: clock, groups: out, items, beds, covers };
}

/** A bed's level as the render plays it: the level set where the sound is named (a beat's, else its scene's or the story's) *replaces* the
 * sound's own, which replaces the lane's default. Not a product: a scene at 0.5 over a sound at 0.8 plays at 0.5. */
function bedLevel(lane: LaneSpec, sound: Row, named: number | null): number {
  return named ?? level(field(sound, lane.volume)) ?? lane.bed?.default_volume ?? 1;
}

/** How far the music goes down under a spoken line, set by the story: the same amounts as the render (about -9 dB and -18 dB), which this
 * must keep in step with (ScreenplayStudio render/storyrender/build.py: DUCK_DEPTH, DUCK_ATTACK, DUCK_RELEASE). */
export const DUCK_DEPTH = { light: 0.35, strong: 0.12 } as const;
export const DUCK_ATTACK = 0.2;
export const DUCK_RELEASE = 0.5;
const duckDepth = (value: unknown): number | null => (value === "light" || value === "strong" ? DUCK_DEPTH[value] : null);

/** How a bed block fades as the render plays it: in over the sound's own `fade_in` (else the lane's default), out over its `fade_out`, and a
 * block that runs to the end of the film out over the story's own setting when it has one. Neither is longer than half the block. */
function bedFades(spec: BedSpec, sound: Row, start: number, seconds: number, total: number, entry: Row | undefined): { fadeIn: number; fadeOut: number } {
  const own = (key: string | undefined, fallback: number | undefined) => Math.max(0, num(field(sound, key)) ?? fallback ?? 0);
  const atEnd = start + seconds >= total - 1e-6;
  const story = atEnd && entry ? num(field(entry, spec.end_fade)) : null;
  const half = seconds / 2;
  return { fadeIn: Math.min(own(spec.fade_in, spec.default_fade_in), half), fadeOut: Math.min(story !== null && story > 0 ? story : own(spec.fade_out, spec.default_fade_out), half) };
}

/** The blocks of a bed lane: which sound runs under each item, merged across consecutive items that share one, at what level. */
function bedsOf(lane: LaneSpec, items: Item[], rows: Rows, total: number, sounds: Map<string, Row>): Bed[] {
  const spec = lane.bed!;
  const via = new Map((rows.via?.[lane.id] ?? []).map((r) => [r.slug, r] as const));
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const make = (sound: Row, start: number, seconds: number, at: number | null, muffled: boolean, ids: string[]): Bed => ({
    id: sound.id,
    slug: sound.slug,
    title: sound.title,
    start,
    seconds,
    audio: assetUrl(sound, lane.audio, "audio/"),
    volume: bedLevel(lane, sound, at),
    loop: lane.loop ? field(sound, lane.loop) !== false : true,
    muffled,
    items: ids,
    steps: [],
    ...bedFades(spec, sound, start, seconds, total, rows.entry),
    duck: rows.entry && !spec.via && spec.on !== "spine" ? duckDepth(field(rows.entry, spec.duck)) : null,
  });
  if (!spec.via && spec.on !== "spine") {
    const sound = rows.entry ? sounds.get(str(field(rows.entry, spec.field))) : undefined;
    if (!sound || total <= 0) return [];
    const whole = make(sound, 0, total, level(field(rows.entry!, spec.volume)), false, items.map((i) => i.id));
    whole.steps = stepsOf(spec, items, rows, whole.volume);
    return [whole];
  }
  const out: Bed[] = [];
  for (const item of items) {
    const row = spine.get(item.id);
    if (!row) continue;
    const named = spec.via ? via.get(str(field(row, spec.via))) : row;
    const sound = named ? sounds.get(str(field(named, spec.field))) : undefined;
    if (!sound) continue;
    const at = level(field(row, spec.item_volume)) ?? level(named ? field(named, spec.volume) : null);
    const muffled = !!(named && spec.muffled && field(named, spec.muffled) === true);
    const last = out[out.length - 1];
    if (last && last.slug === sound.slug && last.volume === bedLevel(lane, sound, at) && last.muffled === muffled && last.start + last.seconds >= item.start - 1e-6) {
      last.seconds = item.start + item.seconds - last.start;
      last.items.push(item.id);
    } else {
      out.push(make(sound, item.start, item.seconds, at, muffled, [item.id]));
    }
  }
  return out;
}

/** A story-wide bed's level over time when spine items set one of their own: runs at one level each, or none when no item changes it. */
function stepsOf(spec: BedSpec, items: Item[], rows: Rows, base: number): BedStep[] {
  if (!spec.item_volume) return [];
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const runs: BedStep[] = [];
  for (const item of items) {
    const row = spine.get(item.id);
    const volume = (row ? level(field(row, spec.item_volume)) : null) ?? base;
    const last = runs[runs.length - 1];
    if (last && Math.abs(last.volume - volume) < 1e-9) last.seconds = item.start + item.seconds - last.start;
    else runs.push({ start: item.start, seconds: item.seconds, volume });
  }
  return runs.length > 1 || (runs.length === 1 && Math.abs(runs[0].volume - base) > 1e-9) ? runs : [];
}

/** The file name of a published address, without its query. */
const fileName = (url: string): string => decodeURIComponent(url.split("?")[0].split("/").pop() ?? url);

/** The cover blocks of a cover lane: for each item the video its own field, else its `via` entry's, else the view's entry's names. */
function coversOf(spec: CoverSpec, view: TimelineSpec, items: Item[], rows: Rows, laneId: string): Cover[] {
  const via = new Map((rows.via?.[laneId] ?? []).map((r) => [r.slug, r] as const));
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const out: Cover[] = [];
  for (const item of items) {
    const row = spine.get(item.id);
    const named = row && spec.via ? via.get(str(field(row, spec.via))) : undefined;
    const tiers: [Row | undefined, string][] = [
      [row, view.spine.entry_type],
      [named, spec.entry_type ?? ""],
      [rows.entry, view.entry_type],
    ];
    let found: Cover | null = null;
    for (const [owner, from] of tiers) {
      if (!owner) continue;
      const blend = str(field(owner, spec.blend));
      if (blend === "none") break;
      const url = assetUrl(owner, spec.field, "video/");
      if (!url) continue;
      found = { url, name: fileName(url), from, blend: blend || "normal", opacity: level(field(owner, spec.opacity)) ?? 1, start: item.start, seconds: item.seconds, items: [item.id] };
      break;
    }
    if (!found) continue;
    const last = out[out.length - 1];
    if (last && last.url === found.url && last.blend === found.blend && last.opacity === found.opacity && last.from === found.from && last.start + last.seconds >= item.start - 1e-6) {
      last.seconds = item.start + item.seconds - last.start;
      last.items.push(item.id);
    } else out.push(found);
  }
  return out;
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
    unmeasured: estimated && !!assetUrl(row, lane.audio, "audio/"),
    audio: assetUrl(row, lane.audio, "audio/"),
    volume: level(field(row, lane.volume)),
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
/** A stretch of an item where its lane is quiet: what the renderer adds around the pieces, or the whole item when nothing is timed. */
export interface Quiet {
  id: string;
  kind: "lead" | "gap" | "tail" | "hold";
  start: number;
  seconds: number;
}

const QUIET_WORDS: Record<Quiet["kind"], string> = {
  lead: "lead-in: quiet before the first line",
  gap: "gap: the pause between two lines",
  tail: "tail: room after the last line, before the next beat",
  hold: "hold: nothing is timed, so the beat holds",
};
export const quietWords = (kind: Quiet["kind"]): string => QUIET_WORDS[kind];

/** The silences the renderer adds in a lane that sits inside the spine items (lines): lead before the first piece, gap between pieces, tail after the last, or the item's whole hold when no piece is timed. Placed and bed lanes have none. */
export function quiets(items: Item[], lane: LaneSpec): Quiet[] {
  if (!lane.in || lane.placed || lane.bed) return [];
  const out: Quiet[] = [];
  const add = (id: string, kind: Quiet["kind"], start: number, seconds: number) => {
    if (seconds > 0.005) out.push({ id, kind, start, seconds });
  };
  for (const item of items) {
    const timed = (item.lanes[lane.id] ?? []).filter((p) => p.seconds > 0).sort((a, b) => a.start - b.start);
    if (!timed.length) {
      add(`${item.id}:hold`, "hold", item.start, item.seconds);
      continue;
    }
    add(`${item.id}:lead`, "lead", item.start, timed[0].start - item.start);
    timed.slice(1).forEach((p, i) => add(`${item.id}:gap${i}`, "gap", timed[i].start + timed[i].seconds, p.start - (timed[i].start + timed[i].seconds)));
    const end = timed[timed.length - 1].start + timed[timed.length - 1].seconds;
    add(`${item.id}:tail`, "tail", end, item.start + item.seconds - end);
  }
  return out;
}

/**
 * The row each piece of a lane goes on, so overlapping pieces (two sound effects at the same moment) stack instead of sitting on top of each
 * other: in time order, each takes the first row that is free by its start. `minSeconds` stops a very short piece from sharing a row with a
 * neighbour whose label it would hide. The rows come back in the order the pieces were given.
 */
export function stackRows(pieces: { start: number; seconds: number }[], minSeconds = 0.8): number[] {
  const rows: number[] = [];
  const free: number[] = []; // for each row, when it is free again
  [...pieces.keys()]
    .sort((a, b) => pieces[a].start - pieces[b].start || b - a)
    .forEach((i) => {
      const p = pieces[i];
      let r = free.findIndex((end) => end <= p.start + 1e-6);
      if (r < 0) r = free.length;
      free[r] = p.start + Math.max(p.seconds, minSeconds);
      rows[i] = r;
    });
  return rows;
}

export function scale(items: { seconds: number }[], total: number, width: number): number {
  if (total <= 0 || width <= 0) return 0;
  const fit = width / total;
  const shortest = Math.min(...items.map((i) => i.seconds).filter((s) => s > 0), Infinity);
  return shortest === Infinity ? fit : Math.max(fit, MIN_ITEM_PX / shortest);
}

/** The narrowest the strip may be (px) so the shortest item still gets its minimum card; wider than this it fills whatever room there is. */
export function minInnerWidth(items: { seconds: number }[], total: number): number {
  const shortest = Math.min(...items.map((i) => i.seconds).filter((s) => s > 0), Infinity);
  return shortest === Infinity || total <= 0 ? 0 : Math.ceil((MIN_ITEM_PX / shortest) * total);
}

/** A position or length in seconds as a CSS percentage of the whole timeline (the strip is laid out in percent, so it fills its container). */
export const percent = (seconds: number, total: number): string => `${total > 0 ? Number(((seconds / total) * 100).toFixed(4)) : 0}%`;

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

export const ZOOM_LEVELS = [1, 2, 4, 8] as const;

/** Ruler ticks for every zoom level at once: each tick says at which levels it shows (a finer step at a higher zoom), so the page can
 * render them all and switch with CSS. Level 1 is the strip fitted to the page; level n is n pages wide. */
export function tickLevels(total: number, want = 10): { t: number; levels: number[] }[] {
  const byLevel = new Map<number, Set<number>>();
  for (const level of ZOOM_LEVELS) for (const t of ticks(total, want * level)) byLevel.set(t, (byLevel.get(t) ?? new Set()).add(level));
  return [...byLevel.entries()].sort((a, b) => a[0] - b[0]).map(([t, levels]) => ({ t, levels: [...levels].sort((a, b) => a - b) }));
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
    // A bed lane counts its blocks with a take; the others their pieces. A lane with nothing in it says nothing.
    const sounds: { audio: string | null }[] = lane.bed ? (laid.beds[lane.id] ?? []) : laid.items.flatMap((i) => i.lanes[lane.id] ?? []);
    if (sounds.length === 0) continue;
    out.push({ label: lane.bed ? `${lane.title.toLowerCase()} with a take` : `${lane.title.toLowerCase()} recorded`, done: sounds.filter((p) => p.audio).length, total: sounds.length });
  }
  return out;
}

export const progressLine = (steps: Progress[]): string => steps.map((p) => `${p.done} of ${p.total} ${p.label}`).join(" · ");

/** What the player walks: each item, then each timed piece in it, in order, with where it starts and what (if anything) plays. */
export interface Cue {
  item: string;
  piece: string | null;
  /** The lane the piece is in (so its lane's mute applies); null for a silence. */
  lane: string | null;
  start: number;
  seconds: number;
  audio: string | null;
}

/** What plays *over* the cues: each placed sound at its offset and each bed under its stretch, with its level; `seconds` 0 means "to the end
 * of the file" (a sound with no declared length). */
export interface Overlay {
  id: string;
  lane: string;
  start: number;
  seconds: number;
  audio: string;
  volume: number;
  loop: boolean;
  /** Where the file's own start falls on the timeline, when that is earlier than `start` (a bed cut into steps keeps playing through them). */
  origin?: number;
  /** The bed's whole block and its fades: rising from nothing over `in` at `from`, falling to nothing over `out` before `to`. */
  fade?: { from: number; to: number; in: number; out: number };
  /** Going down to `depth` of its level under each speech window (start, end), easing as the render does. */
  duck?: { depth: number; windows: [number, number][] };
}

/** When someone is heard speaking: the spans of the timed lanes' pieces that have a take, joined when closer than one ramp down and up (so the
 * music does not pump in a short pause). Pieces with no take are silent in Play, so nothing ducks for them. */
export function speechWindows(laid: Layout, lanes: LaneSpec[]): [number, number][] {
  const timed = lanes.filter((l) => l.in && (l.seconds || l.estimate_from)).map((l) => l.id);
  const spans = laid.items
    .flatMap((i) => timed.flatMap((id) => i.lanes[id] ?? []))
    .filter((p) => p.audio && p.seconds > 0)
    .map((p): [number, number] => [p.start, p.start + p.seconds])
    .sort((a, b) => a[0] - b[0]);
  const joined: [number, number][] = [];
  for (const [begin, end] of spans) {
    const last = joined[joined.length - 1];
    if (last && begin - last[1] < DUCK_ATTACK + DUCK_RELEASE) last[1] = Math.max(last[1], end);
    else joined.push([begin, end]);
  }
  return joined;
}

const clip01 = (x: number): number => Math.max(0, Math.min(1, x));

/** The share of its level an overlay plays at, at time `t`: 1, less its fade at either end of its block and its dip under speech. */
export function gainAt(o: Overlay, t: number): number {
  let gain = 1;
  if (o.fade) {
    if (o.fade.in > 0) gain = Math.min(gain, clip01((t - o.fade.from) / o.fade.in));
    if (o.fade.out > 0) gain = Math.min(gain, clip01((o.fade.to - t) / o.fade.out));
  }
  if (o.duck) {
    let down = 0;
    for (const [begin, end] of o.duck.windows) down += Math.min(clip01((t - (begin - DUCK_ATTACK)) / DUCK_ATTACK), clip01((end + DUCK_RELEASE - t) / DUCK_RELEASE));
    gain *= 1 - (1 - o.duck.depth) * Math.min(1, down);
  }
  return gain;
}

export function overlays(laid: Layout, lanes: LaneSpec[]): Overlay[] {
  const out: Overlay[] = [];
  let windows: [number, number][] | undefined; // the speech windows, found once and only when a bed ducks
  for (const lane of lanes.filter((l) => l.placed)) {
    for (const p of laid.items.flatMap((i) => i.lanes[lane.id] ?? [])) {
      if (p.audio) out.push({ id: p.id, lane: lane.id, start: p.start, seconds: p.seconds, audio: p.audio, volume: p.volume ?? 1, loop: false });
    }
  }
  for (const lane of lanes.filter((l) => l.bed)) {
    for (const b of laid.beds[lane.id] ?? []) {
      if (!b.audio) continue;
      const shape: Partial<Overlay> = {
        ...(b.fadeIn > 0 || b.fadeOut > 0 ? { fade: { from: b.start, to: b.start + b.seconds, in: b.fadeIn, out: b.fadeOut } } : {}),
        ...(b.duck !== null ? { duck: { depth: b.duck, windows: windows ??= speechWindows(laid, lanes) } } : {}),
      };
      if (b.steps.length === 0) out.push({ id: b.id, lane: lane.id, start: b.start, seconds: b.seconds, audio: b.audio, volume: b.volume, loop: b.loop, ...shape });
      else for (const step of b.steps) if (step.volume > 0) out.push({ id: b.id, lane: lane.id, start: step.start, seconds: step.seconds, audio: b.audio, volume: step.volume, loop: b.loop, origin: b.start, ...shape });
    }
  }
  return out.sort((a, b) => a.start - b.start);
}

export function cues(laid: Layout, lanes: LaneSpec[]): Cue[] {
  const timedLanes = lanes.filter((l) => l.in && (l.seconds || l.estimate_from)).map((l) => l.id);
  const out: Cue[] = [];
  for (const item of laid.items) {
    const timed = timedLanes
      .flatMap((id) => (item.lanes[id] ?? []).map((p) => ({ p, lane: id })))
      .filter(({ p }) => p.seconds > 0)
      .sort((a, b) => a.p.start - b.p.start);
    if (timed.length === 0) {
      out.push({ item: item.id, piece: null, lane: null, start: item.start, seconds: item.seconds, audio: null });
      continue;
    }
    let at = item.start;
    for (const { p, lane } of timed) {
      if (p.start > at) out.push({ item: item.id, piece: null, lane: null, start: at, seconds: p.start - at, audio: null });
      out.push({ item: item.id, piece: p.id, lane, start: p.start, seconds: p.seconds, audio: p.audio });
      at = p.start + p.seconds;
    }
    const end = item.start + item.seconds;
    if (end > at) out.push({ item: item.id, piece: null, lane: null, start: at, seconds: end - at, audio: null });
  }
  return out;
}
